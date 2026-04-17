from pydantic import BaseModel


class RegisterRequest(BaseModel):
    agent_id: str
    name: str
    description: str
    url: str
    card_json: dict


class TokenRequest(BaseModel):
    target_agent_id: str
    requester_id: str
    ttl_seconds: int = 3600


class TokenResponse(BaseModel):
    token: str
    target_agent_id: str
    expires_at: str


class TokenValidation(BaseModel):
    valid: bool
    target_agent_id: str | None = None
    requester_id: str | None = None
    expires_at: str | None = None


class AgentInfo(BaseModel):
    agent_id: str
    name: str
    description: str | None
    url: str
    card_json: dict
    status: str
    registered_at: str


# ── Auth Models ──────────────────────────────────────────────

class SignupRequest(BaseModel):
    username: str
    password: str
    email: str


class VerifyEmailRequest(BaseModel):
    username: str
    otp: str


class LoginRequest(BaseModel):
    username: str
    password: str


class UserProfile(BaseModel):
    user_id: str
    username: str
    role: str
    credits: int
    created_at: str


class AddCreditsRequest(BaseModel):
    username: str
    amount: int


class ChatMessage(BaseModel):
    message: str
