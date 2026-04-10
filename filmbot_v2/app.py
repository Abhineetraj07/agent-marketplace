"""
FilmBot V2 — FastAPI server with async endpoints and Redis caching.
Multi-modal AI movie agent: SQL + Vector Search + Knowledge Graph.
"""

import hashlib
import json
import asyncio
from contextlib import asynccontextmanager

import redis
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field

from config import REDIS_HOST, REDIS_PORT, REDIS_TTL
from agent import invoke_agent


# ── Redis Cache ───────────────────────────────────────────────

redis_client = None


def get_redis():
    global redis_client
    if redis_client is None:
        try:
            redis_client = redis.Redis(
                host=REDIS_HOST, port=REDIS_PORT, db=0,
                decode_responses=True, socket_connect_timeout=2,
            )
            redis_client.ping()
        except (redis.ConnectionError, redis.TimeoutError):
            redis_client = None
    return redis_client


def cache_key(question: str) -> str:
    """Generate a deterministic cache key from the question."""
    normalized = question.strip().lower()
    return f"filmbot:v2:{hashlib.md5(normalized.encode()).hexdigest()}"


def get_cached(question: str) -> dict | None:
    """Try to get a cached response."""
    r = get_redis()
    if r is None:
        return None
    try:
        data = r.get(cache_key(question))
        if data:
            return json.loads(data)
    except Exception:
        pass
    return None


def set_cache(question: str, result: dict):
    """Cache a response with TTL."""
    r = get_redis()
    if r is None:
        return
    try:
        r.setex(cache_key(question), REDIS_TTL, json.dumps(result))
    except Exception:
        pass


# ── Pydantic Models ───────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str = Field(..., description="Natural language question about movies")


class QueryResponse(BaseModel):
    question: str
    response: str
    latency: float
    tool_calls: int
    tools_used: list[str]
    prompt_tokens: int
    completion_tokens: int
    cached: bool = False


class HealthResponse(BaseModel):
    status: str
    services: dict


# ── Lifespan ──────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: verify services
    r = get_redis()
    redis_ok = r is not None
    print(f"  Redis: {'connected' if redis_ok else 'not available (caching disabled)'}")
    yield
    # Shutdown
    if redis_client:
        redis_client.close()


# ── FastAPI App ───────────────────────────────────────────────

app = FastAPI(
    title="FilmBot V2",
    description="Multi-modal AI movie agent — SQL + Vector Search + Knowledge Graph",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health():
    """Check health of all services."""
    r = get_redis()
    return HealthResponse(
        status="ok",
        services={
            "agent": "ready",
            "redis": "connected" if r else "unavailable",
        },
    )


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    """Ask FilmBot a question. Routes to SQL, Vector Search, or Knowledge Graph automatically."""
    # Check cache first
    cached = get_cached(req.question)
    if cached:
        return QueryResponse(**cached, cached=True)

    # Run agent in thread pool to avoid blocking the event loop
    result = await asyncio.to_thread(invoke_agent, req.question)

    response = QueryResponse(
        question=req.question,
        response=result["response"],
        latency=result["latency"],
        tool_calls=result["tool_calls"],
        tools_used=result["tools_used"],
        prompt_tokens=result["prompt_tokens"],
        completion_tokens=result["completion_tokens"],
        cached=False,
    )

    # Cache the result
    set_cache(req.question, response.model_dump())

    return response


@app.post("/query/batch")
async def query_batch(questions: list[QueryRequest]):
    """Run multiple questions concurrently."""
    tasks = [asyncio.to_thread(invoke_agent, q.question) for q in questions]
    results = await asyncio.gather(*tasks)

    responses = []
    for q, result in zip(questions, results):
        resp = QueryResponse(
            question=q.question,
            response=result["response"],
            latency=result["latency"],
            tool_calls=result["tool_calls"],
            tools_used=result["tools_used"],
            prompt_tokens=result["prompt_tokens"],
            completion_tokens=result["completion_tokens"],
        )
        set_cache(q.question, resp.model_dump())
        responses.append(resp)

    return responses


@app.delete("/cache")
async def clear_cache():
    """Clear all cached responses."""
    r = get_redis()
    if r is None:
        return {"status": "redis unavailable"}
    try:
        keys = r.keys("filmbot:v2:*")
        if keys:
            r.delete(*keys)
        return {"status": "cleared", "keys_removed": len(keys)}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# ── Run ───────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
