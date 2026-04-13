"""
Auth bridge: validates API keys and JWTs for MCP tool calls.

MCP has no native auth headers, so credentials are passed as tool parameters.
This module wraps existing marketplace auth to validate them.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from marketplace.users import validate_api_key, get_user, verify_jwt


def authenticate_api_key(api_key: str) -> dict | None:
    """Validate an API key and return user context.

    Returns:
        {"user_id": str, "agent_id": str, "credits": int} or None
    """
    key_info = validate_api_key(api_key)
    if not key_info:
        return None

    user = get_user(key_info["user_id"])
    if not user:
        return None
    if user["locked"]:
        return None

    return {
        "user_id": key_info["user_id"],
        "agent_id": key_info["agent_id"],
        "credits": user["credits"],
        "username": user["username"],
    }


def authenticate_jwt(token: str) -> dict | None:
    """Validate a JWT token and return user context.

    Returns:
        {"user_id": str, "username": str, "role": str} or None
    """
    payload = verify_jwt(token)
    if not payload:
        return None

    user = get_user(payload["user_id"])
    if not user:
        return None
    if user["locked"]:
        return None

    # Check token version matches (instant revocation)
    if payload.get("ver", 0) != user.get("token_version", 0):
        return None

    return {
        "user_id": payload["user_id"],
        "username": payload["username"],
        "role": payload.get("role", "user"),
        "credits": user["credits"],
    }
