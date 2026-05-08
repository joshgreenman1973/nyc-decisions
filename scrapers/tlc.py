"""TLC Chairperson Review of OATH decisions.

Page: /site/tlc/about/chairperson-review-oath.page

Each PDF is the Chairperson's review of an OATH-TLC adjudication. The link
text is usually the case caption; we parse a date from the PDF body if possible.
"""
from __future__ import annotations

import re
from typing import Iterator

from selectolax.parser import HTMLParser

from . import _base as B

SOURCE = "tlc"
INDEX_URL = "https://www.nyc.gov/site/tlc/about/chairperson-review-oath.page"
DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})"
)
MONTHS = {m: i for i, m in enumerate(
    ["January","February","March","April","May","June","July","August",
     "September","October","November","December"], start=1)}


def _date_from_text(text: str) -> str:
    if not text:
        return ""
    m = DATE_RE.search(text)
    return f"{m.group(3)}-{MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}" if m else ""


def scrape(fetch_text: bool = True, max_records: int = 200) -> Iterator[dict]:
    yielded = 0
    seen = set()
    with B.http_client() as client:
        try:
            r = client.get(INDEX_URL)
            r.raise_for_status()
        except Exception as e:
            print(f"[{SOURCE}] fetch fail: {e}")
            return
        tree = HTMLParser(r.text)
        for a in tree.css("a"):
            href = (a.attributes.get("href") or "").strip()
            if not href.lower().endswith(".pdf"):
                continue
            if "/tlc/" not in href:
                continue
            if href.startswith("/"):
                href = "https://www.nyc.gov" + href
            if href in seen:
                continue
            seen.add(href)
            title = a.text(strip=True) or href.rsplit("/", 1)[-1].replace(".pdf", "")
            full_text = ""
            if fetch_text:
                full_text = B.fetch_pdf_text(
                    client, href,
                    cache_key=B.stable_id(SOURCE, href),
                    max_pages=30,
                )
            date = _date_from_text(full_text)
            rec = B.Record(
                id=B.stable_id(SOURCE, href),
                source=SOURCE,
                source_url=INDEX_URL,
                title=f"TLC Chairperson Review: {title}"[:280],
                decision_date=date,
                summary=B.truncate(full_text, 500) if full_text else "",
                full_text=B.truncate(full_text, 8000),
                doc_url=href,
                agency="TLC",
                scraped_at=B.now_iso(),
            )
            yield rec.to_dict()
            yielded += 1
            if yielded >= max_records:
                return


if __name__ == "__main__":
    B.write_jsonl(SOURCE, scrape())
