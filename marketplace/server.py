import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from marketplace.auth import check_secret, MARKETPLACE_SECRET
from marketplace.db import (
    init_db,
    register_agent,
    remove_agent,
    list_agents,
    get_agent,
    create_token,
    validate_token,
    log_usage,
    get_usage_logs,
)
from marketplace.models import (
    RegisterRequest, TokenRequest, TokenResponse, TokenValidation, AgentInfo,
    SignupRequest, LoginRequest, UserProfile, AddCreditsRequest, ChatMessage, VerifyEmailRequest,
)
from marketplace.users import (
    create_user, authenticate_user, get_user, get_user_by_username,
    create_jwt, verify_jwt, invalidate_user_tokens, unlock_user,
    deduct_credits, add_credits,
    purchase_agent, get_user_agents,
    validate_api_key, revoke_api_key, get_user_all_keys,
    store_otp, verify_otp,
    AGENT_PURCHASE_PRICE, AGENT_QUERY_COST,
)
from marketplace.sanitizer import sanitize_input, sanitize_output
from marketplace.rate_limiter import rate_limiter, auth_rate_limiter, signup_rate_limiter, ip_signup_tracker
from marketplace.email_service import generate_otp, send_otp_email
from mcp_server.defenses import (
    validate_tool_manifest,
    sanitize_tool_description,
    tool_registry,
    ToolShadowingError,
    definition_monitor,
    sandbox,
)

MARKETPLACE_PORT = int(os.environ.get("MARKETPLACE_PORT", 8000))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    print("Marketplace DB initialized")
    yield


app = FastAPI(title="Agent Marketplace", version="2.0.0", lifespan=lifespan)

_ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "").split(",")
_ALLOWED_ORIGINS = [o.strip() for o in _ALLOWED_ORIGINS if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS if _ALLOWED_ORIGINS else [],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "x-api-key", "x-marketplace-secret"],
    allow_credentials=False,
)

STATIC_DIR = Path(__file__).parent / "static"


# ── JWT Dependency ───────────────────────────────────────────

def get_current_user(request: Request) -> dict:
    """FastAPI dependency: extract and verify JWT from Authorization header."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth_header[len("Bearer "):]
    payload = verify_jwt(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired JWT")

    user = get_user(payload["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user["locked"]:
        raise HTTPException(status_code=403, detail="Account is locked")

    # Check token version — invalidated tokens are rejected
    if payload.get("ver", 0) != user.get("token_version", 0):
        raise HTTPException(status_code=401, detail="Token has been revoked")

    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    # Check role from DB (user dict comes from get_user()), NOT from JWT payload
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ── Security Headers Middleware ─────────────────────────────

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Server"] = "Marketplace"  # Hide server tech
        return response


app.add_middleware(SecurityHeadersMiddleware)


# ── Web UI ───────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def serve_storefront():
    return FileResponse(STATIC_DIR / "index.html")


# ── Auth Endpoints ───────────────────────────────────────────

import re as _re

_USERNAME_RE = _re.compile(r"^[a-zA-Z0-9_-]+$")


def _get_client_ip(request: Request) -> str:
    """Get real client IP from socket connection. Never trust proxy headers."""
    return request.client.host if request.client else "unknown"


@app.post("/auth/signup")
def api_signup(req: SignupRequest, request: Request):
    # Rate limit signups per IP (blocks credit farming)
    ip = _get_client_ip(request)
    rate_check = signup_rate_limiter.check(f"signup:{ip}")
    if not rate_check["allowed"]:
        raise HTTPException(
            status_code=429,
            detail=f"Too many signups. Try again in {rate_check['retry_after']} seconds",
            headers={"Retry-After": str(rate_check["retry_after"])},
        )

    # Global IP cap: max 5 accounts per IP ever (blocks VPN-cycling credit farmers)
    if not ip_signup_tracker.check_and_record(ip):
        raise HTTPException(
            status_code=403,
            detail="Account creation limit reached for this IP address",
        )

    # Username validation
    if len(req.username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    if len(req.username) > 30:
        raise HTTPException(status_code=400, detail="Username must be at most 30 characters")
    if not _USERNAME_RE.match(req.username):
        raise HTTPException(status_code=400, detail="Username must be alphanumeric (a-z, 0-9, _, -)")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if "@" not in req.email or "." not in req.email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Invalid email address")

    user = create_user(req.username, req.password, req.email)
    if not user:
        raise HTTPException(status_code=409, detail="Username already exists")

    # Send OTP
    otp = generate_otp()
    store_otp(user["user_id"], otp)
    send_otp_email(req.email, req.username, otp)

    return {
        "message": "Account created. Check your email for a 6-digit verification code.",
        "username": user["username"],
        "verified": False,
    }


@app.post("/auth/verify-email")
def api_verify_email(req: VerifyEmailRequest):
    success = verify_otp(req.username, req.otp)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    user = get_user_by_username(req.username)
    token = create_jwt(user["user_id"], user["username"], user["role"], user.get("token_version", 0))
    return {
        "message": "Email verified successfully!",
        "token": token,
        "user": {
            "user_id": user["user_id"],
            "username": user["username"],
            "role": user["role"],
            "credits": user["credits"],
        },
    }


@app.post("/auth/login")
def api_login(req: LoginRequest, request: Request):
    # Rate limit login per IP (blocks brute force)
    ip = _get_client_ip(request)
    rate_check = auth_rate_limiter.check(f"login:{ip}")
    if not rate_check["allowed"]:
        raise HTTPException(
            status_code=429,
            detail=f"Too many login attempts. Try again in {rate_check['retry_after']} seconds",
            headers={"Retry-After": str(rate_check["retry_after"])},
        )

    # Check if user exists, is locked, or is unverified
    existing = get_user_by_username(req.username)
    if existing and existing["locked"]:
        raise HTTPException(status_code=403, detail="Account is locked due to too many failed login attempts")
    if existing and not existing.get("verified", 1):
        raise HTTPException(status_code=403, detail="Please verify your email before logging in")

    user = authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_jwt(user["user_id"], user["username"], user["role"], user.get("token_version", 0))
    return {
        "token": token,
        "user": {
            "user_id": user["user_id"],
            "username": user["username"],
            "role": user["role"],
            "credits": user["credits"],
        },
    }


@app.post("/auth/logout")
def api_logout(user: dict = Depends(get_current_user)):
    """Invalidate all existing JWTs for this user."""
    invalidate_user_tokens(user["user_id"])
    return {"status": "logged_out", "detail": "All sessions invalidated"}


# ── User Profile ─────────────────────────────────────────────

@app.get("/me")
def api_me(user: dict = Depends(get_current_user)):
    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "role": user["role"],
        "credits": user["credits"],
        "created_at": user["created_at"],
    }


@app.get("/me/agents")
def api_my_agents(user: dict = Depends(get_current_user)):
    agents = get_user_agents(user["user_id"])
    result = []
    for a in agents:
        result.append({
            "agent_id": a["agent_id"],
            "purchased_at": a["purchased_at"],
            "api_key": a["api_key"] if not a.get("revoked") else None,
            "key_id": a["key_id"],
            "query_cost": AGENT_QUERY_COST.get(a["agent_id"], 1),
        })
    return {"agents": result, "credits": user["credits"]}


@app.get("/me/usage")
def api_my_usage(user: dict = Depends(get_current_user)):
    logs = get_usage_logs(user["user_id"])
    return {"usage": logs}


@app.get("/me/keys")
def api_my_keys(user: dict = Depends(get_current_user)):
    """All API keys (active + revoked) for the dashboard."""
    keys = get_user_all_keys(user["user_id"])
    result = []
    for k in keys:
        result.append({
            "key_id": k["key_id"],
            "agent_id": k["agent_id"],
            "api_key": k["api_key"] if not k["revoked"] else k["api_key"][:12] + "••••(revoked)",
            "status": "revoked" if k["revoked"] else "active",
            "created_at": k["created_at"],
            "purchase_price": AGENT_PURCHASE_PRICE.get(k["agent_id"], 10),
            "query_cost": AGENT_QUERY_COST.get(k["agent_id"], 1),
        })
    return {"keys": result, "credits": user["credits"]}


# ── Agent Purchase ───────────────────────────────────────────

@app.post("/agents/{agent_id}/buy")
def api_buy_agent(agent_id: str, user: dict = Depends(get_current_user)):
    # Verify agent exists in registry
    agent = get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    result = purchase_agent(user["user_id"], agent_id)
    if not result["success"]:
        if result["error"] == "Agent already purchased":
            raise HTTPException(status_code=409, detail=result["error"])
        elif result["error"] == "Insufficient credits":
            raise HTTPException(status_code=402, detail=result["error"])
        else:
            raise HTTPException(status_code=400, detail=result["error"])

    return result


# ── API Key Management ───────────────────────────────────────

@app.delete("/me/api-key/{key_id}")
def api_revoke_key(key_id: str, user: dict = Depends(get_current_user)):
    if not revoke_api_key(key_id, user["user_id"]):
        raise HTTPException(status_code=404, detail="API key not found")
    return {"status": "revoked", "key_id": key_id}



# ── Programmatic Agent Access ────────────────────────────────

@app.post("/api/v1/chat")
async def api_chat(req: ChatMessage, request: Request):
    """
    Programmatic agent access via API key.
    Security pipeline: auth → rate limit → sanitize → credits → call → sanitize output → deduct → log
    """
    ip_address = _get_client_ip(request)

    # Step 1: Validate API key
    api_key = request.headers.get("x-api-key", "")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")

    key_info = validate_api_key(api_key)
    if not key_info:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    user_id = key_info["user_id"]
    agent_id = key_info["agent_id"]

    # Step 2: Rate limit
    rate_check = rate_limiter.check(user_id)
    if not rate_check["allowed"]:
        log_usage(user_id, agent_id, req.message, 0, True, "rate_limited", ip_address)
        raise HTTPException(
            status_code=429,
            detail=f"Rate limited. Try again in {rate_check['retry_after']} seconds",
            headers={"Retry-After": str(rate_check["retry_after"])},
        )

    # Step 3: Input sanitization
    input_check = sanitize_input(req.message)
    if not input_check["safe"]:
        log_usage(user_id, agent_id, req.message, 0, True, input_check["reason"], ip_address)
        raise HTTPException(
            status_code=400,
            detail=f"Blocked: {input_check['reason']} detected",
        )

    # Step 4: Deduct credits FIRST (atomic — prevents TOCTOU race condition)
    query_cost = AGENT_QUERY_COST.get(agent_id, 1)
    if not deduct_credits(user_id, query_cost):
        user = get_user(user_id)
        log_usage(user_id, agent_id, req.message, 0, True, "insufficient_credits", ip_address)
        raise HTTPException(
            status_code=402,
            detail=f"Insufficient credits. Need {query_cost}, have {user['credits'] if user else 0}",
        )

    # Step 5: Get agent info and call
    agent_info = get_agent(agent_id)
    if not agent_info:
        add_credits(user_id, query_cost)  # Refund — agent not found
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' is not available")

    agent_url = agent_info["url"]

    # Get scoped token for agent
    token_data = create_token(agent_id, f"user:{user_id}", 300)
    token = token_data["token"]

    try:
        response_text = await call_agent_a2a(agent_url, token, req.message)
    except httpx.ConnectError:
        add_credits(user_id, query_cost)  # Refund — agent offline
        log_usage(user_id, agent_id, req.message, 0, True, "agent_offline", ip_address)
        raise HTTPException(status_code=503, detail=f"Agent '{agent_id}' is offline")
    except Exception as e:
        add_credits(user_id, query_cost)  # Refund — agent error
        log_usage(user_id, agent_id, req.message, 0, True, f"agent_error: {str(e)[:100]}", ip_address)
        raise HTTPException(status_code=502, detail=f"Error from agent: {str(e)[:200]}")

    # Step 6: Output sanitization
    output_check = sanitize_output(response_text)
    cleaned_response = output_check["cleaned"]

    # Step 7: Log usage (credits already deducted at step 4)
    log_usage(user_id, agent_id, req.message, query_cost, False, "", ip_address)

    # Step 8: Return response
    updated_user = get_user(user_id)
    return {
        "response": cleaned_response,
        "agent": agent_info["name"],
        "agent_id": agent_id,
        "credits_used": query_cost,
        "credits_remaining": updated_user["credits"] if updated_user else 0,
    }


async def call_agent_a2a(agent_url: str, token: str, question: str) -> str:
    """Send an A2A message to an agent and extract the response text."""
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

    for part in result.get("parts", []):
        if isinstance(part, dict) and part.get("text"):
            return part["text"]

    for art in result.get("artifacts", []):
        for part in art.get("parts", []):
            if isinstance(part, dict) and part.get("text"):
                return part["text"]

    for msg in reversed(result.get("history", [])):
        if msg.get("role") == "agent":
            for part in msg.get("parts", []):
                if isinstance(part, dict) and part.get("text"):
                    return part["text"]

    return "Agent responded but no text was found."


# ── Discovery (public) ───────────────────────────────────────

@app.get("/agents", response_model=list[AgentInfo])
def api_list_agents():
    agents = list_agents()
    for a in agents:
        a["card_json"] = json.loads(a["card_json"]) if isinstance(a["card_json"], str) else a["card_json"]
    return agents


@app.get("/agents/{agent_id}", response_model=AgentInfo)
def api_get_agent(agent_id: str):
    agent = get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent["card_json"] = json.loads(agent["card_json"]) if isinstance(agent["card_json"], str) else agent["card_json"]
    return agent


# ── Agent Pricing (public) ───────────────────────────────────

@app.get("/agents/pricing/all")
def api_agent_pricing():
    return {
        "purchase_prices": AGENT_PURCHASE_PRICE,
        "query_costs": AGENT_QUERY_COST,
    }


# ── Registration (requires secret) ───────────────────────────

@app.post("/agents/register")
def api_register_agent(req: RegisterRequest, request: Request):
    if not check_secret(request):
        raise HTTPException(status_code=403, detail="Invalid marketplace secret")

    # MCP Defense: Sanitize tool descriptions (Vuln 2 — Tool Poisoning)
    card = req.card_json if isinstance(req.card_json, dict) else {}
    for skill in card.get("skills", []):
        desc_check = sanitize_tool_description(skill.get("description", ""))
        if not desc_check["safe"]:
            print(f"  [DEFENSE] Blocked agent '{req.agent_id}': poisoned tool description — {desc_check['flags']}")
            raise HTTPException(
                status_code=400,
                detail=f"Tool description blocked: {', '.join(desc_check['flags'])}",
            )

    # MCP Defense: Check tool name collisions (Vuln 3 — Tool Shadowing)
    for skill in card.get("skills", []):
        try:
            tool_registry.register_tool(
                tool_name=skill.get("name", ""),
                server_name=req.agent_id,
                description=skill.get("description", ""),
            )
        except ToolShadowingError as e:
            print(f"  [DEFENSE] Blocked agent '{req.agent_id}': tool shadowing — {e}")
            raise HTTPException(status_code=409, detail=str(e))

    # MCP Defense: Snapshot tool definitions (Vuln 4 — Rug Pull)
    tools_for_snapshot = [
        {"name": s.get("name", ""), "description": s.get("description", ""), "parameters": s.get("parameters", {})}
        for s in card.get("skills", [])
    ]
    if tools_for_snapshot:
        definition_monitor.snapshot(tools_for_snapshot)

    agent = register_agent(
        agent_id=req.agent_id,
        name=req.name,
        description=req.description,
        url=req.url,
        card_json=json.dumps(req.card_json),
    )
    agent["card_json"] = json.loads(agent["card_json"])
    print(f"  Registered agent: {req.agent_id} @ {req.url}")
    return {"status": "registered", "agent": agent}


@app.delete("/agents/{agent_id}")
def api_remove_agent(agent_id: str, request: Request):
    if not check_secret(request):
        raise HTTPException(status_code=403, detail="Invalid marketplace secret")

    if not remove_agent(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    print(f"  Removed agent: {agent_id}")
    return {"status": "removed", "agent_id": agent_id}


# ── Tokens (requires secret to issue, public to validate) ────

@app.post("/tokens", response_model=TokenResponse)
def api_create_token(req: TokenRequest, request: Request):
    if not check_secret(request):
        raise HTTPException(status_code=403, detail="Invalid marketplace secret")

    agent = get_agent(req.target_agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Target agent '{req.target_agent_id}' not found")

    result = create_token(req.target_agent_id, req.requester_id, req.ttl_seconds)
    return result


@app.get("/tokens/validate", response_model=TokenValidation)
def api_validate_token(token: str, request: Request):
    if not check_secret(request):
        raise HTTPException(status_code=403, detail="Invalid marketplace secret")
    return validate_token(token)


# ── Admin ────────────────────────────────────────────────────

@app.post("/admin/credits")
def api_add_credits(req: AddCreditsRequest, admin: dict = Depends(require_admin)):
    target = get_user_by_username(req.username)
    if not target:
        raise HTTPException(status_code=404, detail=f"User '{req.username}' not found")

    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    add_credits(target["user_id"], req.amount)
    updated = get_user(target["user_id"])
    return {"status": "credits_added", "username": req.username, "new_balance": updated["credits"]}


@app.post("/admin/unlock/{username}")
def api_unlock_user(username: str, admin: dict = Depends(require_admin)):
    target = get_user_by_username(username)
    if not target:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")

    if not target["locked"]:
        return {"status": "already_unlocked", "username": username}

    unlock_user(target["user_id"])
    return {"status": "unlocked", "username": username}


# ── Health ────────────────────────────────────────────────────

@app.get("/health")
def health():
    agents = list_agents()
    return {"status": "ok", "registered_agents": len(agents)}


if __name__ == "__main__":
    print(f"Agent Marketplace starting on http://0.0.0.0:{MARKETPLACE_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=MARKETPLACE_PORT, server_header=False)
