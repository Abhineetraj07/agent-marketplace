"""
Ingest IMDB SQLite data into ChromaDB (vector store) and Neo4j (knowledge graph).
Run this once before starting the FilmBot V2 server.
"""

import sqlite3
import chromadb
from neo4j import GraphDatabase
from langchain_ollama import OllamaEmbeddings
from config import (
    SQLITE_PATH, CHROMADB_PATH, CHROMA_COLLECTION,
    EMBEDDING_MODEL, NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD,
)


def load_movies_from_sqlite() -> list[dict]:
    """Load all movies from SQLite as list of dicts."""
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM movies")
    movies = [dict(row) for row in cursor.fetchall()]
    conn.close()
    print(f"Loaded {len(movies)} movies from SQLite.")
    return movies


# ── ChromaDB ingestion ────────────────────────────────────────

def ingest_chromadb(movies: list[dict]):
    """Chunk movie overviews and ingest into ChromaDB with metadata."""
    embeddings = OllamaEmbeddings(model=EMBEDDING_MODEL)
    client = chromadb.PersistentClient(path=CHROMADB_PATH)

    # Delete existing collection if present
    try:
        client.delete_collection(CHROMA_COLLECTION)
    except Exception:
        pass

    collection = client.create_collection(
        name=CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

    docs, metas, ids = [], [], []

    for i, m in enumerate(movies):
        title = m.get("series_title", "Unknown")
        overview = m.get("overview", "")
        if not overview or overview.strip() == "":
            continue

        # Build a rich document combining title + metadata + overview
        doc = (
            f"Title: {title}\n"
            f"Year: {m.get('released_year', 'N/A')}\n"
            f"Director: {m.get('director', 'N/A')}\n"
            f"Genre: {m.get('genre', 'N/A')}\n"
            f"Rating: {m.get('imdb_rating', 'N/A')}\n"
            f"Stars: {m.get('star1', '')}, {m.get('star2', '')}, "
            f"{m.get('star3', '')}, {m.get('star4', '')}\n"
            f"Overview: {overview}"
        )

        meta = {
            "title": title,
            "year": str(m.get("released_year", "")),
            "director": m.get("director", ""),
            "genre": m.get("genre", ""),
            "imdb_rating": float(m.get("imdb_rating", 0) or 0),
        }

        docs.append(doc)
        metas.append(meta)
        ids.append(f"movie_{i}")

    # Batch embed and insert (ChromaDB handles batching internally)
    BATCH_SIZE = 50
    for start in range(0, len(docs), BATCH_SIZE):
        end = min(start + BATCH_SIZE, len(docs))
        batch_docs = docs[start:end]
        batch_embeddings = embeddings.embed_documents(batch_docs)
        collection.add(
            documents=batch_docs,
            embeddings=batch_embeddings,
            metadatas=metas[start:end],
            ids=ids[start:end],
        )
        print(f"  ChromaDB: ingested {end}/{len(docs)} documents")

    print(f"ChromaDB ingestion complete: {len(docs)} documents in '{CHROMA_COLLECTION}'.")


# ── Neo4j ingestion ───────────────────────────────────────────

def ingest_neo4j(movies: list[dict]):
    """Create knowledge graph: Movie, Director, Actor, Genre nodes + relationships."""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    with driver.session() as session:
        # Clear existing data
        session.run("MATCH (n) DETACH DELETE n")
        print("  Neo4j: cleared existing data.")

        # Create constraints for performance
        for label in ["Movie", "Director", "Actor", "Genre"]:
            session.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.name IS UNIQUE")

        # Batch ingest movies
        for m in movies:
            title = m.get("series_title", "Unknown")
            year = m.get("released_year", "")
            rating = float(m.get("imdb_rating", 0) or 0)
            votes = int(m.get("no_of_votes", 0) or 0)
            gross = m.get("gross", "")
            runtime = m.get("runtime", "")
            overview = m.get("overview", "")
            meta_score = float(m.get("meta_score", 0) or 0)
            director = m.get("director", "")
            genres = [g.strip() for g in m.get("genre", "").split(",") if g.strip()]
            stars = [
                m.get(f"star{i}", "") for i in range(1, 5)
                if m.get(f"star{i}", "")
            ]

            # Create Movie node
            session.run(
                """
                MERGE (m:Movie {name: $title})
                SET m.year = $year, m.rating = $rating, m.votes = $votes,
                    m.gross = $gross, m.runtime = $runtime,
                    m.overview = $overview, m.meta_score = $meta_score
                """,
                title=title, year=year, rating=rating, votes=votes,
                gross=gross, runtime=runtime, overview=overview, meta_score=meta_score,
            )

            # Director → DIRECTED → Movie
            if director:
                session.run(
                    """
                    MERGE (d:Director {name: $director})
                    MERGE (m:Movie {name: $title})
                    MERGE (d)-[:DIRECTED]->(m)
                    """,
                    director=director, title=title,
                )

            # Actor → ACTED_IN → Movie
            for star in stars:
                session.run(
                    """
                    MERGE (a:Actor {name: $star})
                    MERGE (m:Movie {name: $title})
                    MERGE (a)-[:ACTED_IN]->(m)
                    """,
                    star=star, title=title,
                )

            # Movie → HAS_GENRE → Genre
            for genre in genres:
                session.run(
                    """
                    MERGE (g:Genre {name: $genre})
                    MERGE (m:Movie {name: $title})
                    MERGE (m)-[:HAS_GENRE]->(g)
                    """,
                    genre=genre, title=title,
                )

        # Print stats
        result = session.run(
            "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY label"
        )
        print("  Neo4j graph stats:")
        for record in result:
            print(f"    {record['label']}: {record['count']} nodes")

        rels = session.run(
            "MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS count ORDER BY type"
        )
        for record in rels:
            print(f"    {record['type']}: {record['count']} relationships")

    driver.close()
    print("Neo4j ingestion complete.")


# ── Main ──────────────────────────────────────────────────────

if __name__ == "__main__":
    movies = load_movies_from_sqlite()

    print("\n=== Ingesting into ChromaDB ===")
    ingest_chromadb(movies)

    print("\n=== Ingesting into Neo4j ===")
    ingest_neo4j(movies)

    print("\nAll ingestion complete!")
