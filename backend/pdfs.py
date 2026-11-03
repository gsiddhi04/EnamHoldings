"""Download filings once, extract per-page text once; both cached on disk under data/."""
from __future__ import annotations

import json
import logging
import re
import time
from typing import List, Optional

import requests
from pypdf import PdfReader

from . import config

logging.getLogger("pypdf").setLevel(logging.ERROR)  # NSE PDFs are routinely slightly malformed
_session: Optional[requests.Session] = None


def _http() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(config.NSE_HEADERS)
    return _session


def _squeeze(t: str) -> str:
    lines = (re.sub(r"[ \t]{3,}", "  ", ln).strip() for ln in t.splitlines())
    return "\n".join(ln for ln in lines if ln)


def get_pdf(ann_id: str, url: str, retries: int = 3) -> Optional[str]:
    """Return the local path of the filing PDF (downloading if needed) or None if it isn't a PDF."""
    config.PDF_DIR.mkdir(parents=True, exist_ok=True)
    path = config.PDF_DIR / f"{ann_id}.pdf"
    if path.exists() and path.stat().st_size > 0:
        return str(path)
    for attempt in range(retries):
        try:
            r = _http().get(url, timeout=60)
            if r.status_code == 200 and r.content[:5] == b"%PDF-":
                path.write_bytes(r.content)
                return str(path)
            if r.status_code == 200:  # xml / zip / html error page
                return None
        except requests.RequestException:
            pass
        time.sleep(1 + attempt)
    return None


def get_pages(ann_id: str, url: str, layout: bool = True) -> Optional[List[str]]:
    """Per-page text for a filing. [] = PDF has no text layer (scanned); None = couldn't fetch a PDF."""
    config.TEXT_DIR.mkdir(parents=True, exist_ok=True)
    cache = config.TEXT_DIR / f"{ann_id}.json"
    if cache.exists():
        return json.loads(cache.read_text())["pages"]
    pdf = get_pdf(ann_id, url)
    if not pdf:
        return None
    try:
        # layout mode keeps each table row (label + all its columns) on one line; squeeze the padding to save tokens
        # (transcripts are prose, not tables: plain mode reads better there)
        pages = [_squeeze((p.extract_text(extraction_mode="layout") if layout else p.extract_text()) or "")
                 for p in PdfReader(pdf).pages]
    except Exception:
        return None
    if sum(len(p) for p in pages) < 80:  # image-only PDF; OCR is out of scope for the prototype
        pages = []
    cache.write_text(json.dumps({"pages": pages}))
    return pages
