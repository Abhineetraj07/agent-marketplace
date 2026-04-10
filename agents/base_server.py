import asyncio
import json
import os
import sys
from typing import Callable

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Route

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

from marketplace.auth import MarketplaceAuthMiddleware, MARKETPLACE_SECRET, MARKETPLACE_URL


class GenericExecutor(AgentExecutor):
    """Wraps any invoke_fn(question: str) -> dict into an A2A executor."""

    def __init__(self, invoke_fn: Callable):
        self.invoke_fn = invoke_fn

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_input = context.get_user_input()
        result = await asyncio.to_thread(self.invoke_fn, user_input)

        response_text = result.get("response", str(result))
        await event_queue.enqueue_event(
            new_agent_text_message(
                response_text,
                context_id=context.context_id,
                task_id=context.task_id,
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise Exception("Cancel not supported")


def make_agent_card(
    agent_id: str,
    name: str,
    description: str,
    port: int,
    skills: list[AgentSkill],
    host: str = "localhost",
) -> AgentCard:
    return AgentCard(
        name=name,
        description=description,
        url=f"http://{host}:{port}",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        security_schemes={
            "bearer": SecurityScheme(
                root=HTTPAuthSecurityScheme(
                    scheme="bearer",
                    bearer_format="Marketplace Token",
                    description="Token issued by the Agent Marketplace.",
                )
            ),
        },
        security=[{"bearer": []}],
        skills=skills,
    )


async def register_with_marketplace(agent_id: str, card: AgentCard):
    """Register this agent with the marketplace on startup."""
    payload = {
        "agent_id": agent_id,
        "name": card.name,
        "description": card.description,
        "url": card.url,
        "card_json": json.loads(card.model_dump_json()),
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.post(
                f"{MARKETPLACE_URL}/agents/register",
                json=payload,
                headers={"x-marketplace-secret": MARKETPLACE_SECRET},
            )
        if resp.status_code == 200:
            print(f"  Registered with marketplace as '{agent_id}'")
        else:
            print(f"  Marketplace registration failed: {resp.status_code} {resp.text}")
    except httpx.ConnectError:
        print(f"  WARNING: Marketplace not reachable at {MARKETPLACE_URL} — running standalone")


def make_a2a_app(
    agent_id: str,
    name: str,
    description: str,
    port: int,
    invoke_fn: Callable,
    skills: list[AgentSkill],
    host: str = "localhost",
) -> tuple[Starlette, AgentCard]:
    card = make_agent_card(agent_id, name, description, port, skills, host)

    handler = DefaultRequestHandler(
        agent_executor=GenericExecutor(invoke_fn),
        task_store=InMemoryTaskStore(),
    )

    a2a_app = A2AStarletteApplication(
        agent_card=card,
        http_handler=handler,
    )
    app = a2a_app.build()
    app.add_middleware(MarketplaceAuthMiddleware, marketplace_url=MARKETPLACE_URL, agent_id=agent_id)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app, card


def run_agent_server(
    agent_id: str,
    name: str,
    description: str,
    port: int,
    invoke_fn: Callable,
    skills: list[AgentSkill],
    host: str = "localhost",
):
    app, card = make_a2a_app(agent_id, name, description, port, invoke_fn, skills, host)

    async def on_startup():
        await register_with_marketplace(agent_id, card)

    app.add_event_handler("startup", on_startup)

    print(f"{name} A2A Server starting on http://{host}:{port}")
    print(f"Agent Card: http://{host}:{port}/.well-known/agent-card.json")
    uvicorn.run(app, host=host, port=port)
