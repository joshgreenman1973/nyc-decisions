"""Shared utilities for NYC Decisions scrapers.

Each scraper module exposes a `scrape()` function that yields normalized
records as dicts. The orchestrator writes them to data/normalized/<source>.jsonl.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Optional

import httpx
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
NORMALIZED_DIR = DATA_DIR / "normalized"
CACHE_DIR = DATA_DIR / "cache"

USER_AGENT = (
    "NYCDecisionsBot/0.1 (+https://github.com/joshgreenman1973/nyc-decisions; "
    "contact: josh.greenman@gmail.com)"
)


@dataclass
class Record:
    id: str
    source: str
    source_url: str
    title: str
    decision_date: str  # ISO YYYY-MM-DD or empty
    summary: str = ""
    full_text: str = ""
    doc_url: str = ""
    agency: str = ""
    respondent: str = ""
    judge: str = ""
    outcome: str = ""
    penalty: str = ""
    scraped_at: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v != "" or k in ("id", "source", "title")}


def http_client(timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        follow_redirects=True,
        timeout=timeout,
    )


def stable_id(source: str, key: str) -> str:
    h = hashlib.sha1(f"{source}:{key}".encode()).hexdigest()[:12]
    return f"{source}-{h}"


def fetch_pdf_text(client: httpx.Client, url: str, cache_key: str, max_pages: int = 100) -> str:
    """Download a PDF (with caching) and extract text. No OCR here — relies on
    embedded text. Sources where OCR matters (CCHR scanned PDFs) get their own
    handler."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{cache_key}.pdf"
    if not cache_path.exists():
        try:
            r = client.get(url)
            r.raise_for_status()
            cache_path.write_bytes(r.content)
        except Exception as e:
            print(f"  ! pdf fetch failed {url}: {e}")
            return ""
    try:
        reader = PdfReader(str(cache_path))
        parts = []
        for i, page in enumerate(reader.pages[:max_pages]):
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
        text = "\n".join(parts)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    except Exception as e:
        print(f"  ! pdf parse failed {url}: {e}")
        return ""


def write_jsonl(source: str, records: Iterable[dict]) -> int:
    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    out = NORMALIZED_DIR / f"{source}.jsonl"
    n = 0
    with out.open("w") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    print(f"[{source}] wrote {n} records -> {out.relative_to(ROOT)}")
    return n


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def truncate(text: str, n: int = 2000) -> str:
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0] + "…"
