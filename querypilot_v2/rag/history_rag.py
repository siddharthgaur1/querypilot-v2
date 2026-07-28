"""Indexes past (question, sql) pairs and retrieves the top-k most similar
ones as few-shot examples for the next SQL generation prompt."""
from __future__ import annotations

import uuid

from querypilot_v2.rag.client import get_collection_if_exists, get_or_create_collection

COLLECTION_PREFIX = "history"


def _collection_name(db_name: str) -> str:
    return f"{COLLECTION_PREFIX}__{db_name}"


def index_query(db_name: str, question: str, sql: str) -> None:
    collection = get_or_create_collection(_collection_name(db_name))
    collection.upsert(
        ids=[str(uuid.uuid4())],
        documents=[question],
        metadatas=[{"sql": sql}],
    )


def retrieve_similar_queries(question: str, db_name: str, top_k: int) -> list[dict]:
    collection = get_collection_if_exists(_collection_name(db_name))
    if collection is None or collection.count() == 0:
        return []
    results = collection.query(query_texts=[question], n_results=min(top_k, collection.count()))
    return [
        {"question": doc, "sql": meta["sql"], "distance": dist}
        for doc, meta, dist in zip(
            results["documents"][0], results["metadatas"][0], results["distances"][0]
        )
    ]
