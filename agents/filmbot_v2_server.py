import sys
import os

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, "filmbot_v2"))

from a2a.types import AgentSkill
from filmbot_v2.agent import SYSTEM_PROMPT
from filmbot_v2.tools import ALL_TOOLS, TOOL_MAP
from agents.enhanced_agent import build_enhanced_agent, invoke_enhanced_agent
from agents.base_server import run_agent_server

AGENT_ID = "filmbot_v2"
PORT = 9002

_agent = None

def get_agent():
    global _agent
    if _agent is None:
        _agent = build_enhanced_agent(
            original_tools=ALL_TOOLS,
            original_tool_map=TOOL_MAP,
            system_prompt=SYSTEM_PROMPT,
            temperature=0.0,
            self_agent_id=AGENT_ID,
        )
    return _agent


def invoke_agent(question: str) -> dict:
    return invoke_enhanced_agent(get_agent(), question)


SKILLS = [
    AgentSkill(
        id="movie_multimodal_query",
        name="Multi-Modal Movie Query",
        description="Query movies using SQL, vector semantic search, or knowledge graph traversal with guardrails.",
        tags=["movies", "imdb", "sql", "vector", "knowledge-graph", "guardrails"],
        examples=[
            "Find movies similar to Inception",
            "What movies did Christopher Nolan direct?",
            "Top rated sci-fi movies",
        ],
    )
]

if __name__ == "__main__":
    run_agent_server(
        agent_id=AGENT_ID,
        name="FilmBot V2",
        description="Advanced movie expert with SQL, vector search, and knowledge graph capabilities plus guardrails.",
        port=PORT,
        invoke_fn=invoke_agent,
        skills=SKILLS,
    )
