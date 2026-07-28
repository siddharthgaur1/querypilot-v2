"""Query history + human feedback, in Postgres (replaces v1's local JSON file
so multiple API workers/instances share one history)."""
from __future__ import annotations

import json

import psycopg2
import psycopg2.pool

from querypilot_v2.config import POSTGRES_DSN

_pool: psycopg2.pool.SimpleConnectionPool | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS query_history (
    id SERIAL PRIMARY KEY,
    db_name TEXT NOT NULL,
    question TEXT NOT NULL,
    sql TEXT NOT NULL,
    result_count INTEGER NOT NULL,
    error TEXT,
    corrected BOOLEAN NOT NULL DEFAULT false,
    confidence DOUBLE PRECISION,
    latency_ms DOUBLE PRECISION,
    retrieved_schemas JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS feedback (
    id SERIAL PRIMARY KEY,
    query_id INTEGER NOT NULL REFERENCES query_history(id),
    rating SMALLINT NOT NULL CHECK (rating IN (-1, 1)),
    correction TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def init_pool(minconn: int = 1, maxconn: int = 10) -> None:
    global _pool
    _pool = psycopg2.pool.SimpleConnectionPool(minconn, maxconn, dsn=POSTGRES_DSN)
    conn = _pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
        conn.commit()
    finally:
        _pool.putconn(conn)


def close_pool() -> None:
    if _pool:
        _pool.closeall()


def save_query(db_name: str, question: str, sql: str, result_count: int, error: str, corrected: bool,
               confidence: float, latency_ms: float, retrieved_schemas: list) -> int:
    conn = _pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO query_history "
                "(db_name, question, sql, result_count, error, corrected, confidence, "
                "latency_ms, retrieved_schemas) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (db_name, question, sql, result_count, error or None, corrected, confidence, latency_ms,
                 json.dumps(retrieved_schemas)),
            )
            query_id = cur.fetchone()[0]
        conn.commit()
        return query_id
    finally:
        _pool.putconn(conn)


def list_history(limit: int = 20, offset: int = 0) -> list[dict]:
    conn = _pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, db_name, question, sql, result_count, error, corrected, confidence, "
                "latency_ms, created_at FROM query_history ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (limit, offset),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        _pool.putconn(conn)


def save_feedback(query_id: int, rating: int, correction: str) -> None:
    conn = _pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO feedback (query_id, rating, correction) VALUES (%s,%s,%s)",
                (query_id, rating, correction or None),
            )
        conn.commit()
    finally:
        _pool.putconn(conn)


def ping() -> bool:
    try:
        conn = _pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return True
        finally:
            _pool.putconn(conn)
    except psycopg2.Error:
        return False
