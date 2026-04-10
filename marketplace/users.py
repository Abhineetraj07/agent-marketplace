"""
User management: signup, login, JWT, credits, API keys.
"""

import os
import uuid
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from marketplace.db import get_connection

_SECRET_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".jwt_secret")


def _get_jwt_secret() -> str:
    """Get JWT secret: env var > file > auto-generate. Never uses a weak default."""
    env = os.environ.get("JWT_SECRET", "")
    if env and env != "dev-jwt-secret-change-in-prod":
        return env
    # Auto-generate and persist a strong secret on first run
    if os.path.exists(_SECRET_FILE):
        with open(_SECRET_FILE) as f:
            return f.read().strip()
    secret = secrets.token_hex(32)
    with open(_SECRET_FILE, "w") as f:
        f.write(secret)
    os.chmod(_SECRET_FILE, 0o600)  # Owner-only read/write
    print(f"  [SECURITY] Auto-generated JWT_SECRET (saved to {_SECRET_FILE})")
    return secret


JWT_SECRET = _get_jwt_secret()
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_MINUTES = 60


# ── User CRUD ────────────────────────────────────────────────

def create_user(username: str, password: str) -> dict | None:
    """Create a new user with hashed password. Returns user dict or None if exists."""
    user_id = uuid.uuid4().hex
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO users (user_id, username, password_hash) VALUES (?, ?, ?)",
            (user_id, username, password_hash),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row)
    except Exception:
        return None
    finally:
        conn.close()


def authenticate_user(username: str, password: str) -> dict | None:
    """Verify credentials. Returns user dict, None if bad password, raises on lockout."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()

    if not row:
        return None

    user = dict(row)

    if user["locked"]:
        return None

    if not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        increment_failed_logins(user["user_id"])
        return None

    # Reset failed logins on success
    conn = get_connection()
    conn.execute(
        "UPDATE users SET failed_logins = 0 WHERE user_id = ?",
        (user["user_id"],),
    )
    conn.commit()
    conn.close()

    return user


def increment_failed_logins(user_id: str):
    """Increment failed login count. Lock account after 5 failures."""
    conn = get_connection()
    conn.execute(
        "UPDATE users SET failed_logins = failed_logins + 1 WHERE user_id = ?",
        (user_id,),
    )
    conn.execute(
        "UPDATE users SET locked = 1 WHERE user_id = ? AND failed_logins >= 5",
        (user_id,),
    )
    conn.commit()
    conn.close()


def unlock_user(user_id: str) -> bool:
    """Unlock a locked account and reset failed login counter."""
    conn = get_connection()
    cursor = conn.execute(
        "UPDATE users SET locked = 0, failed_logins = 0 WHERE user_id = ?",
        (user_id,),
    )
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


def get_user(user_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_username(username: str) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ── JWT ──────────────────────────────────────────────────────

def create_jwt(user_id: str, username: str, role: str, token_version: int = 0) -> str:
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "ver": token_version,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRY_MINUTES),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_jwt(token: str) -> dict | None:
    """Decode and verify JWT. Returns payload or None."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def invalidate_user_tokens(user_id: str):
    """Increment token_version to invalidate all existing JWTs for this user."""
    conn = get_connection()
    conn.execute("UPDATE users SET token_version = token_version + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


# ── Credits ──────────────────────────────────────────────────

def deduct_credits(user_id: str, amount: int) -> bool:
    """Atomically deduct credits. Returns False if insufficient."""
    conn = get_connection()
    cursor = conn.execute(
        "UPDATE users SET credits = credits - ? WHERE user_id = ? AND credits >= ?",
        (amount, user_id, amount),
    )
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


def add_credits(user_id: str, amount: int) -> bool:
    """Add credits to a user (admin operation)."""
    conn = get_connection()
    cursor = conn.execute(
        "UPDATE users SET credits = credits + ? WHERE user_id = ?",
        (amount, user_id),
    )
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


def get_credits(user_id: str) -> int:
    user = get_user(user_id)
    return user["credits"] if user else 0


# ── Agent Purchase ───────────────────────────────────────────

AGENT_PURCHASE_PRICE = {
    "filmbot": 10,
    "filmbot_v2": 30,
    "melody": 10,
    "rock": 10,
}

AGENT_QUERY_COST = {
    "filmbot": 1,
    "filmbot_v2": 3,
    "melody": 1,
    "rock": 1,
}


def purchase_agent(user_id: str, agent_id: str) -> dict:
    """Purchase an agent. Returns {"success": bool, "api_key": str, ...}."""
    price = AGENT_PURCHASE_PRICE.get(agent_id)
    if price is None:
        return {"success": False, "error": "Unknown agent"}

    # Check if already purchased with an active (non-revoked) key
    conn = get_connection()
    active_key = conn.execute(
        """SELECT 1 FROM user_agents ua
           JOIN api_keys ak ON ua.user_id = ak.user_id AND ua.agent_id = ak.agent_id
           WHERE ua.user_id = ? AND ua.agent_id = ? AND ak.revoked = 0""",
        (user_id, agent_id),
    ).fetchone()

    if active_key:
        conn.close()
        return {"success": False, "error": "Agent already purchased"}

    # Remove old purchase record if key was revoked (allows re-buy)
    conn.execute(
        "DELETE FROM user_agents WHERE user_id = ? AND agent_id = ?",
        (user_id, agent_id),
    )

    # Check credits
    user = conn.execute("SELECT credits FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not user or user["credits"] < price:
        conn.close()
        return {"success": False, "error": "Insufficient credits"}

    # Deduct credits + create purchase + generate API key
    api_key = f"mk_{agent_id}_{secrets.token_urlsafe(24)}"
    key_id = uuid.uuid4().hex

    conn.execute("UPDATE users SET credits = credits - ? WHERE user_id = ?", (price, user_id))
    conn.execute(
        "INSERT INTO user_agents (user_id, agent_id) VALUES (?, ?)",
        (user_id, agent_id),
    )
    conn.execute(
        "INSERT INTO api_keys (key_id, user_id, agent_id, api_key) VALUES (?, ?, ?, ?)",
        (key_id, user_id, agent_id, api_key),
    )
    conn.commit()

    updated_user = conn.execute("SELECT credits FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()

    return {
        "success": True,
        "api_key": api_key,
        "agent_id": agent_id,
        "query_cost": AGENT_QUERY_COST.get(agent_id, 1),
        "credits_remaining": updated_user["credits"],
    }


def get_user_agents(user_id: str) -> list[dict]:
    """Get all agents purchased by a user with their active API keys."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT ua.agent_id, ua.purchased_at, ak.api_key, ak.key_id, ak.revoked
           FROM user_agents ua
           LEFT JOIN api_keys ak ON ua.user_id = ak.user_id AND ua.agent_id = ak.agent_id AND ak.revoked = 0
           WHERE ua.user_id = ?""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_user_all_keys(user_id: str) -> list[dict]:
    """Get ALL API keys for a user (active + revoked) for the dashboard."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT ak.key_id, ak.agent_id, ak.api_key, ak.revoked, ak.created_at
           FROM api_keys ak
           WHERE ak.user_id = ?
           ORDER BY ak.created_at DESC""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def has_purchased_agent(user_id: str, agent_id: str) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM user_agents WHERE user_id = ? AND agent_id = ?",
        (user_id, agent_id),
    ).fetchone()
    conn.close()
    return row is not None


# ── API Keys ─────────────────────────────────────────────────

def validate_api_key(api_key: str) -> dict | None:
    """Validate an API key. Returns {user_id, agent_id} or None."""
    conn = get_connection()
    row = conn.execute(
        "SELECT ak.user_id, ak.agent_id, u.locked FROM api_keys ak JOIN users u ON ak.user_id = u.user_id WHERE ak.api_key = ? AND ak.revoked = 0",
        (api_key,),
    ).fetchone()
    conn.close()

    if not row:
        return None
    if row["locked"]:
        return None

    return {"user_id": row["user_id"], "agent_id": row["agent_id"]}


def regenerate_api_key(user_id: str, agent_id: str) -> dict | None:
    """Generate a new API key for a purchased agent (after revoking the old one)."""
    conn = get_connection()

    # Check user owns this agent
    owned = conn.execute(
        "SELECT 1 FROM user_agents WHERE user_id = ? AND agent_id = ?",
        (user_id, agent_id),
    ).fetchone()
    if not owned:
        conn.close()
        return None

    # Revoke any existing keys for this agent
    conn.execute(
        "UPDATE api_keys SET revoked = 1 WHERE user_id = ? AND agent_id = ?",
        (user_id, agent_id),
    )

    # Generate new key
    api_key = f"mk_{agent_id}_{secrets.token_urlsafe(24)}"
    key_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO api_keys (key_id, user_id, agent_id, api_key) VALUES (?, ?, ?, ?)",
        (key_id, user_id, agent_id, api_key),
    )
    conn.commit()
    conn.close()

    return {"api_key": api_key, "key_id": key_id, "agent_id": agent_id}


def revoke_api_key(key_id: str, user_id: str) -> bool:
    """Revoke an API key. Returns True if revoked."""
    conn = get_connection()
    cursor = conn.execute(
        "UPDATE api_keys SET revoked = 1 WHERE key_id = ? AND user_id = ?",
        (key_id, user_id),
    )
    conn.commit()
    conn.close()
    return cursor.rowcount > 0
