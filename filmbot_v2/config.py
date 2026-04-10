"""FilmBot V2 — Centralized configuration."""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)

# --- Databases ---
SQLITE_PATH = os.path.join(PARENT_DIR, "imdb.db")
CHROMADB_PATH = os.path.join(BASE_DIR, "chroma_store")

# --- Neo4j ---
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4j")

# --- Redis ---
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_TTL = 3600  # 1 hour cache TTL

# --- Ollama ---
OLLAMA_MODEL = "qwen2.5:7b"
EMBEDDING_MODEL = "nomic-embed-text"

# --- ChromaDB ---
CHROMA_COLLECTION = "imdb_movies"
