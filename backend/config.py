"""Central config: paths, demo universe, default thresholds, NSE client settings."""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_env = ROOT / ".env"      # git-ignored; KEY=value lines, real environment variables win
if _env.exists():
    for _ln in _env.read_text().splitlines():
        _k, _, _v = _ln.partition("=")
        if _k.strip() and not _k.strip().startswith("#") and _v.strip():
            os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))
DB_PATH = Path(os.environ.get("FINN_DB", ROOT / "data" / "finn.db"))
PDF_DIR = ROOT / "data" / "pdfs"      # downloaded filings, keyed by announcement id
TEXT_DIR = ROOT / "data" / "text"     # per-page extracted text (JSON), so a PDF is parsed once

# symbol -> (company name, sector). Mix of mega/large/mid/small caps across sectors.
PORTFOLIO = {
    "RELIANCE":   ("Reliance Industries", "Energy & Conglomerate"),
    "TCS":        ("Tata Consultancy Services", "IT Services"),
    "HDFCBANK":   ("HDFC Bank", "Private Banks"),
    "INFY":       ("Infosys", "IT Services"),
    "ICICIBANK":  ("ICICI Bank", "Private Banks"),
    "ITC":        ("ITC", "FMCG & Tobacco"),
    "LT":         ("Larsen & Toubro", "Capital Goods"),
    "BHARTIARTL": ("Bharti Airtel", "Telecom"),
    "SUNPHARMA":  ("Sun Pharmaceutical", "Pharma"),
    "MARUTI":     ("Maruti Suzuki", "Autos"),
    "TATASTEEL":  ("Tata Steel", "Metals"),
    "TITAN":      ("Titan Company", "Consumer Discretionary"),
    "ADANIPORTS": ("Adani Ports & SEZ", "Infrastructure"),
    "DIXON":      ("Dixon Technologies", "Electronics Mfg"),
    "PERSISTENT": ("Persistent Systems", "IT Services (Mid)"),
    "TRENT":      ("Trent", "Retail"),
    "IRCTC":      ("IRCTC", "Travel & Railways"),
    "SUZLON":     ("Suzlon Energy", "Renewables"),
}

# Ad-hoc research demo set (outside the portfolio). The engine must work for any NSE ticker.
ADHOC = {
    "BAJFINANCE": ("Bajaj Finance", "NBFC"),
    "PIDILITIND": ("Pidilite Industries", "Specialty Chemicals"),
    "DMART":      ("Avenue Supermarts", "Retail"),
    "HINDUNILVR": ("Hindustan Unilever", "FMCG"),
}

# Seeded into the `settings` table on first run; the user edits them in-app later.
DEFAULT_SETTINGS = {
    "volume_multiple": 2.0,         # alert when volume > N x trailing average
    "volume_avg_days": 20,          # trailing window for that average
    "price_move_pct": 5.0,          # alert when |1-day move| exceeds this %
    "alert_categories": ["results", "M&A", "management_change", "litigation", "credit_rating"],
    "alert_min_priority": 60,       # filings at/above this, in followed categories, raise an alert
    "digest_window_hours": 24,
}

CATEGORIES = [
    "results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading",
    "earnings_call", "investor_meetings", "credit_rating", "dividend", "bonus_split", "capex",
    "press_release", "postal_ballot", "agm_egm", "pledging", "unclassified",
]

# Digest tiers on the 0-100 priority scale.
TOP_MIN, LOOK_MIN = 60, 35

CHEAP_MODEL = "claude-haiku-5-5"   # bulk work: classification, extraction, one-line summaries
STRONG_MODEL = "claude-sonnet-5-5"  # only as a retry when a cheap-model extraction fails its self-check
LLM_BATCH = 25

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def now_ist() -> dt.datetime:
    """Naive IST 'now' - NSE timestamps are naive IST, so compare like with like."""
    return dt.datetime.now(IST).replace(tzinfo=None)

# Prices need history beyond the announcement window to compute the trailing volume average.
ANNOUNCEMENT_DAYS = 7
PRICE_DAYS = 35

NSE_BASE = "https://www.nseindia.com"
NSE_ANN_URL = f"{NSE_BASE}/api/corporate-announcements"
NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{NSE_BASE}/companies-listing/corporate-filings-announcements",
}
NSE_DELAY_SECONDS = 0.5  # be polite; NSE rate-limits aggressively
