"""The NL -> SQL -> safe execution pipeline. Same shape as the original
QueryPilot's `ask()`, with two upgrades: the prompt is built from RAG-retrieved
schema chunks + similar past queries instead of a full schema dump, and every
query passes through the 4 safety layers (querypilot_v2/safety/layers.py)
before touching `core.db.execute` (which itself enforces the real read-only
boundary — see that module's docstring).
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from querypilot_v2.config import ALLOWED_TABLES, DATA_DIR, DENIED_COLUMNS, MAX_ROWS, QUERY_TIMEOUT_S
from querypilot_v2.core import db
from querypilot_v2.core.llm import chat, has_llm_backend
from querypilot_v2.rag.history_rag import index_query, retrieve_similar_queries
from querypilot_v2.rag.schema_rag import retrieve_schema
from querypilot_v2.safety.errors import UnsafeQueryError
from querypilot_v2.safety.layers import layer1_classify, layer2_injection_patterns, layer3_llm_self_check

SYSTEM_PROMPT = """You are an expert SQLite analyst. Convert the user's question into a single SQLite SELECT query.

Rules:
- Output ONLY the SQL query. No explanation, no markdown fences, no commentary.
- SQLite dialect only. Use date('now'), datetime('now'), julianday() for dates.
- Use ONLY the tables/columns shown below — do not invent columns.
- Always use meaningful column aliases for aggregates (e.g. COUNT(*) AS txn_count).
- Add ORDER BY for rankings. Add LIMIT only if the question implies "top N".
- Use CTEs (WITH clause) for complex multi-step logic.
- If the question is ambiguous, choose the most reasonable interpretation.
"""


@dataclass
class QueryResult:
    question: str
    sql: str = ""
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    error: str = ""
    corrected: bool = False
    explanation: str = ""
    confidence: float = 0.0
    execution_ms: float = 0.0
    retrieved_schemas: list = field(default_factory=list)
    retrieved_examples: list = field(default_factory=list)


def _extract_sql(raw: str) -> str:
    raw = raw.strip()
    fence = re.search(r"```(?:sql)?\s*(.+?)```", raw, re.DOTALL | re.IGNORECASE)
    return fence.group(1).strip() if fence else raw


def _build_prompt(question: str, schema_chunks: list[dict], examples: list[dict]) -> list[dict]:
    schema_text = "\n\n".join(c["text"] for c in schema_chunks) or "(no schema indexed yet)"
    examples_text = "\n".join(
        f"Q: {e['question']}\nSQL: {e['sql']}" for e in examples
    ) or "(no similar past queries yet)"
    user_content = (
        f"Relevant schema (top {len(schema_chunks)} tables, not the full database):\n{schema_text}\n\n"
        f"Similar past questions and their SQL (few-shot examples):\n{examples_text}\n\n"
        f"Question: {question}"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_content}]


def _demo_answer(question: str) -> dict | None:
    """No LLM backend: serve the closest pre-verified example (data/examples.json),
    executed LIVE through the same safety+execution path — not a canned result."""
    examples_path = Path(DATA_DIR) / "examples.json"
    if not examples_path.exists():
        return None
    examples = json.loads(examples_path.read_text())
    q_words = set(question.lower().split())
    best = max(examples, key=lambda e: len(q_words & set(e["question"].lower().split())), default=None)
    if best is None or not (q_words & set(best["question"].lower().split())):
        return None
    return best


def ask(question: str, db_path: str, db_name: str, max_rows: int = MAX_ROWS) -> QueryResult:
    result = QueryResult(question=question)
    schema_chunks = retrieve_schema(question, db_name, top_k=3)
    examples = retrieve_similar_queries(question, db_name, top_k=3)
    result.retrieved_schemas = schema_chunks
    result.retrieved_examples = examples

    if not has_llm_backend():
        demo = _demo_answer(question)
        if demo is None:
            result.error = (
                "No LLM backend configured (set ANTHROPIC_API_KEY or run a local Ollama daemon) "
                "and no matching demo example found for this question."
            )
            return result
        sql = demo["sql"]
    else:
        sql = _extract_sql(chat(_build_prompt(question, schema_chunks, examples)))

    for attempt in range(2):
        try:
            safe_sql = layer1_classify(sql)
            layer2_injection_patterns(safe_sql)
            capped_rows = min(max_rows, MAX_ROWS)
            columns, rows, exec_ms = db.execute(safe_sql, db_path, capped_rows, QUERY_TIMEOUT_S,
                                                ALLOWED_TABLES, DENIED_COLUMNS)
            result.sql, result.columns, result.rows, result.execution_ms = safe_sql, columns, rows, exec_ms
            break
        except (sqlite3.Error, UnsafeQueryError) as e:
            if attempt == 0 and has_llm_backend():
                sql = _extract_sql(chat([
                    *_build_prompt(question, schema_chunks, examples),
                    {"role": "assistant", "content": sql},
                    {"role": "user", "content": f"That failed with: {e}\nFix it. Output ONLY the corrected SQL."},
                ]))
                result.corrected = True
            else:
                result.error = str(e)
                result.sql = sql
                return result

    caveat = None
    if has_llm_backend() and result.sql:
        caveat = layer3_llm_self_check(question, result.sql)

    result.confidence = _confidence(result.corrected, caveat, bool(result.error))

    if has_llm_backend() and result.rows:
        result.explanation = _summarise(question, result.columns, result.rows)
    elif result.rows:
        result.explanation = f"Returned {len(result.rows)} row(s) with columns: {', '.join(result.columns)}."
    if caveat:
        result.explanation = (result.explanation + f" (Self-check note: {caveat})").strip()

    if not result.error:
        index_query(db_name, question, result.sql)

    return result


def _confidence(corrected: bool, caveat: str | None, errored: bool) -> float:
    if errored:
        return 0.0
    score = 0.9
    if corrected:
        score -= 0.2
    if caveat:
        score -= 0.15
    return round(max(score, 0.1), 2)


def _summarise(question: str, columns: list, rows: list) -> str:
    preview = "\n".join(str(r) for r in rows[:10])
    return chat([{
        "role": "user",
        "content": (
            f"Question: {question}\nColumns: {columns}\nFirst rows:\n{preview}\nTotal rows: {len(rows)}\n\n"
            "Write ONE short sentence summarising this result for a business user. Be specific with numbers."
        ),
    }]).strip()
