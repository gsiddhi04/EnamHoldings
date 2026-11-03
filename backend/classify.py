"""Classify announcements: ordered regex rules first (free, deterministic), cheap LLM only for leftovers.

Usage:  python -m backend.classify [--redo] [--no-llm]
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3

from . import config, db, llm
from .rules import classify as rule_classify

SYSTEM = f"""You classify filings made by Indian listed companies to NSE/BSE for an investor's triage feed.
For each filing pick ONE category from: {", ".join(config.CATEGORIES)}.
('unclassified' = routine paperwork that does not move a stock; 'press_release' = general news not covered elsewhere.)
Give a priority 0-100 for how much a portfolio investor should care. Anchors: results filed 92; CEO/CFO/MD change 86;
M&A 80; buyback/QIP/rights 75; promoter pledge created 70; order win 55; dividend 40; concall transcript 40;
routine compliance / ESOP / newspaper ad 5. Use only what the text says; if it is too vague, say unclassified, 15.
Reply with ONLY a JSON array: [{{"i": <number>, "category": "...", "priority": <int>, "why": "<=10 words"}}] covering every i."""


def _rule_pass(conn: sqlite3.Connection, redo: bool) -> collections.Counter:
    if redo:  # re-run rules over everything except filings the LLM already judged
        conn.execute("UPDATE announcements SET category=NULL, classified_by=NULL "
                     "WHERE COALESCE(classified_by,'') != 'llm'")
    hits = collections.Counter()
    rows = conn.execute("SELECT id, nse_desc, text FROM announcements WHERE category IS NULL").fetchall()
    for r in rows:
        res = rule_classify(r["nse_desc"], r["text"])
        if res:
            cat, pri, why, rid = res
            by = f"rule:{rid}"
        else:  # park as low-priority unclassified until the LLM sees it
            cat, pri, why, by = "unclassified", 20, "No rule matched", "fallback"
        hits[by] += 1
        conn.execute("UPDATE announcements SET category=?, priority=?, why=?, classified_by=? WHERE id=?",
                     (cat, pri, why, by, r["id"]))
    return hits


def _parse(raw: str) -> list:
    m = re.search(r"\[.*\]", raw, re.S)
    return json.loads(m.group(0)) if m else []


def _llm_pass(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT id, symbol, nse_desc, text FROM announcements WHERE classified_by='fallback'").fetchall()
    stats = {"pending": len(rows), "classified": 0, "calls": 0, "skipped": None}
    if not rows:
        return stats
    if not llm.available():
        stats["skipped"] = "no LLM key set (GEMINI_API_KEY) - left as low-priority unclassified; re-run with a key"
        return stats
    for i in range(0, len(rows), config.LLM_BATCH):
        chunk = rows[i:i + config.LLM_BATCH]
        user = "\n".join(
            f'{n}. [{r["symbol"]}] subject: {r["nse_desc"]} | text: {(r["text"] or "")[:400]}'
            for n, r in enumerate(chunk, 1))
        try:
            out = _parse(llm.complete(conn, SYSTEM, user))
        except Exception as e:  # bad JSON / API error: leave this batch as fallback, try the next
            stats["skipped"] = f"batch {i // config.LLM_BATCH + 1} failed: {e}"
            continue
        stats["calls"] += 1
        for o in out:
            try:
                r = chunk[int(o["i"]) - 1]
                pri = max(0, min(100, int(o["priority"])))
                if o["category"] in config.CATEGORIES:
                    cat = o["category"]
                else:  # malformed verdict: don't let it jump the queue
                    cat, pri = "unclassified", min(pri, 20)
            except (KeyError, ValueError, IndexError, TypeError):
                continue
            conn.execute("UPDATE announcements SET category=?, priority=?, why=?, classified_by='llm' WHERE id=?",
                         (cat, pri, str(o.get("why", ""))[:90], r["id"]))
            stats["classified"] += 1
    return stats


def run(redo: bool = False, use_llm: bool = True) -> dict:
    with db.session() as conn:
        hits = _rule_pass(conn, redo)
        llm_stats = _llm_pass(conn) if use_llm else {"skipped": "disabled"}
    return {"rule_hits": dict(hits), "llm": llm_stats}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--redo", action="store_true", help="re-run rules over everything (keeps LLM verdicts)")
    p.add_argument("--no-llm", action="store_true")
    a = p.parse_args()
    db.init_db()
    res = run(a.redo, not a.no_llm)
    n_rule = sum(v for k, v in res["rule_hits"].items() if k.startswith("rule:"))
    print(f"rules classified {n_rule}; unmatched {res['rule_hits'].get('fallback', 0)}; llm: {res['llm']}")


if __name__ == "__main__":
    main()
