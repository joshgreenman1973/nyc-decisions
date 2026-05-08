"""COIB (Conflicts of Interest Board) — enforcement dispositions and advisory opinions.

The enforcement page links a single annual `Enforcement_Case_Summaries.pdf` plus
year-by-year disposition PDFs. The advisory opinions page lists each opinion as
its own PDF. We pull both.
"""
from __future__ import annotations

import re
from typing import Iterator

from selectolax.parser import HTMLParser

from . import _base as B

SOURCE = "coib"

PAGES = [
    ("https://www.nyc.gov/site/coib/public-documents/enforcement-dispositions.page", "enforcement"),
    ("https://www.nyc.gov/site/coib/the-law/advisory-opinions.page", "advisory"),
]


def _extract_pdfs(html: str, base_page: str) -> list[dict]:
    tree = HTMLParser(html)
    out = []
    seen = set()
    for a in tree.css("a"):
        href = (a.attributes.get("href") or "").strip()
        if not href.endswith(".pdf"):
            continue
        if "/coib/" not in href:
            continue
        if href.startswith("/"):
            href = "https://www.nyc.gov" + href
        if href in seen:
            continue
        seen.add(href)
        title = a.text(strip=True) or href.rsplit("/", 1)[-1]
        # Date heuristics: filename often contains YYYY or YYYY-MM-DD
        m = re.search(r"(\d{4})[-_](\d{1,2})[-_](\d{1,2})", href)
        if m:
            date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        else:
            m2 = re.search(r"(20\d{2})", href)
            date = f"{m2.group(1)}-01-01" if m2 else ""
        out.append({"title": title, "doc_url": href, "date": date})
    return out


def scrape(fetch_text: bool = True, max_records: int = 500) -> Iterator[dict]:
    yielded = 0
    seen_urls = set()
    with B.http_client() as client:
        for page_url, kind in PAGES:
            try:
                r = client.get(page_url)
                r.raise_for_status()
            except Exception as e:
                print(f"[{SOURCE}] fetch fail {page_url}: {e}")
                continue
            for item in _extract_pdfs(r.text, page_url):
                if item["doc_url"] in seen_urls:
                    continue
                seen_urls.add(item["doc_url"])
                full_text = ""
                if fetch_text:
                    full_text = B.fetch_pdf_text(
                        client, item["doc_url"],
                        cache_key=B.stable_id(SOURCE, item["doc_url"]),
                        max_pages=60,
                    )
                title = item["title"]
                # Advisory opinions often have no link text; pull from PDF text
                if (not title or title.lower().endswith(".pdf")) and full_text:
                    title = full_text.splitlines()[0][:200]
                rec = B.Record(
                    id=B.stable_id(SOURCE, item["doc_url"]),
                    source=SOURCE,
                    source_url=page_url,
                    title=f"COIB {kind}: {title}"[:280],
                    decision_date=item["date"],
                    summary=B.truncate(full_text, 500) if full_text else "",
                    full_text=B.truncate(full_text, 8000),
                    doc_url=item["doc_url"],
                    agency="COIB",
                    outcome=kind,
                    scraped_at=B.now_iso(),
                )
                yield rec.to_dict()
                yielded += 1
                if yielded >= max_records:
                    return


if __name__ == "__main__":
    B.write_jsonl(SOURCE, scrape())
