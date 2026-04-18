<h1 align="center">🛒 Agent Marketplace</h1>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-Backend-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/LangGraph-Agents-2CA5E0?style=for-the-badge" />
  <img src="https://img.shields.io/badge/A2A-Protocol-6750A4?style=for-the-badge" />
  <img src="https://img.shields.io/badge/MCP-Server-FF6B35?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Security-9_Layer_Pipeline-red?style=for-the-badge&logo=shield&logoColor=white" />
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" />
</p>

<p align="center">
  <img src="https://img.shields.io/github/last-commit/Abhineetraj07/agent-marketplace?style=flat-square&color=blue" />
  <img src="https://img.shields.io/badge/Agents-4_Live-brightgreen?style=flat-square" />
  <img src="https://img.shields.io/badge/Security_Checks-9_per_request-red?style=flat-square" />
  <img src="https://img.shields.io/badge/Input_Patterns-66_blocked-orange?style=flat-square" />
  <img src="https://img.shields.io/badge/MCP_Vulns-5_Demonstrated-purple?style=flat-square" />
  <img src="https://img.shields.io/badge/Signup-Email_OTP_Verified-green?style=flat-square" />
</p>

<p align="center">
  A <b>production-grade AI Agent Marketplace</b> built with FastAPI and the A2A (Agent-to-Agent) protocol.<br/>
  Users sign up with <b>email OTP verification</b>, purchase AI agents with credits, and query them via scoped API keys —<br/>
  with every request passing through a <b>9-step security pipeline</b>.<br/>
  Also includes a full <b>MCP server</b> for Claude Desktop integration and an <b>MCP vulnerability demo suite</b>.
</p>

---

## 🏗️ Architecture

```
Internet ──▶ Marketplace :8000  (public-facing HTTP API + UI)
                │
                ├── /auth/signup       Email + OTP verification flow
                ├── /auth/verify-otp   OTP confirmation → account activated
                ├── /auth/login        JWT authentication
                ├── /agents            Discovery + purchase
                ├── /api/v1/chat       API key + credits + 9-step pipeline
                └── /me                Profile, keys, usage
                │
                │   (internal-only — not exposed to internet)
                ├── FilmBot        :9001
                ├── FilmBot V2     :9002
                ├── Melody Bot     :9003
                └── Rock Agent     :9004

Claude Desktop ──▶ MCP Server (stdio / SSE :8100)
                │
                ├── list_agents     Browse available agents (no auth)
                ├── purchase_agent  Buy an agent with JWT token
                ├── query_agent     Query via API key (full security pipeline)
                └── get_credits     Check remaining credits
```

All agent ports are **internal only**. Only port 8000 is public-facing.

---

## 🤖 Available Agents

| Agent | Port | Database | Description | Purchase | Per Query |
|-------|------|----------|-------------|----------|-----------|
| **FilmBot** | 9001 | IMDB (SQLite) | Movie expert — ratings, actors, directors, box office | 10 credits | 1 credit |
| **FilmBot V2** | 9002 | IMDB + ChromaDB + Neo4j | Advanced movie AI — SQL + vector search + knowledge graph | 30 credits | 3 credits |
| **Melody Bot** | 9003 | Chinook (SQLite) | Music store assistant — artists, albums, tracks, playlists | 10 credits | 1 credit |
| **Rock Agent** | 9004 | IMDB (SQLite) | Deep movie analyst with step-by-step SQL reasoning | 10 credits | 1 credit |

Agents can **collaborate with each other** — a movie agent can call the music agent and vice versa, all routed through the marketplace with credit accounting.

---

## 📧 Email OTP Signup Flow

New users must verify their email address before their account is activated:

```
1. POST /auth/signup      → username + password + email
                            → account created (unverified)
                            → 6-digit OTP sent via Gmail SMTP (expires 10 min)

2. POST /auth/verify-otp  → username + OTP
                            → account marked verified
                            → ready to login

3. POST /auth/login       → returns JWT (only for verified accounts)
```

- OTP is a **6-digit code**, valid for **10 minutes**
- Styled HTML email sent via **Gmail SMTP** (`GMAIL_USER` + `GMAIL_APP_PASSWORD` env vars)
- In local dev with no `GMAIL_APP_PASSWORD` set, OTP is printed to console for testing
- Unverified accounts **cannot log in**

---

## 🛡️ 9-Step Security Pipeline

Every `/api/v1/chat` request (and every `query_agent` MCP call) passes through all 9 checks:

```
Request arrives
      │
      ▼
1. API Key Validation    ── Valid and not revoked?
      │
      ▼
2. Account Check         ── Account locked or unverified?
      │
      ▼
3. Rate Limiting         ── Under 10 requests/minute? (sliding window per user)
      │
      ▼
4. Input Sanitization    ── SQL injection? Prompt injection? Path traversal?
      │
      ▼
5. Credit Check          ── Enough credits? (deducted upfront before agent call)
      │
      ▼
6. Agent Call            ── A2A protocol with scoped token
      │
      ▼
7. Output Sanitization   ── Strip leaked secrets, PII, schema info
      │
      ▼
8. Usage Logging         ── Full audit trail: IP, credits, block reasons
      │
      ▼
9. Response              ── Return cleaned response + remaining credit balance
```

---

## 🔒 Security Features

### Authentication & Sessions
- JWT authentication with auto-generated secrets (persisted at `0o600` permissions)
- `bcrypt` password hashing
- Token versioning for **instant JWT revocation** on logout — no blacklist needed
- Account lockout after **5 failed login attempts**
- **Email OTP verification** required before first login

### Rate Limiting — 4-tier sliding window

| Tier | Limit | Window | Scope |
|------|-------|--------|-------|
| Chat / MCP queries | 10 requests | per minute | per user |
| Login / Auth | 5 requests | per minute | per IP |
| Signup | 3 accounts | per hour | per IP |
| IP signup cap | 5 accounts | lifetime | per IP |

The **IP-level signup cap** (`IPSignupTracker`) permanently blocks any IP that has created 5 accounts — preventing credit farming via repeated signups regardless of timing.

### Input Sanitization
- **26 SQL injection patterns** blocked
- **40 prompt injection patterns** blocked
- Path traversal detection
- Unicode normalization: NFKC + Cyrillic homoglyph mapping + zero-width char stripping + HTML entity decoding + dot/space deobfuscation

### Output Sanitization
- Strips leaked password hashes, API keys, JWT tokens, bcrypt hashes, schema info

### Agent-Level SQL Protection
- Only `SELECT` and `PRAGMA` allowed in agent queries
- Blocks `ATTACH DATABASE`, `LOAD_EXTENSION`, marketplace table references

### Infrastructure Security
- Security headers: `X-Frame-Options`, `X-Content-Type-Options`, `Cache-Control`, hidden server identity
- Timing-safe secret comparison via `hmac.compare_digest`
- CORS restriction (configurable allowed origins)
- Parameterized SQL queries throughout — zero string interpolation
- ASGI lifespan wrapper for reliable agent startup registration

---

## 🔌 MCP Server

The marketplace exposes a full **Model Context Protocol (MCP) server** so tools like **Claude Desktop** can browse, purchase, and query agents directly — through the same security pipeline.

### MCP Tools

| Tool | Auth Required | Description |
|------|--------------|-------------|
| `list_agents` | None | Browse all available agents with skills and pricing |
| `purchase_agent` | JWT token | Buy an agent and receive an API key |
| `query_agent` | API key | Query an agent (full 9-step security pipeline) |
| `get_credits` | API key | Check remaining credit balance |

### Running the MCP Server

```bash
# stdio transport — for Claude Desktop
python -m mcp_server.server

# SSE transport — for remote MCP clients (default port 8100)
python -m mcp_server.server --sse 8100
```

### Claude Desktop Configuration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "agent-marketplace": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/path/to/agent-marketplace"
    }
  }
}
```

---

## 🧪 MCP Vulnerability Demo Suite

The `mcp_vulns/` directory demonstrates **5 real MCP-specific attacks** and how the marketplace's defenses block each one.

| # | Attack | Description |
|---|--------|-------------|
| 1 | **Supply-Chain Attack** | Malicious tool injected via a compromised MCP registry |
| 2 | **Tool Poisoning** | Hidden instructions embedded in tool descriptions to hijack the LLM |
| 3 | **Tool Shadowing** | A rogue tool overrides a legitimate one to intercept calls |
| 4 | **Rug Pull Attack** | Tool behaviour changes silently after trust is established |
| 5 | **Sandbox Escape / RAC** | Repeated Adversarial Clarification — probing for filesystem/shell access |

```bash
python -m mcp_vulns.runner --all              # Run all 5 demos
python -m mcp_vulns.runner --vuln 2           # Run specific vulnerability
python -m mcp_vulns.runner --all --defense-only  # Show defense results only
```

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- [Ollama](https://ollama.ai) with `qwen2.5:7b` pulled
- Neo4j Community Edition (optional — FilmBot V2 only)

### Install

```bash
git clone https://github.com/Abhineetraj07/agent-marketplace.git
cd agent-marketplace
pip install -r requirements.txt
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GMAIL_USER` | For email OTP | Gmail address to send OTP from |
| `GMAIL_APP_PASSWORD` | For email OTP | Gmail app password (not your account password) |
| `JWT_SECRET` | Optional | Auto-generated if not set |
| `MARKETPLACE_SECRET` | Optional | Auto-generated if not set |
| `MARKETPLACE_PORT` | Optional | Default: `8000` |
| `ALLOWED_ORIGINS` | Optional | Comma-separated CORS origins |

> **Local dev tip:** If `GMAIL_APP_PASSWORD` is not set, OTPs are printed to the console instead of emailed — no email setup needed for development.

### Run

```bash
python run_marketplace.py
```

Starts all 5 services:
- Marketplace UI + API → `http://localhost:8000`
- FilmBot → `:9001` · FilmBot V2 → `:9002` · Melody Bot → `:9003` · Rock Agent → `:9004`

---

## 📖 Usage

### Step 1 — Sign Up & Verify Email

```bash
# 1. Sign up
curl -X POST http://localhost:8000/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "MyPassword123!", "email": "alice@example.com"}'
# → OTP sent to alice@example.com (or printed to console in dev)

# 2. Verify OTP
curl -X POST http://localhost:8000/auth/verify-otp \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "otp": "482951"}'
# → Account activated, 100 free credits added
```

### Step 2 — Login & Buy an Agent

```bash
# Login
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "MyPassword123!"}'
# → Returns JWT token

# Purchase FilmBot
curl -X POST http://localhost:8000/agents/filmbot/buy \
  -H "Authorization: Bearer <your-jwt>"
# → Returns API key: mk_filmbot_a8f3c2...
```

### Step 3 — Query via API Key

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "x-api-key: mk_filmbot_a8f3c2..." \
  -H "Content-Type: application/json" \
  -d '{"message": "Top 5 movies by IMDb rating"}'
```

### Step 4 — Monitor Usage

The web UI at `http://localhost:8000` provides three tabs:

| Tab | What you see |
|-----|-------------|
| **Browse Agents** | All available agents with pricing and purchase |
| **My API Keys** | All keys (active + revoked) with purchase details |
| **Usage History** | Every query logged with IP, credits spent, block reasons |

---

## ☁️ EC2 Deployment

```bash
# 1. Open ONLY port 8000 in your security group
# 2. Set environment variables
export ALLOWED_ORIGINS="http://<your-ec2-ip>:8000"
export GMAIL_USER="your-gmail@gmail.com"
export GMAIL_APP_PASSWORD="your-app-password"

# 3. Launch
python run_marketplace.py
```

---

## 📁 Project Structure

```
agent-marketplace/
├── marketplace/
│   ├── server.py          # FastAPI app — all endpoints
│   ├── auth.py            # Marketplace secret + agent auth middleware
│   ├── users.py           # User CRUD, JWT, OTP verify, credits, API keys
│   ├── email_service.py   # Gmail SMTP OTP sender (6-digit, 10-min expiry)
│   ├── db.py              # SQLite schema + queries
│   ├── sanitizer.py       # Input/output validation (SQL, prompt, PII, path)
│   ├── rate_limiter.py    # 4-tier rate limiter + IP signup cap
│   ├── agent_tools.py     # LangChain tools for agent-to-agent collaboration
│   ├── models.py          # Pydantic request/response models
│   └── static/
│       └── index.html     # Storefront UI (dark theme, responsive)
│
├── agents/
│   ├── base_server.py        # Generic A2A agent server builder
│   ├── enhanced_agent.py     # LangGraph agent + marketplace collaboration tools
│   ├── filmbot_server.py     # FilmBot A2A server (port 9001)
│   ├── filmbot_v2_server.py  # FilmBot V2 A2A server (port 9002)
│   ├── melody_server.py      # Melody Bot A2A server (port 9003)
│   └── rock_server.py        # Rock Agent A2A server (port 9004)
│
├── mcp_server/            # MCP server for Claude Desktop / MCP clients
│   ├── server.py          # FastMCP server — 4 tools
│   ├── auth_bridge.py     # JWT + API key auth for MCP context
│   └── defenses.py        # MCP-specific defenses (registry, sandbox, manifest)
│
├── mcp_vulns/             # MCP vulnerability demo suite
│   ├── runner.py                # CLI runner
│   ├── vuln1_supply_chain.py
│   ├── vuln2_tool_poisoning.py
│   ├── vuln3_tool_shadowing.py
│   ├── vuln4_rug_pull.py
│   └── vuln5_sandbox_escape.py
│
├── filmbot_agent.py       # FilmBot core — tools, prompts, LangGraph agent
├── filmbot_v2/            # FilmBot V2 — SQL + vector + knowledge graph
├── rock.py                # Rock Agent core
├── rock2.py               # Melody Bot core (Chinook DB)
├── run_marketplace.py     # Launch all 5 services
└── requirements.txt
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | FastAPI · Uvicorn · SQLite |
| **Authentication** | PyJWT · bcrypt · Email OTP (Gmail SMTP) |
| **AI Agents** | LangChain · LangGraph · Ollama (`qwen2.5:7b`) |
| **Vector Search** | ChromaDB + Nomic embeddings |
| **Knowledge Graph** | Neo4j (Cypher) |
| **Agent Protocol** | A2A SDK (Agent-to-Agent) |
| **MCP Server** | FastMCP (stdio + SSE transport) |
| **Frontend** | Vanilla HTML/CSS/JS (dark theme, responsive) |

---

## 👨‍💻 Author

**Abhineet Raj** · CS @ SRM Institute of Science & Technology
🌐 [Portfolio](https://aabhineet07-portfolio.netlify.app/) · 🐙 [GitHub](https://github.com/Abhineetraj07) · 💼 [LinkedIn](https://www.linkedin.com/in/abhineet2005/)

---

## 📄 License

MIT License
