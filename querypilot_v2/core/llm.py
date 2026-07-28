"""LLM chat backend: Claude first, Ollama fallback, same as the original
QueryPilot (src/agent.py) — kept verbatim in spirit so v2 behaves identically
when neither/either key is present.
"""
from __future__ import annotations

from querypilot_v2.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, OLLAMA_MODEL, QUERYPILOT_DEMO

try:
    import anthropic
    _USE_ANTHROPIC = bool(ANTHROPIC_API_KEY)
except ImportError:
    _USE_ANTHROPIC = False

_USE_OLLAMA = False
if not _USE_ANTHROPIC:
    try:
        import ollama as _ollama
        _USE_OLLAMA = True
    except ImportError:
        _USE_OLLAMA = False


def has_llm_backend() -> bool:
    """Ping, don't just import-check — an installed ollama client with no reachable
    daemon is not a usable backend (same reasoning as the original repo)."""
    if QUERYPILOT_DEMO:
        return False
    if _USE_ANTHROPIC:
        return True
    if _USE_OLLAMA:
        try:
            _ollama.list()
            return True
        except Exception:  # noqa: BLE001 - daemon unreachable => no backend
            return False
    return False


def chat(messages: list[dict], temperature: float = 0.0) -> str:
    if _USE_ANTHROPIC:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msgs = [m for m in messages if m["role"] != "system"]
        resp = client.messages.create(model=ANTHROPIC_MODEL, max_tokens=1024, system=system, messages=user_msgs)
        return resp.content[0].text
    if _USE_OLLAMA:
        resp = _ollama.chat(model=OLLAMA_MODEL, messages=messages, options={"temperature": temperature})
        return resp["message"]["content"]
    raise RuntimeError("No LLM backend available. Set ANTHROPIC_API_KEY or run a local Ollama daemon.")


def chat_stream(messages: list[dict]):
    """Yields text chunks as they're generated. Used by WS /query/stream."""
    if _USE_ANTHROPIC:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msgs = [m for m in messages if m["role"] != "system"]
        with client.messages.stream(
            model=ANTHROPIC_MODEL, max_tokens=1024, system=system, messages=user_msgs
        ) as stream:
            yield from stream.text_stream
        return
    if _USE_OLLAMA:
        for chunk in _ollama.chat(model=OLLAMA_MODEL, messages=messages, stream=True):
            yield chunk["message"]["content"]
        return
    raise RuntimeError("No LLM backend available. Set ANTHROPIC_API_KEY or run a local Ollama daemon.")
