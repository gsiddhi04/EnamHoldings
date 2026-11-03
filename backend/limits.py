"""Small in-memory rate limiter. A public demo link must not let one visitor burn the model quota.

Two layers: a per-client sliding window, and a global daily cap on model-backed work (FINN_DAILY_LLM_CAP, default 400).
In-memory is fine for a single-process demo; it resets on restart.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_lock = threading.Lock()
_hits = defaultdict(deque)
DAILY_CAP = int(os.environ.get("FINN_DAILY_LLM_CAP", "400"))


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")          # behind Render's proxy the real client is the first hop
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?"))


def check(request: Request, name: str, limit: int, per_seconds: int, what: str) -> None:
    """Raise 429 when this client has done `limit` of `name` in the last `per_seconds`."""
    who, now = f"{name}:{client_ip(request)}", time.time()
    with _lock:
        q = _hits[who]
        while q and q[0] <= now - per_seconds:
            q.popleft()
        if len(q) >= limit:
            wait = int(q[0] + per_seconds - now) + 1
            mins = max(1, round(wait / 60))
            raise HTTPException(429, f"Slow down: this demo allows {limit} {what} per "
                                     f"{'hour' if per_seconds == 3600 else 'few minutes'}. Try again in about {mins} min.")
        q.append(now)


def llm_budget(request: Request, name: str, limit: int, per_seconds: int, what: str) -> None:
    """Per-client limit plus the shared daily cap, for calls that spend model quota."""
    check(request, name, limit, per_seconds, what)
    now = time.time()
    with _lock:
        q = _hits["__daily__"]
        while q and q[0] <= now - 86400:
            q.popleft()
        if len(q) >= DAILY_CAP:
            raise HTTPException(429, "The demo's daily limit for AI-generated answers has been reached. "
                                     "Anything already generated still opens instantly; try new questions tomorrow.")
        q.append(now)


def usage() -> dict:
    now = time.time()
    with _lock:
        used = sum(1 for t in _hits["__daily__"] if t > now - 86400)
    return {"llm_calls_24h": used, "daily_cap": DAILY_CAP}
