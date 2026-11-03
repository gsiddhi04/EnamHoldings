"""screener.in scraper: multi-year tables + concall transcript links for any NSE symbol. No LLM involved."""
from __future__ import annotations

import datetime as dt
import re
import time
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

BASE = "https://www.screener.in/company"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}
SECTIONS = ["quarters", "profit-loss", "balance-sheet", "cash-flow", "ratios"]

# screener's row labels -> stable keys (matched on the lower-cased start of the label)
ROW_KEYS = [
    ("sales", "revenue"), ("revenue", "revenue"), ("expenses", "expenses"),
    ("operating profit", "op_profit"), ("financing profit", "op_profit"),
    ("opm", "opm"), ("financing margin", "opm"),
    ("other income", "other_income"), ("interest", "interest"), ("depreciation", "depreciation"),
    ("profit before tax", "pbt"), ("tax", "tax_pct"), ("net profit", "pat"), ("eps", "eps"),
    ("dividend payout", "payout"), ("gross npa", "gnpa"), ("net npa", "nnpa"),
    ("equity capital", "equity_capital"), ("reserves", "reserves"), ("borrowing", "borrowings"),
    ("deposits", "deposits"), ("total liabilities", "total_liabilities"), ("total assets", "total_assets"),
    ("fixed assets", "fixed_assets"), ("cwip", "cwip"), ("investments", "investments"),
    ("cash from operating", "cfo"), ("cash from investing", "cfi"), ("cash from financing", "cff"),
    ("net cash flow", "net_cash"), ("free cash flow", "fcf"),
    ("debtor days", "debtor_days"), ("inventory days", "inventory_days"), ("days payable", "payable_days"),
    ("cash conversion cycle", "ccc"), ("working capital days", "wc_days"),
    ("roce", "roce"), ("roe", "roe"),
]


class ScreenerError(RuntimeError):
    pass


def _num(s: str) -> Optional[float]:
    s = s.replace(",", "").replace("%", "").replace("₹", "").strip()
    if not s or s in {"-", "—"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _key(label: str) -> Optional[str]:
    low = re.sub(r"\s+", " ", label.lower()).strip()
    for prefix, key in ROW_KEYS:
        if low.startswith(prefix):
            return key
    return None


def period_end(label: str) -> Optional[dt.date]:
    """'Sep 2026' -> 2026-09-30 (last day of that month)."""
    try:
        d = dt.datetime.strptime(label.strip(), "%b %Y").date()
    except ValueError:
        return None
    nxt = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def _table(section) -> Optional[dict]:
    t = section.select_one("table") if section else None
    if not t:
        return None
    periods = [th.get_text(" ", strip=True) for th in t.select("thead th")][1:]
    rows: Dict[str, List[Optional[float]]] = {}
    for tr in t.select("tbody tr"):
        tds = tr.select("td")
        if len(tds) < 2:
            continue
        # the first cell can carry a tooltip/button text after the label (e.g. CFO/EBITDA): keep it simple
        key = _key(tds[0].get_text(" ", strip=True))
        if key and key not in rows:
            vals = [_num(td.get_text(" ", strip=True)) for td in tds[1:]]
            rows[key] = (vals + [None] * len(periods))[:len(periods)]
    return {"periods": periods, "rows": rows}


def parse(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    out: dict = {"tables": {}}
    h1 = soup.select_one("h1")
    out["name"] = h1.get_text(" ", strip=True) if h1 else None
    for sec in SECTIONS:
        tbl = _table(soup.select_one(f"section#{sec}"))
        if tbl:
            out["tables"][sec] = tbl
    q = soup.select_one("section#quarters p.sub")
    out["lender"] = bool(q and "financing profit" in soup.select_one("section#quarters").get_text(" ").lower())
    out["basis"] = "standalone" if q and "view consolidated" in q.get_text(" ", strip=True).lower() else "consolidated"

    ratios = {}
    for li in soup.select("#top-ratios li"):
        name = li.select_one(".name")
        val = li.select_one(".number")
        if name and val:
            ratios[name.get_text(" ", strip=True)] = _num(val.get_text())
    out["top_ratios"] = ratios

    out["annual_reports"] = []
    h = next((h for h in soup.select("section#documents h3") if "Annual reports" in h.get_text()), None)
    box = h.find_parent("div", class_="documents") if h else None
    for a in (box.select("ul.list-links a") if box else []):
        if a.get("href"):
            out["annual_reports"].append({"label": a.get_text(" ", strip=True), "url": a["href"]})

    out["concalls"] = []
    h = next((h for h in soup.select("section#documents h3") if "Concalls" in h.get_text()), None)
    box = h.find_parent("div", class_="documents") if h else None
    for li in (box.select("li") if box else []):
        date = li.select_one("div")
        link = li.select_one('a[title="Raw Transcript"]') or next(
            (a for a in li.select("a") if a.get_text(strip=True).lower() == "transcript"), None)
        if date and link and link.get("href"):
            out["concalls"].append({"month": date.get_text(strip=True), "url": link["href"]})
    return out


def fetch(symbol: str, retries: int = 3) -> dict:
    """Consolidated page when there is one (screener serves the standalone page otherwise)."""
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(f"{BASE}/{symbol}/consolidated/", headers=HEADERS, timeout=30)
            if r.status_code == 404:
                raise ScreenerError(f"{symbol} not found on screener.in")
            if r.status_code == 200:
                data = parse(r.text)
                if "profit-loss" not in data["tables"]:
                    raise ScreenerError(f"No financial tables for {symbol} on screener.in")
                data["url"] = f"{BASE}/{symbol}/" + ("consolidated/" if data["basis"] == "consolidated" else "")
                data["fetched_at"] = dt.datetime.utcnow().isoformat(timespec="seconds")
                return data
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(1 + attempt)
    raise ScreenerError(f"screener.in unreachable: {last}")
