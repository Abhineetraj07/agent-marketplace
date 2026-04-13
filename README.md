<h1 align="center">🛒 Agent Marketplace</h1>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-Backend-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/LangGraph-Agents-2CA5E0?style=for-the-badge" />
  <img src="https://img.shields.io/badge/A2A-Protocol-6750A4?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Security-9_Layer_Pipeline-red?style=for-the-badge&logo=shield&logoColor=white" />
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" />
</p>

<p align="center">
  <img src="https://img.shields.io/github/last-commit/Abhineetraj07/agent-marketplace?style=flat-square&color=blue" />
  <img src="https://img.shields.io/badge/Agents-4_Live-brightgreen?style=flat-square" />
  <img src="https://img.shields.io/badge/Security_Checks-9_per_request-red?style=flat-square" />
  <img src="https://img.shields.io/badge/Input_Patterns-66_blocked-orange?style=flat-square" />
</p>

<p align="center">
  A <b>production-grade AI Agent Marketplace</b> built with FastAPI and the A2A (Agent-to-Agent) protocol.<br/>
  Users sign up, purchase AI agents with credits, and query them programmatically via scoped API keys —<br/>
  with every request passing through a <b>9-step security pipeline</b>.
</p>

---

## 🏗️ Architecture

```
Internet ──▶ Marketplace :8000  (public-facing)
                │
                ├── /auth/signup, /auth/login      JWT authentication
                ├── /agents                         Discovery + purchase
                ├── /api/v1/chat                    API key + credits + sanitizer
                └── /me                             Profile, keys, usage
                │
                │   (internal-only — not exposed to internet)
                ├── FilmBot        :9001
                ├── FilmBot V2     :9002
                ├── Melody Bot     :9003
                └── Rock Agent     :9004
```

All agent ports are **internal only**. Only port 8000 is public-facing. Agents communicate with each other via the A2A protocol with scoped tokens.

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

## 🛡️ 9-Step Security Pipeline

Every `/api/v1/chat` request passes through all 9 checks in order:

```
Request arrives
      │
      ▼
1. API Key Validation    ── Is the key valid and not revoked?
      │
      ▼
2. Account Check         ── Is the user's account locked?
      │
      ▼
3. Rate Limiting         ── Under 10 requests/minute? (sliding window)
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

**Authentication & Sessions**
- JWT authentication with auto-generated secrets (persisted at `0o600` permissions)
- `bcrypt` password hashing
- Token versioning for **instant JWT revocation** on logout — no blacklist needed
- Account lockout after **5 failed login attempts**

**Rate Limiting** (3-tier sliding window)
- Signup: 3 requests/min
- Login: 5 requests/min
- Chat: 10 requests/min per user

**Input Sanitization**
- **26 SQL injection patterns** blocked
- **40 prompt injection patterns** blocked
- Path traversal detection
- Unicode normalization: NFKC + Cyrillic homoglyph mapping + zero-width char stripping + HTML entity decoding + dot/space deobfuscation

**Output Sanitization**
- Strips leaked password hashes, API keys, JWT tokens, bcrypt hashes, schema info

**Agent-Level SQL Protection**
- Only `SELECT` and `PRAGMA` allowed in agent queries
- Blocks `ATTACH DATABASE`, `LOAD_EXTENSION`, and references to marketplace tables

**Infrastructure Security**
- Security headers: `X-Frame-Options`, `X-Content-Type-Options`, `Cache-Control`, hidden server identity
- Timing-safe secret comparison via `hmac.compare_digest`
- CORS restriction (configurable allowed origins)
- Parameterized SQL queries throughout — zero string interpolation

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- [Ollama](https://ollama.ai) with `qwen2.5:7b` pulled
- Neo4j Community Edition (optional — only for FilmBot V2 knowledge graph)

### Install

```bash
git clone https://github.com/Abhineetraj07/agent-marketplace.git
cd agent-marketplace
pip install -r requirements.txt
```

### Run

```bash
python run_marketplace.py
```

This starts **all 5 services** simultaneously:
- Marketplace UI + API → `http://localhost:8000`
- FilmBot → `:9001`
- FilmBot V2 → `:9002`
- Melody Bot → `:9003`
- Rock Agent → `:9004`

Open `http://localhost:8000` in your browser to use the storefront.

---

## 📖 Usage

### Step 1 — Sign Up (get 100 free credits)

```bash
curl -X POST http://localhost:8000/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "MyPassword123!"}'
```

### Step 2 — Browse & Buy an Agent

```bash
# List available agents
curl http://localhost:8000/agents

# Purchase FilmBot (requires JWT from login)
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

## ⚙️ Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MARKETPLACE_SECRET` | Auto-generated | Secret for agent registration |
| `JWT_SECRET` | Auto-generated | Secret for JWT signing |
| `MARKETPLACE_PORT` | `8000` | Marketplace server port |
| `ALLOWED_ORIGINS` | *(empty)* | Comma-separated CORS allowed origins |

Secrets are auto-generated on first run and persisted to `.jwt_secret` and `.marketplace_secret` with owner-only (`0o600`) permissions.

---

## ☁️ EC2 Deployment

```bash
# 1. Open ONLY port 8000 in your security group — agents are internal
# 2. Set CORS to your EC2 public IP
export ALLOWED_ORIGINS="http://<your-ec2-ip>:8000"

# 3. Launch all services
python run_marketplace.py
```

All servers bind to `0.0.0.0`. Agent ports (9001–9004) are **never exposed** to the internet.

---

## 📁 Project Structure

```
agent-marketplace/
├── marketplace/
│   ├── server.py          # FastAPI app — all endpoints
│   ├── auth.py            # Marketplace secret + agent auth middleware
│   ├── users.py           # User CRUD, JWT, credits, API keys, purchases
│   ├── db.py              # SQLite schema + queries
│   ├── sanitizer.py       # Input/output validation (SQL, prompt, PII, path)
│   ├── rate_limiter.py    # Sliding window rate limiter
│   ├── agent_tools.py     # LangChain tools for agent-to-agent collaboration
│   ├── models.py          # Pydantic request/response models
│   └── static/
│       └── index.html     # Storefront UI (dark theme, responsive)
│
├── agents/
│   ├── base_server.py     # Generic A2A agent server builder
│   ├── enhanced_agent.py  # LangGraph agent + marketplace collaboration tools
│   ├── filmbot_server.py  # FilmBot A2A server (port 9001)
│   ├── filmbot_v2_server.py  # FilmBot V2 A2A server (port 9002)
│   ├── melody_server.py   # Melody Bot A2A server (port 9003)
│   └── rock_server.py     # Rock Agent A2A server (port 9004)
│
├── filmbot_agent.py       # FilmBot core — tools, prompts, LangGraph agent
├── filmbot_v2/            # FilmBot V2 — SQL + vector + knowledge graph
├── rock.py                # Rock Agent core
├── rock2.py               # Melody Bot core (Chinook DB)
├── filmbot_a2a_server.py  # Standalone A2A server for FilmBot
├── filmbot_a2a_client.py  # A2A client for testing
├── filmbot_comparison.py  # Benchmark: standard vs A2A FilmBot
├── run_marketplace.py     # Launch all 5 services
└── requirements.txt
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | FastAPI · Uvicorn · SQLite |
| **Authentication** | PyJWT · bcrypt |
| **AI Agents** | LangChain · LangGraph · Ollama (`qwen2.5:7b`) |
| **Vector Search** | ChromaDB + Nomic embeddings |
| **Knowledge Graph** | Neo4j (Cypher) |
| **Agent Protocol** | A2A SDK (Agent-to-Agent) |
| **Frontend** | Vanilla HTML/CSS/JS (dark theme, responsive) |

---

## 👨‍💻 Author

**Abhineet Raj** · CS @ SRM Institute of Science & Technology
🌐 [Portfolio](https://aabhineet07-portfolio.netlify.app/) · 🐙 [GitHub](https://github.com/Abhineetraj07) · 💼 [LinkedIn](https://www.linkedin.com/in/abhineet2005/)

---

## 📄 License

MIT License
