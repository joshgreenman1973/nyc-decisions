"""NYC Public Advocate reports."""
from __future__ import annotations

import re
from typing import Iterator

from selectolax.parser import HTMLParser

from . import _base as B

SOURCE = "public-advocate"
LISTING = "https://advocate.nyc.gov/reports/"


def scrape(fetch_text: bool = True, max_records: int = 100) -> Iterator[dict]:
    yielded = 0
    seen = set()
    with B.http_client() as client:
        try:
            r = client.get(LISTING)
            r.raise_for_status()
        except Exception as e:
            print(f"[{SOURCE}] fetch fail: {e}")
            return
        tree = HTMLParser(r.text)
        for a in tree.css("a"):
            href = (a.attributes.get("href") or "").strip()
            if not href:
                continue
            if not (href.endswith(".pdf") or "/reports/" in href and href != LISTING):
                continue
            if href in seen:
                continue
            seen.add(href)
            title = a.text(strip=True)[:300]
            if not title or len(title) < 8:
                continue
            m = re.search(r"(20\d{2})[-/_]?(\d{2})?", href)
            date = ""
            if m:
                date = f"{m.group(1)}-{m.group(2) or '01'}-01"
            doc_url = href if href.endswith(".pdf") else ""
            full_text = ""
            if fetch_text and doc_url:
                full_text = B.fetch_pdf_text(
                    client, doc_url,
                    cache_key=B.stable_id(SOURCE, doc_url),
                    max_pages=30,
                )
            rec = B.Record(
                id=B.stable_id(SOURCE, href),
                source=SOURCE,
                source_url=LISTING,
                title=title,
                decision_date=date,
                summary=B.truncate(full_text, 500),
                full_text=B.truncate(full_text, 8000),
                doc_url=doc_url or href,
                agency="NYC Public Advocate",
                scraped_at=B.now_iso(),
            )
            yield rec.to_dict()
            yielded += 1
            if yielded >= max_records:
                return


if __name__ == "__main__":
    B.write_jsonl(SOURCE, scrape())
