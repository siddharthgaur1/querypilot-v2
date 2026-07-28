"""Self-check for the safety layers + schema chunking against the real
committed fintech.db. Run: python tests/test_safety_layers.py
"""
import sqlite3

from querypilot_v2.core.db import connect_readonly, table_chunks
from querypilot_v2.safety.errors import UnsafeQueryError
from querypilot_v2.safety.layers import layer1_classify, layer2_injection_patterns

DB_PATH = "data/fintech.db"


def test_layer1_rejects_non_select():
    for bad in ["DROP TABLE customers", "INSERT INTO customers VALUES (1)", "SELECT 1; DROP TABLE x", ""]:
        try:
            layer1_classify(bad)
            raise AssertionError(f"expected rejection for: {bad!r}")
        except UnsafeQueryError:
            pass


def test_layer1_allows_select_and_with():
    assert layer1_classify("SELECT * FROM customers") == "SELECT * FROM customers"
    assert layer1_classify("WITH x AS (SELECT 1) SELECT * FROM x").startswith("WITH")


def test_layer2_blocks_forbidden_keywords():
    for bad in ["SELECT * FROM x WHERE 1=1; DROP", "SELECT * FROM customers, PRAGMA writable_schema"]:
        try:
            layer2_injection_patterns(bad)
            raise AssertionError(f"expected rejection for: {bad!r}")
        except UnsafeQueryError:
            pass
    layer2_injection_patterns("SELECT COUNT(*) FROM customers")  # should not raise


def test_authorizer_denies_writes_bypassing_the_regex_layers():
    """Feeds writes DIRECTLY to the connection, skipping layer1/2 entirely —
    this is what actually proves the guarantee (ported from the original
    QueryPilot's TestReadOnlyEnforcement)."""
    conn = connect_readonly(DB_PATH)
    for bad_sql in [
        "DROP TABLE customers", "UPDATE customers SET name='x'",
        "INSERT INTO customers (customer_id) VALUES (999999)", "ATTACH DATABASE ':memory:' AS x",
    ]:
        try:
            conn.execute(bad_sql)
            raise AssertionError(f"authorizer should have denied: {bad_sql}")
        except sqlite3.DatabaseError:
            pass
    conn.close()


def test_schema_chunking_produces_one_chunk_per_table():
    chunks = table_chunks(DB_PATH)
    tables = {c["table"] for c in chunks}
    assert tables == {"customers", "accounts", "merchants", "transactions"}
    for c in chunks:
        assert "sample rows" in c["text"]


if __name__ == "__main__":
    test_layer1_rejects_non_select()
    test_layer1_allows_select_and_with()
    test_layer2_blocks_forbidden_keywords()
    test_authorizer_denies_writes_bypassing_the_regex_layers()
    test_schema_chunking_produces_one_chunk_per_table()
    print("all safety/schema checks passed")
