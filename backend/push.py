"""Web Push: a lock-screen notification when a refresh finds a NEW alert that crosses a visitor's own thresholds.

VAPID keys: FINN_VAPID_PRIVATE (PEM, with newlines escaped as \\n is fine) in the environment, otherwise generated once into
data/vapid.json for local use. On a host whose disk is wiped on restart, set the env var, or subscriptions stop working.
Subscriptions are per visitor; alerts already existing at subscribe time are marked sent, so you only hear about what happens next.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import sqlite3
from typing import Optional

from cryptography.hazmat.primitives import serialization

from . import alerts, config, db

log = logging.getLogger("finn.push")
MAX_PER_RUN = 3          # a burst of filings becomes 3 notifications and a "+N more", not a buzzing phone
_vapid = None


def _load():
    """(py_vapid.Vapid, public key as base64url) or None when push isn't configured."""
    global _vapid
    if _vapid:
        return _vapid
    from py_vapid import Vapid
    pem = os.environ.get("FINN_VAPID_PRIVATE")
    path = config.DB_PATH.parent / "vapid.json"
    if pem:
        v = Vapid.from_pem(pem.replace("\\n", "\n").encode())
    elif path.exists():
        v = Vapid.from_pem(json.loads(path.read_text())["private_pem"].encode())
    else:
        v = Vapid()
        v.generate_keys()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"private_pem": v.private_pem().decode()}))
        path.chmod(0o600)
    pub = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    _vapid = (v, base64.urlsafe_b64encode(pub).decode().rstrip("="))
    return _vapid


def public_key() -> Optional[str]:
    try:
        return _load()[1]
    except Exception:
        log.exception("push disabled: VAPID keys unavailable")
        return None


def subscribe(conn: sqlite3.Connection, visitor: str, sub: dict) -> None:
    keys = sub.get("keys") or {}
    if not (sub.get("endpoint", "").startswith("https://") and keys.get("p256dh") and keys.get("auth")):
        raise ValueError("invalid push subscription")
    conn.execute("INSERT OR REPLACE INTO push_subs(endpoint, visitor, p256dh, auth) VALUES (?,?,?,?)",
                 (sub["endpoint"], visitor, keys["p256dh"], keys["auth"]))
    for a in alerts.derive(conn, db.visitor_settings(conn, visitor)):      # only NEW alerts from here on
        conn.execute("INSERT OR IGNORE INTO push_sent(visitor, alert_key) VALUES (?,?)", (visitor, a["key"]))


def unsubscribe(conn: sqlite3.Connection, visitor: str, endpoint: str) -> None:
    conn.execute("DELETE FROM push_subs WHERE visitor=? AND endpoint=?", (visitor, endpoint))


def _message(a: dict, names: dict, summaries: dict) -> dict:
    d, sym = a["detail"], a["symbol"]
    if a["kind"] == "price_move":
        return {"title": f"{sym} {d['pct']:+.1f}% today", "body": f"Closed at ₹{d['close']:,.1f}, from ₹{d['prev_close']:,.1f}."}
    if a["kind"] == "volume_spike":
        return {"title": f"{sym} volume is {d['multiple']:.1f}× its usual", "body": f"{d['volume']:,} shares traded against a {d['avg_volume']:,} average."}
    return {"title": names.get(sym, sym), "body": summaries.get(a["ref_id"]) or a["title"].split(": ", 1)[-1]}


def notify_new(conn: sqlite3.Connection, send=None) -> int:
    """Push every subscribed visitor the alerts they haven't been told about. `send` is injectable for tests."""
    subs = conn.execute("SELECT * FROM push_subs").fetchall()
    if not subs:
        return 0
    if send is None:
        from pywebpush import WebPushException, webpush
        vapid = _load()[0]

        def send(sub, payload):
            try:
                webpush({"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}}, json.dumps(payload),
                        vapid_private_key=vapid, vapid_claims={"sub": "mailto:finn@example.com"}, ttl=3600)
                return True
            except WebPushException as e:
                if getattr(e.response, "status_code", None) in (404, 410):      # the browser revoked it
                    conn.execute("DELETE FROM push_subs WHERE endpoint=?", (sub["endpoint"],))
                    return None
                log.warning("push failed: %s", e)
                return False
    names = {r["symbol"]: r["name"] for r in conn.execute("SELECT symbol, name FROM stocks")}
    summaries = {r["id"]: r["summary"] for r in conn.execute("SELECT id, summary FROM announcements WHERE summary IS NOT NULL")}
    sent = 0
    by_visitor = {}
    for s in subs:
        by_visitor.setdefault(s["visitor"], []).append(s)
    for visitor, vsubs in by_visitor.items():
        done = {r["alert_key"] for r in conn.execute("SELECT alert_key FROM push_sent WHERE visitor=?", (visitor,))}
        fresh = [a for a in alerts.derive(conn, db.visitor_settings(conn, visitor)) if a["key"] not in done]
        if not fresh:
            continue
        msgs = [_message(a, names, summaries) for a in fresh[:MAX_PER_RUN]]
        if len(fresh) > MAX_PER_RUN:
            msgs.append({"title": f"+{len(fresh) - MAX_PER_RUN} more alerts", "body": "Open FINN to see them."})
        delivered = False
        for sub in vsubs:
            for m in msgs:
                if send(sub, {**m, "url": "/#/alerts"}):
                    delivered = True
                    sent += 1
        if delivered:    # if nothing was delivered (all subs dead) keep them pending for the next run
            for a in fresh:
                conn.execute("INSERT OR IGNORE INTO push_sent(visitor, alert_key) VALUES (?,?)", (visitor, a["key"]))
    conn.commit()
    return sent


if __name__ == "__main__":      # python -m backend.push   -> the env value to paste into your host (FINN_VAPID_PRIVATE)
    v, pub = _load()
    print("FINN_VAPID_PRIVATE=" + v.private_pem().decode().strip().replace("\n", "\\n"))
    print("(public key, for reference) " + pub)
