import sqlite3
import operator
from typing import Annotated, TypedDict
import matplotlib.pyplot as plt

from langgraph.graph import StateGraph, END
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

# CONFIG

DATABASE_PATH = "Chinook.db"
OLLAMA_MODEL = "qwen2.5:7b"

SYSTEM_PROMPT = """You are Melody, a friendly AI music store assistant with access to the Chinook digital music store database.

IMPORTANT: When answering questions about the database, follow this process:
1. FIRST use `list_tables` to see what tables are available
2. THEN use `get_schema` to understand the structure of relevant tables
3. FINALLY use `execute_sql` to query the data

This ensures you write accurate SQL queries based on the actual database structure.

Available tools:
- list_tables: Lists all tables in the database
- get_schema: Gets the schema (columns, types, sample data) for specific tables
- execute_sql: Executes SQL queries on the database
- generate_chart: Creates visualizations (genre_popularity, top_artists, sales_trend)

Be friendly and musical! """


# TOOLS

@tool
def list_tables() -> str:
    """List all tables in the Chinook database. Use this FIRST to discover available tables."""
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
        table_names: Comma-separated list of table names (e.g., "Album, Genre, Track")
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        tables = [t.strip() for t in table_names.split(",")]
        result = ""
        
        for table in tables:
            # Get table schema
            cursor.execute(f"PRAGMA table_info({table});")
            columns = cursor.fetchall()
            
            if not columns:
                result += f"\nTable '{table}' not found.\n"
                continue
            
            # Build CREATE TABLE statement
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
            
            # Get foreign keys
            cursor.execute(f"PRAGMA foreign_key_list({table});")
            fks = cursor.fetchall()
            for fk in fks:
                result += f',\n\tFOREIGN KEY("{fk[3]}") REFERENCES "{fk[2]}" ("{fk[4]}")'
            
            result += "\n)\n"
            
            # Get sample data (3 rows)
            cursor.execute(f"SELECT * FROM {table} LIMIT 3;")
            rows = cursor.fetchall()
            col_names = [col[1] for col in columns]
            
            result += f"\n/*\n3 rows from {table} table:\n"
            result += "\t".join(col_names) + "\n"
            for row in rows:
                result += "\t".join(str(v)[:30] if v is not None else "None" for v in row) + "\n"
            result += "*/\n"
        
        conn.close()
        return result
    except Exception as e:
        return f"Error getting schema: {e}"


@tool
def execute_sql(query: str) -> str:
    """Execute SQL query on the Chinook database. Use this AFTER understanding the schema.

    Args:
        query: The SQL query to execute
    """
    import re
    q = query.strip().upper()
    if not q.startswith("SELECT") and not q.startswith("PRAGMA"):
        return "Only SELECT queries are allowed."
    for blocked in ["ATTACH", "DETACH", "LOAD_EXTENSION", "DROP", "DELETE", "UPDATE",
                     "INSERT", "ALTER", "CREATE", "REPLACE", "EXEC", "TRUNCATE",
                     "MARKETPLACE", "API_KEY", "PASSWORD_HASH", "JWT_SECRET"]:
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
        
        # Format as simple table
        result = " | ".join(columns) + "\n" + "-" * 50 + "\n"
        for row in rows:
            result += " | ".join(str(v)[:30] for v in row) + "\n"
        return result
    except Exception as e:
        return f"SQL Error: {e}"


@tool
def generate_chart(chart_type: str) -> str:
    """Generate a chart visualization.
    
    Args:
        chart_type: Type of chart - 'genre_popularity', 'top_artists', or 'sales_trend'
    """
    conn = sqlite3.connect(DATABASE_PATH)
    
    if chart_type == "genre_popularity":
        query = """
        SELECT g.Name, COUNT(il.InvoiceLineId) as Sold
        FROM Genre g
        JOIN Track t ON g.GenreId = t.GenreId
        JOIN InvoiceLine il ON t.TrackId = il.TrackId
        GROUP BY g.GenreId ORDER BY Sold DESC LIMIT 10
        """
        df = conn.execute(query).fetchall()
        labels, values = zip(*df) if df else ([], [])
        
        plt.figure(figsize=(10, 6))
        plt.barh(labels[::-1], values[::-1], color='steelblue')
        plt.xlabel('Tracks Sold')
        plt.title('Top 10 Genres by Popularity')
        plt.tight_layout()
        plt.savefig('chart.png', dpi=150)
        plt.close()
        
    elif chart_type == "top_artists":
        query = """
        SELECT ar.Name, COUNT(il.InvoiceLineId) as Sold
        FROM Artist ar
        JOIN Album al ON ar.ArtistId = al.ArtistId
        JOIN Track t ON al.AlbumId = t.AlbumId
        JOIN InvoiceLine il ON t.TrackId = il.TrackId
        GROUP BY ar.ArtistId ORDER BY Sold DESC LIMIT 10
        """
        df = conn.execute(query).fetchall()
        labels, values = zip(*df) if df else ([], [])
        
        plt.figure(figsize=(10, 6))
        plt.bar([l[:15] for l in labels], values, color='coral')
        plt.xticks(rotation=45, ha='right')
        plt.ylabel('Tracks Sold')
        plt.title('Top 10 Artists')
        plt.tight_layout()
        plt.savefig('chart.png', dpi=150)
        plt.close()
        
    elif chart_type == "sales_trend":
        query = """
        SELECT strftime('%Y-%m', InvoiceDate) as Month, SUM(Total) as Revenue
        FROM Invoice GROUP BY Month ORDER BY Month
        """
        df = conn.execute(query).fetchall()
        labels, values = zip(*df) if df else ([], [])
        
        plt.figure(figsize=(12, 5))
        plt.plot(labels, values, marker='o', color='green')
        plt.xticks(rotation=45, ha='right')
        plt.ylabel('Revenue ($)')
        plt.title('Monthly Sales Trend')
        plt.tight_layout()
        plt.savefig('chart.png', dpi=150)
        plt.close()
    else:
        conn.close()
        return f"Unknown chart type: {chart_type}. Available: genre_popularity, top_artists, sales_trend"
    
    conn.close()
    return f"Chart saved to chart.png"


# All available tools
TOOLS = [list_tables, get_schema, execute_sql, generate_chart]

# Tool name to function mapping
TOOL_MAP = {
    "list_tables": list_tables,
    "get_schema": get_schema,
    "execute_sql": execute_sql,
    "generate_chart": generate_chart
}


# STATE

class AgentState(TypedDict):
    messages: Annotated[list, operator.add]


# NODES

llm = ChatOllama(model=OLLAMA_MODEL, temperature=0.7).bind_tools(TOOLS)


def llm_node(state: AgentState) -> dict:
    """Call the LLM"""
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response]}


def tool_node(state: AgentState) -> dict:
    """Execute tools from last AI message and display what's being called"""
    last_message = state["messages"][-1]
    results = []
    
    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        
        # Display tool being called based on type
        print("\n" + "=" * 60)
        
        if tool_name == "list_tables":
            print(" TOOL CALL: list_tables")
            print("=" * 60)
            print("Purpose: Discovering available tables in database")
            
        elif tool_name == "get_schema":
            print(" TOOL CALL: get_schema")
            print("=" * 60)
            print(f"Tables requested: {tool_args.get('table_names', 'N/A')}")
            
        elif tool_name == "execute_sql":
            print(" TOOL CALL: execute_sql")
            print("=" * 60)
            print("SQL Query:")
            print("-" * 60)
            print(tool_args.get("query", "N/A").strip())
            print("-" * 60)
            
        elif tool_name == "generate_chart":
            print(" TOOL CALL: generate_chart")
            print("=" * 60)
            print(f"Chart type: {tool_args.get('chart_type', 'N/A')}")
        
        else:
            print(f" TOOL CALL: {tool_name}")
            print("=" * 60)
            print(f"Args: {tool_args}")
        
        # Execute the tool
        tool_fn = TOOL_MAP.get(tool_name)
        
        if tool_fn:
            result = tool_fn.invoke(tool_args)
            # Show brief result preview
            result_preview = result[:200] + "..." if len(result) > 200 else result
            print(f"\n Result Preview:\n{result_preview}")
        else:
            result = f"Unknown tool: {tool_name}"
            print(f"\n Error: {result}")
        
        print("=" * 60 + "\n")
        
        results.append(ToolMessage(content=result, tool_call_id=tool_call["id"]))
    
    return {"messages": results}


def should_use_tools(state: AgentState) -> str:
    """Route: tools or end?"""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "end"


# GRAPH

def build_graph():
    graph = StateGraph(AgentState)
    
    # Nodes
    graph.add_node("llm", llm_node)
    graph.add_node("tools", tool_node)
    
    # Edges
    graph.set_entry_point("llm")
    graph.add_conditional_edges("llm", should_use_tools, {"tools": "tools", "end": END})
    graph.add_edge("tools", "llm")  # After tools, go back to LLM
    
    return graph.compile()


# CHAT

def main():
    print("\n" + "=" * 60)
    print("Melody - Music Store Assistant ")
    print("=" * 60)
    print("\nI can help you explore the Chinook music database!")
    print("I'll show you my reasoning process as I work.\n")
    print("Commands:")
    print("  - Ask any question about the music store")
    print("  - Type 'quit' to exit")
    print("-" * 60 + "\n")
    
    agent = build_graph()
    messages = []
    
    while True:
        try:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            if user_input.lower() == "quit":
                print("\n Bye! Keep the music playing!")
                break
            
            messages.append(HumanMessage(content=user_input))
            
            print("\n" + "-" * 60)
            print(" Melody is thinking...")
            print("-" * 60)
            
            result = agent.invoke({"messages": messages})
            
            # Get final AI response
            ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
            if ai_messages:
                response = ai_messages[-1].content
                messages = result["messages"]  # Update history
                print("\n" + "=" * 60)
                print(" Melody's Answer:")
                print("=" * 60)
                print(f"\n{response}\n")
            
        except KeyboardInterrupt:
            print("\n\n Goodbye!")
            break


if __name__ == "__main__":
    # ---- Save LangGraph visualization to file ----
    try:
        agent = build_graph()
        png_bytes = agent.get_graph(xray=True).draw_mermaid_png()
        with open("langgraph_melody_agent.png", "wb") as f:
            f.write(png_bytes)
        print(" LangGraph diagram saved as langgraph_melody_agent.png")
    except Exception as e:
        print(f" Could not save graph diagram: {e}")
    
    # Start the chat
    main()