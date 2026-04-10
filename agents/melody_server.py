import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from a2a.types import AgentSkill
from rock2 import TOOLS, TOOL_MAP, SYSTEM_PROMPT
from agents.enhanced_agent import build_enhanced_agent, invoke_enhanced_agent
from agents.base_server import run_agent_server

AGENT_ID = "melody"
PORT = 9003

_agent = None

def get_agent():
    global _agent
    if _agent is None:
        _agent = build_enhanced_agent(
            original_tools=TOOLS,
            original_tool_map=TOOL_MAP,
            system_prompt=SYSTEM_PROMPT,
            temperature=0.7,
            self_agent_id=AGENT_ID,
        )
    return _agent


def invoke_agent(question: str) -> dict:
    return invoke_enhanced_agent(get_agent(), question)


SKILLS = [
    AgentSkill(
        id="music_query",
        name="Music Store Query",
        description="Query the Chinook music store database for artists, albums, tracks, genres, playlists, and sales.",
        tags=["music", "chinook", "database", "sql"],
        examples=[
            "How many artists are in the database?",
            "Top 5 genres by number of tracks",
            "Which album has the most tracks?",
        ],
    )
]

if __name__ == "__main__":
    run_agent_server(
        agent_id=AGENT_ID,
        name="Melody Bot",
        description="Music store assistant that queries the Chinook database for artists, albums, tracks, and more.",
        port=PORT,
        invoke_fn=invoke_agent,
        skills=SKILLS,
    )
