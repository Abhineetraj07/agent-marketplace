import sqlite3
import operator
import time
import csv
from typing import Annotated, TypedDict
from datetime import datetime

from langgraph.graph import StateGraph, END
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

# ============================================================
# CONFIG
# ============================================================

DATABASE_PATH = "imdb.db"
OLLAMA_MODEL = "qwen2.5:7b"

SYSTEM_PROMPT = """You are FilmBot, a friendly AI movie expert assistant with access to the IMDB movies database.

IMPORTANT: When answering questions about the database, follow this process:
1. FIRST use `list_tables` to see what tables are available
2. THEN use `get_schema` to understand the structure of relevant tables
3. FINALLY use `execute_sql` to query the data
4. ONLY answer questions related to the IMDB movies database. For any other questions (general knowledge, math, science, current events, etc.), politely decline and redirect the user to ask about movies. Greetings are allowed.

SQL BEST PRACTICES:
- The database has a single 'movies' table with movie information
- Use LIKE for partial text matches (e.g., genre LIKE '%Action%')
- imdb_rating is a REAL number (0-10 scale)
- released_year is TEXT, so use quotes when filtering
- gross is TEXT with commas, may need cleaning for calculations
- Stars are in separate columns: star1, star2, star3, star4
- To search for an actor, check ALL star columns with OR conditions
- Verify column names from schema before writing SQL

DATABASE COLUMNS:
- poster_link: URL to movie poster
- series_title: Movie name
- released_year: Year of release (TEXT)
- certificate: Age rating (A, UA, PG, etc.)
- runtime: Duration (e.g., "142 min")
- genre: Movie genres (comma-separated)
- imdb_rating: IMDB score (0-10)
- overview: Plot summary
- meta_score: Metacritic score
- director: Director name
- star1, star2, star3, star4: Main actors
- no_of_votes: Number of IMDB votes
- gross: Box office earnings (TEXT with commas)

Available tools:
- list_tables: Lists all tables in the database
- get_schema: Gets the schema (columns, types, sample data) for specific tables
- execute_sql: Executes SQL queries on the database

Be friendly and cinematic!"""


# ============================================================
# TOOLS
# ============================================================

@tool
def list_tables() -> str:
    """List all tables in the IMDB database. Use this FIRST to discover available tables."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        return ", ".join(tables)
    except Exception as e:
        return f"Error listing tables: {e}"


@tool
def get_schema(table_names: str) -> str:
    """Get schema information for specified tables. Use this AFTER list_tables to understand table structure.
    
    Args:
        table_names: Comma-separated list of table names (e.g., "movies")
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        tables = [t.strip() for t in table_names.split(",")]
        result = ""
        
        for table in tables:
            cursor.execute(f"PRAGMA table_info({table});")
            columns = cursor.fetchall()
            
            if not columns:
                result += f"\nTable '{table}' not found.\n"
                continue
            
            result += f"\n\nCREATE TABLE \"{table}\" (\n"
            col_defs = []
            pk_cols = []
            for col in columns:
                col_name, col_type, not_null, default, is_pk = col[1], col[2], col[3], col[4], col[5]
                col_def = f'\t"{col_name}" {col_type or "TEXT"}'
                if not_null:
                    col_def += " NOT NULL"
                col_defs.append(col_def)
                if is_pk:
                    pk_cols.append(col_name)
            
            result += ",\n".join(col_defs)
            if pk_cols:
                result += f',\n\tPRIMARY KEY ("{", ".join(pk_cols)}")'
            
            result += "\n)\n"
            
            cursor.execute(f"SELECT series_title, released_year, genre, imdb_rating, director FROM {table} LIMIT 3;")
            rows = cursor.fetchall()
            
            result += f"\n/*\n3 sample rows from {table} table:\n"
            result += "series_title\treleased_year\tgenre\timdb_rating\tdirector\n"
            for row in rows:
                result += "\t".join(str(v)[:30] if v is not None else "None" for v in row) + "\n"
            result += "*/\n"
        
        conn.close()
        return result
    except Exception as e:
        return f"Error getting schema: {e}"


@tool
def execute_sql(query: str) -> str:
    """Execute SQL query on the IMDB database. Use this AFTER understanding the schema.

    Args:
        query: The SQL query to execute
    """
    import re
    q = query.strip().upper()
    if not q.startswith("SELECT") and not q.startswith("PRAGMA"):
        return "Only SELECT queries are allowed."
    for blocked in ["ATTACH", "DETACH", "LOAD_EXTENSION", "DROP", "DELETE", "UPDATE",
                     "INSERT", "ALTER", "CREATE", "REPLACE", "EXEC", "TRUNCATE",
                     "MARKETPLACE", "API_KEY", "PASSWORD", "USERS"]:
        if blocked in q:
            return f"Blocked: {blocked} is not allowed in queries."
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute(query)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()[:30]
        conn.close()
        
        if not rows:
            return "No results found."
        
        result = " | ".join(columns) + "\n" + "-" * 50 + "\n"
        for row in rows:
            result += " | ".join(str(v)[:30] for v in row) + "\n"
        return result
    except Exception as e:
        return f"SQL Error: {e}"


# Tool setup
TOOLS = [list_tables, get_schema, execute_sql]
TOOL_MAP = {
    "list_tables": list_tables,
    "get_schema": get_schema,
    "execute_sql": execute_sql,
}


# ============================================================
# STATE & NODES
# ============================================================

class AgentState(TypedDict):
    messages: Annotated[list, operator.add]


llm = ChatOllama(model=OLLAMA_MODEL, temperature=0.0).bind_tools(TOOLS)


def llm_node(state: AgentState) -> dict:
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response]}


def tool_node(state: AgentState) -> dict:
    last_message = state["messages"][-1]
    results = []
    
    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_fn = TOOL_MAP.get(tool_name)
        
        if tool_fn:
            result = tool_fn.invoke(tool_args)
        else:
            result = f"Unknown tool: {tool_name}"
        
        results.append(ToolMessage(content=result, tool_call_id=tool_call["id"]))
    
    return {"messages": results}


def should_use_tools(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "end"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("llm", llm_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("llm")
    graph.add_conditional_edges("llm", should_use_tools, {"tools": "tools", "end": END})
    graph.add_edge("tools", "llm")
    return graph.compile()


# ============================================================
# GROUND TRUTH - Expected answers from direct SQL queries
# ============================================================

def get_ground_truth():
    """Run direct SQL queries to get expected answers for benchmarking"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    ground_truth = {}
    
    # 1. Top 5 movies by IMDb rating
    cursor.execute("SELECT series_title, imdb_rating FROM movies ORDER BY imdb_rating DESC LIMIT 5")
    ground_truth["Top 5 movies by IMDb rating"] = cursor.fetchall()
    
    # 2. Top 5 movies by number of votes
    cursor.execute("SELECT series_title, no_of_votes FROM movies ORDER BY no_of_votes DESC LIMIT 5")
    ground_truth["Top 5 movies by number of votes"] = cursor.fetchall()
    
    # 3. How many movies are in the dataset?
    cursor.execute("SELECT COUNT(*) FROM movies")
    ground_truth["How many movies are in the dataset?"] = cursor.fetchone()[0]
    
    # 4. Average IMDb rating of all movies
    cursor.execute("SELECT ROUND(AVG(imdb_rating), 2) FROM movies")
    ground_truth["Average IMDb rating of all movies"] = cursor.fetchone()[0]
    
    # 5. Movies released after 2015
    cursor.execute("SELECT COUNT(*) FROM movies WHERE CAST(released_year AS INTEGER) > 2015")
    ground_truth["Movies released after 2015"] = cursor.fetchone()[0]
    
    # 6. Top 5 directors by number of movies
    cursor.execute("SELECT director, COUNT(*) as count FROM movies GROUP BY director ORDER BY count DESC LIMIT 5")
    ground_truth["Top 5 directors by number of movies"] = cursor.fetchall()
    
    # 7. Highest rated movie released before 2000
    cursor.execute("SELECT series_title, imdb_rating FROM movies WHERE CAST(released_year AS INTEGER) < 2000 ORDER BY imdb_rating DESC LIMIT 1")
    ground_truth["Highest rated movie released before 2000"] = cursor.fetchone()
    
    # 8. Movies with IMDb rating above 9
    cursor.execute("SELECT series_title, imdb_rating FROM movies WHERE imdb_rating > 9 ORDER BY imdb_rating DESC")
    ground_truth["Movies with IMDb rating above 9"] = cursor.fetchall()
    
    # 9. Average IMDb rating per certificate
    cursor.execute("SELECT certificate, ROUND(AVG(imdb_rating), 2) FROM movies WHERE certificate IS NOT NULL GROUP BY certificate ORDER BY AVG(imdb_rating) DESC")
    ground_truth["Average IMDb rating per certificate"] = cursor.fetchall()
    
    # 10. Top 3 most common genres
    cursor.execute("SELECT genre, COUNT(*) as count FROM movies GROUP BY genre ORDER BY count DESC LIMIT 3")
    ground_truth["Top 3 most common genres"] = cursor.fetchall()
    
    # 11. Top 5 movies by Meta score
    cursor.execute("SELECT series_title, meta_score FROM movies WHERE meta_score IS NOT NULL ORDER BY meta_score DESC LIMIT 5")
    ground_truth["Top 5 movies by Meta score"] = cursor.fetchall()
    
    # 12. Average IMDb rating by release decade
    cursor.execute("""
        SELECT (CAST(released_year AS INTEGER) / 10) * 10 as decade, ROUND(AVG(imdb_rating), 2) 
        FROM movies WHERE released_year IS NOT NULL 
        GROUP BY decade ORDER BY decade
    """)
    ground_truth["Average IMDb rating by release decade"] = cursor.fetchall()
    
    # 13. Top 5 movies with highest gross revenue
    cursor.execute("""
        SELECT series_title, gross FROM movies 
        WHERE gross IS NOT NULL 
        ORDER BY CAST(REPLACE(REPLACE(gross, ',', ''), '$', '') AS INTEGER) DESC 
        LIMIT 5
    """)
    ground_truth["Top 5 movies with highest gross revenue"] = cursor.fetchall()
    
    # 14. Number of movies released each year (top 10 years)
    cursor.execute("SELECT released_year, COUNT(*) as count FROM movies GROUP BY released_year ORDER BY count DESC LIMIT 10")
    ground_truth["Number of movies released each year"] = cursor.fetchall()
    
    # 15. Top 5 actors (Star1) by number of movies
    cursor.execute("SELECT star1, COUNT(*) as count FROM movies GROUP BY star1 ORDER BY count DESC LIMIT 5")
    ground_truth["Top 5 actors (Star1) by number of movies"] = cursor.fetchall()
    
    # 16. Movies with more than 1,000,000 votes
    cursor.execute("SELECT series_title, no_of_votes FROM movies WHERE no_of_votes > 1000000 ORDER BY no_of_votes DESC")
    ground_truth["Movies with more than 1,000,000 votes"] = cursor.fetchall()
    
    # 17. Average IMDb rating for each genre (top 10)
    cursor.execute("SELECT genre, ROUND(AVG(imdb_rating), 2) as avg_rating FROM movies GROUP BY genre ORDER BY avg_rating DESC LIMIT 10")
    ground_truth["Average IMDb rating for each genre"] = cursor.fetchall()
    
    # 18. Highest rated movie for each certificate
    cursor.execute("""
        SELECT certificate, series_title, MAX(imdb_rating) 
        FROM movies WHERE certificate IS NOT NULL 
        GROUP BY certificate ORDER BY MAX(imdb_rating) DESC
    """)
    ground_truth["Highest rated movie for each certificate"] = cursor.fetchall()
    
    # 19. Top 5 directors by average IMDb rating with at least 3 movies
    cursor.execute("""
        SELECT director, ROUND(AVG(imdb_rating), 2) as avg_rating, COUNT(*) as count 
        FROM movies GROUP BY director HAVING count >= 3 
        ORDER BY avg_rating DESC LIMIT 5
    """)
    ground_truth["Top 5 directors by average IMDb rating with at least 3 movies"] = cursor.fetchall()
    
    # 20. Oldest movie in the dataset
    cursor.execute("SELECT series_title, released_year FROM movies ORDER BY CAST(released_year AS INTEGER) ASC LIMIT 1")
    ground_truth["Oldest movie in the dataset"] = cursor.fetchone()
    
    conn.close()
    return ground_truth


# ============================================================
# BENCHMARK FUNCTIONS
# ============================================================

def check_accuracy(question: str, agent_response: str, ground_truth: dict) -> tuple:
    """
    Check if the agent's response contains the expected answer.
    Returns (is_accurate: bool, details: str)
    """
    expected = ground_truth.get(question)
    
    if expected is None:
        return False, "No ground truth available"
    
    response_lower = agent_response.lower()
    
    # Convert expected to string for comparison
    if isinstance(expected, (list, tuple)):
        if len(expected) == 0:
            return False, "Empty result"
        
        # For list results, check if key items are mentioned
        matches = 0
        total = min(len(expected), 5)  # Check up to 5 items
        
        for item in expected[:total]:
            if isinstance(item, tuple):
                # Check if the main identifier (usually first element) is in response
                key_value = str(item[0]).lower()
                if key_value in response_lower:
                    matches += 1
            else:
                if str(item).lower() in response_lower:
                    matches += 1
        
        accuracy_pct = (matches / total) * 100
        is_accurate = accuracy_pct >= 60  # 60% threshold
        return is_accurate, f"{matches}/{total} items found ({accuracy_pct:.0f}%)"
    
    else:
        # Single value comparison
        expected_str = str(expected).lower()
        is_accurate = expected_str in response_lower
        return is_accurate, f"Expected: {expected}, Found: {is_accurate}"


def run_benchmark(agent, benchmark_questions: list, ground_truth: dict) -> list:
    """Run all benchmark questions and collect results"""
    results = []
    
    print("\n" + "=" * 70)
    print("   FilmBot Benchmark - Testing Accuracy & Latency")
    print("=" * 70)
    print(f"   Total Questions: {len(benchmark_questions)}")
    print(f"   Model: {OLLAMA_MODEL}")
    print(f"   Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70 + "\n")
    
    for i, question in enumerate(benchmark_questions, 1):
        print(f"[{i}/{len(benchmark_questions)}] Testing: {question[:50]}...")
        
        # Measure latency
        start_time = time.time()
        
        try:
            # Run agent
            messages = [HumanMessage(content=question)]
            result = agent.invoke({"messages": messages})
            
            end_time = time.time()
            latency = end_time - start_time
            
            # Get response
            ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
            response = ai_messages[-1].content if ai_messages else "No response"
            
            # Count tool calls
            tool_calls = sum(1 for m in result["messages"] if isinstance(m, ToolMessage))
            
            # Check accuracy
            is_accurate, accuracy_details = check_accuracy(question, response, ground_truth)
            
            status = "✓" if is_accurate else "✗"
            print(f"    {status} Latency: {latency:.2f}s | Tools: {tool_calls} | {accuracy_details}")
            
            results.append({
                "question_id": i,
                "question": question,
                "response": response[:500],  # Truncate for CSV
                "latency_seconds": round(latency, 2),
                "tool_calls": tool_calls,
                "is_accurate": is_accurate,
                "accuracy_details": accuracy_details,
                "status": "SUCCESS"
            })
            
        except Exception as e:
            end_time = time.time()
            latency = end_time - start_time
            
            print(f"    ✗ ERROR: {str(e)[:50]}")
            
            results.append({
                "question_id": i,
                "question": question,
                "response": f"ERROR: {str(e)}",
                "latency_seconds": round(latency, 2),
                "tool_calls": 0,
                "is_accurate": False,
                "accuracy_details": f"Error: {str(e)[:100]}",
                "status": "ERROR"
            })
    
    return results


def save_results_to_csv(results: list, filename: str = "filmbot_benchmark_results.csv"):
    """Save benchmark results to CSV file with summary statistics"""
    
    if not results:
        print("No results to save!")
        return
    
    # Calculate summary statistics
    total = len(results)
    successful = sum(1 for r in results if r["status"] == "SUCCESS")
    accurate = sum(1 for r in results if r["is_accurate"])
    
    latencies = [r["latency_seconds"] for r in results if r["status"] == "SUCCESS"]
    avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0
    min_latency = round(min(latencies), 2) if latencies else 0
    max_latency = round(max(latencies), 2) if latencies else 0
    
    total_tool_calls = sum(r["tool_calls"] for r in results)
    avg_tool_calls = round(total_tool_calls / total, 1) if total > 0 else 0
    
    success_rate = round(100 * successful / total, 1) if total > 0 else 0
    accuracy_rate = round(100 * accurate / total, 1) if total > 0 else 0
    
    fieldnames = [
        "question_id",
        "question", 
        "response",
        "latency_seconds",
        "tool_calls",
        "is_accurate",
        "accuracy_details",
        "status"
    ]
    
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
        
        # Add empty row as separator
        writer.writerow({field: "" for field in fieldnames})
        
        # Add summary section
        writer.writerow({
            "question_id": "SUMMARY",
            "question": "=== BENCHMARK SUMMARY ===",
            "response": "",
            "latency_seconds": "",
            "tool_calls": "",
            "is_accurate": "",
            "accuracy_details": "",
            "status": ""
        })
        
        writer.writerow({
            "question_id": "",
            "question": "Total Questions",
            "response": total,
            "latency_seconds": "",
            "tool_calls": "",
            "is_accurate": "",
            "accuracy_details": "",
            "status": ""
        })
        
        writer.writerow({
            "question_id": "",
            "question": "Successful Runs",
            "response": f"{successful}/{total} ({success_rate}%)",
            "latency_seconds": "",
            "tool_calls": "",
            "is_accurate": "",
            "accuracy_details": "",
            "status": ""
        })
        
        writer.writerow({
            "question_id": "",
            "question": "Accurate Answers",
            "response": f"{accurate}/{total} ({accuracy_rate}%)",
            "latency_seconds": "",
            "tool_calls": "",
            "is_accurate": "",
            "accuracy_details": "",
            "status": ""
        })
        
        writer.writerow({
            "question_id": "",
            "question": "Average Latency",
            "response": f"{avg_latency}s",
            "latency_seconds": "",
            "tool_calls": "",
            "is_accurate": "",
            "accuracy_details": "",
            "status": ""
        })
        
        writer.writerow({
            "question_id": "",
            "question": "Min Latency",
            "response": f"{min_latency}s",
            "latency_seconds": "",
            "tool_calls": "",
            "is_accurate": "",
            "accuracy_details": "",
            "status": ""
        })
        
        writer.writerow({
            "question_id": "",
            "question": "Max Latency",
            "response": f"{max_latency}s",
            "latency_seconds": "",
            "tool_calls": "",
            "is_accurate": "",
            "accuracy_details": "",
            "status": ""
        })
        
        writer.writerow({
            "question_id": "",
            "question": "Total Tool Calls",
            "response": total_tool_calls,
            "latency_seconds": "",
            "tool_calls": "",
            "is_accurate": "",
            "accuracy_details": "",
            "status": ""
        })
        
        writer.writerow({
            "question_id": "",
            "question": "Avg Tools/Question",
            "response": avg_tool_calls,
            "latency_seconds": "",
            "tool_calls": "",
            "is_accurate": "",
            "accuracy_details": "",
            "status": ""
        })
        
        writer.writerow({
            "question_id": "",
            "question": "Model Used",
            "response": OLLAMA_MODEL,
            "latency_seconds": "",
            "tool_calls": "",
            "is_accurate": "",
            "accuracy_details": "",
            "status": ""
        })
        
        writer.writerow({
            "question_id": "",
            "question": "Timestamp",
            "response": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "latency_seconds": "",
            "tool_calls": "",
            "is_accurate": "",
            "accuracy_details": "",
            "status": ""
        })
    
    print(f"\n[OK] Results saved to: {filename}")


def print_summary(results: list):
    """Print benchmark summary statistics"""
    
    total = len(results)
    successful = sum(1 for r in results if r["status"] == "SUCCESS")
    accurate = sum(1 for r in results if r["is_accurate"])
    
    latencies = [r["latency_seconds"] for r in results if r["status"] == "SUCCESS"]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    min_latency = min(latencies) if latencies else 0
    max_latency = max(latencies) if latencies else 0
    
    total_tool_calls = sum(r["tool_calls"] for r in results)
    avg_tool_calls = total_tool_calls / total if total > 0 else 0
    
    print("\n" + "=" * 70)
    print("   BENCHMARK SUMMARY")
    print("=" * 70)
    print(f"   Total Questions:     {total}")
    print(f"   Successful Runs:     {successful}/{total} ({100*successful/total:.1f}%)")
    print(f"   Accurate Answers:    {accurate}/{total} ({100*accurate/total:.1f}%)")
    print("-" * 70)
    print(f"   Avg Latency:         {avg_latency:.2f}s")
    print(f"   Min Latency:         {min_latency:.2f}s")
    print(f"   Max Latency:         {max_latency:.2f}s")
    print("-" * 70)
    print(f"   Total Tool Calls:    {total_tool_calls}")
    print(f"   Avg Tools/Question:  {avg_tool_calls:.1f}")
    print("=" * 70 + "\n")


# ============================================================
# MAIN
# ============================================================

def main():
    # Benchmark questions
    benchmark_questions = [
        "Top 5 movies by IMDb rating",
        "Top 5 movies by number of votes",
        "How many movies are in the dataset?",
        "Average IMDb rating of all movies",
        "Movies released after 2015",
        "Top 5 directors by number of movies",
        "Highest rated movie released before 2000",
        "Movies with IMDb rating above 9",
        "Average IMDb rating per certificate",
        "Top 3 most common genres",
        "Top 5 movies by Meta score",
        "Average IMDb rating by release decade",
        "Top 5 movies with highest gross revenue",
        "Number of movies released each year",
        "Top 5 actors (Star1) by number of movies",
        "Movies with more than 1,000,000 votes",
        "Average IMDb rating for each genre",
        "Highest rated movie for each certificate",
        "Top 5 directors by average IMDb rating with at least 3 movies",
        "Oldest movie in the dataset"
    ]
    
    # Get ground truth
    print("Loading ground truth from database...")
    ground_truth = get_ground_truth()
    
    # Build agent
    print("Building FilmBot agent...")
    agent = build_graph()
    
    # Run benchmark
    results = run_benchmark(agent, benchmark_questions, ground_truth)
    
    # Save to CSV
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"filmbot_benchmark_{timestamp}.csv"
    save_results_to_csv(results, filename)
    
    # Print summary
    print_summary(results)
    
    return results


if __name__ == "__main__":
    main()