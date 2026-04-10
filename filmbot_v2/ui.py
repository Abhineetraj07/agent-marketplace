"""
FilmBot V2 — Streamlit UI with Knowledge Graph Visualization.
"""

import sys
import os
import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network
from neo4j import GraphDatabase

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent import invoke_agent
from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD


# ── Page Config ───────────────────────────────────────────────

st.set_page_config(
    page_title="FilmBot V2",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────

st.markdown("""
<style>
    .main-header {
        text-align: center;
        padding: 1rem 0;
    }
    .main-header h1 {
        background: linear-gradient(135deg, #FF6B6B, #4ECDC4, #45B7D1);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 2.5rem;
        font-weight: 800;
    }
    .main-header p {
        color: #888;
        font-size: 1rem;
    }
    .tool-badge {
        display: inline-block;
        padding: 0.2rem 0.6rem;
        border-radius: 1rem;
        font-size: 0.75rem;
        font-weight: 600;
        margin: 0.1rem;
    }
    .tool-sql { background: #DBEAFE; color: #1E40AF; }
    .tool-vector { background: #D1FAE5; color: #065F46; }
    .tool-graph { background: #FDE68A; color: #92400E; }
    .guardrail-blocked {
        background: #FEE2E2;
        border-left: 4px solid #EF4444;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    .metric-card {
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 0.75rem;
        padding: 1rem;
        text-align: center;
    }
    .stChatMessage { max-width: 100% !important; }
</style>
""", unsafe_allow_html=True)


# ── Helper Functions ──────────────────────────────────────────

def get_tool_badge(tool_name: str) -> str:
    if tool_name in ("list_tables", "get_schema", "execute_sql"):
        return f'<span class="tool-badge tool-sql">SQL: {tool_name}</span>'
    elif tool_name == "vector_search":
        return f'<span class="tool-badge tool-vector">Vector: {tool_name}</span>'
    elif tool_name in ("graph_schema", "query_knowledge_graph"):
        return f'<span class="tool-badge tool-graph">Graph: {tool_name}</span>'
    return f'<span class="tool-badge">{tool_name}</span>'


def get_retrieval_mode(tools_used: list[str]) -> str:
    modes = set()
    for t in tools_used:
        if t in ("list_tables", "get_schema", "execute_sql"):
            modes.add("SQL")
        elif t == "vector_search":
            modes.add("Vector Search")
        elif t in ("graph_schema", "query_knowledge_graph"):
            modes.add("Knowledge Graph")
    return " + ".join(sorted(modes)) if modes else "Direct"


def build_graph_visualization(question: str) -> str | None:
    """Query Neo4j for relevant graph data and build a pyvis visualization."""
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        q_lower = question.lower()

        # Determine what to visualize based on the question
        cypher = None

        # Extract potential entity names from question
        if any(kw in q_lower for kw in ["director", "directed", "nolan", "spielberg", "tarantino", "scorsese"]):
            # Try to extract director name
            for name in _extract_names(question):
                cypher = f"""
                MATCH (d:Director)-[:DIRECTED]->(m:Movie)<-[:ACTED_IN]-(a:Actor)
                WHERE d.name CONTAINS '{name}'
                RETURN d, m, a LIMIT 40
                """
                break

        elif any(kw in q_lower for kw in ["actor", "acted", "star", "worked with"]):
            for name in _extract_names(question):
                cypher = f"""
                MATCH (a:Actor)-[:ACTED_IN]->(m:Movie)<-[:DIRECTED]-(d:Director)
                WHERE a.name CONTAINS '{name}'
                RETURN a, m, d LIMIT 40
                """
                break

        elif any(kw in q_lower for kw in ["genre", "action", "drama", "comedy", "thriller", "sci-fi", "horror"]):
            genres = [g for g in ["Action", "Drama", "Comedy", "Thriller", "Sci-Fi", "Horror", "Romance", "Crime"]
                      if g.lower() in q_lower]
            if genres:
                cypher = f"""
                MATCH (m:Movie)-[:HAS_GENRE]->(g:Genre {{name: '{genres[0]}'}})
                MATCH (m)<-[:DIRECTED]-(d:Director)
                RETURN m, g, d LIMIT 40
                """

        if not cypher:
            # Default: show a small sample of the graph
            cypher = """
            MATCH (d:Director)-[:DIRECTED]->(m:Movie)-[:HAS_GENRE]->(g:Genre)
            RETURN d, m, g LIMIT 50
            """

        with driver.session() as session:
            result = session.run(cypher)
            records = list(result)

        driver.close()

        if not records:
            return None

        # Build pyvis network
        net = Network(height="450px", width="100%", bgcolor="#0E1117", font_color="white")
        net.barnes_hut(gravity=-8000, central_gravity=0.3, spring_length=150)

        added_nodes = set()
        colors = {
            "Movie": "#45B7D1",
            "Director": "#FF6B6B",
            "Actor": "#4ECDC4",
            "Genre": "#FDE68A",
        }

        for record in records:
            for key in record.keys():
                node = record[key]
                if hasattr(node, "labels"):
                    label = list(node.labels)[0]
                    name = node.get("name", "Unknown")
                    node_id = f"{label}:{name}"

                    if node_id not in added_nodes:
                        size = 25 if label == "Movie" else 20
                        title = f"{label}: {name}"
                        if label == "Movie" and node.get("rating"):
                            title += f"\nRating: {node.get('rating')}"
                            title += f"\nYear: {node.get('year', 'N/A')}"
                        net.add_node(node_id, label=name[:20], color=colors.get(label, "#999"),
                                     size=size, title=title, shape="dot")
                        added_nodes.add(node_id)

            # Add edges between consecutive node pairs
            keys = list(record.keys())
            for i in range(len(keys) - 1):
                n1, n2 = record[keys[i]], record[keys[i + 1]]
                if hasattr(n1, "labels") and hasattr(n2, "labels"):
                    l1, l2 = list(n1.labels)[0], list(n2.labels)[0]
                    id1 = f"{l1}:{n1.get('name', '')}"
                    id2 = f"{l2}:{n2.get('name', '')}"
                    if id1 in added_nodes and id2 in added_nodes:
                        net.add_edge(id1, id2, color="#555")

        html_path = "/tmp/filmbot_graph.html"
        net.save_graph(html_path)

        with open(html_path, "r") as f:
            return f.read()

    except Exception as e:
        return None


def _extract_names(text: str) -> list[str]:
    """Extract potential proper names (capitalized words) from text."""
    words = text.split()
    names = []
    current_name = []

    for word in words:
        cleaned = word.strip("?.,!'\"")
        if cleaned and cleaned[0].isupper() and cleaned.lower() not in (
            "which", "who", "what", "how", "the", "a", "an", "find", "show",
            "list", "get", "movies", "films", "actors", "directors", "with",
            "have", "has", "worked", "acted", "directed", "and", "or", "in",
            "are", "is", "top", "best", "knowledge", "graph",
        ):
            current_name.append(cleaned)
        else:
            if current_name:
                names.append(" ".join(current_name))
                current_name = []
    if current_name:
        names.append(" ".join(current_name))

    return names


# ── Sidebar ───────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### Settings")

    show_graph = st.toggle("Show Knowledge Graph", value=True)
    show_metrics = st.toggle("Show Metrics", value=True)

    st.markdown("---")
    st.markdown("### Retrieval Modes")
    st.markdown("""
    - **SQL** — Rankings, stats, counts
    - **Vector** — Plot/theme similarity
    - **Graph** — Relationships, networks
    """)

    st.markdown("---")
    st.markdown("### Sample Questions")

    sample_questions = [
        "Top 5 movies by IMDb rating",
        "Movies about time travel and love",
        "Which actors worked with Christopher Nolan?",
        "Find war movies with a tragic ending",
        "Directors who made both Drama and Sci-Fi",
        "Movies where Al Pacino starred",
        "How many Comedy movies are there?",
    ]

    for q in sample_questions:
        if st.button(q, key=f"sample_{q}", use_container_width=True):
            st.session_state.pending_question = q

    st.markdown("---")
    st.markdown("### Guardrails Active")
    st.markdown("""
    - Data/Content Accuracy
    - Role-Based Restrictions
    - Data Access & Compliance
    - Ethical & Compliance
    - Real-Time Monitoring
    - Security & Privacy
    - Rate Limiting
    """)

    st.markdown("---")
    if st.button("Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()


# ── Header ────────────────────────────────────────────────────

st.markdown("""
<div class="main-header">
    <h1>FilmBot V2</h1>
    <p>Multi-Modal AI Movie Agent — SQL + Vector Search + Knowledge Graph</p>
</div>
""", unsafe_allow_html=True)


# ── Chat ──────────────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant" and "metadata" in msg:
            meta = msg["metadata"]
            if meta.get("guardrail_blocked"):
                st.markdown(
                    f'<div class="guardrail-blocked">Guardrail: {meta["guardrail_category"]}</div>',
                    unsafe_allow_html=True,
                )
            elif meta.get("tools_used"):
                badges = " ".join(get_tool_badge(t) for t in meta["tools_used"])
                st.markdown(badges, unsafe_allow_html=True)
                if show_metrics:
                    cols = st.columns(4)
                    cols[0].metric("Mode", get_retrieval_mode(meta["tools_used"]))
                    cols[1].metric("Latency", f"{meta['latency']}s")
                    cols[2].metric("Tool Calls", meta["tool_calls"])
                    cols[3].metric("Tokens", meta["prompt_tokens"] + meta["completion_tokens"])
            if "graph_html" in msg and msg["graph_html"] and show_graph:
                with st.expander("Knowledge Graph Visualization", expanded=True):
                    components.html(msg["graph_html"], height=470, scrolling=False)

# Handle input
question = st.chat_input("Ask me about movies...")

# Check for sample question clicks
if "pending_question" in st.session_state:
    question = st.session_state.pending_question
    del st.session_state.pending_question

if question:
    # Show user message
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    # Get response
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            result = invoke_agent(question)

        st.markdown(result["response"])

        graph_html = None

        if result.get("guardrail_blocked"):
            st.markdown(
                f'<div class="guardrail-blocked">Guardrail: {result["guardrail_category"]}</div>',
                unsafe_allow_html=True,
            )
        elif result["tools_used"]:
            badges = " ".join(get_tool_badge(t) for t in result["tools_used"])
            st.markdown(badges, unsafe_allow_html=True)

            if show_metrics:
                cols = st.columns(4)
                cols[0].metric("Mode", get_retrieval_mode(result["tools_used"]))
                cols[1].metric("Latency", f"{result['latency']}s")
                cols[2].metric("Tool Calls", result["tool_calls"])
                cols[3].metric("Tokens", result["prompt_tokens"] + result["completion_tokens"])

            # Show graph visualization if graph tools were used
            if show_graph and any(t in result["tools_used"] for t in ("graph_schema", "query_knowledge_graph")):
                graph_html = build_graph_visualization(question)
                if graph_html:
                    with st.expander("Knowledge Graph Visualization", expanded=True):
                        components.html(graph_html, height=470, scrolling=False)

    # Save to history
    st.session_state.messages.append({
        "role": "assistant",
        "content": result["response"],
        "metadata": result,
        "graph_html": graph_html,
    })
