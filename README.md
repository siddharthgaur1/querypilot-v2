# querypilot-v2

[![CI](https://github.com/siddharthgaur1/querypilot-v2/actions/workflows/ci.yml/badge.svg)](https://github.com/siddharthgaur1/querypilot-v2/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)

Production-ready rebuild of [QueryPilot](https://github.com/siddharthgaur1/Query-pilot)
(NL→SQL over SQLite): same 4-layer safety system, but Streamlit is gone,
replaced by a FastAPI backend + a schema-aware RAG layer + Postgres query
history + Docker Compose. **This is a new, separate repo — the original
QueryPilot is untouched.**

> **Demo GIF placeholder** — record `docker compose up` → open http://localhost:8080
> → ask "Top 5 merchants by total transaction value this year" → drop the GIF at
> `docs/demo.gif` and reference it here: `![demo](docs/demo.gif)`.

See [SECURITY.md](SECURITY.md) for the safety-layer/security model in full.

## What changed vs. v1

| | v1 (QueryPilot) | v2 (this repo) |
|---|---|---|
| UI | Streamlit | FastAPI + Alpine.js (no build step) |
| Prompt schema | Full schema dump, every query | **Top-3 relevant table chunks**, retrieved from Chroma |
| Few-shot examples | None | Top-3 similar past questions, retrieved from query history |
| History | Local JSON file | Postgres (`query_history`, `feedback`) |
| Deployment | `streamlit run` | `docker compose up` (api, chroma, postgres, nginx) |
| Streaming | None | WebSocket `/query/stream` (token-by-token SQL generation) |

The safety system is **unchanged in substance** — same SQLite authorizer as
the real boundary — reorganized into 4 explicit middleware layers. See
[SECURITY.md](SECURITY.md).

## Architecture

```
 browser ──▶ nginx :8080 ──▶ /            static frontend (Alpine.js, no build step)
                         └──▶ /api/*      proxy ──▶ api :8000

 api (FastAPI)
   POST /query ────────┐
   WS   /query/stream ─┤
                        ▼
             querypilot_v2/core/agent.py
                        │
        ┌───────────────┼────────────────┐
        ▼                                 ▼
  rag/schema_rag.py               rag/history_rag.py
  top-3 relevant table            top-3 similar past
  chunks (Chroma)                 (question, sql) pairs (Chroma)
        │                                 │
        └───────────────┬────────────────┘
                         ▼
              LLM (Claude / Ollama) generates SQL
              — or demo mode: closest verified
                example from data/examples.json
                         │
                         ▼
        querypilot_v2/safety/layers.py (1-4)
        1. statement-shape   2. injection-pattern regex
        3. LLM self-check    4. row-limit cap
                         │
                         ▼
        core/db.py: PRAGMA query_only + SQLite
        authorizer — the REAL boundary, cannot be
        bypassed by query text (layers 1-3 are early,
        friendly rejections, not the guarantee)
                         │
                         ▼
              results ──▶ Postgres (query_history)
```

## Schema RAG (the key upgrade)

At startup (and on `/upload-db`), every table's DDL + sample rows is embedded
and indexed as its **own chunk** in Chroma (`querypilot_v2/rag/schema_rag.py`)
— not one blob for the whole database. Each question retrieves only the
top-3 most relevant table chunks, which is what actually goes into the LLM
prompt. Verified live against the real committed `fintech.db` (4 tables:
customers, accounts, merchants, transactions):

```json
{"db_name": "fintech.db", "tables": [
  {"table": "accounts", "columns": "account_id, customer_id, account_type, balance, is_active, opened_at"},
  {"table": "customers", "columns": "customer_id, name, email, phone, city, kyc_verified, risk_segment, created_at"},
  {"table": "merchants", "columns": "merchant_id, name, category, city"},
  {"table": "transactions", "columns": "txn_id, account_id, merchant_id, amount, payment_method, status, failure_reason, created_at"}
]}
```

A join-heavy question retrieves exactly the tables it needs:
`"Which city has the highest transaction failure rate?"` retrieves
`transactions`, `customers`, `merchants` — the 3 tables the join actually
spans, out of the 4 in the database.

## No LLM key? It still runs — live, not mocked

Without `ANTHROPIC_API_KEY` (or a reachable Ollama daemon), `/query` serves
the closest pre-verified question from `data/examples.json`, but still runs
it through the **full** safety + RAG + execution path against the real
database — this is not a canned response. Real captured output:

```bash
curl -X POST http://localhost:8000/query -H "Content-Type: application/json" \
  -d '{"question": "Top 5 merchants by total transaction value this year"}'
```

```json
{
  "query_id": 1,
  "sql": "SELECT m.name AS merchant, m.category, ROUND(SUM(t.amount), 2) AS total_value, COUNT(*) AS txn_count\nFROM transactions t\nJOIN merchants m ON t.merchant_id = m.merchant_id\nWHERE t.status = 'success' AND t.created_at >= datetime('now', '-365 days')\nGROUP BY m.merchant_id\nORDER BY total_value DESC\nLIMIT 5",
  "results": [
    {"merchant": "PharmEasy", "category": "health", "total_value": 56236.9, "txn_count": 2},
    {"merchant": "IRCTC", "category": "travel", "total_value": 9126.43, "txn_count": 7},
    {"merchant": "BookMyShow", "category": "entertainment", "total_value": 4738.05, "txn_count": 3}
  ],
  "explanation": "Returned 5 row(s) with columns: merchant, category, total_value, txn_count.",
  "confidence": 0.9,
  "retrieved_schemas": ["merchants", "transactions", "accounts"],
  "latency_ms": 186.6
}
```

Set `ANTHROPIC_API_KEY` (or run Ollama) to answer arbitrary questions instead
of just the pre-verified set.

## Setup

```bash
cp .env.example .env   # optional: add ANTHROPIC_API_KEY for live NL->SQL
docker compose up -d --build
```

Cold start (images already built): ~20s for the api container to index the
bundled `data/fintech.db` schema and be ready. Open http://localhost:8080.

```bash
# one-off: seed a model without waiting for `docker compose up` to build
docker compose build

curl http://localhost:8000/health
curl http://localhost:8000/schema
curl -X POST http://localhost:8000/query -H "Content-Type: application/json" \
  -d '{"question": "Which city has the highest transaction failure rate?"}'
curl http://localhost:8000/history
curl -X POST http://localhost:8000/feedback -H "Content-Type: application/json" \
  -d '{"query_id": 1, "rating": 1}'
curl -X POST http://localhost:8000/upload-db -F "file=@/path/to/your.db"
```

## Local development (no Docker)

```bash
python -m venv .venv && source .venv/Scripts/activate
pip install -r requirements.txt
PYTHONPATH=. python tests/test_safety_layers.py   # safety layers + schema chunking, real DB, no keys
```

Running the API outside Docker additionally needs a reachable Chroma server
and Postgres instance (see `.env.example` for the URLs).

## Project structure

```
querypilot_v2/
  core/        db.py (SQLite introspection + the real read-only boundary), agent.py (NL->SQL pipeline), llm.py
  safety/      the 4 middleware layers (layers.py) + UnsafeQueryError
  rag/         schema_rag.py, history_rag.py, client.py (Chroma HttpClient)
  api/         FastAPI app: /query /history /feedback /schema /upload-db /query/stream
  frontend/    single-file Alpine.js UI, no build step
  storage.py   Postgres query_history + feedback
data/          fintech.db (committed seed DB) + examples.json (verified demo Q&A)
nginx/         reverse proxy + static frontend serving
```

## Results

The demo-mode capture above (real request, full safety+RAG+execution path,
186.6ms) is the only measured latency figure in this repo. No exact-
match/execution-success accuracy number against a golden question set is
committed yet — `eval/golden_set.json` + `eval/benchmark.py` (ported from
v1's manually-curated 20-question set, rewritten against this repo's actual
`ask()` pipeline) exist for exactly this, but `TODO(metric)`: running it
needs a live LLM backend (`ANTHROPIC_API_KEY` or Ollama), so the numbers
aren't in this README yet — run `python eval/benchmark.py` and report the
printed summary.

## Limitations

- The bundled frontend uses the simpler `POST /query` path, not the
  streaming WebSocket, for the demo UI. `WS /query/stream` exists and works
  (tested directly) — wire it into `frontend/index.html` if you want the
  token-by-token UX.
- `chromadb` client is pinned to `0.5.20` to match the `chromadb/chroma`
  server image tag — the client/server wire protocol is not stable across
  major versions (this broke during development: an unpinned client resolved
  to 1.5.9, which speaks a v2 API the 0.5.20 server doesn't implement).
- No caching volume for the HuggingFace model download — the embedding model
  re-downloads on every fresh container (not on restart of an existing one).
