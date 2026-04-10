import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from a2a.types import AgentSkill
from rock import TOOLS, TOOL_MAP, SYSTEM_PROMPT
from agents.enhanced_agent import build_enhanced_agent, invoke_enhanced_agent
from agents.base_server import run_agent_server

AGENT_ID = "rock"
PORT = 9004

_agent = None

def get_agent():
    global _agent
    if _agent is None:
        _agent = build_enhanced_agent(
            original_tools=TOOLS,
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
        id="movie_query_detailed",
        name="Detailed Movie Query",
        description="Query the IMDB database with detailed reasoning and step-by-step SQL analysis.",
        tags=["movies", "imdb", "database", "sql", "detailed"],
        examples=[
            "Top 5 movies by IMDb rating",
            "Directors with the most movies",
            "Average rating by genre",
        ],
    )
]

if __name__ == "__main__":
    run_agent_server(
        agent_id=AGENT_ID,
        name="Rock Agent",
        description="Detailed IMDB movie analyst with step-by-step SQL reasoning.",
        port=PORT,
        invoke_fn=invoke_agent,
        skills=SKILLS,
    )
