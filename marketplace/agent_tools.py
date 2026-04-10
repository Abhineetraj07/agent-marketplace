import os
import httpx
from langchain_core.tools import tool

from marketplace.auth import MARKETPLACE_SECRET, MARKETPLACE_URL


@tool
def list_marketplace_agents() -> str:
    """List all agents available in the marketplace. Use this to discover what other agents exist and what they can do. Returns agent names, descriptions, and skills."""
    try:
        resp = httpx.get(f"{MARKETPLACE_URL}/agents", timeout=5.0)
        resp.raise_for_status()
        agents = resp.json()

        if not agents:
            return "No agents are currently registered in the marketplace."

        lines = []
        for a in agents:
            skills = a.get("card_json", {}).get("skills", [])
            skill_names = [s.get("name", "") for s in skills]
            tags = []
            for s in skills:
                tags.extend(s.get("tags", []))

            lines.append(
                f"- {a['name']} (id: {a['agent_id']}): {a['description']}"
                f"\n  Skills: {', '.join(skill_names)}"
                f"\n  Tags: {', '.join(set(tags))}"
            )

        return "Available agents in the marketplace:\n\n" + "\n\n".join(lines)
    except Exception as e:
        return f"Error discovering agents: {e}"


@tool
def ask_agent(agent_id: str, question: str) -> str:
    """Ask another agent a question through the marketplace. Use this when you need information that another agent has access to.

    Args:
        agent_id: The ID of the agent to ask (e.g., 'filmbot', 'melody', 'rock', 'filmbot_v2')
        question: The question to ask that agent
    """
    try:
        # Step 1: Get agent info
        resp = httpx.get(f"{MARKETPLACE_URL}/agents/{agent_id}", timeout=5.0)
        if resp.status_code == 404:
            return f"Agent '{agent_id}' not found. Use list_marketplace_agents to see available agents."
        resp.raise_for_status()
        agent_info = resp.json()
        agent_url = agent_info["url"]

        # Step 2: Get a scoped token
        resp = httpx.post(
            f"{MARKETPLACE_URL}/tokens",
            json={
                "target_agent_id": agent_id,
                "requester_id": "agent-call",
                "ttl_seconds": 300,
            },
            headers={"x-marketplace-secret": MARKETPLACE_SECRET},
            timeout=5.0,
        )
        resp.raise_for_status()
        token = resp.json()["token"]

        # Step 3: Call the agent via A2A
        import uuid
        a2a_request = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex,
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": question}],
                    "messageId": uuid.uuid4().hex,
                },
            },
        }

        resp = httpx.post(
            f"{agent_url}/",
            json=a2a_request,
            headers={"Authorization": f"Bearer {token}"},
            timeout=300.0,
        )
        resp.raise_for_status()
        data = resp.json()

        # Step 4: Extract response text
        result = data.get("result", {})

        # Direct message with parts
        for part in result.get("parts", []):
            if isinstance(part, dict) and part.get("text"):
                return f"[Response from {agent_info['name']}]: {part['text']}"

        # Artifacts
        for art in result.get("artifacts", []):
            for part in art.get("parts", []):
                if isinstance(part, dict) and part.get("text"):
                    return f"[Response from {agent_info['name']}]: {part['text']}"

        # History
        for msg in reversed(result.get("history", [])):
            if msg.get("role") == "agent":
                for part in msg.get("parts", []):
                    if isinstance(part, dict) and part.get("text"):
                        return f"[Response from {agent_info['name']}]: {part['text']}"

        return f"Agent '{agent_id}' responded but no text was found in the response."

    except httpx.ConnectError:
        return f"Could not connect to agent '{agent_id}'. It may be offline."
    except Exception as e:
        return f"Error calling agent '{agent_id}': {e}"


# Convenient list for importing
MARKETPLACE_TOOLS = [list_marketplace_agents, ask_agent]
MARKETPLACE_TOOL_MAP = {
    "list_marketplace_agents": list_marketplace_agents,
    "ask_agent": ask_agent,
}
