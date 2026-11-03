"""Public background for an incoming director/executive when the filing's own annexure doesn't give one.

Source: Wikipedia's keyless public API. It only covers notable people, which is the honest trade: whatever we show is a real
page with a link, never a model's recollection. We accept a page only if its title is that person AND its intro mentions the company.
"""
from __future__ import annotations

import re
import time
from typing import List, Optional

import requests

API = "https://en.wikipedia.org/w/api.php"
UA = {"User-Agent": "FINN/0.1 (research prototype; contact via repository)"}
HONORIFIC = re.compile(r"^(mr|ms|mrs|miss|dr|shri|smt|prof|justice|ca|cs)\.?\s+", re.I)
COMPANY_NOISE = {"ltd", "limited", "india", "indian", "industries", "company", "corporation", "corp", "the", "and", "of", "private", "pvt"}


def _tokens(s: str) -> List[str]:
    return [t for t in re.findall(r"[a-z]+", s.lower()) if len(t) > 1]


def _company_words(company: str) -> List[str]:
    return [t for t in _tokens(company) if t not in COMPANY_NOISE and len(t) >= 3]


def _sentences(text: str, max_words: int = 55) -> str:
    out, n = [], 0
    for s in re.split(r"(?<=[.!?])\s+", text.strip()):
        w = len(s.split())
        if out and n + w > max_words:
            break
        out.append(s)
        n += w
        if n >= 25:
            break
    return " ".join(out)


def _get(params: dict) -> dict:
    """GET with a polite retry: Wikipedia answers bursts with 429, which must not look like 'person not found'."""
    for attempt in range(4):
        r = requests.get(API, params=params, headers=UA, timeout=15)
        if r.status_code in (429, 503):
            time.sleep(1.5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise requests.RequestException("Wikipedia is rate-limiting")


def wiki_bio(name: str, company: str) -> Optional[dict]:
    """{text, source, url} or None. Never raises on network trouble."""
    clean = re.sub(r"\(.*?\)", "", HONORIFIC.sub("", name)).strip()
    want = _tokens(clean)
    cwords = _company_words(company)
    if len(want) < 2 or not cwords:     # a single name can't be matched safely
        return None
    try:
        hits = _get({"action": "query", "list": "search", "srsearch": f"{' '.join(want)} {company}", "format": "json",
                     "srlimit": 4})["query"]["search"]
        for h in hits:
            title = h["title"]
            if not all(t in _tokens(title) for t in want):          # the page must be this person
                continue
            page = next(iter(_get({"action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1,
                                   "titles": title, "format": "json", "redirects": 1})["query"]["pages"].values()))
            intro = page.get("extract") or ""
            if not any(w in intro.lower() for w in cwords):         # and must mention the company
                continue
            return {"text": _sentences(intro), "source": "Wikipedia", "url": "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")}
    except (requests.RequestException, KeyError, ValueError):
        return None
    return None
