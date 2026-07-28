"""Indexes each table's DDL+samples as its own chunk and retrieves the top-k
most relevant ones for a question — the actual upgrade over v1, which dumped
the *entire* schema into every prompt regardless of what the question needed.
"""
from __future__ import annotations

from querypilot_v2.core.db import table_chunks
from querypilot_v2.rag.client import get_collection_if_exists, get_or_create_collection

COLLECTION_PREFIX = "schema"


def _collection_name(db_name: str) -> str:
    return f"{COLLECTION_PREFIX}__{db_name}"


def index_schema(db_path: str, db_name: str) -> int:
    chunks = table_chunks(db_path)
    if not chunks:
        return 0
    collection = get_or_create_collection(_collection_name(db_name))
    collection.upsert(
        ids=[c["table"] for c in chunks],
        documents=[c["text"] for c in chunks],
        metadatas=[{"table": c["table"], "columns": ", ".join(c["columns"])} for c in chunks],
    )
    return len(chunks)


def retrieve_schema(question: str, db_name: str, top_k: int) -> list[dict]:
    collection = get_collection_if_exists(_collection_name(db_name))
    if collection is None or collection.count() == 0:
        return []
    results = collection.query(query_texts=[question], n_results=min(top_k, collection.count()))
    return [
        {"table": meta["table"], "text": doc, "distance": dist}
        for doc, meta, dist in zip(
            results["documents"][0], results["metadatas"][0], results["distances"][0]
        )
    ]


def schema_summary(db_name: str) -> list[dict]:
    """All indexed tables for GET /schema — not query-scoped, this is the full list."""
    collection = get_collection_if_exists(_collection_name(db_name))
    if collection is None:
        return []
    data = collection.get()
    return [
        {"table": meta["table"], "columns": meta["columns"]}
        for meta in data.get("metadatas", [])
    ]
