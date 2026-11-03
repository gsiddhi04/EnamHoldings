"""End-of-day price + volume via yfinance (NSE tickers carry the .NS suffix)."""
from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Iterable

import yfinance as yf


def fetch_prices(symbols: Iterable[str], days: int) -> dict:
    """Return {symbol: [(date, o, h, l, c, volume), ...]} for the last `days` calendar days.

    One batched download for all symbols (a single HTTP round trip instead of N).
    """
    symbols = list(symbols)
    if not symbols:
        return {}
    start = dt.date.today() - dt.timedelta(days=days)
    df = yf.download(
        [f"{s}.NS" for s in symbols],
        start=start.isoformat(),
        auto_adjust=False,
        group_by="ticker",
        progress=False,
        threads=True,
    )
    out = {}
    for sym in symbols:
        try:
            sub = df[f"{sym}.NS"]
        except KeyError:
            out[sym] = []
            continue
        sub = sub.dropna(subset=["Close"])
        out[sym] = [
            (idx.strftime("%Y-%m-%d"), _f(r["Open"]), _f(r["High"]), _f(r["Low"]), _f(r["Close"]),
             int(r["Volume"]) if r["Volume"] == r["Volume"] else None)
            for idx, r in sub.iterrows()
        ]
    return out


def _f(x):
    return None if x != x else round(float(x), 2)


def store_prices(conn: sqlite3.Connection, symbol: str, rows: list) -> int:
    conn.executemany(
        "INSERT OR REPLACE INTO prices(symbol,date,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)",
        [(symbol, *r) for r in rows],
    )
    return len(rows)
