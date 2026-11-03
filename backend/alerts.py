"""Alert engine. The thresholds belong to each visitor, so everyone decides what "unusual" means for themselves.

Alerts are derived on demand from prices + filings under a visitor's settings (nothing shared is stored); only the
"seen" marks are kept, per visitor. Three kinds, all for portfolio holdings, each with a stable key symbol:kind:ref_id:
  price_move    |1-day close-to-close move| >= price_move_pct
  volume_spike  volume >= volume_multiple x trailing volume_avg_days average
  announcement  filing priority >= alert_min_priority AND category in alert_categories
"""
from __future__ import annotations

import json
import sqlite3

from . import config, db

SCAN_DAYS = 5  # trading sessions re-checked on every run


def _provisional(date: str) -> bool:
    """Today's bar fetched before the close is partial - flag it rather than pretend it's final."""
    now = config.now_ist()
    return date == now.date().isoformat() and now.hour * 60 + now.minute < 15 * 60 + 45


def derive(conn: sqlite3.Connection, st: dict) -> list:
    """All alerts that `st` (a settings dict) would raise right now, newest first."""
    pct_thr, vol_thr = float(st["price_move_pct"]), float(st["volume_multiple"])
    avg_days, min_pri = int(st["volume_avg_days"]), int(st["alert_min_priority"])
    cats = set(st["alert_categories"])
    out: list = []

    def add(symbol, kind, ref_id, title, detail, event_at):
        out.append({"key": f"{symbol}:{kind}:{ref_id}", "symbol": symbol, "kind": kind, "ref_id": str(ref_id),
                    "title": title, "detail": detail, "event_at": event_at})

    symbols = [r["symbol"] for r in conn.execute("SELECT symbol FROM stocks WHERE in_portfolio=1")]
    for sym in symbols:
        bars = conn.execute(
            "SELECT date, close, volume FROM prices WHERE symbol=? ORDER BY date DESC LIMIT ?",
            (sym, SCAN_DAYS + avg_days + 1),
        ).fetchall()[::-1]  # oldest -> newest
        for i in range(max(1, len(bars) - SCAN_DAYS), len(bars)):
            b, prev = bars[i], bars[i - 1]
            tag = " (intraday)" if _provisional(b["date"]) else ""
            if prev["close"]:
                pct = (b["close"] / prev["close"] - 1) * 100
                if abs(pct) >= pct_thr:
                    add(sym, "price_move", b["date"], f"{sym} {pct:+.1f}% on {b['date']}{tag}",
                        {"pct": round(pct, 2), "close": b["close"], "prev_close": prev["close"],
                         "threshold": pct_thr, "provisional": bool(tag)}, b["date"])
            window = [x["volume"] for x in bars[max(0, i - avg_days):i] if x["volume"]]
            if len(window) >= min(avg_days, 10) and b["volume"]:
                avg = sum(window) / len(window)
                mult = b["volume"] / avg
                if mult >= vol_thr:
                    add(sym, "volume_spike", b["date"],
                        f"{sym} volume {mult:.1f}x its {len(window)}-day average on {b['date']}{tag}",
                        {"multiple": round(mult, 2), "volume": b["volume"], "avg_volume": round(avg),
                         "threshold": vol_thr, "provisional": bool(tag)}, b["date"])

    if cats:
        marks = ",".join("?" * len(cats))
        rows = conn.execute(
            f"""SELECT a.* FROM announcements a JOIN stocks s ON s.symbol=a.symbol
                WHERE s.in_portfolio=1 AND a.priority >= ? AND a.category IN ({marks})
                ORDER BY a.priority DESC, a.ann_dt""",
            (min_pri, *sorted(cats)),
        ).fetchall()
        seen_events = set()
        for a in rows:  # one alert per company+category+day: the results filing and its board-outcome note are one event
            key = (a["symbol"], a["category"], a["ann_dt"][:10])
            if key in seen_events:
                continue
            seen_events.add(key)
            add(a["symbol"], "announcement", a["id"], f"{a['symbol']}: {a['why']}",
                {"category": a["category"], "priority": a["priority"], "subject": a["nse_desc"],
                 "attachment": a["attachment"]}, a["ann_dt"])
    out.sort(key=lambda r: r["event_at"], reverse=True)
    return out


def generate(conn: sqlite3.Connection) -> int:
    """How many alerts the default settings raise right now (used for the refresh log line)."""
    return len(derive(conn, {k: db.get_setting(conn, k) for k in config.DEFAULT_SETTINGS}))
