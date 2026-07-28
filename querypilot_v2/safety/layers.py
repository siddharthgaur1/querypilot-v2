"""The 4 safety layers, as independent middleware functions run in order
before any SQL touches a real connection. Layers 1-3 are early, friendly
rejections — text/LLM-level checks that a sufficiently clever query could in
theory dodge. Layer 4's row cap plus `core.db.connect_readonly`'s
`PRAGMA query_only` + SQLite authorizer (ported from the original QueryPilot,
see core/db.py) are the actual boundary: they run inside SQLite on the
compiled statement and cannot be talked around by query text. Layers 1-3
existing doesn't weaken that boundary — they just fail fast with a readable
error instead of making the user wait for the DB round-trip.
"""
from __future__ import annotations

import re

from querypilot_v2.core.llm import chat, has_llm_backend
from querypilot_v2.safety.errors import UnsafeQueryError

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach|pragma|vacuum)\b",
    re.IGNORECASE,
)


def layer1_classify(sql: str) -> str:
    """Statement-shape check: single statement, must start SELECT/WITH."""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise UnsafeQueryError("The model returned an empty query.")
    if ";" in cleaned:
        raise UnsafeQueryError("Multiple statements are not allowed.")
    if not re.match(r"^\s*(select|with)\b", cleaned, re.IGNORECASE):
        raise UnsafeQueryError("Only SELECT / WITH (CTE) queries are allowed.")
    return cleaned


def layer2_injection_patterns(sql: str) -> None:
    """Forbidden-keyword / injection-pattern check."""
    if FORBIDDEN.search(sql):
        raise UnsafeQueryError("Query contains a forbidden keyword (write/DDL operation).")


def layer3_llm_self_check(question: str, sql: str) -> str | None:
    """Ask the LLM whether this SQL actually answers the question and looks
    safe. Advisory, not a security boundary (an LLM can be wrong or
    manipulated) — layers 1/2/4 plus the authorizer are what actually can't be
    bypassed. Skipped when no LLM backend is configured (demo mode);
    returns None in that case rather than blocking the query."""
    if not has_llm_backend():
        return None

    response = chat([{
        "role": "user",
        "content": (
            f"Question: {question}\nSQL: {sql}\n\n"
            "Does this SQL correctly and safely answer the question (read-only, "
            "no destructive intent, reasonable interpretation)? "
            "Reply with exactly 'OK' if yes, or one short sentence explaining the problem if no."
        ),
    }])
    verdict = response.strip()
    if verdict.upper().startswith("OK"):
        return None
    return verdict


def layer4_enforce_row_limit(requested_max_rows: int, hard_cap: int) -> int:
    return min(requested_max_rows, hard_cap) if requested_max_rows else hard_cap
