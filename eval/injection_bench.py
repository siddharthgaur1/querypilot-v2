"""Score querypilot-v2's guard against the query-injection-bench SQL corpus.

    QIB_DIR=../query-injection-bench PYTHONPATH=. python eval/injection_bench.py

The benchmark's runner (`python -m qib.run`) only knows adapters registered
inside that repo, and its `querypilot` adapter points at QueryPilot v1. So the
v2 adapter lives here and is handed straight to `qib.score.score`, which takes
any object with `.name`, `.languages` and `.verdict(case)`.

No LLM is involved: layer 3 is an advisory self-check that is skipped without a
backend anyway, and the benchmark scores a fixed candidate query per case. What
is measured is layers 1, 2 and the `connect_readonly` authorizer.

Exits 1 if the safe-work score drops below eval/injection_baseline.json.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from querypilot_v2.config import ALLOWED_TABLES
from querypilot_v2.core.db import connect_readonly
from querypilot_v2.safety.layers import layer1_classify, layer2_injection_patterns

QIB_DIR = Path(os.environ.get("QIB_DIR", Path(__file__).resolve().parents[2] / "query-injection-bench"))
BASELINE = Path(__file__).with_name("injection_baseline.json")


class QueryPilotV2Adapter:
    name = "querypilot_v2"
    languages = ("sql",)

    def __init__(self, db_path: Path) -> None:
        self._db = str(db_path)

    def verdict(self, case) -> str:
        try:
            cleaned = layer1_classify(case.candidate_query)
            layer2_injection_patterns(cleaned)
        except Exception:  # noqa: BLE001 - fail-closed: any validator error counts as blocked
            return "block"
        conn = connect_readonly(self._db, ALLOWED_TABLES)
        try:
            conn.execute(cleaned).fetchmany(1)
            return "allow"
        except Exception:  # noqa: BLE001 - fail-closed: authorizer/SQL error counts as blocked
            return "block"
        finally:
            conn.close()


def main() -> int:
    sys.path.insert(0, str(QIB_DIR))
    from qib.adapters import _sql_fixture
    from qib.case import load
    from qib.score import score

    fixture = QIB_DIR / "results" / "qpv2_fixture.sqlite"
    fixture.parent.mkdir(exist_ok=True)
    report = score(QueryPilotV2Adapter(_sql_fixture(fixture)), load(QIB_DIR / "corpus" / "cases.jsonl"))
    row = report.as_dict()

    print(f"adapter={row['adapter']} scored={row['scored']} "
          f"ASR={row['attack_success_rate']:.3f} wASR={row['weighted_attack_success_rate']:.3f} "
          f"FPR={row['false_positive_rate']:.3f} score={row['safe_work_score']:.3f}")
    for f in row["failures"]:
        print(f"  FAIL {f['id']:24} {f['kind']:20} {f['query'][:70]}")

    if not BASELINE.exists():
        BASELINE.write_text(json.dumps({k: row[k] for k in
            ("adapter", "scored", "attack_success_rate", "weighted_attack_success_rate",
             "false_positive_rate", "safe_work_score")}, indent=2) + "\n", encoding="utf-8")
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
