import os
import sqlite3
import secrets
from datetime import datetime, timedelta, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "marketplace.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            agent_id      TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            description   TEXT,
            url           TEXT NOT NULL UNIQUE,
            card_json     TEXT NOT NULL,
            registered_at TEXT DEFAULT (datetime('now')),
            last_heartbeat TEXT DEFAULT (datetime('now')),
            status        TEXT DEFAULT 'active'
        );

        CREATE TABLE IF NOT EXISTS tokens (
            token         TEXT PRIMARY KEY,
            agent_id      TEXT NOT NULL,
            issued_to     TEXT NOT NULL,
            created_at    TEXT DEFAULT (datetime('now')),
            expires_at    TEXT NOT NULL,
            revoked       INTEGER DEFAULT 0,
            FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
        );

        CREATE INDEX IF NOT EXISTS idx_tokens_agent ON tokens(agent_id);
        CREATE INDEX IF NOT EXISTS idx_tokens_expires ON tokens(expires_at);

        CREATE TABLE IF NOT EXISTS users (
            user_id       TEXT PRIMARY KEY,
            username      TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role          TEXT DEFAULT 'user',
            credits       INTEGER DEFAULT 100,
            locked        INTEGER DEFAULT 0,
            failed_logins INTEGER DEFAULT 0,
            token_version INTEGER DEFAULT 0,
            created_at    TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS user_agents (
            user_id      TEXT NOT NULL,
            agent_id     TEXT NOT NULL,
            purchased_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, agent_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS api_keys (
            key_id     TEXT PRIMARY KEY,
            user_id    TEXT NOT NULL,
            agent_id   TEXT NOT NULL,
            api_key    TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT (datetime('now')),
            revoked    INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS usage_logs (
            log_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       TEXT NOT NULL,
            agent_id      TEXT,
            question      TEXT,
            credits_spent INTEGER DEFAULT 0,
            blocked       INTEGER DEFAULT 0,
            block_reason  TEXT,
            ip_address    TEXT,
            timestamp     TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_api_keys_key ON api_keys(api_key);
        CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);
        CREATE INDEX IF NOT EXISTS idx_usage_logs_user ON usage_logs(user_id);
    """)
    conn.commit()
    conn.close()


def register_agent(agent_id: str, name: str, description: str, url: str, card_json: str) -> dict:
    conn = get_connection()
    conn.execute(
        """INSERT INTO agents (agent_id, name, description, url, card_json)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(agent_id) DO UPDATE SET
               name = excluded.name,
               description = excluded.description,
               url = excluded.url,
               card_json = excluded.card_json,
               last_heartbeat = datetime('now'),
               status = 'active'
        """,
        (agent_id, name, description, url, card_json),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
    conn.close()
    return dict(row)


def remove_agent(agent_id: str) -> bool:
    conn = get_connection()
    cursor = conn.execute("DELETE FROM agents WHERE agent_id = ?", (agent_id,))
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


def list_agents() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM agents WHERE status = 'active'").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_agent(agent_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_token(target_agent_id: str, requester_id: str, ttl_seconds: int = 3600) -> dict:
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()

    conn = get_connection()
    conn.execute(
        "INSERT INTO tokens (token, agent_id, issued_to, expires_at) VALUES (?, ?, ?, ?)",
        (token, target_agent_id, requester_id, expires_at),
    )
    conn.commit()
    conn.close()
    return {"token": token, "target_agent_id": target_agent_id, "expires_at": expires_at}


def log_usage(user_id: str, agent_id: str, question: str, credits_spent: int,
              blocked: bool, block_reason: str, ip_address: str):
    conn = get_connection()
    conn.execute(
        """INSERT INTO usage_logs (user_id, agent_id, question, credits_spent, blocked, block_reason, ip_address)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, agent_id, question[:500], credits_spent, int(blocked), block_reason, ip_address),
    )
    conn.commit()
    conn.close()


def get_usage_logs(user_id: str, limit: int = 50) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM usage_logs WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def validate_token(token: str) -> dict:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM tokens WHERE token = ? AND revoked = 0", (token,)
    ).fetchone()
    conn.close()

    if not row:
        return {"valid": False}

    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if datetime.now(timezone.utc) > expires_at:
        return {"valid": False}

    return {
        "valid": True,
        "target_agent_id": row["agent_id"],
        "requester_id": row["issued_to"],
        "expires_at": row["expires_at"],
    }
