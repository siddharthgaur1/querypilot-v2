"""Env-driven config. Mirrors the original QueryPilot's LLM-backend fallback
(Claude -> Ollama -> demo mode) and safety defaults, plus the new RAG/Postgres
settings v2 adds.
"""
import os

# LLM backend (unchanged from v1: Claude first, Ollama fallback, demo mode if neither)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")
QUERYPILOT_DEMO = os.environ.get("QUERYPILOT_DEMO", "").lower() in ("1", "true", "yes")

# Safety (v1 defaults, spec asks for a 1000-row cap instead of v1's 500)
MAX_ROWS = int(os.environ.get("MAX_ROWS", "1000"))
QUERY_TIMEOUT_S = float(os.environ.get("QUERY_TIMEOUT_S", "15"))
ALLOWED_TABLES = frozenset(
    t.strip() for t in os.environ.get("QUERYPILOT_ALLOWED_TABLES", "").split(",") if t.strip()
)

# Data
DATA_DIR = os.environ.get("DATA_DIR", "./data")
DEFAULT_DB_PATH = os.environ.get("DEFAULT_DB_PATH", os.path.join(DATA_DIR, "fintech.db"))

# RAG
CHROMA_HOST = os.environ.get("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8001"))
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
SCHEMA_TOP_K = int(os.environ.get("SCHEMA_TOP_K", "3"))
HISTORY_TOP_K = int(os.environ.get("HISTORY_TOP_K", "3"))

# Postgres (query history + feedback)
POSTGRES_DSN = os.environ.get("POSTGRES_DSN", "postgresql://querypilot:querypilot@localhost:5433/querypilot")
