"""Thin cached wrapper around the cheap model. Every call is keyed in llm_cache, so re-runs cost nothing."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from typing import Optional

import requests

from . import config


class LLMUnavailable(RuntimeError):
    pass


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODELS = {   # the two tiers the app asks for, mapped onto Gemini; override with FINN_GEMINI_CHEAP / _STRONG
    config.CHEAP_MODEL: os.environ.get("FINN_GEMINI_CHEAP", "gemini-3.5-flash-lite"),
    config.STRONG_MODEL: os.environ.get("FINN_GEMINI_STRONG", "gemini-3-flash-preview"),
}


def _gemini_key() -> str:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""


def provider() -> Optional[str]:
    """Gemini wins when its key is set; otherwise Anthropic; otherwise None (LLM stages are skipped)."""
    if _gemini_key():
        return "gemini"
    return "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else None


def available() -> bool:
    return provider() is not None


def resolve(model: Optional[str]) -> str:
    """Tier name (config.CHEAP_MODEL / STRONG_MODEL, or None = cheap) -> the concrete model id for the active provider."""
    model = model or os.environ.get("FINN_CHEAP_MODEL", config.CHEAP_MODEL)
    return GEMINI_MODELS.get(model, model) if provider() == "gemini" else model


def _gemini(model: str, system: str, user: str, max_tokens: int):
    # Bulk extraction runs without "thinking" (fast, cheap); the strong tier keeps it on and gets token headroom.
    no_think = model == GEMINI_MODELS[config.CHEAP_MODEL]
    cfg = {"temperature": 0, "responseMimeType": "application/json",
           "maxOutputTokens": max_tokens + (0 if no_think else 8000)}   # thinking tokens count against this
    cfg["thinkingConfig"] = {"thinkingLevel": "minimal" if no_think else "low"}
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": cfg}
    for attempt in range(4):
        r = requests.post(GEMINI_URL.format(model=model), json=body, timeout=180,
                          headers={"x-goog-api-key": _gemini_key()})
        if r.status_code in (429, 500, 503):      # rate limit / overloaded: back off and retry
            time.sleep(2 ** attempt * 2)
            continue
        if r.status_code != 200:
            raise RuntimeError(f"Gemini {r.status_code}: {r.text[:300]}")
        j = r.json()
        parts = (j.get("candidates") or [{}])[0].get("content", {}).get("parts") or []
        text = "".join(x.get("text", "") for x in parts if not x.get("thought"))
        reason = (j.get("candidates") or [{}])[0].get("finishReason", "blocked")
        if not text or reason not in ("STOP", None):      # MAX_TOKENS etc.: a cut-off JSON reply must not be cached/parsed
            raise RuntimeError(f"Gemini reply unusable (finishReason={reason}, {len(text)} chars)")
        u = j.get("usageMetadata", {})
        return text, u.get("promptTokenCount"), u.get("candidatesTokenCount")
    raise RuntimeError("Gemini is rate-limiting or overloaded; retry shortly")


def complete(conn: sqlite3.Connection, system: str, user: str, model: Optional[str] = None,
             max_tokens: int = 4000) -> str:
    model = resolve(model)
    key = hashlib.sha256(f"{model}\x00{system}\x00{user}".encode()).hexdigest()
    row = conn.execute("SELECT response FROM llm_cache WHERE key=?", (key,)).fetchone()
    if row:
        return row["response"]
    prov = provider()
    if not prov:
        raise LLMUnavailable("no LLM key set (GEMINI_API_KEY or ANTHROPIC_API_KEY)")
    if prov == "gemini":
        out, tin, tout = _gemini(model, system, user, max_tokens)
    else:
        import anthropic

        msg = anthropic.Anthropic().messages.create(
            model=model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": user}],
        )
        out = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        tin, tout = msg.usage.input_tokens, msg.usage.output_tokens
    conn.execute(
        "INSERT OR REPLACE INTO llm_cache(key, model, response, tokens_in, tokens_out) VALUES (?,?,?,?,?)",
        (key, model, out, tin, tout),
    )
    conn.commit()
    return out


def parse_json(raw: str):
    """Pull the first JSON object/array out of a model reply (tolerates prose or code fences around it)."""
    m = re.search(r"(\{.*\}|\[.*\])", raw, re.S)
    if not m:
        raise ValueError("no JSON in model reply")
    return json.loads(m.group(1))
