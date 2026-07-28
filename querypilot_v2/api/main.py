"""FastAPI backend: schema-RAG-augmented NL->SQL, query history + feedback in
Postgres, SQLite DB upload/(re)indexing, and a token-streaming WebSocket."""
from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from querypilot_v2 import storage
from querypilot_v2.config import DATA_DIR, DEFAULT_DB_PATH, MAX_ROWS
from querypilot_v2.core import db as core_db
from querypilot_v2.core.agent import _build_prompt, _demo_answer, _extract_sql, ask
from querypilot_v2.core.llm import chat_stream, has_llm_backend
from querypilot_v2.rag.history_rag import retrieve_similar_queries
from querypilot_v2.rag.schema_rag import index_schema, retrieve_schema, schema_summary
from querypilot_v2.safety.layers import layer1_classify, layer2_injection_patterns

log = structlog.get_logger()

DEFAULT_DB_NAME = os.path.basename(DEFAULT_DB_PATH)


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.init_pool()
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(DEFAULT_DB_PATH):
        index_schema(DEFAULT_DB_PATH, DEFAULT_DB_NAME)
        log.info("default_db_indexed", db=DEFAULT_DB_NAME)
    yield
    storage.close_pool()


app = FastAPI(title="querypilot-v2", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class QueryRequest(BaseModel):
    question: str
    db_path: str | None = None


class FeedbackRequest(BaseModel):
    query_id: int
    rating: int  # 1 or -1
    correction: str = ""


def _resolve_db(db_path: str | None) -> tuple[str, str]:
    path = db_path or DEFAULT_DB_PATH
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"database not found: {path}")
    return path, os.path.basename(path)


@app.post("/query")
def query(req: QueryRequest):
    path, name = _resolve_db(req.db_path)
    start = time.perf_counter()
    result = ask(req.question, path, name)
    latency_ms = (time.perf_counter() - start) * 1000

    query_id = storage.save_query(
        name, req.question, result.sql, len(result.rows), result.error, result.corrected,
        result.confidence, latency_ms, result.retrieved_schemas,
    )

    if result.error:
        raise HTTPException(status_code=400, detail=result.error)

    return {
        "query_id": query_id,
        "sql": result.sql,
        "results": [dict(zip(result.columns, row)) for row in result.rows],
        "explanation": result.explanation,
        "confidence": result.confidence,
        "retrieved_schemas": [c["table"] for c in result.retrieved_schemas],
        "latency_ms": round(latency_ms, 1),
    }


@app.get("/history")
def history(limit: int = 20, offset: int = 0):
    return storage.list_history(limit=limit, offset=offset)


@app.post("/feedback")
def feedback(req: FeedbackRequest):
    if req.rating not in (1, -1):
        raise HTTPException(status_code=400, detail="rating must be 1 or -1")
    storage.save_feedback(req.query_id, req.rating, req.correction)
    return {"status": "ok"}


@app.get("/schema")
def schema(db_path: str | None = None):
    _, name = _resolve_db(db_path)
    return {"db_name": name, "tables": schema_summary(name)}


@app.post("/upload-db")
async def upload_db(file: UploadFile):
    if not file.filename.endswith(".db"):
        raise HTTPException(status_code=400, detail="only .sqlite/.db files are accepted")

    # basename only + resolve-inside-DATA_DIR guards against path traversal
    # (e.g. "../../etc/passwd.db") — same pattern used across the other repos.
    safe_name = os.path.basename(file.filename)
    dest = os.path.abspath(os.path.join(DATA_DIR, safe_name))
    if not dest.startswith(os.path.abspath(DATA_DIR) + os.sep):
        raise HTTPException(status_code=400, detail="invalid filename")

    contents = await file.read()
    with open(dest, "wb") as f:
        f.write(contents)

    n_tables = index_schema(dest, safe_name)
    return {"db_name": safe_name, "tables_indexed": n_tables}


@app.get("/health")
def health():
    return {"status": "ok", "llm_backend": has_llm_backend(), "db_connected": storage.ping()}


@app.websocket("/query/stream")
async def query_stream(ws: WebSocket):
    await ws.accept()
    try:
        payload = await ws.receive_json()
        question = payload["question"]
        path, name = _resolve_db(payload.get("db_path"))

        schema_chunks = retrieve_schema(question, name, top_k=3)
        examples = retrieve_similar_queries(question, name, top_k=3)
        await ws.send_json({"event": "retrieved_schemas", "tables": [c["table"] for c in schema_chunks]})

        sql_parts = []
        if has_llm_backend():
            for chunk in chat_stream(_build_prompt(question, schema_chunks, examples)):
                sql_parts.append(chunk)
                await ws.send_json({"event": "token", "text": chunk})
            sql = _extract_sql("".join(sql_parts))
        else:
            demo = _demo_answer(question)
            sql = demo["sql"] if demo else ""
            for word in (sql or "-- no demo match for this question").split(" "):
                await ws.send_json({"event": "token", "text": word + " "})

        try:
            safe_sql = layer1_classify(sql)
            layer2_injection_patterns(safe_sql)
            columns, rows, exec_ms = core_db.execute(safe_sql, path, MAX_ROWS, 15)
            await ws.send_json({
                "event": "result", "sql": safe_sql,
                "results": [dict(zip(columns, row)) for row in rows],
                "execution_ms": exec_ms,
            })
            storage.save_query(name, question, safe_sql, len(rows), "", False, 0.8, exec_ms, schema_chunks)
        except Exception as e:  # noqa: BLE001 - report cleanly to the client, don't crash the socket
            await ws.send_json({"event": "error", "detail": str(e)})
    except WebSocketDisconnect:
        pass
    finally:
        await ws.close()
