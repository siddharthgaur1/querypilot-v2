"""Self-check for API logic that needs no Postgres/Chroma/LLM: storage and the
Chroma write are stubbed. Run: python tests/test_api.py
"""
from querypilot_v2.api import main


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


if __name__ == "__main__":
    test_only_thumbs_up_on_a_successful_query_is_indexed()
    print("all api checks passed")
