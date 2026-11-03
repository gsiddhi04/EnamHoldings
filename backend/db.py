"""SQLite schema and connection helpers."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    symbol        TEXT PRIMARY KEY,           -- NSE symbol, e.g. RELIANCE
    name          TEXT,
    sector        TEXT,
    in_portfolio  INTEGER NOT NULL DEFAULT 0, -- 1 = in the mock portfolio, 0 = ad-hoc
    added_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS prices (           -- end-of-day bars
    symbol  TEXT NOT NULL,
    date    TEXT NOT NULL,                    -- YYYY-MM-DD
    open    REAL, high REAL, low REAL, close REAL,
    volume  INTEGER,
    PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS announcements (
    id          TEXT PRIMARY KEY,             -- NSE seq_id (fallback: hash)
    symbol      TEXT NOT NULL,
    ann_dt      TEXT NOT NULL,                -- ISO timestamp the company filed
    nse_desc    TEXT,                         -- NSE's own subject label
    text        TEXT,                         -- filing blurb
    attachment  TEXT,                         -- PDF url
    file_size   TEXT,
    has_xbrl    INTEGER,
    category    TEXT,                         -- our taxonomy; filled by the classifier
    priority    INTEGER,                      -- 0-100 relevance; filled by the classifier
    why         TEXT,                         -- short reason for the priority (rule + nudges)
    classified_by TEXT,                       -- rule:<id> | llm | fallback (unmatched, LLM not yet run)
    summary     TEXT,                         -- plain-English one-liner shown with the filing
    facts       TEXT,                         -- structured extraction (JSON): results table / people
    raw         TEXT,                         -- original NSE JSON
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ann_symbol_dt ON announcements(symbol, ann_dt DESC);
CREATE INDEX IF NOT EXISTS idx_ann_dt ON announcements(ann_dt DESC);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    kind        TEXT NOT NULL,                -- announcement | volume_spike | price_move
    ref_id      TEXT,                         -- announcement id or price date
    title       TEXT NOT NULL,
    detail      TEXT,                         -- JSON payload
    event_at    TEXT,                         -- when the underlying event happened (sort key)
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    seen        INTEGER NOT NULL DEFAULT 0,
    UNIQUE (symbol, kind, ref_id)             -- one alert per event, however often we refresh
);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL                      -- JSON-encoded
);

CREATE TABLE IF NOT EXISTS llm_cache (
    key         TEXT PRIMARY KEY,             -- sha256(model + prompt + inputs)
    model       TEXT NOT NULL,
    response    TEXT NOT NULL,
    tokens_in   INTEGER,
    tokens_out  INTEGER,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS research (         -- generated pull-side sections, cached per company
    symbol      TEXT NOT NULL,
    section     TEXT NOT NULL,                -- business | financials | trajectory | ...
    content     TEXT NOT NULL,                -- JSON
    sources     TEXT,                         -- JSON list of AR / transcript refs used
    model       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (symbol, section)
);
"""


def connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


MIGRATIONS = [  # (table, column, ddl) for databases created before the column existed
    ("announcements", "why", "TEXT"),
    ("announcements", "classified_by", "TEXT"),
    ("announcements", "facts", "TEXT"),
    ("alerts", "event_at", "TEXT"),
]


def init_db() -> None:
    """Create tables and seed default settings + the demo universe (idempotent)."""
    with session() as conn:
        conn.executescript(SCHEMA)
        for table, col, ddl in MIGRATIONS:
            if col not in {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        for k, v in config.DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, json.dumps(v)))
        for universe, flag in ((config.PORTFOLIO, 1), (config.ADHOC, 0)):
            for sym, (name, sector) in universe.items():
                conn.execute(
                    "INSERT OR IGNORE INTO stocks(symbol, name, sector, in_portfolio) VALUES (?,?,?,?)",
                    (sym, name, sector, flag),
                )


def get_setting(conn: sqlite3.Connection, key: str):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else config.DEFAULT_SETTINGS.get(key)
