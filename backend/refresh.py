"""Pull prices + announcements into SQLite.   Usage:  python -m backend.refresh [--days 7] [SYMBOL ...]"""
from __future__ import annotations

import argparse
import json
import time

from . import alerts, classify, config, db, enrich, llm, push
from .announcements import NSEClient, store_announcements
from .prices import fetch_prices, store_prices


def refresh(symbols: list, ann_days: int, price_days: int, verbose: bool = True) -> dict:
    log = print if verbose else (lambda *a, **k: None)
    db.init_db()
    stats = {"prices": 0, "new_announcements": 0, "errors": []}

    log(f"Prices: {len(symbols)} symbols, last {price_days}d (yfinance, one batched call)...")
    bars = {}
    try:
        bars = fetch_prices(symbols, price_days)
    except Exception as e:  # network / yahoo hiccup shouldn't block announcements
        stats["errors"].append(f"prices: {e}")
    with db.session() as conn:
        for sym, rows in bars.items():
            n = store_prices(conn, sym, rows)
            stats["prices"] += n
            if not rows:
                stats["errors"].append(f"prices: no data for {sym}")
            log(f"  {sym:<11} {n:>3} bars")

    log(f"Announcements: last {ann_days}d from NSE...")
    nse = NSEClient()
    for sym in symbols:
        try:
            items = nse.announcements(sym, ann_days)
            with db.session() as conn:
                new = store_announcements(conn, sym, items)
            stats["new_announcements"] += new
            log(f"  {sym:<11} {len(items):>3} fetched, {new:>3} new")
        except Exception as e:
            stats["errors"].append(f"{sym}: {e}")
            log(f"  {sym:<11} FAILED: {e}")
        time.sleep(config.NSE_DELAY_SECONDS)

    cls = classify.run()
    log(f"Classified: {sum(v for k, v in cls['rule_hits'].items() if k.startswith('rule:'))} by rule, "
        f"{cls['rule_hits'].get('fallback', 0)} unmatched; llm: {cls['llm']}")
    if llm.available():  # PDF downloads + LLM calls only when there is a key to spend; all results are cached
        stats["enrich"] = enrich.run()
        log(f"Enriched: {stats['enrich']}")
    else:
        log("Enrichment skipped (no LLM key): results tables, mgmt profiles, summaries stay empty.")
    with db.session() as conn:
        stats["new_alerts"] = alerts.generate(conn)
        conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('last_refresh_at', ?)",
                     (json.dumps(config.now_ist().isoformat(timespec="seconds")),))
    log(f"Alerts: {stats['new_alerts']} under the default settings right now.")
    try:
        with db.session() as conn:
            stats["notified"] = push.notify_new(conn)
        if stats["notified"]:
            log(f"Push: {stats['notified']} notifications sent.")
    except Exception as e:   # a push problem must never fail the data refresh
        stats["errors"].append(f"push: {e}")

    log(f"Done. {stats['prices']} price rows, {stats['new_announcements']} new announcements, "
        f"{len(stats['errors'])} errors.")
    return stats


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("symbols", nargs="*", help="NSE symbols (default: whole portfolio + ad-hoc set)")
    p.add_argument("--days", type=int, default=config.ANNOUNCEMENT_DAYS, help="announcement lookback")
    p.add_argument("--price-days", type=int, default=config.PRICE_DAYS,
                   help="price lookback (kept > 7 so the 20-day volume average works)")
    a = p.parse_args()
    symbols = [s.upper() for s in a.symbols] or list(config.PORTFOLIO) + list(config.ADHOC)
    refresh(symbols, a.days, a.price_days)


if __name__ == "__main__":
    main()
