"""NSE corporate announcements. Unofficial API: needs browser-like headers and tolerates cookie churn."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import time
from typing import Optional

import requests

from . import config


class NSEClient:
    def __init__(self) -> None:
        self.s = requests.Session()
        self.s.headers.update(config.NSE_HEADERS)
        self._warm()

    def _warm(self) -> None:
        # Homepage visit sets the cookies NSE expects. It may 403 while still handing out cookies,
        # and the API sometimes works without them, so never fail here.
        try:
            self.s.get(config.NSE_BASE, timeout=15)
        except requests.RequestException:
            pass

    def announcements(self, symbol: str, days: int, retries: int = 3) -> list:
        to = dt.date.today()
        frm = to - dt.timedelta(days=days)
        params = {
            "index": "equities",
            "symbol": symbol,
            "from_date": frm.strftime("%d-%m-%Y"),
            "to_date": to.strftime("%d-%m-%Y"),
        }
        last_err: Optional[Exception] = None
        for attempt in range(retries):
            try:
                r = self.s.get(config.NSE_ANN_URL, params=params, timeout=20)
                if r.status_code in (401, 403):
                    self._warm()
                    time.sleep(1 + attempt)
                    continue
                r.raise_for_status()
                data = r.json()
                return data if isinstance(data, list) else data.get("data", [])
            except (requests.RequestException, ValueError) as e:
                last_err = e
                time.sleep(1 + attempt)
        raise RuntimeError(f"NSE announcements failed for {symbol}: {last_err}")


def _iso(nse_ts: Optional[str]) -> Optional[str]:
    """'01-Nov-2026 23:09:22' -> '2026-11-01T23:09:22'."""
    if not nse_ts:
        return None
    try:
        return dt.datetime.strptime(nse_ts, "%d-%b-%Y %H:%M:%S").isoformat()
    except ValueError:
        return None


def store_announcements(conn: sqlite3.Connection, symbol: str, items: list) -> int:
    """Upsert raw announcements. Returns the number of NEW rows (so refreshes can report fresh items)."""
    new = 0
    for it in items:
        ann_dt = _iso(it.get("an_dt")) or _iso(it.get("exchdisstime"))
        if not ann_dt:
            continue
        uid = it.get("seq_id") or hashlib.sha1(
            f"{symbol}|{ann_dt}|{it.get('attchmntFile')}".encode()
        ).hexdigest()[:16]
        cur = conn.execute(
            """INSERT OR IGNORE INTO announcements
               (id, symbol, ann_dt, nse_desc, text, attachment, file_size, has_xbrl, raw)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                str(uid), symbol, ann_dt, it.get("desc"), it.get("attchmntText"),
                it.get("attchmntFile"), it.get("attFileSize"), int(bool(it.get("hasXbrl"))),
                json.dumps(it),
            ),
        )
        new += cur.rowcount
    return new
