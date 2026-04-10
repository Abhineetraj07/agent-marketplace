import asyncio
from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, A2AClient
from a2a.types import Message, MessageSendParams, SendMessageRequest, TextPart, Role, Task


class MarketplaceClient:
    """Client for discovering agents and communicating via the marketplace."""

    def __init__(self, marketplace_url: str = "http://localhost:8000", requester_id: str = "client", secret: str = ""):
        self.marketplace_url = marketplace_url
        self.requester_id = requester_id
        self.secret = secret

    async def discover_agents(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(f"{self.marketplace_url}/agents")
            resp.raise_for_status()
            return resp.json()

    async def get_agent(self, agent_id: str) -> dict:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(f"{self.marketplace_url}/agents/{agent_id}")
            resp.raise_for_status()
            return resp.json()

    async def get_token(self, target_agent_id: str, ttl_seconds: int = 3600) -> str:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.post(
                f"{self.marketplace_url}/tokens",
                json={
                    "target_agent_id": target_agent_id,
                    "requester_id": self.requester_id,
                    "ttl_seconds": ttl_seconds,
                },
                headers={"x-marketplace-secret": self.secret},
            )
            resp.raise_for_status()
            return resp.json()["token"]

    async def call_agent(self, agent_id: str, question: str) -> str:
        """Discover agent, get a token, and send a message via A2A."""
        # Get agent info
        agent_info = await self.get_agent(agent_id)
        agent_url = agent_info["url"]

        # Get scoped token
        token = await self.get_token(agent_id)

        # Call via A2A
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(300.0),
            headers={"Authorization": f"Bearer {token}"},
        ) as httpx_client:
            a2a_client = A2AClient(httpx_client=httpx_client, url=agent_url)

            message = Message(
                role=Role.user,
                parts=[TextPart(text=question)],
                message_id=uuid4().hex,
            )

            request = SendMessageRequest(
                id=uuid4().hex,
                params=MessageSendParams(message=message),
            )

            response = await a2a_client.send_message(request)
            return self._extract_response(response)

    @staticmethod
    def _extract_response(response) -> str:
        result = response.root
        if hasattr(result, "result"):
            inner = result.result
            if isinstance(inner, Task):
                if inner.artifacts:
                    for artifact in inner.artifacts:
                        for part in artifact.parts:
                            inner_part = part.root if hasattr(part, "root") else part
                            if hasattr(inner_part, "text"):
                                return inner_part.text
                if inner.history:
                    for msg in reversed(inner.history):
                        if msg.role == Role.agent:
                            for part in msg.parts:
                                inner_part = part.root if hasattr(part, "root") else part
                                if hasattr(inner_part, "text"):
                                    return inner_part.text
            else:
                for part in inner.parts:
                    inner_part = part.root if hasattr(part, "root") else part
                    if hasattr(inner_part, "text"):
                        return inner_part.text

        if hasattr(result, "error"):
            return f"Error: {result.error.message}"
        return "No response"
