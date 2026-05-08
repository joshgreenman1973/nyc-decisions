"""NYC Department of Investigation (DOI) Public Reports.

Scrapes the search portal which returns HTML with PDF links.
"""
from __future__ import annotations

import re
from typing import Iterator

from selectolax.parser import HTMLParser

from . import _base as B

INDEX_URL = "https://www.nyc.gov/site/doi/newsroom/public-reports-current.page"
ARCHIVE_URL = "https://www.nyc.gov/site/doi/newsroom/doi-reports-search.page"
SOURCE = "doi"
SEARCH_URL = "https://www.nyc.gov/site/doi/newsroom/doi-reports-search.page"


def _extract_reports(html: str) -> list[dict]:
    tree = HTMLParser(html)
    results = []
    seen = set()
    for a in tree.css("a"):
        href = (a.attributes.get("href") or "").strip()
        if not href.endswith(".pdf"):
            continue
        if "/doi/" not in href:
            continue
        if href.startswith("/"):
            href = "https://www.nyc.gov" + href
        if href in seen:
            continue
        seen.add(href)
        title = a.text(strip=True) or href.rsplit("/", 1)[-1]
        # Skip generic "Read More" type links — find a parent text node
        if title.lower() in ("", "read more", "press release", "report"):
            parent = a.parent
            if parent:
                title = parent.text(strip=True)[:300]
        # Try to glean date from URL path: /pdf/2024/...
        m = re.search(r"/pdf/(\d{4})/", href)
        year = m.group(1) if m else ""
        m2 = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", href)
        date = f"{m2.group(3)}-{m2.group(1)}-{m2.group(2)}" if m2 else (f"{year}-01-01" if year else "")
        results.append({"title": title, "doc_url": href, "date": date})
    return results


def scrape(include_archive: bool = True, fetch_text: bool = True, max_records: int = 200) -> Iterator[dict]:
    urls = [INDEX_URL] + ([ARCHIVE_URL] if include_archive else [])
    seen_urls = set()
    yielded = 0
    with B.http_client() as client:
        for url in urls:
            try:
                r = client.get(url)
                r.raise_for_status()
            except Exception as e:
                print(f"[{SOURCE}] failed to fetch {url}: {e}")
                continue
            for item in _extract_reports(r.text):
                if item["doc_url"] in seen_urls:
                    continue
                seen_urls.add(item["doc_url"])
                full_text = ""
                if fetch_text:
                    full_text = B.fetch_pdf_text(
                        client, item["doc_url"],
                        cache_key=B.stable_id(SOURCE, item["doc_url"]),
                        max_pages=40,
                    )
                rec = B.Record(
                    id=B.stable_id(SOURCE, item["doc_url"]),
                    source=SOURCE,
                    source_url=url,
                    title=item["title"][:300],
                    decision_date=item["date"],
                    summary=B.truncate(full_text, 500) if full_text else "",
                    full_text=B.truncate(full_text, 8000),
                    doc_url=item["doc_url"],
                    agency="DOI",
                    scraped_at=B.now_iso(),
                )
                yield rec.to_dict()
                yielded += 1
                if yielded >= max_records:
                    return


if __name__ == "__main__":
    B.write_jsonl(SOURCE, scrape())
