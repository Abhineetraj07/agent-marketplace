import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from a2a.types import AgentSkill
from filmbot_agent import TOOLS, TOOL_MAP, SYSTEM_PROMPT
from agents.enhanced_agent import build_enhanced_agent, invoke_enhanced_agent
from agents.base_server import run_agent_server

AGENT_ID = "filmbot"
PORT = 9001

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
        id="movie_query",
        name="Movie Database Query",
        description="Query the IMDB movie database for information about movies, ratings, actors, directors, genres, and more.",
        tags=["movies", "imdb", "database", "sql"],
        examples=[
            "Top 5 movies by IMDb rating",
            "How many movies are in the dataset?",
            "Movies with IMDb rating above 9",
        ],
    )
]

if __name__ == "__main__":
    run_agent_server(
        agent_id=AGENT_ID,
        name="FilmBot",
        description="AI movie expert that queries an IMDB database for ratings, actors, directors, and more.",
        port=PORT,
        invoke_fn=invoke_agent,
        skills=SKILLS,
    )
