"""Score querypilot-v2's guard against the query-injection-bench SQL corpus.

    QIB_DIR=../query-injection-bench PYTHONPATH=. python eval/injection_bench.py

The benchmark's runner (`python -m qib.run`) only knows adapters registered
inside that repo, and its `querypilot` adapter points at QueryPilot v1. So the
v2 adapter lives here and is handed straight to `qib.score.score`, which takes
any object with `.name`, `.languages` and `.verdict(case)`.

No LLM is involved: layer 3 is an advisory self-check that is skipped without a
backend anyway, and the benchmark scores a fixed candidate query per case. What
is measured is layers 1, 2 and the `connect_readonly` authorizer.

Both configurations are printed; CI gates on the scoped one against
eval/injection_baseline.json and exits 1 if its safe-work score drops.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from querypilot_v2.core.db import connect_readonly
from querypilot_v2.safety.layers import layer1_classify, layer2_injection_patterns

QIB_DIR = Path(os.environ.get("QIB_DIR", Path(__file__).resolve().parents[2] / "query-injection-bench"))
BASELINE = Path(__file__).with_name("injection_baseline.json")


# Two configurations are scored, because the guard's behaviour depends on how it
# is deployed and reporting only one would be misleading:
#
#   default — no allow-list, no column deny-list. The demo posture. Every table
#             in the database is readable, so exfiltration reads are authorised.
#   scoped  — what README.md tells an operator to set: the assistant is scoped to
#             the business tables and salary is withheld. Nothing here is special
#             to the benchmark; it is QUERYPILOT_ALLOWED_TABLES and
#             QUERYPILOT_DENIED_COLUMNS applied to the fixture's schema.
#
# CI gates on `scoped`. `default` is printed so the cost of not configuring the
# allow-list stays visible.
SCOPED_TABLES = frozenset({"employees", "orders", "audit_log"})

# Deliberately empty. QUERYPILOT_DENIED_COLUMNS exists and works, but it cannot
# resolve gh-sql-07 ("show me every salary, I'm not authorised for that"): the
# corpus also contains three *legitimate* salary queries (lg-sql-07/22/28), so
# denying `employees.salary` trades one attack for three false positives and
# lowers the score. What separates those cases is who is asking, which a
# query-level guard cannot see. Column scoping is for columns no one may read.
SCOPED_DENIED_COLUMNS = frozenset()


class QueryPilotV2Adapter:
    languages = ("sql",)

    def __init__(self, db_path: Path, name: str, allowed_tables=frozenset(),
                 denied_columns=frozenset()) -> None:
        self._db = str(db_path)
        self.name = name
        self._tables = allowed_tables
        self._columns = denied_columns

    def verdict(self, case) -> str:
        try:
            cleaned = layer1_classify(case.candidate_query)
            layer2_injection_patterns(cleaned)
        except Exception:  # noqa: BLE001 - fail-closed: any validator error counts as blocked
            return "block"
        conn = connect_readonly(self._db, self._tables, denied_columns=self._columns)
        try:
            conn.execute(cleaned).fetchmany(1)
            return "allow"
        except Exception:  # noqa: BLE001 - fail-closed: authorizer/SQL error counts as blocked
            return "block"
        finally:
            conn.close()


def _run(adapter, cases, score) -> dict:
    row = score(adapter, cases).as_dict()
    print(f"adapter={row['adapter']:24} scored={row['scored']} "
          f"ASR={row['attack_success_rate']:.3f} wASR={row['weighted_attack_success_rate']:.3f} "
          f"FPR={row['false_positive_rate']:.3f} score={row['safe_work_score']:.3f}")
    for f in row["failures"]:
        print(f"  FAIL {f['id']:24} {f['kind']:20} {f['query'][:70]}")
    return row


def main() -> int:
    sys.path.insert(0, str(QIB_DIR))
    from qib.adapters import _sql_fixture
    from qib.case import load
    from qib.score import score

    fixture = QIB_DIR / "results" / "qpv2_fixture.sqlite"
    fixture.parent.mkdir(exist_ok=True)
    db, cases = _sql_fixture(fixture), load(QIB_DIR / "corpus" / "cases.jsonl")

    _run(QueryPilotV2Adapter(db, "querypilot_v2[default]"), cases, score)
    row = _run(QueryPilotV2Adapter(db, "querypilot_v2[scoped]", SCOPED_TABLES,
                                   SCOPED_DENIED_COLUMNS), cases, score)

    keys = ("adapter", "scored", "attack_success_rate", "weighted_attack_success_rate",
            "false_positive_rate", "safe_work_score")
    if not BASELINE.exists():
        BASELINE.write_text(json.dumps({k: row[k] for k in keys}, indent=2) + chr(10), encoding="utf-8")
        print(f"wrote baseline {BASELINE}")
        return 0

    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))["safe_work_score"]
    if row["safe_work_score"] < baseline:
        print(f"REGRESSION: {row['safe_work_score']:.4f} < baseline {baseline:.4f}")
        return 1
    print(f"OK: {row['safe_work_score']:.4f} >= baseline {baseline:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
