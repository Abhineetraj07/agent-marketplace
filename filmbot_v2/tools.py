"""
FilmBot V2 — Tool definitions for the three retrieval modes:
  1. SQL (SQLite) — structured queries
  2. Vector Search (ChromaDB) — semantic similarity over plot overviews
  3. Knowledge Graph (Neo4j) — relationship traversal via Cypher
"""

import sqlite3
import chromadb
from neo4j import GraphDatabase
from langchain_ollama import OllamaEmbeddings
from langchain_core.tools import tool

from config import (
    SQLITE_PATH, CHROMADB_PATH, CHROMA_COLLECTION,
    EMBEDDING_MODEL, NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD,
)


# ── SQL Tools (SQLite) ────────────────────────────────────────

@tool
def list_tables() -> str:
    """List all tables in the IMDB SQLite database. Use this FIRST before writing SQL."""
    conn = sqlite3.connect(SQLITE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    return f"Tables: {', '.join(tables)}"


@tool
def get_schema(table_names: str) -> str:
    """Get schema and sample data for SQLite tables.

    Args:
        table_names: Comma-separated table names (e.g., "movies")
    """
    conn = sqlite3.connect(SQLITE_PATH)
    cursor = conn.cursor()
    tables = [t.strip() for t in table_names.split(",")]
    result = ""

    for table in tables:
        cursor.execute(f"PRAGMA table_info({table});")
        columns = cursor.fetchall()
        if not columns:
            result += f"\nTable '{table}' not found.\n"
            continue

        result += f'\nCREATE TABLE "{table}" (\n'
        col_defs = []
        for col in columns:
            col_name, col_type = col[1], col[2]
            col_defs.append(f'  "{col_name}" {col_type or "TEXT"}')
        result += ",\n".join(col_defs) + "\n)\n"

        cursor.execute(f"SELECT series_title, released_year, genre, imdb_rating, director FROM {table} LIMIT 3;")
        rows = cursor.fetchall()
        result += f"\nSample rows:\n"
        for row in rows:
            result += " | ".join(str(v)[:30] if v else "None" for v in row) + "\n"

    conn.close()
    return result


@tool
def execute_sql(query: str) -> str:
    """Execute a SQL query on the IMDB SQLite database. Use AFTER checking schema.

    Args:
        query: SQL query to execute
    """
    q = query.strip().upper()
    if not q.startswith("SELECT") and not q.startswith("PRAGMA"):
        return "Only SELECT queries are allowed."
    for blocked in ["ATTACH", "DETACH", "LOAD_EXTENSION", "DROP", "DELETE", "UPDATE",
                     "INSERT", "ALTER", "CREATE", "REPLACE", "EXEC", "TRUNCATE",
                     "MARKETPLACE", "API_KEY", "PASSWORD", "USERS"]:
        if blocked in q:
            return f"Blocked: {blocked} is not allowed in queries."
    try:
        conn = sqlite3.connect(SQLITE_PATH)
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


# ── Vector Search Tool (ChromaDB) ─────────────────────────────

_embeddings = None
_chroma_collection = None


def _get_chroma_collection():
    global _embeddings, _chroma_collection
    if _chroma_collection is None:
        _embeddings = OllamaEmbeddings(model=EMBEDDING_MODEL)
        client = chromadb.PersistentClient(path=CHROMADB_PATH)
        _chroma_collection = client.get_collection(CHROMA_COLLECTION)
    return _chroma_collection, _embeddings


@tool
def vector_search(query: str, n_results: int = 5) -> str:
    """Search movies by semantic similarity using vector embeddings.
    Best for: finding movies by plot description, theme, mood, or vague descriptions.
    NOT for: exact stats, counts, rankings, or numerical queries — use SQL for those.

    Args:
        query: Natural language description of what you're looking for
        n_results: Number of results to return (default 5)
    """
    collection, embeddings = _get_chroma_collection()
    query_embedding = embeddings.embed_query(query)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(n_results, 10),
        include=["documents", "metadatas", "distances"],
    )

    if not results["documents"][0]:
        return "No matching movies found."

    output = f"Found {len(results['documents'][0])} semantically similar movies:\n\n"
    for i, (doc, meta, dist) in enumerate(
        zip(results["documents"][0], results["metadatas"][0], results["distances"][0])
    ):
        similarity = round(1 - dist, 3)
        output += (
            f"{i+1}. {meta.get('title', 'Unknown')} ({meta.get('year', 'N/A')})\n"
            f"   Director: {meta.get('director', 'N/A')} | Genre: {meta.get('genre', 'N/A')} "
            f"| Rating: {meta.get('imdb_rating', 'N/A')}\n"
            f"   Similarity: {similarity}\n"
            f"   {doc[:200]}...\n\n"
        )
    return output


# ── Knowledge Graph Tool (Neo4j) ──────────────────────────────

_neo4j_driver = None


def _get_neo4j_driver():
    global _neo4j_driver
    if _neo4j_driver is None:
        _neo4j_driver = GraphDatabase.driver(
            NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)
        )
    return _neo4j_driver


@tool
def query_knowledge_graph(cypher_query: str) -> str:
    """Execute a Cypher query on the IMDB knowledge graph (Neo4j).
    Best for: relationship queries — actors who worked together, directors' filmographies,
    genre connections, collaboration networks, paths between entities.
    NOT for: exact statistics or aggregations — use SQL for those.

    Graph schema:
      Nodes: Movie (name, year, rating, votes, gross, runtime, overview, meta_score)
             Director (name), Actor (name), Genre (name)
      Relationships: (Director)-[:DIRECTED]->(Movie)
                     (Actor)-[:ACTED_IN]->(Movie)
                     (Movie)-[:HAS_GENRE]->(Genre)

    Args:
        cypher_query: A Cypher query string
    """
    try:
        driver = _get_neo4j_driver()
        with driver.session() as session:
            result = session.run(cypher_query)
            records = list(result)

            if not records:
                return "No results found."

            keys = records[0].keys()
            output = " | ".join(keys) + "\n" + "-" * 50 + "\n"
            for record in records[:30]:
                output += " | ".join(str(record[k])[:40] for k in keys) + "\n"
            return output
    except Exception as e:
        return f"Cypher Error: {e}"


@tool
def graph_schema() -> str:
    """Get the schema of the IMDB knowledge graph — node labels, relationship types, and counts.
    Use this BEFORE writing Cypher queries to understand the graph structure."""
    driver = _get_neo4j_driver()
    with driver.session() as session:
        nodes = session.run(
            "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY label"
        )
        rels = session.run(
            "MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS count ORDER BY type"
        )

        output = "=== Knowledge Graph Schema ===\n\nNode Labels:\n"
        for r in nodes:
            output += f"  :{r['label']} — {r['count']} nodes\n"
        output += "\nRelationship Types:\n"
        for r in rels:
            output += f"  [:{r['type']}] — {r['count']} relationships\n"

        output += (
            "\nPatterns:\n"
            "  (Director)-[:DIRECTED]->(Movie)\n"
            "  (Actor)-[:ACTED_IN]->(Movie)\n"
            "  (Movie)-[:HAS_GENRE]->(Genre)\n"
            "\nMovie properties: name, year, rating, votes, gross, runtime, overview, meta_score\n"
            "Director/Actor/Genre properties: name\n"
        )
        return output


# ── All tools ─────────────────────────────────────────────────

SQL_TOOLS = [list_tables, get_schema, execute_sql]
VECTOR_TOOLS = [vector_search]
GRAPH_TOOLS = [graph_schema, query_knowledge_graph]
ALL_TOOLS = SQL_TOOLS + VECTOR_TOOLS + GRAPH_TOOLS

TOOL_MAP = {t.name: t for t in ALL_TOOLS}
