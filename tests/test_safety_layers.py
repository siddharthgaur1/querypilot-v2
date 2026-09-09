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


def test_keywords_inside_string_literals_and_comments_are_not_write_operations():
    """Quoted text is data, not SQL. These are legitimate reads and must pass."""
    for sql in [
        "SELECT * FROM audit_log WHERE action = 'insert'",
        "SELECT * FROM orders WHERE notes LIKE '%truncate the message%'",
        "SELECT * FROM t WHERE a = 'a;b'",
        "SELECT * FROM t WHERE a = 'it''s a drop'",
        'SELECT "drop" FROM t',
    ]:
        layer2_injection_patterns(layer1_classify(sql))


def test_masking_does_not_open_a_hole():
    """Same masking must not let a real write or a second statement through."""
    for sql in [
        "SELECT 1; DROP TABLE t",
        "SELECT * FROM t WHERE a='x' AND 1=1; DROP TABLE t",
        "SELECT 'abc DROP TABLE t",          # unterminated literal -> fail closed
        "SELECT 1 /* drop",                  # unterminated comment -> fail closed
        "SELECT 1 -- c" + chr(10) + "; drop table t",  # ; is outside the comment
    ]:
        try:
            layer2_injection_patterns(layer1_classify(sql))
            raise AssertionError(f"should have been rejected: {sql!r}")
        except UnsafeQueryError:
            pass



def _denied(conn, sql):
    try:
        conn.execute(sql).fetchmany(1)
        return False
    except sqlite3.DatabaseError:
        return True


def test_authorizer_scopes_reads_to_the_allow_list():
    """Read-only is not the same as safe: an out-of-scope table must be denied
    however it is reached — directly, via a join, a subquery, a UNION or a CTE."""
    conn = connect_readonly(DB_PATH, frozenset({"customers"}))
    for sql in [
        "SELECT * FROM merchants",
        "SELECT c.customer_id, m.name FROM customers c, merchants m",
        "SELECT (SELECT name FROM merchants LIMIT 1) AS x FROM customers LIMIT 1",
        "SELECT customer_id FROM customers UNION ALL SELECT merchant_id FROM merchants",
        "WITH m AS (SELECT name FROM merchants) SELECT * FROM m",
    ]:
        assert _denied(conn, sql), f"allow-list should have denied: {sql}"
    conn.execute("SELECT customer_id FROM customers LIMIT 1").fetchmany(1)
    conn.close()


def test_authorizer_denies_schema_enumeration():
    """sqlite_master is reconnaissance, not a user question, and is denied even
    with no allow-list set."""
    conn = connect_readonly(DB_PATH)
    assert _denied(conn, "SELECT name, sql FROM sqlite_master")
    conn.close()


def test_authorizer_denies_obfuscating_functions_and_scoped_columns():
    conn = connect_readonly(DB_PATH)
    assert _denied(conn, "SELECT * FROM customers WHERE name = char(97,100,109,105,110)")
    conn.close()
    conn = connect_readonly(DB_PATH, denied_columns=frozenset({"transactions.amount"}))
    assert _denied(conn, "SELECT amount FROM transactions")
    conn.execute("SELECT txn_id FROM transactions LIMIT 1").fetchmany(1)
    conn.close()


def test_layer2_rejects_comments():
    """`WHERE 1=1 -- ' AND dept='x'` truncates the predicate the user asked for."""
    for sql in ["SELECT * FROM customers WHERE 1=1 -- ' AND status='x'",
                "SELECT /* hidden */ * FROM customers"]:
        try:
            layer2_injection_patterns(layer1_classify(sql))
            raise AssertionError(f"comment should have been rejected: {sql!r}")
        except UnsafeQueryError:
            pass



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
    test_keywords_inside_string_literals_and_comments_are_not_write_operations()
    test_masking_does_not_open_a_hole()
    test_authorizer_scopes_reads_to_the_allow_list()
    test_authorizer_denies_schema_enumeration()
    test_authorizer_denies_obfuscating_functions_and_scoped_columns()
    test_layer2_rejects_comments()
    test_schema_chunking_produces_one_chunk_per_table()
    print("all safety/schema checks passed")
