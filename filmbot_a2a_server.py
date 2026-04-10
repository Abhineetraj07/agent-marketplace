
import asyncio
import json
import os
import secrets
import uvicorn
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.apps import A2AStarletteApplication
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCard,
    AgentSkill,
    AgentCapabilities,
    HTTPAuthSecurityScheme,
    SecurityScheme,
)
from a2a.utils import new_agent_text_message

from filmbot_agent import invoke_agent

# ============================================================
# CONFIG
# ============================================================

HOST = "localhost"
PORT = 9999
TOKEN_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "a2a_token_log.json")

# Generate a secret API key on startup (printed to console for the client)
API_KEY = os.environ.get("FILMBOT_A2A_API_KEY", secrets.token_urlsafe(32))


# ============================================================
# AUTHENTICATION MIDDLEWARE
# ============================================================

class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Require Bearer token for all endpoints except agent card discovery."""

    OPEN_PATHS = {"/.well-known/agent-card.json"}

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.OPEN_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse({"error": "Missing Bearer token"}, status_code=401)

        token = auth_header[len("Bearer "):]
        if not secrets.compare_digest(token, API_KEY):
            return JSONResponse({"error": "Invalid token"}, status_code=403)

        return await call_next(request)


# ============================================================
# AGENT EXECUTOR
# ============================================================

class FilmBotExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        import time as _time

        t_start = _time.time()
        user_input = context.get_user_input()
        t_after_parse = _time.time()

        # Run sync LangGraph agent in a thread
        result = await asyncio.to_thread(invoke_agent, user_input)
        t_after_agent = _time.time()

        # Send response back via A2A
        await event_queue.enqueue_event(
            new_agent_text_message(
                result["response"],
                context_id=context.context_id,
                task_id=context.task_id,
            )
        )
        t_after_serialize = _time.time()

        # Log with detailed overhead breakdown
        _log_token_usage(context.task_id, result, {
            "parse_context_ms": round((t_after_parse - t_start) * 1000, 2),
            "agent_execution_ms": round((t_after_agent - t_after_parse) * 1000, 2),
            "serialize_response_ms": round((t_after_serialize - t_after_agent) * 1000, 2),
            "total_server_ms": round((t_after_serialize - t_start) * 1000, 2),
        })

        print(f"  [A2A Overhead] Q: {user_input[:40]}...")
        print(f"    Parse context:      {(t_after_parse - t_start)*1000:>8.2f} ms")
        print(f"    Agent execution:    {(t_after_agent - t_after_parse)*1000:>8.2f} ms")
        print(f"    Serialize response: {(t_after_serialize - t_after_agent)*1000:>8.2f} ms")
        print(f"    Server total:       {(t_after_serialize - t_start)*1000:>8.2f} ms")
        print(f"    A2A overhead:       {((t_after_serialize - t_start) - (t_after_agent - t_after_parse))*1000:>8.2f} ms")

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise Exception("Cancel not supported")


def _log_token_usage(task_id: str, result: dict, overhead: dict = None):
    """Append token usage and overhead breakdown to a JSON log file."""
    entry = {
        "task_id": task_id,
        "prompt_tokens": result["prompt_tokens"],
        "completion_tokens": result["completion_tokens"],
        "tool_calls": result["tool_calls"],
        "latency_server": result["latency"],
    }
    if overhead:
        entry["overhead"] = overhead

    log = []
    if os.path.exists(TOKEN_LOG_PATH):
        try:
            with open(TOKEN_LOG_PATH, "r") as f:
                log = json.load(f)
        except (json.JSONDecodeError, IOError):
            log = []

    log.append(entry)
    with open(TOKEN_LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)


# ============================================================
# AGENT CARD
# ============================================================

def get_agent_card() -> AgentCard:
    return AgentCard(
        name="FilmBot",
        description="AI movie expert that queries an IMDB database for ratings, actors, directors, and more.",
        url=f"http://{HOST}:{PORT}",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        security_schemes={
            "bearer": SecurityScheme(
                root=HTTPAuthSecurityScheme(
                    scheme="bearer",
                    bearer_format="API Key",
                    description="Bearer token required. Pass via Authorization header.",
                )
            ),
        },
        security=[{"bearer": []}],
        skills=[
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
        ],
    )


# ============================================================
# SERVER
# ============================================================

def create_app():
    handler = DefaultRequestHandler(
        agent_executor=FilmBotExecutor(),
        task_store=InMemoryTaskStore(),
    )
    a2a_app = A2AStarletteApplication(
        agent_card=get_agent_card(),
        http_handler=handler,
    )
    app = a2a_app.build()
    app.add_middleware(BearerAuthMiddleware)
    return app


def main():
    # Clear previous token log
    if os.path.exists(TOKEN_LOG_PATH):
        os.remove(TOKEN_LOG_PATH)

    print(f"FilmBot A2A Server starting on http://{HOST}:{PORT}")
    print(f"Agent Card: http://{HOST}:{PORT}/.well-known/agent-card.json")
    print(f"API Key: {API_KEY}")
    print("(Set FILMBOT_A2A_API_KEY env var to use a fixed key)")

    app = create_app()
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
