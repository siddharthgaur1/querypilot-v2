# Changelog

## [Unreleased]

2026-09-13:

- First live golden-set run: `llama3.2` (3B) via local Ollama on CPU, all 20 questions — 5.0% exact match, 95.0% execution success. Raw results in `eval/results/2026-09-13-ollama-llama3.2.json`; table and caveats in the README's Results section.
- `docker-compose.yml`: Chroma server image `0.5.20` → `1.5.9` (persist path `/data`). The client had already moved to `chromadb==1.5.9`, which cannot talk to a 0.5.x server, so the compose stack was broken for the RAG path.
- `eval/benchmark.py`: `--out` writes summary plus per-case results as JSON.

Baseline snapshot as of the portfolio hygiene pass (2026-08-04):

- Production rebuild of QueryPilot v1: FastAPI + schema-aware RAG (Chroma) + Postgres query history + Docker Compose, replacing the Streamlit + full-schema-dump approach.
- Ported v1's manually-curated 20-question golden set (`eval/golden_set.json`) and rewrote the benchmark script (`eval/benchmark.py`) against this repo's actual `ask()` pipeline — v1's benchmark compared two internal approaches this repo doesn't have, so it wasn't a straight copy.
- No exact-match/execution-success numbers against the golden set are committed yet — running `eval/benchmark.py` needs a live LLM backend; tracked as an open issue.
- This repo was briefly and incorrectly archived in favor of the older, weaker `querypilot` during the Phase 1 prune — restored and corrected.
