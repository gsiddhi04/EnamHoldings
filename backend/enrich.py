"""Enrich important filings so the feed shows facts, not just titles.

  results      priority >= 80: find the P&L page in the PDF, cheap LLM transcribes the table, Python does the maths
  mgmt         management_change >= 40: extract people + brief-profile background from the annexure
  ratings      credit_rating: read the rating letter, set priority from the direction (downgrade 75, upgrade 55, reaffirm 20)
  bios         incoming people the filing doesn't profile: public Wikipedia page if there is one (no model)
  summaries    everything else >= 40: one plain-English line (<= 18 words), 20 filings per LLM call

Usage:  python -m backend.enrich [results|mgmt|summaries ...] [--limit N] [--force] [--all-stocks]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from typing import Dict, List, Optional, Tuple

from . import config, db, llm, pdfs, profiles

RESULTS_MIN_PRIORITY = 80
SUMMARY_MIN_PRIORITY = 40
SUMMARY_BATCH = 20
SUMMARY_MAX_WORDS = 18
METRICS = ["revenue", "other_income", "finance_costs", "depreciation", "pbt", "tax", "pat", "operating_profit"]
UNIT_TO_CRORE = {"crore": 1.0, "lakh": 0.01, "million": 0.1, "billion": 100.0, "thousand": 0.0001}


# ============================================================ (a) quarterly results ======================

def pick_pl_pages(pages: List[str]) -> Optional[Tuple[List[int], str]]:
    """Find the profit-and-loss statement page(s). Prefers consolidated over standalone.

    Scores pages on P&L vocabulary and on what the heading says, penalising look-alikes (segment tables,
    balance sheet, cash flow, 'extract of' summaries). Returns (zero-based page indexes, basis) or None.
    """
    best = None
    for i, pg in enumerate(pages):
        t = re.sub(r"\s+", " ", pg.lower())   # OCR'd PDFs double their spaces
        head = t[:900]
        if not re.search(r"financial results|statement of (profit|unaudited|audited)|profit and loss", head):
            continue
        score = 0
        score += 3 if "profit before tax" in t or "profit/(loss) before tax" in t or "profit before exceptional" in t else 0
        score += 2 if re.search(r"revenue from operations|total income|interest earned", t) else 0
        score += 1 if re.search(r"finance costs?|interest expended|interest expense", t) else 0
        score += 1 if "depreciation" in t else 0
        score += 1 if re.search(r"tax expense|provision for tax", t) else 0
        score += 1 if re.search(r"profit for the (period|year|quarter)|net profit|profit after tax|profit/\(loss\) for", t) else 0
        score -= 4 if re.search(r"segment", head) else 0
        score -= 5 if re.search(r"balance sheet|cash flow", head) else 0
        score -= 4 if "extract of" in head else 0
        if score < 6:
            continue
        basis = "consolidated" if "consolidated" in head else "standalone"
        rank = score + (3 if basis == "consolidated" else 0)
        if best is None or rank > best[0]:
            best = (rank, i, basis)
    if not best:
        return None
    _, i, basis = best
    idx = [i]
    # the statement can spill onto the next page (PAT / EPS rows): include it if this page ends before the bottom line
    if i + 1 < len(pages) and not re.search(r"profit for the|net profit|profit after tax|profit/\(loss\) for", re.sub(r"\s+", " ", pages[i].lower())):
        idx.append(i + 1)
    return idx, basis


RESULTS_SYSTEM = """You transcribe the profit-and-loss table from an Indian listed company's financial-results filing.
Reply with ONLY one JSON object:
{"basis":"consolidated"|"standalone","unit":"crore"|"lakh"|"million"|"billion"|"thousand",
 "period_type":"quarter"|"year","periods":["<end date of latest column>","<previous>","<year-ago>"],
 "is_bank_or_nbfc":true|false,
 "revenue":[a,b,c],"other_income":[a,b,c],"finance_costs":[a,b,c],"depreciation":[a,b,c],
 "pbt":[a,b,c],"tax":[a,b,c],"pat":[a,b,c],"operating_profit":[a,b,c]}
Each array is [latest quarter, immediately preceding quarter, same quarter a year earlier]. Choose columns by their header
dates, NOT by position - column order differs between companies, and ignore 6-month / 9-month / full-year columns.
If the table has no quarterly columns (annual-only), use [latest year, previous year, null] and period_type "year".
Numbers exactly as printed, commas removed; brackets or a minus sign mean negative; use null when a line is absent.
revenue = Revenue from operations (banks/NBFCs: Total income). other_income = the 'Other income' line. finance_costs = Finance costs.
depreciation = Depreciation and amortisation expense. pbt = Profit before tax (after exceptional items). tax = total tax expense.
pat = Profit/(loss) for the period after tax (total, before minority interest). operating_profit: only for banks/NBFCs, the
'Operating profit before provisions and contingencies' line as printed; otherwise null. unit is the one printed in the table header.
The text may be OCR'd: there a '.' or '-' between digit groups (e.g. '533-402', '1.057.959') is a thousands separator, so read it as 533402. Use the same digit grouping on every line."""


def num(x) -> Optional[float]:
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace(",", "").replace("₹", "").replace(" ", "")
    if s in ("", "-", "--", "NA", "N/A", "null", "nil"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    try:
        v = float(s.strip("()"))
    except ValueError:
        return None
    return -v if neg else v


def pct_change(cur: Optional[float], base: Optional[float]) -> Optional[float]:
    """% change; None when either side is missing or the base isn't positive (not meaningful)."""
    if cur is None or base is None or base <= 0:
        return None
    return round((cur / base - 1) * 100, 1)


def _decimals(x: float) -> int:
    r = repr(round(x, 6))
    return len(r.split(".")[1].rstrip("0")) if "." in r else 0


def compute_results(raw: dict) -> dict:
    """Pure maths on the transcribed table: EBITDA, QoQ/YoY, margins, and the PBT - tax = PAT self-check."""
    cols = {}
    for m in METRICS:
        v = raw.get(m)
        v = list(v) if isinstance(v, (list, tuple)) else []
        cols[m] = [num(x) for x in (v + [None] * 3)[:3]]
    unit = str(raw.get("unit", "")).lower().rstrip("s")
    factor = UNIT_TO_CRORE.get(unit)
    bank = bool(raw.get("is_bank_or_nbfc"))

    def conv(x):
        return None if x is None else round(x * (factor or 1.0), 2)

    notes = []
    if factor is None:
        notes.append(f"unknown unit '{raw.get('unit')}', values left as printed")
    ebitda = []
    for k in range(3):
        pbt, fin, dep, oth, op = (cols[m][k] for m in ("pbt", "finance_costs", "depreciation", "other_income", "operating_profit"))
        if bank and op is not None:
            ebitda.append(op)                                   # banks/NBFCs: operating profit before provisions
        elif None not in (pbt, fin, dep):
            ebitda.append(pbt + fin + dep - (oth or 0.0))       # PBT + finance costs + depreciation - other income
        else:
            ebitda.append(None)
    if not bank and all(x is None for x in cols["other_income"]):
        notes.append("other income not reported separately; EBITDA includes it")

    series = {m: [conv(x) for x in cols[m]] for m in ("revenue", "pbt", "pat", "tax")}
    series["ebitda"] = [conv(x) for x in ebitda]
    rev = series["revenue"]
    out = {}
    for m in ("revenue", "ebitda", "pbt", "pat"):
        v = series[m]
        out[m] = {"values": v, "qoq_pct": pct_change(v[0], v[1]), "yoy_pct": pct_change(v[0], v[2]),
                  "margin_pct": [round(x / r * 100, 1) if x is not None and r and r > 0 else None for x, r in zip(v, rev)]
                  if m != "revenue" else None}

    checks, ok = [], True
    for k, label in enumerate(("latest", "previous", "year_ago")):
        pbt, tax, pat, r = cols["pbt"][k], cols["tax"][k], cols["pat"][k], cols["revenue"][k]
        if None in (pbt, tax, pat):
            continue
        diff = pbt - tax - pat
        tol = max(0.005 * abs(pat), 0.0005 * abs(r or 0.0), 1e-6)   # near-exact by identity; only associates' share can legitimately nudge it
        good = abs(diff) <= tol
        ok = ok and good
        checks.append({"period": label, "pbt_minus_tax_minus_pat": round(diff, 2), "ok": good})
    if not checks:
        ok = False
        notes.append("could not run PBT - tax = PAT check (missing lines)")
    if series["revenue"][0] is None:
        ok = False
        notes.append("latest revenue missing")
    if any(x is not None and _decimals(x) >= 3 for m in METRICS for x in cols[m]):
        ok = False   # statements in crore/million/lakh don't print 3 decimals: OCR'd thousands separators were read as decimal points
        notes.append("values with 3+ decimals: possible OCR thousands-separator misread")
    return {"basis": raw.get("basis"), "unit_printed": raw.get("unit"), "unit": "INR crore" if factor else raw.get("unit"),
            "period_type": raw.get("period_type", "quarter"), "periods": raw.get("periods"), "is_bank_or_nbfc": bank,
            "printed": {m: cols[m] for m in METRICS}, "metrics": out, "checks": checks, "check_ok": ok, "notes": notes}


def results_summary(f: dict) -> Optional[str]:
    m = f["metrics"]
    rev, pat = m["revenue"], m["pat"]
    if rev["values"][0] is None:
        return None

    def part(name, d):
        if d["values"][0] is None:
            return None
        bits = [f"{d['yoy_pct']:+.0f}% YoY" if d["yoy_pct"] is not None else None,
                f"{d['qoq_pct']:+.0f}% QoQ" if d["qoq_pct"] is not None else None]
        return f"{name} ₹{d['values'][0]:,.0f} cr" + (f" ({', '.join(b for b in bits if b)})" if any(bits) else "")

    return "; ".join(p for p in (part("Revenue", rev), part("PAT", pat)) if p)


def enrich_result(conn: sqlite3.Connection, row) -> Tuple[Optional[dict], Optional[str]]:
    """Returns (facts, summary). facts=None means a transient failure (leave for retry)."""
    pages = pdfs.get_pages(row["id"], row["attachment"])
    if pages is None:
        return {"type": "results", "status": "unavailable", "reason": "attachment is not a readable PDF"}, None
    if not pages:
        return {"type": "results", "status": "unavailable", "reason": "scanned PDF (no text layer)"}, None
    picked = pick_pl_pages(pages)
    if not picked:
        return {"type": "results", "status": "unavailable", "reason": "no profit-and-loss page found"}, None
    idx, basis = picked
    text = "\n\n".join(pages[i] for i in idx)[:14000]
    user = f"Company: {row['symbol']}. Statement type: {basis}.\n\n{text}"

    best = None
    for model in (None, config.STRONG_MODEL):          # cheap model first; strong model only if the self-check fails
        parsed = llm.parse_json(llm.complete(conn, RESULTS_SYSTEM, user, model=model, max_tokens=1500))
        facts = compute_results(parsed)
        facts.update({"type": "results", "model": llm.resolve(model), "page": idx[0] + 1,
                      "status": "ok" if facts["check_ok"] else "needs_review"})
        best = facts
        if facts["check_ok"]:
            break
    return best, results_summary(best)


# ============================================================ (b) management change ======================

MGMT_SYSTEM = """You read a stock-exchange filing about a change in a listed company's directors or senior management.
Reply with ONLY JSON: {"people":[{"name":"","role":"","change_type":"appointment|re-appointment|resignation|cessation|retirement|change_in_designation",
"effective_date":"YYYY-MM-DD or null","background":"","reason":""}]}
One entry per person. role = designation exactly as stated (e.g. 'Non-Executive Independent Director'). background = at most 40 words
condensed from the brief-profile / annexure in the document: qualifications, years of experience, notable prior roles and
employers; null if the document has no profile. reason = stated reason for exit, else null. Use ONLY the document - never add
outside knowledge; use null for anything it does not say."""

_VERB = {"appointment": "appointed", "re-appointment": "re-appointed", "resignation": "resigned as",
         "cessation": "ceases as", "retirement": "retires as", "change_in_designation": "now"}


def mgmt_text(pages: List[str], cap: int = 9000) -> str:
    """Whole filing if short; otherwise page 1 plus the pages that talk about appointments / profiles."""
    if sum(map(len, pages)) <= cap:
        return "\n\n".join(pages)
    rx = re.compile(r"brief profile|profile|appoint|resign|cessation|retire|\bDIN\b|qualification|experience", re.I)
    ranked = sorted(range(1, len(pages)), key=lambda i: -len(rx.findall(pages[i])))
    keep, used = {0}, len(pages[0])
    for i in ranked:
        if rx.search(pages[i]) and used + len(pages[i]) <= cap:
            keep.add(i)
            used += len(pages[i])
    return "\n\n".join(pages[i] for i in sorted(keep))[:cap]


def enrich_mgmt(conn: sqlite3.Connection, row) -> Tuple[Optional[dict], Optional[str]]:
    pages = pdfs.get_pages(row["id"], row["attachment"])
    if not pages:
        reason = "attachment is not a readable PDF" if pages is None else "scanned PDF (no text layer)"
        return {"type": "management_change", "status": "unavailable", "reason": reason}, None
    text = mgmt_text(pages)
    parsed = llm.parse_json(llm.complete(conn, MGMT_SYSTEM, f"Company: {row['symbol']}\n\n{text}", max_tokens=1500))
    people = [p for p in parsed.get("people", []) if p.get("name")]
    if not people:
        return {"type": "management_change", "status": "unavailable", "reason": "no people found in filing"}, None
    facts = {"type": "management_change", "status": "ok", "model": llm.resolve(None), "people": people}
    bits = [f"{p['name']} {_VERB.get(p.get('change_type'), 'change:')} {p.get('role') or ''}".strip() for p in people[:2]]
    return facts, "; ".join(bits) + (f" (+{len(people) - 2} more)" if len(people) > 2 else "")


# ============================================================ (d) credit ratings =========================

RATING_SYSTEM = """You read a credit-rating agency's letter or press release about a listed company.
Reply with ONLY JSON: {"agency": "", "instrument": "short description of what was rated, or null",
"action": "assigned|upgraded|downgraded|reaffirmed|withdrawn|outlook_revised|other",
"rating_from": "previous rating or null", "rating_to": "the rating now", "outlook": "positive|stable|negative|watch|null",
"amount_cr": number or null}
Use ONLY the document. If several instruments are rated, describe the most important one (largest amount or the long-term rating)
and take the action from the headline of the letter. Never guess a rating that is not printed."""

# base priority by what the agency did, since direction decides whether an investor cares
RATING_PRIORITY = {"downgraded": (75, "Credit rating downgraded"), "upgraded": (55, "Credit rating upgraded"),
                   "assigned": (45, "New credit rating assigned"), "withdrawn": (40, "Credit rating withdrawn"),
                   "outlook_revised": (45, "Rating outlook changed"), "reaffirmed": (20, "Credit rating reaffirmed"),
                   "other": (30, "Credit rating action")}
_RATING_VERB = {"downgraded": "downgrades", "upgraded": "upgrades", "assigned": "assigns", "reaffirmed": "reaffirms",
                "withdrawn": "withdraws", "outlook_revised": "revises the outlook on", "other": "rates"}


def enrich_rating(conn: sqlite3.Connection, row) -> Tuple[Optional[dict], Optional[str]]:
    pages = pdfs.get_pages(row["id"], row["attachment"])
    if not pages:
        return {"type": "credit_rating", "status": "unavailable",
                "reason": "attachment is not a readable PDF" if pages is None else "scanned PDF (no text layer)"}, None
    text = "\n\n".join(pages)[:7000]
    d = llm.parse_json(llm.complete(conn, RATING_SYSTEM, f"Company: {row['symbol']}\n\n{text}", max_tokens=600))
    action = d.get("action") if d.get("action") in RATING_PRIORITY else "other"
    pri, why = RATING_PRIORITY[action]
    outlook = d.get("outlook")
    if outlook == "negative" and action in ("reaffirmed", "assigned", "other"):
        pri, why = 55, "Credit rating outlook negative"       # a reaffirmation with a negative outlook is still a warning
    elif outlook == "positive" and action == "reaffirmed":
        pri, why = 30, "Credit rating reaffirmed, outlook positive"
    facts = {"type": "credit_rating", "status": "ok", "model": llm.resolve(None), "agency": d.get("agency"),
             "instrument": d.get("instrument"), "action": action, "rating_from": d.get("rating_from"),
             "rating_to": d.get("rating_to"), "outlook": outlook, "amount_cr": d.get("amount_cr"),
             "priority": pri, "why": why}
    bits = [f"{d.get('agency') or 'Rating agency'} {_RATING_VERB[action]} {row['symbol']}"]
    if d.get("rating_to"):
        bits.append(f"to {d['rating_to']}" + (f" from {d['rating_from']}" if d.get("rating_from") and action in ("upgraded", "downgraded") else ""))
    if outlook and outlook != "null":
        bits.append(f"(outlook {outlook})")
    return facts, " ".join(bits)


# ============================================================ (e) public bios for incoming people ========

IN_TYPES = ("appointment", "re-appointment", "change_in_designation")


def enrich_bios(conn: sqlite3.Connection, stats: dict, force: bool = False) -> None:
    """For incoming people whose filing gave no profile, look for a public Wikipedia page. No model involved."""
    rows = conn.execute("""SELECT a.id, a.symbol, a.facts, COALESCE(s.name, a.symbol) AS name FROM announcements a
                           LEFT JOIN stocks s ON s.symbol=a.symbol WHERE a.facts LIKE '%"management_change"%'""").fetchall()
    for r in rows:
        facts, changed = json.loads(r["facts"]), False
        for p in facts.get("people", []):
            if p.get("background") or p.get("change_type") not in IN_TYPES or (p.get("web_checked") and not force):
                continue
            found = profiles.wiki_bio(p["name"], r["name"])
            p["web_checked"] = True
            if found:
                p["web_bio"] = found
                stats["bios"] += 1
            changed = True
        if changed:
            conn.execute("UPDATE announcements SET facts=? WHERE id=?", (json.dumps(facts), r["id"]))
            conn.commit()


# ============================================================ (c) one-line summaries =====================

SUMMARY_SYSTEM = f"""You write one-line plain-English summaries of stock-exchange filings for a busy investor.
For each numbered filing write at most {SUMMARY_MAX_WORDS} words saying what actually happened (who, what, how much) - not 'company informed exchange'.
If the text says nothing substantive, say so briefly (e.g. 'Routine disclosure; no details in text').
Reply with ONLY a JSON array: [{{"i": <number>, "s": "<summary>"}}] covering every number."""

_BOILERPLATE = re.compile(r"^.*?(has (informed|submitted|intimated)[^.]*?exchange|intimation under regulation \d+[^.]*?)\s*(about|regarding|that|the)?\s*",
                          re.I | re.S)


def _thin(text: str) -> bool:
    core = _BOILERPLATE.sub("", text or "", count=1)
    return len(core.strip()) < 90


def _line(conn, row) -> str:
    text = (row["text"] or "")[:500]
    extra = ""
    if _thin(text):  # blurb is just a title: borrow the start of the PDF itself
        pages = pdfs.get_pages(row["id"], row["attachment"])
        if pages:
            doc = re.sub(r"\s+", " ", " ".join(pages[:2]))
            m = re.search(r"\bsub(ject)?\s*[:\-]", doc, re.I)   # skip the letterhead / exchange addresses
            extra = " | doc: " + doc[m.start():][:700] if m else " | doc: " + doc[250:950]
    return f'[{row["symbol"]}] {row["nse_desc"]} | {text}{extra}'


def enrich_summaries(conn: sqlite3.Connection, rows: list, stats: dict) -> None:
    for i in range(0, len(rows), SUMMARY_BATCH):
        chunk = rows[i:i + SUMMARY_BATCH]
        user = "\n".join(f"{n}. {_line(conn, r)}" for n, r in enumerate(chunk, 1))
        try:
            out = llm.parse_json(llm.complete(conn, SUMMARY_SYSTEM, user, max_tokens=1800))
        except llm.LLMUnavailable:
            raise
        except Exception as e:
            stats["errors"].append(f"summaries batch {i // SUMMARY_BATCH + 1}: {e}")
            continue
        stats["llm_calls"] += 1
        for o in out:
            try:
                r = chunk[int(o["i"]) - 1]
                words = str(o["s"]).split()
            except (KeyError, ValueError, IndexError, TypeError):
                continue
            s = " ".join(words[:SUMMARY_MAX_WORDS]).rstrip(",;:")
            if len(words) > SUMMARY_MAX_WORDS:
                s = s.rstrip(".") + "…"      # a cut-off line must read as cut off, not as a finished thought
            conn.execute("UPDATE announcements SET summary=? WHERE id=?", (s, r["id"]))
            stats["summaries"] += 1
        conn.commit()


# ============================================================ driver ======================================

def run(kinds=("results", "mgmt", "ratings", "bios", "summaries"), limit: Optional[int] = None, force: bool = False,
        all_stocks: bool = False, verbose: bool = False) -> dict:
    log = print if verbose else (lambda *a, **k: None)
    stats = {"results": 0, "mgmt": 0, "ratings": 0, "bios": 0, "summaries": 0, "needs_review": 0, "unavailable": 0, "llm_calls": 0,
             "skipped": None, "errors": []}
    scope = "" if all_stocks else "AND s.in_portfolio=1"
    todo = "" if force else "AND a.facts IS NULL"
    with db.session() as conn:
        def fetch(where, extra=""):
            q = f"""SELECT a.* FROM announcements a JOIN stocks s ON s.symbol=a.symbol
                    WHERE {where} {scope} {extra} ORDER BY a.priority DESC, a.ann_dt DESC"""
            return conn.execute(q + (f" LIMIT {int(limit)}" if limit else "")).fetchall()

        jobs = []
        if "results" in kinds:
            jobs += [("results", r, enrich_result) for r in
                     fetch(f"a.category='results' AND a.priority>={RESULTS_MIN_PRIORITY} AND a.attachment IS NOT NULL", todo)]
        if "mgmt" in kinds:
            jobs += [("mgmt", r, enrich_mgmt) for r in
                     fetch(f"a.category='management_change' AND a.priority>={SUMMARY_MIN_PRIORITY} AND a.attachment IS NOT NULL", todo)]
        if "ratings" in kinds:
            jobs += [("ratings", r, enrich_rating) for r in
                     fetch("a.category='credit_rating' AND a.attachment IS NOT NULL", todo)]
        for kind, row, fn in jobs:
            try:
                facts, summary = fn(conn, row)
            except llm.LLMUnavailable:
                pdfs.get_pages(row["id"], row["attachment"])  # still warm the disk cache for the next run
                stats["skipped"] = "no LLM key set (GEMINI_API_KEY) - PDFs cached, extraction pending"
                continue
            except Exception as e:
                stats["errors"].append(f"{row['symbol']} {row['id']}: {e}")
                continue
            if facts is None:
                continue
            stats[kind] += facts.get("status") != "unavailable"
            stats["unavailable"] += facts.get("status") == "unavailable"
            stats["needs_review"] += facts.get("status") == "needs_review"
            conn.execute("UPDATE announcements SET facts=?, summary=COALESCE(?, summary) WHERE id=?",
                         (json.dumps(facts), summary, row["id"]))
            if kind == "ratings" and facts.get("priority") is not None:   # direction of the rating decides where it lands in the brief
                conn.execute("UPDATE announcements SET priority=?, why=?, classified_by=? WHERE id=?",
                             (facts["priority"], facts["why"], "pdf:rating", row["id"]))
            conn.commit()
            log(f"  {kind:<7} {row['symbol']:<10} {facts.get('status'):<12} {summary or facts.get('reason', '')}")

        if "bios" in kinds:
            try:
                enrich_bios(conn, stats, force)
            except Exception as e:      # a Wikipedia hiccup must never block the rest of the pipeline
                stats["errors"].append(f"bios: {e}")

        if "summaries" in kinds:
            rows = fetch(f"a.priority>={SUMMARY_MIN_PRIORITY} AND a.category!='management_change' "
                         f"AND NOT (a.category='results' AND a.priority>={RESULTS_MIN_PRIORITY} AND a.facts IS NOT NULL)",
                         "" if force else "AND a.summary IS NULL")
            try:
                enrich_summaries(conn, rows, stats)
            except llm.LLMUnavailable:
                stats["skipped"] = "no LLM key set (GEMINI_API_KEY) - PDFs cached, extraction pending"
    return stats


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("kinds", nargs="*", help="results | mgmt | ratings | bios | summaries (default: all)")
    p.add_argument("--limit", type=int)
    p.add_argument("--force", action="store_true", help="redo filings already enriched")
    p.add_argument("--all-stocks", action="store_true", help="include non-portfolio (ad-hoc) symbols")
    a = p.parse_args()
    db.init_db()
    bad = [k for k in a.kinds if k not in ("results", "mgmt", "ratings", "bios", "summaries")]
    if bad:
        p.error(f"unknown stage: {bad}")
    print(run(tuple(a.kinds or ("results", "mgmt", "ratings", "bios", "summaries")), a.limit, a.force, a.all_stocks, verbose=True))


if __name__ == "__main__":
    main()
