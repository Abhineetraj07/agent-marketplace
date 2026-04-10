"""
FilmBot V2 — Multi-modal LangGraph agent with three retrieval modes:
  1. SQL (SQLite) — structured queries, stats, rankings
  2. Vector Search (ChromaDB) — semantic similarity over plot overviews
  3. Knowledge Graph (Neo4j) — relationship traversal via Cypher
"""

import operator
import time
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, END
from langchain_ollama import ChatOllama
from langchain_core.messages import (
    HumanMessage, AIMessage, SystemMessage, ToolMessage,
)

from config import OLLAMA_MODEL
from tools import ALL_TOOLS, TOOL_MAP
from guardrails import GuardrailEngine


# ── System Prompt ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are FilmBot V2, an advanced AI movie expert with access to THREE retrieval systems over the IMDB movies database (1,000 movies).

=== YOUR TOOLS ===

1. **SQL Tools** (SQLite) — for structured data queries
   - `list_tables` → discover tables (use FIRST)
   - `get_schema` → understand table structure (use SECOND)
   - `execute_sql` → run SQL queries
   Best for: rankings, counts, averages, filtering, aggregations, exact lookups

2. **Vector Search** (ChromaDB) — semantic similarity over movie overviews
   - `vector_search` → find movies by meaning/theme/plot description
   Best for: "movies like...", plot-based searches, thematic queries, mood-based recommendations

3. **Knowledge Graph** (Neo4j) — relationship traversal
   - `graph_schema` → see graph structure (use before writing Cypher)
   - `query_knowledge_graph` → run Cypher queries
   Best for: relationships between actors/directors/genres, collaboration networks,
   "who worked with whom", shared connections, genre-crossing patterns

=== ROUTING STRATEGY ===

Choose the RIGHT tool based on the question type:
- "Top 5 movies by rating" → SQL (aggregation)
- "Movies about a heist gone wrong" → Vector Search (semantic)
- "Actors who worked with Christopher Nolan" → Knowledge Graph (relationship)
- "Movies where Actor X and Actor Y appeared together" → Knowledge Graph
- "War movies with a love story" → Vector Search (thematic)
- "Average rating of Action movies" → SQL (aggregation)
- "Directors who worked across Drama and Sci-Fi" → Knowledge Graph (cross-genre)

You can combine multiple tools for complex questions. For example:
- Use Knowledge Graph to find related entities, then SQL for stats about them.
- Use Vector Search for thematic matches, then SQL for filtering/ranking.

=== RULES ===
- ONLY answer questions about the IMDB movies database.
- For non-movie questions, politely decline and redirect.
- Greetings and casual chat are allowed.
- Always verify schema/structure before writing queries.
- Be friendly, concise, and cinematic in your responses!

=== SQL TIPS ===
- imdb_rating is REAL (0-10), released_year is TEXT, gross is TEXT with commas
- Stars are in star1, star2, star3, star4 — check ALL with OR for actor searches
- Use LIKE for partial text matches (e.g., genre LIKE '%Action%')
"""


# ── Agent State ───────────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    token_usage: Annotated[list, operator.add]


# ── Nodes ─────────────────────────────────────────────────────

llm = ChatOllama(model=OLLAMA_MODEL, temperature=0.0).bind_tools(ALL_TOOLS)


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
        tool_fn = TOOL_MAP.get(tool_call["name"])
        if tool_fn:
            result = tool_fn.invoke(tool_call["args"])
        else:
            result = f"Unknown tool: {tool_call['name']}"
        results.append(ToolMessage(content=result, tool_call_id=tool_call["id"]))

    return {"messages": results}


def should_use_tools(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "end"


# ── Build Graph ───────────────────────────────────────────────

def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("llm", llm_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("llm")
    graph.add_conditional_edges("llm", should_use_tools, {"tools": "tools", "end": END})
    graph.add_edge("tools", "llm")
    return graph.compile()


_agent = None


def get_agent():
    global _agent
    if _agent is None:
        _agent = build_graph()
    return _agent


# ── Invoke ────────────────────────────────────────────────────

_guardrails = GuardrailEngine()


def invoke_agent(question: str, user_role: str = "user") -> dict:
    """Run a question through FilmBot V2 with guardrails and return response + metrics."""

    # ── Input Guardrails ──
    input_check = _guardrails.check_input(question, user_role)
    if not input_check.passed:
        return {
            "response": input_check.message,
            "latency": 0.0,
            "tool_calls": 0,
            "tools_used": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "guardrail_blocked": True,
            "guardrail_category": input_check.category,
        }

    # ── Agent Execution ──
    agent = get_agent()

    start_time = time.time()
    result = agent.invoke({
        "messages": [HumanMessage(content=question)],
        "token_usage": [],
    })
    latency = time.time() - start_time

    ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
    response = ai_messages[-1].content if ai_messages else "No response"

    tool_calls = sum(1 for m in result["messages"] if isinstance(m, ToolMessage))
    tools_used = list({
        tc["name"]
        for m in result["messages"] if isinstance(m, AIMessage) and m.tool_calls
        for tc in m.tool_calls
    })

    prompt_tokens = sum(t["prompt_tokens"] for t in result.get("token_usage", []))
    completion_tokens = sum(t["completion_tokens"] for t in result.get("token_usage", []))

    # ── Output Guardrails ──
    output_check = _guardrails.check_output(question, response, tools_used)
    if not output_check.passed:
        response = output_check.message

    # ── Log Interaction ──
    _guardrails.log_interaction(question, response, tools_used, latency, user_role)

    return {
        "response": response,
        "latency": round(latency, 2),
        "tool_calls": tool_calls,
        "tools_used": tools_used,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "guardrail_blocked": False,
        "guardrail_category": None,
    }
