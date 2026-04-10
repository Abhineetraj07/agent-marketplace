# Product Requirements Document (PRD)
# Secure Multi-Agent Marketplace with Authenticated Communication

**Author:** Abhineet  
**Date:** 2026-04-06  
**Version:** 1.0  
**Type:** College Assignment — Hackathon-Ready System  
**Deployment Target:** AWS EC2  

---

## 1. Overview

### 1.1 What is this?
A centralized **Agent Marketplace** (storefront) where multiple AI agents register themselves, users can discover and **purchase** them using credits, and receive an API key to use agents programmatically from their own code — all secured by token-scoped authentication, credit-based access control, and input/output guardrails. There is **no chat interface on the website** — all agent interaction happens via API.

### 1.2 Why are we building this?
This is a college assignment with a **hackathon component** — other teams will actively attempt to break the system. The marketplace must:
- Demonstrate multi-agent orchestration with real security
- Survive adversarial attacks (SQL injection, prompt injection, token theft, brute force)
- Be accessible from other laptops over the network (deployed on AWS EC2)
- Provide a purchasable API so users can integrate agents into their own projects

### 1.3 Success Criteria
- 4 agents registered and discoverable via web UI
- Users can sign up, log in, purchase agents, and use them via API keys
- All known attack vectors are defended against
- Other teams on the network can access the marketplace and use agents via API keys
- System survives the hackathon without being compromised

---

## 2. Users and Personas

| Persona | Description | Goals |
|---------|-------------|-------|
| **End User** | Someone browsing the marketplace UI | Discover agents, buy them, get API key |
| **Developer** | Someone integrating agents into their project | Get an API key, call agents programmatically from their code |
| **Admin** | System operator | Manage credits, monitor usage, register/remove agents |
| **Attacker** (hackathon) | Other teams trying to break the system | SQL injection, prompt injection, token theft, credit manipulation |

---

## 3. Functional Requirements

### 3.1 Agent Registry & Discovery

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1 | Agents self-register with the marketplace on startup (name, description, URL, A2A card) | P0 |
| FR-2 | Anyone can browse registered agents via `GET /agents` (no auth required) | P0 |
| FR-3 | Each agent exposes an A2A card at `/.well-known/agent-card.json` | P0 |
| FR-4 | Web UI displays agent cards with name, description, skills, and tags | P0 |

### 3.2 User Authentication

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-5 | Users can sign up with username + password via `POST /auth/signup` | P0 |
| FR-6 | Passwords are hashed with bcrypt (never stored in plaintext) | P0 |
| FR-7 | Users can log in via `POST /auth/login` and receive a JWT | P0 |
| FR-8 | JWT expires after 15 minutes; user must re-login | P0 |
| FR-9 | Account locks after 5 consecutive failed login attempts | P1 |
| FR-10 | JWT is required for all `/me` and `/agents/{id}/buy` endpoints | P0 |

### 3.3 Credit System

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-11 | New users receive 100 free credits on signup | P0 |
| FR-12 | Each agent call costs credits (configurable per agent: filmbot=1, filmbot_v2=3, melody=1, rock=1) | P0 |
| FR-13 | Credits are checked server-side before routing to an agent | P0 |
| FR-14 | Credit deduction is atomic (no race conditions) | P0 |
| FR-15 | Users can view their remaining credits via `GET /me` | P0 |
| FR-16 | Admins can add credits to any user via `POST /admin/credits` | P1 |
| FR-17 | Insufficient credits returns a clear error message, not a silent failure | P0 |

### 3.4 API Chat Endpoint

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-18 | `POST /api/v1/chat` accepts a question + API key and routes to the purchased agent | P0 |
| FR-19 | API key determines which agent to call (no routing needed — key is scoped to one agent) | P0 |
| FR-20 | The endpoint handles scoped token generation and A2A communication transparently | P0 |
| FR-21 | Returns JSON response with agent answer, credits remaining, and agent name | P0 |

### 3.5 Agent Purchase System

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-28 | Agent cards displayed in UI with name, description, skills, tags, and **price** (in credits) | P0 |
| FR-29 | Users can "buy" (unlock) an agent by clicking "Buy" on its card — credits deducted | P0 |
| FR-30 | Purchase prices: filmbot=10, melody=10, rock=10, filmbot_v2=30 | P0 |
| FR-31 | After purchase, agent card shows "Purchased" badge + API key + endpoint URL | P0 |
| FR-32 | Users can only chat with agents they have purchased | P0 |
| FR-33 | Each query to a purchased agent still costs per-query credits (1 or 3) | P0 |

### 3.6 API Key System (Programmatic Access)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-34 | Purchasing an agent auto-generates an API key scoped to that agent (`mk_<agent>_<random>`) | P0 |
| FR-35 | `POST /api/v1/chat` accepts `x-api-key` header for programmatic access | P0 |
| FR-36 | API key calls deduct per-query credits and respect rate limits | P0 |
| FR-37 | Users can revoke an API key via `DELETE /me/api-key/{key_id}` | P1 |
| FR-38 | After purchase, UI shows code example (curl/Python) for using the API | P0 |

### 3.7 Web UI (Storefront Only — No Chat)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-39 | Login/signup screen shown on first visit | P0 |
| FR-40 | After login, show **agent cards grid** as the main view | P0 |
| FR-41 | JWT stored in sessionStorage; sent with every request | P0 |
| FR-42 | Credits displayed in the header (updates after purchase) | P0 |
| FR-43 | Each agent card shows: name, description, tags, price, "Buy" button | P0 |
| FR-44 | After purchase, card shows: "Owned" badge, API key (masked by default with show/hide toggle), endpoint URL, code examples (curl + Python) | P0 |
| FR-45 | **No chat interface on the website** — users use API key from their own code | P0 |
| FR-46 | "My Agents" section listing all purchased agents with their API keys | P1 |
| FR-47 | Logout button that clears JWT and redirects to login | P0 |
| FR-48 | Usage History section showing: timestamp (IST), agent, question, credits spent, IP address, status | P0 |
| FR-49 | All timestamps displayed in Indian Standard Time (IST) using `en-IN` locale | P0 |
| FR-50 | API key masked as `mk_film...xxxx` with "Show"/"Hide" toggle; code examples show `YOUR_API_KEY` placeholder | P0 |

---

## 4. Non-Functional Requirements

### 4.1 Security (Guardrails)

| ID | Requirement | Category | Priority |
|----|-------------|----------|----------|
| NFR-1 | Input sanitization: block SQL injection patterns (`'; DROP`, `UNION SELECT`, etc.) | Security & Privacy | P0 |
| NFR-2 | Input sanitization: block prompt injection patterns (`ignore previous instructions`, `system prompt`, etc.) | Security & Privacy | P0 |
| NFR-3 | Output sanitization: strip PII patterns (emails, phone numbers, SSNs) from responses | Data Access & Compliance | P1 |
| NFR-4 | Output sanitization: block system prompt leakage | Security & Privacy | P0 |
| NFR-5 | Rate limiting: max 10 requests per minute per user | Security & Privacy | P0 |
| NFR-6 | Rate limiting: blocked requests return 429 with `retry_after` | Security & Privacy | P0 |
| NFR-7 | All agent ports (9001-9004) blocked externally — only port 8000 exposed | Security & Privacy | P0 |
| NFR-8 | Direct agent access without a valid token returns 401 | Security & Privacy | P0 |
| NFR-9 | Token for agent A cannot be used to access agent B (scoping) | Security & Privacy | P0 |
| NFR-10 | Expired tokens are rejected with 403 | Security & Privacy | P0 |
| NFR-11 | No secrets (JWT_SECRET, MARKETPLACE_SECRET) in client-side code | Security & Privacy | P0 |
| NFR-12 | Parameterized SQL queries everywhere (no string concatenation) | Security & Privacy | P0 |

### 4.2 Guardrail Categories (from slide)

| Guardrail | Implementation |
|-----------|---------------|
| **Data/Content Accuracy** | Agents query real databases (IMDB, Chinook); responses are grounded in SQL results, not hallucinated |
| **Role-Based Restrictions** | JWT `role` field: `user` can chat + generate API keys; `admin` can add credits + manage agents |
| **Ethical and Compliance** | Output sanitizer filters biased/offensive content patterns |
| **Security and Privacy** | bcrypt passwords, JWT expiry, scoped tokens, input/output sanitization, rate limiting |
| **Data Access and Compliance** | Token scoping ensures users/agents only access authorized agents; credits gate access |
| **Real-Time Monitoring** | `usage_logs` table logs every request: user, agent, question, credits, blocked status, IP, timestamp |
| **Customizable Guardrails** | `sanitizer.py` with configurable regex patterns; easy to add new threat patterns |

### 4.3 Performance

| ID | Requirement | Priority |
|----|-------------|----------|
| NFR-13 | Agent responses return within 300 seconds (LLM timeout) | P0 |
| NFR-14 | Token validation adds < 100ms overhead | P1 |
| NFR-15 | System supports 4 concurrent agents on a single EC2 instance | P0 |

### 4.4 Accessibility

| ID | Requirement | Priority |
|----|-------------|----------|
| NFR-16 | Marketplace accessible from any machine on the network (bind to `0.0.0.0`) | P0 |
| NFR-17 | API accessible via standard HTTP (curl, Python requests, etc.) | P0 |

---

## 5. System Architecture

```
Internet / Other Laptops
         │
         ▼
   EC2 (public IP:8000)
         │
    ┌────┴─────────────────────────────────────────┐
    │           Marketplace Server (:8000)          │
    │                                               │
    │  ┌─────────┐ ┌──────────┐ ┌───────────────┐  │
    │  │  Auth   │ │ Credits  │ │  Sanitizer    │  │
    │  │  (JWT)  │ │ (SQLite) │ │ (Input/Output)│  │
    │  └─────────┘ └──────────┘ └───────────────┘  │
    │  ┌─────────┐ ┌──────────┐ ┌───────────────┐  │
    │  │  Agent  │ │  Token   │ │ Rate Limiter  │  │
    │  │Registry │ │ Manager  │ │ (Per-User)    │  │
    │  └─────────┘ └──────────┘ └───────────────┘  │
    │  ┌─────────┐ ┌──────────┐ ┌───────────────┐  │
    │  │ API Key │ │  Usage   │ │   Web UI      │  │
    │  │ Manager │ │  Logs    │ │ (Storefront)  │  │
    │  └─────────┘ └──────────┘ └───────────────┘  │
    └────┬────────┬────────┬────────┬──────────────┘
         │        │        │        │
    ┌────┴──┐ ┌───┴───┐ ┌──┴────┐ ┌─┴──────┐
    │FilmBot│ │Film V2│ │Melody │ │  Rock  │
    │ :9001 │ │ :9002 │ │ :9003 │ │ :9004  │
    │IMDB   │ │IMDB+  │ │Chinook│ │IMDB    │
    │SQL    │ │Vec+KG │ │Music  │ │Detail  │
    └───────┘ └───────┘ └───────┘ └────────┘
     (internal only — blocked by security group)
```

---

## 6. API Specification

### Public Endpoints (no auth)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Web UI (storefront — browse & buy agents) |
| GET | `/agents` | List all registered agents |
| GET | `/agents/{id}` | Get specific agent details |
| GET | `/health` | System health check |
| GET | `/tokens/validate` | Validate a scoped token |

### Auth Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/auth/signup` | None | Create account → returns JWT |
| POST | `/auth/login` | None | Login → returns JWT |

### Protected Endpoints (JWT required)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/me` | User profile + credits |
| GET | `/me/agents` | List purchased agents with API keys |
| GET | `/me/usage` | Usage history |
| POST | `/agents/{agent_id}/buy` | Purchase an agent (deducts purchase price, generates API key) |
| DELETE | `/me/api-key/{key_id}` | Revoke an API key |

### Agent Access (API key required — used from user's own code)

| Method | Endpoint | Header | Description |
|--------|----------|--------|-------------|
| POST | `/api/v1/chat` | `x-api-key: mk_<agent>_...` | Send question to purchased agent (deducts per-query credits) |

### Admin Endpoints (admin JWT required)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/admin/credits` | Add credits to a user |
| POST | `/agents/register` | Register an agent (also requires marketplace secret) |
| DELETE | `/agents/{id}` | Remove an agent |

---

## 7. Data Model

### Existing Tables (no changes)

**agents** — agent registry
```
agent_id | name | description | url | card_json | status | registered_at
```

**tokens** — scoped agent-to-agent tokens
```
token | target_agent_id | requester_id | expires_at | revoked | created_at
```

### New Tables

**users** — user accounts
```sql
CREATE TABLE users (
    user_id       TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,          -- bcrypt
    role          TEXT DEFAULT 'user',    -- 'user' | 'admin'
    credits       INTEGER DEFAULT 100,
    locked        INTEGER DEFAULT 0,
    failed_logins INTEGER DEFAULT 0,
    created_at    TEXT DEFAULT (datetime('now'))
);
```

**user_agents** — tracks which user purchased which agent
```sql
CREATE TABLE user_agents (
    user_id      TEXT NOT NULL,
    agent_id     TEXT NOT NULL,
    purchased_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, agent_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
```

**api_keys** — programmatic access keys (scoped per agent)
```sql
CREATE TABLE api_keys (
    key_id     TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    agent_id   TEXT NOT NULL,              -- key is scoped to one agent
    api_key    TEXT NOT NULL UNIQUE,        -- mk_<agent_id>_<random>
    created_at TEXT DEFAULT (datetime('now')),
    revoked    INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
```

**usage_logs** — audit trail
```sql
CREATE TABLE usage_logs (
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
```

---

## 8. Agent Cost Configuration

### Purchase Price (one-time, to unlock agent)
| Agent | Price (credits) |
|-------|----------------|
| filmbot | 10 |
| melody | 10 |
| rock | 10 |
| filmbot_v2 | 30 |

### Per-Query Cost (each API call after purchase)
| Agent | Cost (credits) | Justification |
|-------|---------------|---------------|
| filmbot | 1 | Basic SQL queries |
| melody | 1 | Basic SQL queries |
| rock | 1 | Basic SQL queries |
| filmbot_v2 | 3 | Uses vector search + knowledge graph (more compute) |

---

## 9. Security Request Pipeline

Every `POST /api/v1/chat` request passes through this pipeline:

```
Request arrives (with x-api-key header)
    │
    ▼
[1] Auth ──────── Validate API key → get user_id + agent_id
    │              Invalid/revoked/missing → 401 Unauthorized
    ▼
[2] Lockout ───── Is account locked?
    │              Yes → 403 Account Locked
    ▼
[3] Rate Limit ── >10 requests in 60s?
    │              Yes → 429 Too Many Requests
    ▼
[4] Input ─────── SQL injection? Prompt injection?
    Sanitize       Yes → 400 Blocked (reason logged)
    │
    ▼
[5] Credits ───── Enough credits for per-query cost?
    Check          No → 402 Insufficient Credits
    │
    ▼
[6] Call Agent ── Get scoped token → A2A call → get response
    │              (agent_id already known from API key)
    ▼
[7] Output ────── PII? System prompt leak? Sensitive data?
    Sanitize       Strip/redact if found
    │
    ▼
[8] Deduct ────── Atomic credit deduction in DB
    Credits
    │
    ▼
[9] Log ──────── Write to usage_logs (user, agent, question, credits, IP)
    │
    ▼
Return JSON response to user
```

---

## 10. User Flows

### Flow 1: New User — Browse & Buy
```
1. Visit http://<ec2-ip>:8000
2. See login/signup screen
3. Sign up with username + password
4. Receive JWT + 100 credits
5. See agent cards grid (FilmBot, Melody, Rock, FilmBot V2)
   - Each card shows: name, description, tags, price (e.g. "10 credits")
   - "Buy" button on each card
6. Click "Buy" on FilmBot → credits: 100 → 90
7. FilmBot card now shows: "Owned" badge + API key + endpoint URL
8. Copy API key + endpoint
9. Use from their own code (NO chat on website)
```

### Flow 2: Using the API Key Locally
```
1. Sign up + buy FilmBot on the website
2. Card shows: API key (mk_filmbot_a8f3c2...) + endpoint + code examples
3. Copy the key, go to their own terminal/project:

   curl -X POST http://<ec2-ip>:8000/api/v1/chat \
     -H "x-api-key: mk_filmbot_a8f3c2..." \
     -H "Content-Type: application/json" \
     -d '{"message": "Top 5 movies by rating"}'

4. Gets JSON response with agent answer
5. Per-query credits deducted (1 credit per call)
6. Can check remaining credits on the website
```

### Flow 3: Attacker Blocked
```
1. Attacker sends: "'; DROP TABLE users; --"
2. Input sanitizer detects SQL injection pattern
3. Request blocked with 400 error
4. Logged to usage_logs with blocked=1, block_reason="sql_injection"
5. No credits deducted, no agent called
```

---

## 11. Agents

| Agent | Port | Database | Capabilities | Cost |
|-------|------|----------|-------------|------|
| **FilmBot** | 9001 | IMDB (1000 movies) | SQL queries on movies, actors, ratings, gross | 1 credit |
| **FilmBot V2** | 9002 | IMDB + ChromaDB + Neo4j | SQL + vector similarity + knowledge graph queries | 3 credits |
| **Melody Bot** | 9003 | Chinook (music store) | SQL queries on artists, albums, tracks, genres, playlists | 1 credit |
| **Rock Agent** | 9004 | IMDB (1000 movies) | SQL queries with detailed reasoning | 1 credit |

Each agent operates independently — no agent-to-agent calls.

---

## 12. Technology Stack

| Layer | Technology |
|-------|-----------|
| LLM | Ollama (qwen2.5:7b) — local |
| Agent Framework | LangGraph |
| LLM Interface | LangChain (Ollama) |
| Agent Protocol | Google A2A (JSON-RPC) |
| Server | FastAPI + Uvicorn |
| Auth | PyJWT + bcrypt |
| Database | SQLite |
| Vector Store | ChromaDB (FilmBot V2) |
| Knowledge Graph | Neo4j (FilmBot V2) |
| HTTP Client | httpx |
| Deployment | AWS EC2 |

---

## 13. Files to Create/Modify

### New Files
| File | Purpose |
|------|---------|
| `marketplace/users.py` | User management, JWT, bcrypt, API keys, credit operations |
| `marketplace/sanitizer.py` | Input/output validation (SQL injection, prompt injection, PII) |
| `marketplace/rate_limiter.py` | Per-user sliding window rate limiter |

### Files to Modify
| File | Changes |
|------|---------|
| `marketplace/db.py` | Add users, user_agents, api_keys, usage_logs tables; add log_usage() |
| `marketplace/models.py` | Add SignupRequest, LoginRequest, LoginResponse, UserProfile |
| `marketplace/auth.py` | Add JWT verification dependency (keep existing middleware) |
| `marketplace/server.py` | Add auth endpoints, /agents/{id}/buy, credit checks, sanitizer, rate limiter, /api/v1/chat. Remove /chat endpoint |
| `marketplace/static/` | Replace chat.html with storefront index.html — login/signup, agent cards grid, buy buttons, API key display |
| `run_marketplace.py` | Bind to 0.0.0.0 instead of localhost |
| `agents/base_server.py` | Bind to 0.0.0.0 |

---

## 14. Dependencies to Add

```
PyJWT>=2.8.0
bcrypt>=4.1.0
```

---

## 15. Acceptance Tests

| # | Test | Expected Result |
|---|------|----------------|
| 1 | Sign up with new username | 200 + JWT + 100 credits |
| 2 | Sign up with existing username | 409 Conflict |
| 3 | Login with correct password | 200 + JWT |
| 4 | Login with wrong password (5 times) | Account locked |
| 5 | Buy agent without JWT | 401 Unauthorized |
| 6 | Buy FilmBot with sufficient credits | 200 + API key returned + credits: 100 → 90 |
| 7 | Buy agent with insufficient credits | 402 Insufficient Credits |
| 8 | Buy same agent twice | 409 Already purchased |
| 9 | Use API key with `/api/v1/chat` | Agent response + per-query credits deducted |
| 10 | Use API key without purchasing | 401 (no valid key exists) |
| 11 | Send SQL injection in question | 400 Blocked |
| 12 | Send prompt injection in question | 400 Blocked |
| 13 | Send 11 requests in 1 minute | 11th returns 429 |
| 14 | Use revoked API key | 401 Unauthorized |
| 15 | Access agent port directly from outside | Connection refused (EC2 security group) |
| 16 | Access marketplace from another laptop | Works via `http://<ec2-ip>:8000` |
| 17 | Ask Melody about movies via API | Melody responds it only handles music |
| 18 | JWT expires after 15 min | 401 on next website request |
| 19 | Query with 0 credits remaining | 402 Insufficient Credits |
| 20 | No API key in request | 401 Unauthorized |

---

## 16. Deployment Checklist (EC2)

- [ ] Launch EC2 instance (Ubuntu, t2.medium or larger for Ollama)
- [ ] Install Python 3.11+, Ollama, pull qwen2.5:7b
- [ ] Clone repo, install dependencies
- [ ] Set environment variables: `JWT_SECRET`, `MARKETPLACE_SECRET` (strong random values)
- [ ] Security group: allow inbound TCP 8000 from `0.0.0.0/0`, block 9001-9004
- [ ] Run `python run_marketplace.py` (binds to 0.0.0.0)
- [ ] Verify from another machine: `curl http://<ec2-ip>:8000/health`
- [ ] Test signup/login/chat from another laptop's browser
