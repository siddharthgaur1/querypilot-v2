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

## Table allow-list

`QUERYPILOT_ALLOWED_TABLES` scopes reads to named tables, enforced by the
same authorizer — not by string matching against the generated SQL.

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
