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


# SQLite quoting/comment forms. Keyword and multi-statement checks run against a
# masked copy of the query in which every quoted run and comment body is blanked
# out, so `WHERE action = 'insert'` and `notes LIKE '%a;b%'` are not read as a
# write or as two statements. Masking is only for the checks — the text handed on
# to SQLite is always the original.
_QUOTES = {"'": "'", '"': '"', "`": "`", "[": "]"}


def _mask_literals(sql: str, mask_comments: bool = True) -> str:
    """Blank the contents of string/identifier literals and comments, preserving
    length. Fails closed: an unterminated literal or block comment is rejected
    rather than silently masking the rest of the query.

    With `mask_comments=False` comment bodies are left in place — comments are
    still parsed, so a quote inside one cannot desynchronise the scanner, but the
    `--` / `/*` markers survive for the comment check in layer 2."""
    out = list(sql)
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "-" and sql.startswith("--", i):
            end = sql.find(chr(10), i)
            end = n if end == -1 else end
            if mask_comments:
                out[i:end] = " " * (end - i)
            i = end
        elif ch == "/" and sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            if end == -1:
                raise UnsafeQueryError("Unterminated comment in query.")
            if mask_comments:
                out[i:end + 2] = " " * (end + 2 - i)
            i = end + 2
        elif ch in _QUOTES:
            close = _QUOTES[ch]
            j = i + 1
            while j < n:
                if sql[j] == close:
                    # '' inside a '...' literal is an escaped quote, not the end.
                    if close == "'" and j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            if j >= n:
                raise UnsafeQueryError("Unterminated string literal in query.")
            out[i + 1:j] = " " * (j - i - 1)
            i = j + 1
        else:
            i += 1
    return "".join(out)


def layer1_classify(sql: str) -> str:
    """Statement-shape check: single statement, must start SELECT/WITH."""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise UnsafeQueryError("The model returned an empty query.")
    if ";" in _mask_literals(cleaned):
        raise UnsafeQueryError("Multiple statements are not allowed.")
    if not re.match(r"^\s*(select|with)\b", cleaned, re.IGNORECASE):
        raise UnsafeQueryError("Only SELECT / WITH (CTE) queries are allowed.")
    return cleaned


def layer2_injection_patterns(sql: str) -> None:
    """Forbidden-keyword / injection-pattern check."""
    if FORBIDDEN.search(_mask_literals(sql)):
        raise UnsafeQueryError("Query contains a forbidden keyword (write/DDL operation).")
    # A generated query has no reason to carry a comment. Outside a literal, a
    # comment only ever hides text from a reviewer or truncates the predicate the
    # user thought they were getting (`WHERE 1=1 -- ' AND dept='x'`).
    outside_literals = _mask_literals(sql, mask_comments=False)
    if "--" in outside_literals or "/*" in outside_literals:
        raise UnsafeQueryError("Comments are not allowed in a generated query.")


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
