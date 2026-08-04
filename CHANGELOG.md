# Changelog

## [Unreleased]

Baseline snapshot as of the portfolio hygiene pass (2026-08-04):

- Production rebuild of QueryPilot v1: FastAPI + schema-aware RAG (Chroma) + Postgres query history + Docker Compose, replacing the Streamlit + full-schema-dump approach.
- Ported v1's manually-curated 20-question golden set (`eval/golden_set.json`) and rewrote the benchmark script (`eval/benchmark.py`) against this repo's actual `ask()` pipeline — v1's benchmark compared two internal approaches this repo doesn't have, so it wasn't a straight copy.
- No exact-match/execution-success numbers against the golden set are committed yet — running `eval/benchmark.py` needs a live LLM backend; tracked as an open issue.
- This repo was briefly and incorrectly archived in favor of the older, weaker `querypilot` during the Phase 1 prune — restored and corrected.
