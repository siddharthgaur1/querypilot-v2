# Security notes

## The safety layers (kept from the original QueryPilot)

The real boundary is unchanged from v1: `PRAGMA query_only = ON` plus a
SQLite **authorizer** that allows only `SELECT`/`READ`/`FUNCTION`/`RECURSIVE`
and denies every write/DDL/ATTACH/PRAGMA operation at prepare time, inside
SQLite, on the compiled statement (`querypilot_v2/core/db.py::connect_readonly`).
This cannot be bypassed by clever SQL text.

`querypilot_v2/safety/layers.py` adds the spec's 4-layer framing on top as
early, friendly rejections + defense in depth:

1. Statement-shape check (SELECT/WITH only, single statement)
2. Forbidden-keyword / injection-pattern regex
3. LLM self-check (advisory — an LLM can be wrong or manipulated; this is not
   a security boundary, layers 1/2/4 + the authorizer are)
4. Row-limit enforcement (1000 rows, `fetchmany`)

Plus a real wall-clock query timeout (`set_progress_handler`, not the
busy-lock timeout).

## Path traversal

`POST /upload-db` takes `os.path.basename()` of the uploaded filename and
verifies the resolved path stays inside `DATA_DIR` before writing — same
pattern as the path-traversal fix already applied in finrag/agent-eval-harness.

## Scoping reads

`QUERYPILOT_ALLOWED_TABLES` scopes reads to named tables and
`QUERYPILOT_DENIED_COLUMNS` withholds individual columns (`column` or
`table.column`). Both are enforced by the authorizer at prepare time — not by
string matching against the generated SQL — so an out-of-scope table is denied
however it is reached: directly, through a join, a scalar subquery, a `UNION`
or a CTE.

**Leaving the allow-list empty is a demo posture, not a safe one.** Read-only is
not the same as safe: with no allow-list, `SELECT owner, secret FROM api_keys` is
a perfectly legal read and the guard has no reason to refuse it. Measured on
query-injection-bench, that one setting is the difference between an attack
success rate of **0.089 and 0.010**.

`sqlite_master` and the other `sqlite_*` tables are denied unless explicitly
named in the allow-list. Schema enumeration is reconnaissance, never a user
question. A short function deny-list (`char`, `unicode`, `load_extension`,
`readfile`, `writefile`) blocks literal construction used to evade the text
layers — `char(97,100,109,105,110)` is `admin`.

### What scoping cannot do

Column scoping withholds columns *nobody* may read. It cannot answer "is this
person allowed to see salaries?", because that depends on who is asking and a
query-level guard cannot see the asker. The benchmark contains both an attack
and three legitimate queries over the same `salary` column; denying the column
blocks all four. Per-user authorization belongs above this layer.

## No paid calls without a key

Claude is only called if `ANTHROPIC_API_KEY` is set. Without it (and without
a reachable Ollama daemon), `/query` serves the closest pre-verified example
from `data/examples.json`, executed live through the full safety path — never
a fabricated result, and never a network call to Anthropic.

## Local dev credentials

`docker-compose.yml` ships `querypilot`/`querypilot` Postgres creds. Dev-only,
replace before any real deployment.

## Reporting

Personal/portfolio project, no SLA. Open a GitHub issue for anything found.
