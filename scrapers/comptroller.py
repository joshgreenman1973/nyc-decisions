"""NYC Comptroller — Audits and reports.

Scrapes the comptroller.nyc.gov reports listing. The listing pages return HTTP
404 but with full content — we ignore the status code and parse the body.
"""
from __future__ import annotations

import re
from typing import Iterator

from selectolax.parser import HTMLParser

from . import _base as B

SOURCE = "nyc-comptroller"
LISTING_URL = "https://comptroller.nyc.gov/reports/all-reports/page/{page}/"

DATE_RE = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})"
)
MONTHS = {m: i for i, m in enumerate(
    ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], start=1)}


def _parse_title_and_date(raw: str) -> tuple[str, str]:
    raw = raw.strip()
    m = DATE_RE.match(raw)
    if not m:
        return raw, ""
    mon, day, year = m.group(1)[:3], m.group(2), m.group(3)
    date = f"{year}-{MONTHS[mon]:02d}-{int(day):02d}"
    title = DATE_RE.sub("", raw, count=1).strip()
    return title, date


def scrape(max_pages: int = 8, max_records: int = 200, fetch_text: bool = True) -> Iterator[dict]:
    yielded = 0
    seen = set()
    with B.http_client() as client:
        for page_n in range(1, max_pages + 1):
            try:
                r = client.get(LISTING_URL.format(page=page_n))
            except Exception as e:
                print(f"[{SOURCE}] page {page_n} fetch fail: {e}")
                break
            tree = HTMLParser(r.text)
            found_any = False
            for a in tree.css("a[href*='/reports/']"):
                href = (a.attributes.get("href") or "").strip()
                if not href.startswith("https://comptroller.nyc.gov/reports/"):
                    continue
                slug = href.rstrip("/").rsplit("/", 1)[-1]
                if slug in ("reports", "all-reports", ""):
                    continue
                if href in seen:
                    continue
                raw_text = a.text(strip=True)
                title, date = _parse_title_and_date(raw_text)
                if not title or len(title) < 8:
                    continue
                seen.add(href)
                found_any = True
                doc_url = ""
                full_text = ""
                if fetch_text:
                    try:
                        rep = client.get(href)
                        rep_tree = HTMLParser(rep.text)
                        pdfa = rep_tree.css_first("a[href$='.pdf']")
                        if pdfa:
                            doc_url = (pdfa.attributes.get("href") or "")
                            if doc_url.startswith("/"):
                                doc_url = "https://comptroller.nyc.gov" + doc_url
                            full_text = B.fetch_pdf_text(
                                client, doc_url,
                                cache_key=B.stable_id(SOURCE, doc_url),
                                max_pages=20,
                            )
                    except Exception as e:
                        print(f"  ! detail fetch {href}: {e}")
                rec = B.Record(
                    id=B.stable_id(SOURCE, href),
                    source=SOURCE,
                    source_url=href,
                    title=title[:300],
                    decision_date=date,
                    summary=B.truncate(full_text, 500),
                    full_text=B.truncate(full_text, 8000),
                    doc_url=doc_url or href,
                    agency="NYC Comptroller",
                    scraped_at=B.now_iso(),
                )
                yield rec.to_dict()
                yielded += 1
                if yielded >= max_records:
                    return
            if not found_any:
                break


if __name__ == "__main__":
    B.write_jsonl(SOURCE, scrape())
