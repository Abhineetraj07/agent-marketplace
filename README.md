# Agent Marketplace

A secure AI Agent Marketplace built with FastAPI and the A2A (Agent-to-Agent) protocol. Users sign up, purchase AI agents with credits, and access them programmatically via API keys.

Built for a hackathon where other teams actively try to break the system — security is production-grade, not demo-level.

## Architecture

```
Internet --> Marketplace :8000 (public-facing)
                |
                |-- /auth/signup, /auth/login      (JWT authentication)
                |-- /agents                         (discovery + purchase)
                |-- /api/v1/chat                    (API key + credits + sanitizer)
                |-- /me                             (profile, keys, usage)
                |
                |-- FilmBot :9001                   (internal only)
                |-- FilmBot V2 :9002                (internal only)
                |-- Melody Bot :9003                (internal only)
                |-- Rock Agent :9004                (internal only)
```

## Agents

| Agent | Port | Database | Description | Purchase | Per Query |
|-------|------|----------|-------------|----------|-----------|
| FilmBot | 9001 | IMDB (SQLite) | Movie expert — ratings, actors, directors | 10 credits | 1 credit |
| FilmBot V2 | 9002 | IMDB + ChromaDB + Neo4j | Advanced movie expert with SQL, vector search, and knowledge graph | 30 credits | 3 credits |
| Melody Bot | 9003 | Chinook (SQLite) | Music store assistant — artists, albums, tracks | 10 credits | 1 credit |
| Rock Agent | 9004 | IMDB (SQLite) | Detailed movie analyst with step-by-step SQL reasoning | 10 credits | 1 credit |

Agents collaborate via the marketplace — a movie agent can ask the music agent for help and vice versa.

## Security Pipeline (9 Steps)

Every `/api/v1/chat` request passes through:

```
1. API Key Validation    --> Is the key valid and not revoked?
2. Account Check         --> Is the user's account locked?
3. Rate Limiting         --> Under 10 requests/minute?
4. Input Sanitization    --> SQL injection, prompt injection, path traversal?
5. Credit Check          --> Enough credits? (deduct upfront)
6. Agent Call            --> A2A protocol with scoped token
7. Output Sanitization   --> Strip leaked secrets, PII, schema info
8. Usage Logging         --> Audit trail with IP address
9. Response              --> Return cleaned response + credit info
```

## Security Features

- **JWT Authentication** with auto-generated secrets (persisted to file, 0o600 permissions)
- **bcrypt** password hashing
- **Token versioning** for instant JWT revocation on logout (no blacklist needed)
- **Account lockout** after 5 failed login attempts
- **3-tier rate limiting**: signup (3/min), login (5/min), chat (10/min per user)
- **Input sanitization**: 26 SQL injection patterns, 40 prompt injection patterns, path traversal detection
- **Unicode normalization**: NFKC + Cyrillic homoglyph mapping + zero-width char stripping + HTML entity decoding + dot/space deobfuscation
- **Output sanitization**: blocks leaked password hashes, API keys, JWT tokens, schema info, bcrypt hashes
- **Agent-level SQL protection**: only SELECT/PRAGMA allowed, blocks ATTACH DATABASE, LOAD_EXTENSION, and references to marketplace tables
- **Security headers**: X-Frame-Options, X-Content-Type-Options, Cache-Control, hidden server identity
- **Timing-safe** secret comparison (hmac.compare_digest)
- **CORS** restriction (configurable allowed origins)
- **Parameterized SQL queries** throughout (no string interpolation)

## How It Works

### 1. Sign Up and Get Credits
```bash
curl -X POST http://localhost:8000/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "MyPassword123!"}'
```
New users get **100 free credits**.

### 2. Browse and Buy Agents
```bash
# List available agents
curl http://localhost:8000/agents

# Buy an agent (requires JWT)
curl -X POST http://localhost:8000/agents/filmbot/buy \
  -H "Authorization: Bearer <your-jwt>"
```
Returns an API key like `mk_filmbot_a8f3c2...`

### 3. Query via API Key
```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "x-api-key: mk_filmbot_a8f3c2..." \
  -H "Content-Type: application/json" \
  -d '{"message": "Top 5 movies by rating"}'
```

### 4. Monitor Usage
The web UI at `http://localhost:8000` provides:
- **Browse Agents** tab — view and purchase agents
- **My API Keys** tab — all keys (active + revoked) with purchase details
- **Usage History** tab — every query logged with IP, credits spent, and block reasons

## Quick Start

### Prerequisites
- Python 3.11+
- [Ollama](https://ollama.ai) with `qwen2.5:7b` model pulled
- Neo4j (optional, for FilmBot V2 knowledge graph)

### Install
```bash
pip install -r requirements.txt
```

### Run
```bash
python run_marketplace.py
```
This starts the marketplace on port 8000 and all 4 agents on ports 9001-9004.

Open `http://localhost:8000` in your browser.

### Environment Variables (Optional)
| Variable | Default | Description |
|----------|---------|-------------|
| `MARKETPLACE_SECRET` | Auto-generated | Secret for agent registration |
| `JWT_SECRET` | Auto-generated | Secret for JWT signing |
| `MARKETPLACE_PORT` | 8000 | Marketplace server port |
| `ALLOWED_ORIGINS` | (empty) | Comma-separated CORS origins |

If not set, secrets are auto-generated and persisted to `.jwt_secret` and `.marketplace_secret` (owner-only permissions).

## EC2 Deployment

1. Open only port **8000** in the security group (agents are internal-only)
2. Set `ALLOWED_ORIGINS` to your EC2 public IP
3. Run `python run_marketplace.py` — all servers bind to `0.0.0.0`

## Project Structure

```
marketplace/
  server.py          # FastAPI app — all endpoints
  auth.py            # Marketplace secret + agent auth middleware
  users.py           # User CRUD, JWT, credits, API keys, purchases
  db.py              # SQLite schema + queries
  sanitizer.py       # Input/output validation (SQL, prompt, PII, path)
  rate_limiter.py    # Sliding window rate limiter
  agent_tools.py     # LangChain tools for agent-to-agent collaboration
  models.py          # Pydantic request/response models
  static/index.html  # Storefront UI
agents/
  base_server.py     # Generic A2A agent server builder
  enhanced_agent.py  # LangGraph agent with marketplace collaboration tools
  filmbot_server.py  # FilmBot A2A server
  filmbot_v2_server.py
  melody_server.py
  rock_server.py
filmbot_agent.py     # FilmBot core — tools, prompts, LangGraph agent
filmbot_v2/          # FilmBot V2 — SQL + vector + knowledge graph
rock.py              # Rock Agent core
rock2.py             # Melody Bot core (Chinook DB)
run_marketplace.py   # Launch all services
```

## Tech Stack

- **Backend**: FastAPI, Uvicorn, SQLite
- **Auth**: PyJWT, bcrypt
- **AI**: LangChain, LangGraph, Ollama (qwen2.5:7b)
- **Vector Search**: ChromaDB
- **Knowledge Graph**: Neo4j
- **Protocol**: A2A (Agent-to-Agent)
- **Frontend**: Vanilla HTML/CSS/JS (dark theme, responsive)
