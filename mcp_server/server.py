"""
MCP Server for the Agent Marketplace.

Exposes marketplace tools via the Model Context Protocol so MCP clients
(Claude Desktop, etc.) can browse agents, purchase them, query them,
and check credits — all through the same security pipeline as the HTTP API.

Usage:
    python -m mcp_server.server              # stdio transport (Claude Desktop)
    python -m mcp_server.server --sse 8100   # SSE transport on port 8100
"""

import sys
import os
import json
import uuid
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastmcp import FastMCP

from marketplace.db import init_db, list_agents as db_list_agents, get_agent, create_token, log_usage
from marketplace.users import (
    validate_api_key, get_user, verify_jwt, deduct_credits, add_credits,
    purchase_agent as db_purchase_agent, AGENT_QUERY_COST,
)
from marketplace.sanitizer import sanitize_input, sanitize_output
from marketplace.rate_limiter import rate_limiter
from mcp_server.auth_bridge import authenticate_api_key, authenticate_jwt
from mcp_server.defenses import (
    sanitize_tool_description,
    tool_registry,
    definition_monitor,
    sandbox,
    validate_tool_manifest,
)

# Initialize DB on import
init_db()

mcp = FastMCP(
    "Agent Marketplace",
    instructions="Browse, purchase, and query AI agents in the marketplace",
)


# ── Tool 1: List Agents (no auth) ──────────────────────────────

@mcp.tool()
def list_agents() -> str:
    """List all AI agents available in the marketplace.

    Returns agent names, IDs, descriptions, skills, and pricing.
    No authentication required.
    """
    agents = db_list_agents()
    if not agents:
        return "No agents are currently registered in the marketplace."

    lines = []
    for a in agents:
        card = json.loads(a["card_json"]) if isinstance(a["card_json"], str) else a["card_json"]
        skills = card.get("skills", [])
        skill_names = [s.get("name", "") for s in skills]

        lines.append(
            f"- {a['name']} (id: {a['agent_id']}): {a['description']}\n"
            f"  Skills: {', '.join(skill_names) or 'N/A'}"
        )

    return "Available agents:\n\n" + "\n\n".join(lines)


# ── Tool 2: Query Agent (API key auth) ─────────────────────────

@mcp.tool()
async def query_agent(agent_id: str, question: str, api_key: str) -> str:
    """Ask an AI agent a question. Requires a valid API key for that agent.

    This goes through the full security pipeline: auth, rate limiting,
    input sanitization, credit deduction, agent call, output sanitization.

    Args:
        agent_id: The agent to query (e.g., 'filmbot', 'melody', 'rock')
        question: Your question for the agent
        api_key: Your API key (starts with 'mk_')
    """
    # Step 1: Validate API key
    key_info = validate_api_key(api_key)
    if not key_info:
        return "Error: Invalid or revoked API key."

    user_id = key_info["user_id"]
    key_agent_id = key_info["agent_id"]

    # Verify key matches requested agent
    if key_agent_id != agent_id:
        return f"Error: This API key is for agent '{key_agent_id}', not '{agent_id}'."

    # Step 2: Check account status
    user = get_user(user_id)
    if not user or user["locked"]:
        return "Error: Account is locked."

    # Step 3: Rate limit
    rate_check = rate_limiter.check(user_id)
    if not rate_check["allowed"]:
        return f"Rate limited. Try again in {rate_check['retry_after']} seconds."

    # Step 4: Input sanitization
    input_check = sanitize_input(question)
    if not input_check["safe"]:
        log_usage(user_id, agent_id, question, 0, True, input_check["reason"], "mcp-client")
        return f"Blocked: {input_check['reason']} detected in your question."

    # Step 5: Deduct credits
    query_cost = AGENT_QUERY_COST.get(agent_id, 1)
    if not deduct_credits(user_id, query_cost):
        return f"Insufficient credits. Need {query_cost}, have {user['credits']}."

    # Step 6: Get agent info and call
    agent_info = get_agent(agent_id)
    if not agent_info:
        add_credits(user_id, query_cost)  # Refund
        return f"Agent '{agent_id}' is not available."

    agent_url = agent_info["url"]
    token_data = create_token(agent_id, f"user:{user_id}", 300)
    token = token_data["token"]

    try:
        response_text = await _call_agent_a2a(agent_url, token, question)
    except Exception as e:
        add_credits(user_id, query_cost)  # Refund
        log_usage(user_id, agent_id, question, 0, True, f"agent_error: {str(e)[:100]}", "mcp-client")
        return f"Error from agent: {str(e)[:200]}"

    # Step 7: Output sanitization
    output_check = sanitize_output(response_text)
    cleaned_response = output_check["cleaned"]

    # Step 8: Log usage
    log_usage(user_id, agent_id, question, query_cost, False, "", "mcp-client")

    # Step 9: Return response
    updated_user = get_user(user_id)
    credits_remaining = updated_user["credits"] if updated_user else 0
    return f"{cleaned_response}\n\n[Credits used: {query_cost} | Remaining: {credits_remaining}]"


# ── Tool 3: Get Credits (API key auth) ─────────────────────────

@mcp.tool()
def get_credits(api_key: str) -> str:
    """Check your remaining credits using an API key.

    Args:
        api_key: Your API key (starts with 'mk_')
    """
    ctx = authenticate_api_key(api_key)
    if not ctx:
        return "Error: Invalid or revoked API key."

    return (
        f"User: {ctx['username']}\n"
        f"Credits: {ctx['credits']}\n"
        f"API key agent: {ctx['agent_id']}"
    )


# ── Tool 4: Purchase Agent (JWT auth) ──────────────────────────

@mcp.tool()
def purchase_agent(agent_id: str, jwt_token: str) -> str:
    """Purchase an AI agent using your JWT token. Returns an API key.

    You need credits to purchase. Get a JWT by logging in at the marketplace.

    Args:
        agent_id: The agent to purchase (e.g., 'filmbot', 'melody', 'rock', 'filmbot_v2')
        jwt_token: Your JWT token from logging in
    """
    ctx = authenticate_jwt(jwt_token)
    if not ctx:
        return "Error: Invalid or expired JWT token."

    result = db_purchase_agent(ctx["user_id"], agent_id)
    if not result["success"]:
        return f"Purchase failed: {result['error']}"

    return (
        f"Successfully purchased '{agent_id}'!\n"
        f"API Key: {result['api_key']}\n"
        f"Query cost: {result['query_cost']} credits/query\n"
        f"Credits remaining: {result['credits_remaining']}"
    )


# ── A2A helper ──────────────────────────────────────────────────

async def _call_agent_a2a(agent_url: str, token: str, question: str) -> str:
    """Send an A2A message to an agent and extract the response text."""
    import httpx

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

    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
        resp = await client.post(
            f"{agent_url}/",
            json=a2a_request,
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        data = resp.json()

    result = data.get("result", {})

    # Direct parts
    for part in result.get("parts", []):
        if isinstance(part, dict) and part.get("text"):
            return part["text"]

    # Artifacts
    for art in result.get("artifacts", []):
        for part in art.get("parts", []):
            if isinstance(part, dict) and part.get("text"):
                return part["text"]

    # History
    for msg in reversed(result.get("history", [])):
        if msg.get("role") == "agent":
            for part in msg.get("parts", []):
                if isinstance(part, dict) and part.get("text"):
                    return part["text"]

    return "Agent responded but no text was found."


# ── Entry point ─────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Agent Marketplace MCP Server")
    parser.add_argument("--sse", type=int, nargs="?", const=8100, default=None,
                        help="Run with SSE transport on given port (default: 8100)")
    args = parser.parse_args()

    if args.sse:
        mcp.run(transport="sse", port=args.sse)
    else:
        mcp.run()
