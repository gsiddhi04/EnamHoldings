"""FastAPI app.   Run:  uvicorn backend.main:app --reload"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import shutil
import threading
import time

from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import alerts, config, db, research
from .announcements import NSEClient, store_announcements
from .prices import fetch_prices, store_prices

# A fresh container has no database: start from the committed snapshot so the demo is never empty.
_SEED = config.ROOT / "data" / "seed" / "finn.db"
if not config.DB_PATH.exists() and _SEED.exists():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(_SEED, config.DB_PATH)

app = FastAPI(title="FINN")
app.include_router(research.router)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
db.init_db()

SYMBOL_RE = re.compile(r"^[A-Z0-9&\-]{1,20}$")


def _rows(cur):
    return [dict(r) for r in cur.fetchall()]


def _auto_refresh(hours: float) -> None:
    """Optional (FINN_AUTO_REFRESH_HOURS): pull prices + filings and enrich them on a schedule, so a hosted demo stays current."""
    from . import refresh as rf
    while True:
        try:
            rf.refresh(list(config.PORTFOLIO) + list(config.ADHOC), config.ANNOUNCEMENT_DAYS, config.PRICE_DAYS, verbose=False)
        except Exception:
            logging.getLogger("finn").exception("scheduled refresh failed; will retry next cycle")
        time.sleep(hours * 3600)


if os.environ.get("FINN_AUTO_REFRESH_HOURS"):
    threading.Thread(target=_auto_refresh, args=(float(os.environ["FINN_AUTO_REFRESH_HOURS"]),), daemon=True).start()


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/stock/{symbol}")
def stock(symbol: str, ann_limit: int = Query(20, le=100), price_days: int = Query(30, le=365)):
    """Latest snapshot for any NSE symbol. Unknown symbols are fetched live and stored,
    so the engine is not tied to the demo universe."""
    symbol = symbol.upper()
    if not SYMBOL_RE.match(symbol):
        raise HTTPException(400, "Invalid symbol")

    with db.session() as conn:
        have = conn.execute("SELECT COUNT(*) FROM prices WHERE symbol=?", (symbol,)).fetchone()[0]
        if not have:  # not in our DB yet: pull on demand
            bars = fetch_prices([symbol], 35).get(symbol, [])
            if not bars:
                raise HTTPException(404, f"No price data found for NSE:{symbol}")
            conn.execute("INSERT OR IGNORE INTO stocks(symbol, name, in_portfolio) VALUES (?,?,0)", (symbol, symbol))
            store_prices(conn, symbol, bars)
            try:
                store_announcements(conn, symbol, NSEClient().announcements(symbol, 7))
            except Exception:
                pass  # announcements are best-effort for ad-hoc symbols

        info = conn.execute("SELECT * FROM stocks WHERE symbol=?", (symbol,)).fetchone()
        avg_days = db.get_setting(conn, "volume_avg_days")
        prices = _rows(conn.execute(
            "SELECT date, open, high, low, close, volume FROM prices WHERE symbol=? ORDER BY date DESC LIMIT ?",
            (symbol, max(price_days, avg_days + 1)),
        ))
        anns = _rows(conn.execute(
            """SELECT id, ann_dt, nse_desc, category, priority, why, text, attachment, summary, facts
               FROM announcements WHERE symbol=? ORDER BY ann_dt DESC LIMIT ?""",
            (symbol, ann_limit),
        ))
    for a in anns:
        a["facts"] = json.loads(a["facts"]) if a["facts"] else None

    snap = None
    if prices:
        last = prices[0]
        prev = prices[1] if len(prices) > 1 else None
        hist = [p["volume"] for p in prices[1:avg_days + 1] if p["volume"]]
        avg_vol = sum(hist) / len(hist) if hist else None
        snap = {
            "date": last["date"],
            "close": last["close"],
            "change_pct": round((last["close"] / prev["close"] - 1) * 100, 2) if prev and prev["close"] else None,
            "volume": last["volume"],
            "avg_volume": round(avg_vol) if avg_vol else None,
            "volume_multiple": round(last["volume"] / avg_vol, 2) if avg_vol and last["volume"] else None,
        }

    return {
        "symbol": symbol,
        "name": info["name"] if info else symbol,
        "sector": info["sector"] if info else None,
        "in_portfolio": bool(info["in_portfolio"]) if info else False,
        "snapshot": snap,
        "prices": list(reversed(prices[:price_days])),
        "announcements": anns,
    }


@app.get("/api/announcement/{ann_id}")
def announcement(ann_id: str):
    with db.session() as conn:
        r = conn.execute("""SELECT a.*, COALESCE(s.name, a.symbol) AS name FROM announcements a
                            LEFT JOIN stocks s ON s.symbol=a.symbol WHERE a.id=?""", (ann_id,)).fetchone()
    if not r:
        raise HTTPException(404, "No such filing")
    return _item(r)


@app.get("/api/holdings")
def holdings(days: int = Query(30, ge=5, le=120)):
    """Every portfolio stock with a closing-price sparkline, last move and filings count (for the Holdings tab)."""
    since = (config.now_ist() - dt.timedelta(days=7)).isoformat(timespec="seconds")
    out = []
    with db.session() as conn:
        avg_days = db.get_setting(conn, "volume_avg_days")
        for s in _rows(conn.execute("SELECT symbol, name, sector FROM stocks WHERE in_portfolio=1 ORDER BY symbol")):
            bars = _rows(conn.execute(
                "SELECT date, close, volume FROM prices WHERE symbol=? ORDER BY date DESC LIMIT ?",
                (s["symbol"], max(days, avg_days + 1))))
            if not bars:
                out.append({**s, "spark": [], "close": None, "change_pct": None})
                continue
            hist = [b["volume"] for b in bars[1:avg_days + 1] if b["volume"]]
            avg = sum(hist) / len(hist) if hist else None
            prev = bars[1]["close"] if len(bars) > 1 else None
            n_top = conn.execute("SELECT COUNT(*) FROM announcements WHERE symbol=? AND priority>=? AND ann_dt>=?",
                                 (s["symbol"], config.TOP_MIN, since)).fetchone()[0]
            out.append({**s, "date": bars[0]["date"], "close": bars[0]["close"],
                        "intraday": alerts._provisional(bars[0]["date"]),
                        "change_pct": round((bars[0]["close"] / prev - 1) * 100, 2) if prev else None,
                        "volume_multiple": round(bars[0]["volume"] / avg, 2) if avg and bars[0]["volume"] else None,
                        "spark": [b["close"] for b in reversed(bars[:days])], "important_filings_7d": n_top})
    return {"holdings": out}


# ---------------------------------------------------------------- digest ---------------------------------

def _item(r) -> dict:
    return {"id": r["id"], "symbol": r["symbol"], "name": r["name"], "ann_dt": r["ann_dt"],
            "category": r["category"], "priority": r["priority"], "why": r["why"],
            "subject": r["nse_desc"], "text": r["text"], "attachment": r["attachment"],
            "summary": r["summary"], "facts": json.loads(r["facts"]) if r["facts"] else None}


@app.get("/api/digest")
def digest(hours: int = Query(24, ge=1, le=720), movers: int = Query(5, ge=1, le=20)):
    """Filings across the portfolio in the last `hours`, tiered by priority, plus movers and quiet holdings."""
    now = config.now_ist()
    start = now - dt.timedelta(hours=hours)
    with db.session() as conn:
        rows = conn.execute(
            """SELECT a.*, s.name FROM announcements a JOIN stocks s ON s.symbol=a.symbol
               WHERE s.in_portfolio=1 AND a.ann_dt >= ? ORDER BY a.priority DESC, a.ann_dt DESC""",
            (start.isoformat(timespec="seconds"),),
        ).fetchall()
        holdings = _rows(conn.execute("SELECT symbol, name FROM stocks WHERE in_portfolio=1 ORDER BY symbol"))
        coverage = conn.execute("SELECT MIN(ann_dt) FROM announcements").fetchone()[0]

        moves = []
        for h in holdings:
            bars = _rows(conn.execute(
                "SELECT date, close, volume FROM prices WHERE symbol=? ORDER BY date DESC LIMIT 30", (h["symbol"],)))
            if len(bars) < 2:
                continue
            last = bars[0]
            # baseline = last close on/before the window start day, but always before the latest session
            base = next((b for b in bars[1:] if b["date"] <= start.date().isoformat()), bars[1])
            hist = [b["volume"] for b in bars[1:21] if b["volume"]]
            avg = sum(hist) / len(hist) if hist else None
            moves.append({**h, "date": last["date"], "close": last["close"], "since": base["date"],
                          "intraday": alerts._provisional(last["date"]),
                          "change_pct": round((last["close"] / base["close"] - 1) * 100, 2),
                          "volume_multiple": round(last["volume"] / avg, 2) if avg and last["volume"] else None})

    items, seen_events = [], {}
    for r in rows:  # rows arrive priority-desc: fold same company+category+day into the strongest filing
        key = (r["symbol"], r["category"], r["ann_dt"][:10])
        if key in seen_events and r["priority"] >= config.LOOK_MIN:
            seen_events[key]["related"] += 1
            continue
        it = _item(r)
        it["related"] = 0
        seen_events[key] = it
        items.append(it)
    top = [i for i in items if i["priority"] >= config.TOP_MIN]
    look = [i for i in items if config.LOOK_MIN <= i["priority"] < config.TOP_MIN]
    routine: dict = {}
    for i in items:
        if i["priority"] < config.LOOK_MIN:
            g = routine.setdefault(i["symbol"], {"symbol": i["symbol"], "name": i["name"], "count": 0, "items": []})
            g["count"] += 1
            g["items"].append({k: i[k] for k in ("id", "ann_dt", "category", "priority", "why", "subject", "attachment", "summary")})
    filed = {i["symbol"] for i in items}
    return {
        "window": {"hours": hours, "from": start.isoformat(timespec="seconds"), "to": now.isoformat(timespec="seconds"),
                   "data_starts": coverage},
        "counts": {"total": len(items), "top": len(top), "look": len(look),
                   "routine": sum(g["count"] for g in routine.values())},
        "top": top,
        "look": look,
        "routine": sorted(routine.values(), key=lambda g: -g["count"]),
        "movers": sorted(moves, key=lambda m: -abs(m["change_pct"]))[:movers],
        "quiet": [h for h in holdings if h["symbol"] not in filed],
    }


# ---------------------------------------------------------------- alerts ----------------------------------

@app.get("/api/alerts")
def get_alerts(unseen_only: bool = False, limit: int = Query(50, ge=1, le=500)):
    with db.session() as conn:
        rows = _rows(conn.execute(
            f"""SELECT al.id, al.symbol, s.name, al.kind, al.ref_id, al.title, al.detail, al.event_at, al.seen, an.summary
                FROM alerts al LEFT JOIN stocks s ON s.symbol=al.symbol
                LEFT JOIN announcements an ON al.kind='announcement' AND an.id=al.ref_id
                {"WHERE al.seen=0" if unseen_only else ""}
                ORDER BY al.event_at DESC, al.id DESC LIMIT ?""", (limit,)))
    for r in rows:
        r["detail"] = json.loads(r["detail"] or "{}")
        r["seen"] = bool(r["seen"])
    return {"count": len(rows), "alerts": rows}


@app.post("/api/alerts/{alert_id}/seen")
def mark_seen(alert_id: int):
    with db.session() as conn:
        conn.execute("UPDATE alerts SET seen=1 WHERE id=?", (alert_id,))
    return {"ok": True}


# ---------------------------------------------------------------- settings -------------------------------

class SettingsUpdate(BaseModel):
    price_move_pct: Optional[float] = Field(None, gt=0, le=50)
    volume_multiple: Optional[float] = Field(None, gt=1, le=50)
    volume_avg_days: Optional[int] = Field(None, ge=5, le=60)
    alert_categories: Optional[List[str]] = None
    alert_min_priority: Optional[int] = Field(None, ge=0, le=100)
    digest_window_hours: Optional[int] = Field(None, ge=1, le=720)


def _all_settings(conn) -> dict:
    return {k: db.get_setting(conn, k) for k in config.DEFAULT_SETTINGS}


@app.get("/api/settings")
def get_settings():
    with db.session() as conn:
        return _all_settings(conn)


@app.put("/api/settings")
def put_settings(body: SettingsUpdate):
    """Partial update. Alerts nobody has marked seen are re-derived under the new thresholds."""
    changes = body.model_dump(exclude_none=True)
    bad = set(changes.get("alert_categories", [])) - set(config.CATEGORIES)
    if bad:
        raise HTTPException(422, f"Unknown categories: {sorted(bad)}")
    with db.session() as conn:
        for k, v in changes.items():
            conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?,?)", (k, json.dumps(v)))
        alerts.reset_unseen(conn)
        n = alerts.generate(conn)
        return {"settings": _all_settings(conn), "alerts_after": n}


# ---------------------------------------------------------------- built frontend (one URL for the phone) ---
_DIST = config.ROOT / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = _DIST / path
        return FileResponse(f if path and f.is_file() else _DIST / "index.html")
