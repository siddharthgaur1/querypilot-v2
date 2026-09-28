"""Self-check for API logic that needs no Postgres/Chroma/LLM: storage and the
Chroma write are stubbed. Run: python tests/test_api.py
"""
import os
import tempfile

from querypilot_v2.api import main
from querypilot_v2.core.db import is_sqlite_db


def test_only_thumbs_up_on_a_successful_query_is_indexed():
    indexed = []
    rows = {
        1: {"db_name": "fintech.db", "question": "q1", "sql": "SELECT 1", "error": None},
        2: {"db_name": "fintech.db", "question": "q2", "sql": "SELEC", "error": "syntax error"},
    }
    main.storage.save_feedback = lambda *a: None
    main.storage.get_query = rows.get
    main.index_query = lambda *a, **kw: indexed.append((a, kw))

    main.feedback(main.FeedbackRequest(query_id=1, rating=-1))
    assert indexed == [], "thumbs-down must not index"
    main.feedback(main.FeedbackRequest(query_id=2, rating=1))
    assert indexed == [], "a query that errored must not index"
    main.feedback(main.FeedbackRequest(query_id=1, rating=1))
    assert indexed == [(("fintech.db", "q1", "SELECT 1"), {"doc_id": "query-1"})]


def test_upload_gate_accepts_only_intact_sqlite():
    good = open("data/fintech.db", "rb").read()
    corrupt = bytearray(good)
    corrupt[60000:62000] = b"\xff" * 2000  # garbage inside a b-tree page; header intact
    cases = {"good": (good, True), "empty": (b"", False), "text": (b"not a db\n" * 100, False),
             "corrupt": (bytes(corrupt), False)}
    with tempfile.TemporaryDirectory() as d:
        for name, (data, expected) in cases.items():
            path = os.path.join(d, name + ".db")
            with open(path, "wb") as f:
                f.write(data)
            assert is_sqlite_db(path) is expected, name


if __name__ == "__main__":
    test_only_thumbs_up_on_a_successful_query_is_indexed()
    test_upload_gate_accepts_only_intact_sqlite()
    print("all api checks passed")
