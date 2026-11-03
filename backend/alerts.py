"""Alert engine. Thresholds come from the settings table, so the user decides what "unusual" means.

Three kinds, all for portfolio holdings, all idempotent (UNIQUE symbol+kind+ref_id):
  price_move    |1-day close-to-close move| >= price_move_pct
  volume_spike  volume >= volume_multiple x trailing volume_avg_days average
  announcement  filing priority >= alert_min_priority AND category in alert_categories
"""
from __future__ import annotations

import json
import sqlite3

from . import config, db

SCAN_DAYS = 5  # trading sessions re-checked on every run


def _insert(conn, symbol, kind, ref_id, title, detail, event_at) -> int:
    return conn.execute(
        "INSERT OR IGNORE INTO alerts(symbol, kind, ref_id, title, detail, event_at) VALUES (?,?,?,?,?,?)",
        (symbol, kind, ref_id, title, json.dumps(detail), event_at),
    ).rowcount


def _provisional(date: str) -> bool:
    """Today's bar fetched before the close is partial - flag it rather than pretend it's final."""
    now = config.now_ist()
    return date == now.date().isoformat() and now.hour * 60 + now.minute < 15 * 60 + 45


def reset_unseen(conn: sqlite3.Connection) -> None:
    """After a settings change, drop alerts nobody has acted on so they re-derive under the new thresholds."""
    conn.execute("DELETE FROM alerts WHERE seen=0")


def generate(conn: sqlite3.Connection) -> int:
    pct_thr = float(db.get_setting(conn, "price_move_pct"))
    vol_thr = float(db.get_setting(conn, "volume_multiple"))
    avg_days = int(db.get_setting(conn, "volume_avg_days"))
    cats = set(db.get_setting(conn, "alert_categories"))
    min_pri = int(db.get_setting(conn, "alert_min_priority"))
    created = 0

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
                    created += _insert(conn, sym, "price_move", b["date"],
                                       f"{sym} {pct:+.1f}% on {b['date']}{tag}",
                                       {"pct": round(pct, 2), "close": b["close"], "prev_close": prev["close"],
                                        "threshold": pct_thr, "provisional": bool(tag)}, b["date"])
            window = [x["volume"] for x in bars[max(0, i - avg_days):i] if x["volume"]]
            if len(window) >= min(avg_days, 10) and b["volume"]:
                avg = sum(window) / len(window)
                mult = b["volume"] / avg
                if mult >= vol_thr:
                    created += _insert(conn, sym, "volume_spike", b["date"],
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
            created += _insert(conn, a["symbol"], "announcement", a["id"],
                               f"{a['symbol']}: {a['why']}",
                               {"category": a["category"], "priority": a["priority"], "subject": a["nse_desc"],
                                "attachment": a["attachment"]}, a["ann_dt"])
    return created
