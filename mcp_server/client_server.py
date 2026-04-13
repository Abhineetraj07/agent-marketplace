"""
Lightweight MCP client server — connects to a REMOTE marketplace over HTTP.

This is what OTHER users install to use your marketplace from Claude Desktop.
No database, no agent code needed — just HTTP calls to the deployed marketplace.

Usage:
    python -m mcp_server.client_server                          # default: localhost:8000
    MARKETPLACE_URL=http://54.123.45.67:8000 python -m mcp_server.client_server

Claude Desktop config for remote users:
{
    "mcpServers": {
        "ai-marketplace": {
            "command": "python",
            "args": ["-m", "mcp_server.client_server"],
            "env": {
                "MARKETPLACE_URL": "http://YOUR-EC2-IP:8000"
            }
        }
    }
}
"""

import os
import httpx
from fastmcp import FastMCP

MARKETPLACE_URL = os.environ.get("MARKETPLACE_URL", "http://localhost:8000")

mcp = FastMCP(
    "Agent Marketplace",
    instructions=f"Browse, purchase, and query AI agents at {MARKETPLACE_URL}",
)


@mcp.tool()
def list_agents() -> str:
    """List all AI agents available in the marketplace.

    Returns agent names, IDs, descriptions, and skills.
    No authentication required.
    """
    try:
        resp = httpx.get(f"{MARKETPLACE_URL}/agents", timeout=10.0)
        resp.raise_for_status()
        agents = resp.json()

        if not agents:
            return "No agents are currently registered."

        lines = []
        for a in agents:
            card = a.get("card_json", {})
            if isinstance(card, str):
                import json
                card = json.loads(card)
            skills = card.get("skills", [])
            skill_names = [s.get("name", "") for s in skills]

            lines.append(
                f"- {a['name']} (id: {a['agent_id']}): {a['description']}\n"
                f"  Skills: {', '.join(skill_names) or 'N/A'}"
            )

        return "Available agents:\n\n" + "\n\n".join(lines)
    except httpx.ConnectError:
        return f"Cannot connect to marketplace at {MARKETPLACE_URL}. Is it running?"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def signup(username: str, password: str) -> str:
    """Create a new account on the marketplace. Returns a JWT token and 100 free credits.

    Args:
        username: Your desired username
        password: Your password (min 8 chars, needs uppercase, lowercase, number, special char)
    """
    try:
        resp = httpx.post(
            f"{MARKETPLACE_URL}/auth/signup",
            json={"username": username, "password": password},
            timeout=10.0,
        )
        if resp.status_code == 429:
            return "Rate limited. Try again in a minute."
        if resp.status_code != 200:
            return f"Signup failed: {resp.json().get('detail', resp.text)}"

        data = resp.json()
        return (
            f"Account created!\n"
            f"Username: {data['user']['username']}\n"
            f"Credits: {data['user']['credits']}\n"
            f"JWT Token: {data['token']}\n\n"
            f"Use this JWT token to purchase agents."
        )
    except httpx.ConnectError:
        return f"Cannot connect to marketplace at {MARKETPLACE_URL}."
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def login(username: str, password: str) -> str:
    """Log in to your marketplace account. Returns a fresh JWT token.

    Args:
        username: Your username
        password: Your password
    """
    try:
        resp = httpx.post(
            f"{MARKETPLACE_URL}/auth/login",
            json={"username": username, "password": password},
            timeout=10.0,
        )
        if resp.status_code == 429:
            return "Rate limited. Try again in a minute."
        if resp.status_code != 200:
            return f"Login failed: {resp.json().get('detail', resp.text)}"

        data = resp.json()
        return (
            f"Logged in!\n"
            f"Username: {data['user']['username']}\n"
            f"Credits: {data['user']['credits']}\n"
            f"JWT Token: {data['token']}"
        )
    except httpx.ConnectError:
        return f"Cannot connect to marketplace at {MARKETPLACE_URL}."
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def purchase_agent(agent_id: str, jwt_token: str) -> str:
    """Purchase an AI agent. Returns an API key for querying.

    Args:
        agent_id: The agent to buy (e.g., 'filmbot', 'melody', 'rock', 'filmbot_v2')
        jwt_token: Your JWT token from signup/login
    """
    try:
        resp = httpx.post(
            f"{MARKETPLACE_URL}/agents/{agent_id}/buy",
            headers={"Authorization": f"Bearer {jwt_token}"},
            timeout=10.0,
        )
        if resp.status_code != 200:
            return f"Purchase failed: {resp.json().get('detail', resp.text)}"

        data = resp.json()
        return (
            f"Purchased '{agent_id}'!\n"
            f"API Key: {data.get('api_key', 'N/A')}\n"
            f"Query cost: {data.get('query_cost', '?')} credits/query\n"
            f"Credits remaining: {data.get('credits_remaining', '?')}\n\n"
            f"Use this API key with query_agent to ask questions."
        )
    except httpx.ConnectError:
        return f"Cannot connect to marketplace at {MARKETPLACE_URL}."
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def query_agent(agent_id: str, question: str, api_key: str) -> str:
    """Ask an AI agent a question. Goes through the full security pipeline.

    Args:
        agent_id: The agent to query (e.g., 'filmbot', 'melody', 'rock')
        question: Your question
        api_key: Your API key (starts with 'mk_')
    """
    try:
        resp = httpx.post(
            f"{MARKETPLACE_URL}/api/v1/chat",
            json={"message": question},
            headers={"x-api-key": api_key},
            timeout=300.0,
        )
        if resp.status_code == 401:
            return "Invalid or revoked API key."
        if resp.status_code == 402:
            return "Insufficient credits."
        if resp.status_code == 429:
            return "Rate limited. Try again in a minute."
        if resp.status_code == 400:
            detail = resp.json().get("detail", "")
            return f"Blocked: {detail}"
        if resp.status_code != 200:
            return f"Error: {resp.json().get('detail', resp.text)}"

        data = resp.json()
        return (
            f"{data['response']}\n\n"
            f"[Agent: {data.get('agent', agent_id)} | "
            f"Credits used: {data.get('credits_used', '?')} | "
            f"Remaining: {data.get('credits_remaining', '?')}]"
        )
    except httpx.ConnectError:
        return f"Cannot connect to marketplace at {MARKETPLACE_URL}."
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def get_credits(api_key: str) -> str:
    """Check your remaining credits.

    Args:
        api_key: Your API key (starts with 'mk_')
    """
    try:
        resp = httpx.post(
            f"{MARKETPLACE_URL}/api/v1/chat",
            json={"message": "hi"},
            headers={"x-api-key": api_key},
            timeout=10.0,
        )
        # Even if it works or fails, the error message shows credit info
        data = resp.json()
        if "credits_remaining" in data:
            return f"Credits remaining: {data['credits_remaining']}"
        return f"API key status: {data.get('detail', 'valid')}"
    except httpx.ConnectError:
        return f"Cannot connect to marketplace at {MARKETPLACE_URL}."
    except Exception as e:
        return f"Error: {e}"


if __name__ == "__main__":
    mcp.run()
