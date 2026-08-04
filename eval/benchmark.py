"""Run the golden query set (eval/golden_set.json, ported from the original
QueryPilot's manually-curated 20-question set) through the live ask() pipeline
and report exact-match / execution-success per category.

Requires a working LLM backend (ANTHROPIC_API_KEY or a local Ollama daemon) --
every case makes a real LLM call, so repeated runs cost real money or a local
GPU/CPU cycle. Results are NOT committed pre-computed; run this yourself and
paste the printed summary into the README's Results table.

Usage:
    python eval/benchmark.py --db data/fintech.db
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import defaultdict
from pathlib import Path

from querypilot_v2.core.agent import ask
from querypilot_v2.core.llm import has_llm_backend

GOLDEN_SET_FILE = Path(__file__).resolve().parent / "golden_set.json"


def _normalize_sql(sql: str) -> str:
    """Loose equality for exact-match scoring: real SQL equivalence is
    undecidable in general, so this is a lower bound -- execution success
    against expected_sql's result set would be a tighter check, deferred
    (see README Limitations)."""
    return re.sub(r"\s+", " ", sql.strip().rstrip(";")).strip().lower()


def run_benchmark(db_path: str, db_name: str, golden_set_file: Path = GOLDEN_SET_FILE) -> dict:
    if not has_llm_backend():
        raise RuntimeError(
            "No LLM backend available (set ANTHROPIC_API_KEY or run a local Ollama daemon)."
        )

    cases = json.loads(golden_set_file.read_text(encoding="utf-8"))
    per_case = []
    for case in cases:
        t0 = time.perf_counter()
        result = ask(case["question"], db_path, db_name)
        latency = time.perf_counter() - t0
        exact_match = bool(result.sql) and _normalize_sql(result.sql) == _normalize_sql(case["expected_sql"])
        per_case.append({
            "question": case["question"],
            "category": case["category"],
            "sql": result.sql,
            "expected_sql": case["expected_sql"],
            "exec_success": not bool(result.error),
            "exact_match": exact_match,
            "latency_s": round(latency, 3),
        })

    by_category: dict[str, list[dict]] = defaultdict(list)
    for r in per_case:
        by_category[r["category"]].append(r)

    summary = {
        cat: {
            "n": len(rows),
            "exact_match_pct": round(100 * sum(r["exact_match"] for r in rows) / len(rows), 1),
            "execution_success_pct": round(100 * sum(r["exec_success"] for r in rows) / len(rows), 1),
        }
        for cat, rows in by_category.items()
    }
    summary["overall"] = {
        "n": len(per_case),
        "exact_match_pct": round(100 * sum(r["exact_match"] for r in per_case) / len(per_case), 1),
        "execution_success_pct": round(100 * sum(r["exec_success"] for r in per_case) / len(per_case), 1),
    }
    return {"summary": summary, "per_case": per_case}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/fintech.db")
    parser.add_argument("--db-name", default="fintech")
    args = parser.parse_args()
    out = run_benchmark(args.db, args.db_name)
    print(json.dumps(out["summary"], indent=2))
