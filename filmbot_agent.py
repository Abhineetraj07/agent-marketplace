"""
FilmBot Agent Core — Shared module for direct and A2A benchmarking.
Extracts the LangGraph agent, tools, ground truth, and accuracy checking
from rock.py, adding token counting via AIMessage.usage_metadata.
"""

import os
import sqlite3
import operator
import time
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, END
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

# ============================================================
# CONFIG
# ============================================================

DATABASE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "imdb.db")
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

            result += f'\n\nCREATE TABLE "{table}" (\n'
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


def _safe_sql_check(query: str) -> str | None:
    """Block dangerous SQL. Returns error message or None if safe."""
    import re
    q = query.strip().upper()
    # Only allow SELECT queries
    if not q.startswith("SELECT") and not q.startswith("PRAGMA"):
        return "Only SELECT queries are allowed."
    # Block cross-database and dangerous commands
    for blocked in ["ATTACH", "DETACH", "LOAD_EXTENSION", "DROP", "DELETE", "UPDATE",
                     "INSERT", "ALTER", "CREATE", "REPLACE", "EXEC", "TRUNCATE",
                     "MARKETPLACE", "API_KEY", "PASSWORD", "USERS"]:
        if blocked in q:
            return f"Blocked: {blocked} is not allowed in queries."
    return None


@tool
def execute_sql(query: str) -> str:
    """Execute SQL query on the IMDB database. Use this AFTER understanding the schema.

    Args:
        query: The SQL query to execute
    """
    blocked = _safe_sql_check(query)
    if blocked:
        return blocked
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


TOOLS = [list_tables, get_schema, execute_sql]
TOOL_MAP = {
    "list_tables": list_tables,
    "get_schema": get_schema,
    "execute_sql": execute_sql,
}


# ============================================================
# STATE & GRAPH (with token counting)
# ============================================================

class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    token_usage: Annotated[list, operator.add]


llm = ChatOllama(model=OLLAMA_MODEL, temperature=0.0).bind_tools(TOOLS)


def llm_node(state: AgentState) -> dict:
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    response = llm.invoke(messages)

    token_entry = {"prompt_tokens": 0, "completion_tokens": 0}
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        token_entry["prompt_tokens"] = response.usage_metadata.get("input_tokens", 0)
        token_entry["completion_tokens"] = response.usage_metadata.get("output_tokens", 0)

    return {"messages": [response], "token_usage": [token_entry]}


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


# Singleton agent instance
_agent = None

def get_agent():
    global _agent
    if _agent is None:
        _agent = build_graph()
    return _agent


# ============================================================
# INVOKE FUNCTION (used by both direct and A2A modes)
# ============================================================

def invoke_agent(question: str) -> dict:
    """Run a question through the FilmBot agent and return metrics.

    Returns:
        dict with keys: response, latency, tool_calls, prompt_tokens, completion_tokens
    """
    agent = get_agent()

    start_time = time.time()
    result = agent.invoke({"messages": [HumanMessage(content=question)], "token_usage": []})
    latency = time.time() - start_time

    # Extract response text
    ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
    response = ai_messages[-1].content if ai_messages else "No response"

    # Count tool calls
    tool_calls = sum(1 for m in result["messages"] if isinstance(m, ToolMessage))

    # Sum token usage across all LLM invocations in the loop
    prompt_tokens = sum(t["prompt_tokens"] for t in result.get("token_usage", []))
    completion_tokens = sum(t["completion_tokens"] for t in result.get("token_usage", []))

    return {
        "response": response,
        "latency": round(latency, 2),
        "tool_calls": tool_calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }


# ============================================================
# GROUND TRUTH & ACCURACY
# ============================================================

def get_ground_truth():
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    ground_truth = {}

    cursor.execute("SELECT series_title, imdb_rating FROM movies ORDER BY imdb_rating DESC LIMIT 5")
    ground_truth["Top 5 movies by IMDb rating"] = cursor.fetchall()

    cursor.execute("SELECT series_title, no_of_votes FROM movies ORDER BY no_of_votes DESC LIMIT 5")
    ground_truth["Top 5 movies by number of votes"] = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) FROM movies")
    ground_truth["How many movies are in the dataset?"] = cursor.fetchone()[0]

    cursor.execute("SELECT ROUND(AVG(imdb_rating), 2) FROM movies")
    ground_truth["Average IMDb rating of all movies"] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM movies WHERE CAST(released_year AS INTEGER) > 2015")
    ground_truth["Movies released after 2015"] = cursor.fetchone()[0]

    cursor.execute("SELECT director, COUNT(*) as count FROM movies GROUP BY director ORDER BY count DESC LIMIT 5")
    ground_truth["Top 5 directors by number of movies"] = cursor.fetchall()

    cursor.execute("SELECT series_title, imdb_rating FROM movies WHERE CAST(released_year AS INTEGER) < 2000 ORDER BY imdb_rating DESC LIMIT 1")
    ground_truth["Highest rated movie released before 2000"] = cursor.fetchone()

    cursor.execute("SELECT series_title, imdb_rating FROM movies WHERE imdb_rating > 9 ORDER BY imdb_rating DESC")
    ground_truth["Movies with IMDb rating above 9"] = cursor.fetchall()

    cursor.execute("SELECT certificate, ROUND(AVG(imdb_rating), 2) FROM movies WHERE certificate IS NOT NULL GROUP BY certificate ORDER BY AVG(imdb_rating) DESC")
    ground_truth["Average IMDb rating per certificate"] = cursor.fetchall()

    cursor.execute("SELECT genre, COUNT(*) as count FROM movies GROUP BY genre ORDER BY count DESC LIMIT 3")
    ground_truth["Top 3 most common genres"] = cursor.fetchall()

    cursor.execute("SELECT series_title, meta_score FROM movies WHERE meta_score IS NOT NULL ORDER BY meta_score DESC LIMIT 5")
    ground_truth["Top 5 movies by Meta score"] = cursor.fetchall()

    cursor.execute("""
        SELECT (CAST(released_year AS INTEGER) / 10) * 10 as decade, ROUND(AVG(imdb_rating), 2)
        FROM movies WHERE released_year IS NOT NULL
        GROUP BY decade ORDER BY decade
    """)
    ground_truth["Average IMDb rating by release decade"] = cursor.fetchall()

    cursor.execute("""
        SELECT series_title, gross FROM movies
        WHERE gross IS NOT NULL
        ORDER BY CAST(REPLACE(REPLACE(gross, ',', ''), '$', '') AS INTEGER) DESC
        LIMIT 5
    """)
    ground_truth["Top 5 movies with highest gross revenue"] = cursor.fetchall()

    cursor.execute("SELECT released_year, COUNT(*) as count FROM movies GROUP BY released_year ORDER BY count DESC LIMIT 10")
    ground_truth["Number of movies released each year"] = cursor.fetchall()

    cursor.execute("SELECT star1, COUNT(*) as count FROM movies GROUP BY star1 ORDER BY count DESC LIMIT 5")
    ground_truth["Top 5 actors (Star1) by number of movies"] = cursor.fetchall()

    cursor.execute("SELECT series_title, no_of_votes FROM movies WHERE no_of_votes > 1000000 ORDER BY no_of_votes DESC")
    ground_truth["Movies with more than 1,000,000 votes"] = cursor.fetchall()

    cursor.execute("SELECT genre, ROUND(AVG(imdb_rating), 2) as avg_rating FROM movies GROUP BY genre ORDER BY avg_rating DESC LIMIT 10")
    ground_truth["Average IMDb rating for each genre"] = cursor.fetchall()

    cursor.execute("""
        SELECT certificate, series_title, MAX(imdb_rating)
        FROM movies WHERE certificate IS NOT NULL
        GROUP BY certificate ORDER BY MAX(imdb_rating) DESC
    """)
    ground_truth["Highest rated movie for each certificate"] = cursor.fetchall()

    cursor.execute("""
        SELECT director, ROUND(AVG(imdb_rating), 2) as avg_rating, COUNT(*) as count
        FROM movies GROUP BY director HAVING count >= 3
        ORDER BY avg_rating DESC LIMIT 5
    """)
    ground_truth["Top 5 directors by average IMDb rating with at least 3 movies"] = cursor.fetchall()

    cursor.execute("SELECT series_title, released_year FROM movies ORDER BY CAST(released_year AS INTEGER) ASC LIMIT 1")
    ground_truth["Oldest movie in the dataset"] = cursor.fetchone()

    conn.close()
    return ground_truth


def check_accuracy(question: str, agent_response: str, ground_truth: dict) -> tuple:
    """Check if the agent's response contains the expected answer."""
    expected = ground_truth.get(question)

    if expected is None:
        return False, "No ground truth available"

    response_lower = agent_response.lower()

    if isinstance(expected, (list, tuple)):
        if len(expected) == 0:
            return False, "Empty result"

        if isinstance(expected, tuple):
            # Single tuple result
            key_value = str(expected[0]).lower()
            is_accurate = key_value in response_lower
            return is_accurate, f"Expected: {expected[0]}, Found: {is_accurate}"

        # List of results
        matches = 0
        total = min(len(expected), 5)

        for item in expected[:total]:
            if isinstance(item, tuple):
                key_value = str(item[0]).lower()
                if key_value in response_lower:
                    matches += 1
            else:
                if str(item).lower() in response_lower:
                    matches += 1

        accuracy_pct = (matches / total) * 100
        is_accurate = accuracy_pct >= 60
        return is_accurate, f"{matches}/{total} items found ({accuracy_pct:.0f}%)"

    else:
        expected_str = str(expected).lower()
        is_accurate = expected_str in response_lower
        return is_accurate, f"Expected: {expected}, Found: {is_accurate}"


BENCHMARK_QUESTIONS = [
    "Top 5 movies by IMDb rating",
    "Top 5 movies by number of votes",
    "How many movies are in the dataset?",
    "Average IMDb rating of all movies",
    "Top 5 directors by number of movies",
    "Movies with IMDb rating above 9",
    "Top 5 movies with highest gross revenue",
    "Movies with more than 1,000,000 votes",
    "Top 5 directors by average IMDb rating with at least 3 movies",
    "Oldest movie in the dataset",
]

# Subset of 10 questions for quick benchmarking
BENCHMARK_QUESTIONS_10 = BENCHMARK_QUESTIONS[:10]
