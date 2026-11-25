"""
Knowledge Base service — ChromaDB-backed vector store wrapper.

ChromaDB runs embedded in the Python process (no external server needed).
Embeddings use ChromaDB's default function (all-MiniLM-L6-v2, ~22MB ONNX
model — small enough to bundle, fast enough for local-first use).

The persistent client writes to data/chroma/ so embeddings survive restarts.
Vector IDs (UUIDs) are stored in the SQLite knowledge_entries table alongside
metadata — the SQL row is the source of truth; Chroma is the searchable index.
"""

import os
import uuid
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

COLLECTION_NAME = "imua_knowledge"
_CLIENT: Any = None
_COLLECTION: Any = None


def _chroma_path(app_data_dir: str) -> str:
    path = os.path.join(app_data_dir, "chroma")
    os.makedirs(path, exist_ok=True)
    return path


def init_knowledge_base(app) -> None:
    """Initialize the ChromaDB client and collection. Idempotent."""
    global _CLIENT, _COLLECTION
    if os.environ.get("IMUA_TESTING"):
        # Tests use in-memory ephemeral client (no disk writes).
        _CLIENT = chromadb.EphemeralClient()
    else:
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "data")
        _CLIENT = chromadb.PersistentClient(
            path=_chroma_path(data_dir),
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=False),
        )
    _COLLECTION = _CLIENT.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"description": "Imua shared knowledge base"},
    )
    app.config["KNOWLEDGE_COLLECTION"] = _COLLECTION


def reset_for_tests() -> None:
    """Drop the cached client/collection (test fixture teardown)."""
    global _CLIENT, _COLLECTION
    _CLIENT = None
    _COLLECTION = None


def add_entry(body: str, source: str = "manual", agent: str | None = None,
              title: str | None = None, tags: list[str] | None = None, project: str | None = None) -> str:
    """Add an entry to the vector store. Returns the chroma_id (UUID)."""
    if _COLLECTION is None:
        raise RuntimeError("Knowledge base not initialized — call init_knowledge_base() first")
    chroma_id = str(uuid.uuid4())
    metadata = {"source": source, "agent": agent or "", "title": title or "",
                "tags": ",".join(tags or []), "project": project or ""}
    _COLLECTION.add(documents=[body], ids=[chroma_id], metadatas=[metadata])
    return chroma_id


def search(query: str, n_results: int = 10,
           where: dict | None = None) -> dict:
    """Semantic search. Returns dict with ids, documents, metadatas, distances."""
    if _COLLECTION is None:
        raise RuntimeError("Knowledge base not initialized")
    kwargs: dict[str, Any] = {"query_texts": [query], "n_results": n_results}
    if where:
        kwargs["where"] = where
    return _COLLECTION.query(**kwargs)


def set_project(chroma_id: str, project: str | None) -> None:
    """Record an entry's project slug in its metadata, so search can filter by it
    (projects plan D6). project_items stays the source of truth; this mirrors it.
    No-op if the store isn't running or the entry isn't in it."""
    if _COLLECTION is None:
        return
    res = _COLLECTION.get(ids=[chroma_id])
    if not res or not res.get("ids"):
        return
    meta = dict((res.get("metadatas") or [{}])[0] or {})
    meta["project"] = project or ""
    _COLLECTION.update(ids=[chroma_id], metadatas=[meta])


def update_entry(chroma_id: str, body: str | None = None, title: str | None = None,
                 tags: list[str] | None = None) -> None:
    """Change an entry's text and/or title/tags (task 5.18). A new body is re-embedded,
    so search matches the new text. Other metadata (source, agent, project) is kept."""
    if _COLLECTION is None:
        raise RuntimeError("Knowledge base not initialized")
    res = _COLLECTION.get(ids=[chroma_id])
    if not res or not res.get("ids"):
        raise KeyError(chroma_id)
    meta = dict((res.get("metadatas") or [{}])[0] or {})
    if title is not None:
        meta["title"] = title
    if tags is not None:
        meta["tags"] = ",".join(tags)
    kwargs: dict[str, Any] = {"ids": [chroma_id], "metadatas": [meta]}
    if body is not None:
        kwargs["documents"] = [body]
    _COLLECTION.update(**kwargs)


def delete_entry(chroma_id: str) -> None:
    """Remove an entry from the vector store by its UUID."""
    if _COLLECTION is None:
        raise RuntimeError("Knowledge base not initialized")
    _COLLECTION.delete(ids=[chroma_id])


def get_stats() -> dict:
    """Return collection statistics — entry count and sample."""
    if _COLLECTION is None:
        raise RuntimeError("Knowledge base not initialized")
    count = _COLLECTION.count()
    return {
        "collection": COLLECTION_NAME,
        "entry_count": count,
    }


def fetch_by_id(chroma_id: str) -> dict | None:
    """Get raw vector entry by chroma_id (no query)."""
    if _COLLECTION is None:
        raise RuntimeError("Knowledge base not initialized")
    res = _COLLECTION.get(ids=[chroma_id])
    if not res or not res.get("ids"):
        return None
    return {
        "id": res["ids"][0],
        "document": res["documents"][0] if res.get("documents") else "",
        "metadata": res["metadatas"][0] if res.get("metadatas") else {},
    }