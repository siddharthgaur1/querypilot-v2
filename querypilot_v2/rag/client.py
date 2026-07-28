"""Shared Chroma client. HttpClient against the `chroma` docker-compose
service — not an embedded PersistentClient — because the spec calls for
ChromaDB as its own service. Local sentence-transformers embeddings (same
keyless-by-design pattern as the original FinRAG/finagent repos): no API key.
"""
from __future__ import annotations

import chromadb
from chromadb.utils import embedding_functions

from querypilot_v2.config import CHROMA_HOST, CHROMA_PORT, EMBEDDING_MODEL

_client = None
_embedding_fn = None


def get_client():
    global _client, _embedding_fn
    if _client is None:
        _client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        _embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)
    return _client, _embedding_fn


def get_or_create_collection(name: str):
    client, embedding_fn = get_client()
    return client.get_or_create_collection(name, embedding_function=embedding_fn)


def get_collection_if_exists(name: str):
    client, embedding_fn = get_client()
    try:
        return client.get_collection(name, embedding_function=embedding_fn)
    except Exception:
        return None
