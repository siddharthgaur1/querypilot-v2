"""SQLite introspection + execution helpers, adapted from the original
QueryPilot's src/agent.py get_schema()/_execute() — same logic, split into
per-table chunks here because the RAG layer indexes one chunk per table
instead of dumping the whole schema into the prompt.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path


def table_chunks(db_path: str) -> list[dict]:
    """One chunk per table: DDL + sample rows + column list. This is what
    rag/schema_indexer.py embeds and retrieves top-k from."""
    conn = sqlite3.connect(db_path)
    try:
        tables = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        chunks = []
        for name, ddl in tables:
            cols = [d[0] for d in conn.execute(f"SELECT * FROM {name} LIMIT 0").description]
            samples = conn.execute(f"SELECT * FROM {name} LIMIT 3").fetchall()
            text = ddl.strip() + f"\n-- sample rows ({', '.join(cols)}):\n"
            text += "\n".join(f"--   {row}" for row in samples)
            chunks.append({"table": name, "columns": cols, "text": text})
        return chunks
    finally:
        conn.close()


def full_schema_text(db_path: str) -> str:
    """Only used as a fallback / GET /schema summary — NOT sent to the LLM
    prompt in the RAG path (that's the whole point of the schema RAG layer)."""
    return "\n\n".join(c["text"] for c in table_chunks(db_path))


_ALLOWED_ACTIONS = frozenset(
    {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
)


def _make_authorizer(allowed_tables: frozenset[str]):
    def _authorizer(action, arg1, arg2, db_name, trigger):
        if action not in _ALLOWED_ACTIONS:
            return sqlite3.SQLITE_DENY
        if (
            action == sqlite3.SQLITE_READ and allowed_tables and arg1
            and not arg1.startswith("sqlite_") and arg1 not in allowed_tables
        ):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    return _authorizer


def connect_readonly(
    db_path: str, allowed_tables: frozenset[str] = frozenset(), timeout: float = 15
) -> sqlite3.Connection:
    """The real safety boundary (see querypilot_v2/safety/): query_only + an
    authorizer that denies every non-read action at prepare time, regardless
    of what the regex-based layers already caught or missed."""
    conn = sqlite3.connect(db_path, timeout=timeout)
    conn.execute("PRAGMA query_only = ON")
    conn.set_authorizer(_make_authorizer(allowed_tables))
    return conn


def execute(sql: str, db_path: str, max_rows: int, timeout_s: float,
            allowed_tables: frozenset[str] = frozenset()) -> tuple[list, list, float]:
    conn = connect_readonly(db_path, allowed_tables, timeout=timeout_s)
    t0 = time.perf_counter()
    conn.set_progress_handler(lambda: (time.perf_counter() - t0) > timeout_s, 1000)
    try:
        cur = conn.execute(sql)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(max_rows)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return columns, rows, round(elapsed_ms, 1)
    except sqlite3.OperationalError as e:
        if (time.perf_counter() - t0) > timeout_s:
            raise sqlite3.OperationalError(f"Query exceeded {timeout_s}s timeout") from e
        raise
    finally:
        conn.set_progress_handler(None, 0)
        conn.close()


def list_databases(data_dir: str) -> list[str]:
    return sorted(str(p) for p in Path(data_dir).glob("*.db"))
