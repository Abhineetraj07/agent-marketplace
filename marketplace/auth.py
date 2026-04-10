import os
import secrets as _secrets

import httpx
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_MKT_SECRET_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".marketplace_secret")


def _get_marketplace_secret() -> str:
    """Get marketplace secret: env var > file > auto-generate. Never uses a weak default."""
    env = os.environ.get("MARKETPLACE_SECRET", "")
    if env and env != "dev-marketplace-secret":
        return env
    if os.path.exists(_MKT_SECRET_FILE):
        with open(_MKT_SECRET_FILE) as f:
            return f.read().strip()
    secret = _secrets.token_hex(32)
    with open(_MKT_SECRET_FILE, "w") as f:
        f.write(secret)
    os.chmod(_MKT_SECRET_FILE, 0o600)  # Owner-only read/write
    print(f"  [SECURITY] Auto-generated MARKETPLACE_SECRET (saved to {_MKT_SECRET_FILE})")
    return secret


MARKETPLACE_SECRET = _get_marketplace_secret()
MARKETPLACE_PORT = os.environ.get("MARKETPLACE_PORT", "8000")
MARKETPLACE_URL = os.environ.get("MARKETPLACE_URL", f"http://localhost:{MARKETPLACE_PORT}")


import hmac as _hmac


def check_secret(request: Request) -> bool:
    provided = request.headers.get("x-marketplace-secret", "")
    return _hmac.compare_digest(provided, MARKETPLACE_SECRET)


class MarketplaceAuthMiddleware(BaseHTTPMiddleware):
    """Auth middleware for agent servers — validates tokens against the marketplace."""

    OPEN_PATHS = {"/.well-known/agent-card.json"}

    def __init__(self, app, marketplace_url: str, agent_id: str):
        super().__init__(app)
        self.marketplace_url = marketplace_url
        self.agent_id = agent_id

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.OPEN_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse({"error": "Missing Bearer token"}, status_code=401)

        token = auth_header[len("Bearer "):]

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(
                    f"{self.marketplace_url}/tokens/validate",
                    params={"token": token},
                    headers={"x-marketplace-secret": MARKETPLACE_SECRET},
                )

            if resp.status_code != 200:
                return JSONResponse({"error": "Token validation failed"}, status_code=403)

            data = resp.json()
            if not data.get("valid"):
                return JSONResponse({"error": "Invalid or expired token"}, status_code=403)

            if data.get("target_agent_id") != self.agent_id:
                return JSONResponse({"error": "Token not scoped for this agent"}, status_code=403)

        except httpx.ConnectError:
            return JSONResponse({"error": "Marketplace unreachable"}, status_code=503)

        return await call_next(request)
