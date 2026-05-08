"""NYC Commission on Human Rights — Decisions and Orders.

Index page: /site/cchr/enforcement/decisions-and-orders.page
Year pages: /site/cchr/enforcement/decisions-and-orders-YYYY.page

Each year page lists PDFs of full-text decisions. Title is the link text;
date is parsed from the PDF body when possible (fallback: year-of-folder).
PDFs have an embedded text layer — pypdf works without OCR.
"""
from __future__ import annotations

import re
from typing import Iterator

from selectolax.parser import HTMLParser

from . import _base as B

SOURCE = "cchr"
INDEX_URL = "https://www.nyc.gov/site/cchr/enforcement/decisions-and-orders.page"
YEAR_RE = re.compile(r"decisions-and-orders-(\d{4})\.page")
DATE_IN_TEXT_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})"
)
MONTHS = {m: i for i, m in enumerate(
    ["January","February","March","April","May","June","July","August",
     "September","October","November","December"], start=1)}


def _date_from_text(text: str) -> str:
    if not text:
        return ""
    m = DATE_IN_TEXT_RE.search(text)
    if not m:
        return ""
    return f"{m.group(3)}-{MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"


def _enumerate_years(client) -> list[int]:
    r = client.get(INDEX_URL)
    r.raise_for_status()
    tree = HTMLParser(r.text)
    years = set()
    for a in tree.css("a"):
        h = a.attributes.get("href") or ""
        m = YEAR_RE.search(h)
        if m:
            years.add(int(m.group(1)))
    return sorted(years)


def _enumerate_pdfs(client, year: int) -> list[dict]:
    url = f"https://www.nyc.gov/site/cchr/enforcement/decisions-and-orders-{year}.page"
    try:
        r = client.get(url)
        r.raise_for_status()
    except Exception as e:
        print(f"[{SOURCE}] year {year} fetch fail: {e}")
        return []
    tree = HTMLParser(r.text)
    out = []
    seen = set()
    for a in tree.css("a"):
        href = (a.attributes.get("href") or "").strip()
        if not href.lower().endswith(".pdf"):
            continue
        if href.startswith("/"):
            href = "https://www.nyc.gov" + href
        if href in seen:
            continue
        seen.add(href)
        title = a.text(strip=True) or ""
        if not title or len(title) < 4:
            # Fall back to filename
            title = href.rsplit("/", 1)[-1].replace(".pdf", "").replace("-", " ").replace("_", " ")
        out.append({"url": href, "title": title, "year": year, "page_url": url})
    return out


def scrape(fetch_text: bool = True, max_records: int = 200) -> Iterator[dict]:
    yielded = 0
    with B.http_client() as client:
        years = _enumerate_years(client)
        print(f"[{SOURCE}] year pages: {years}")
        for year in years:
            for item in _enumerate_pdfs(client, year):
                full_text = ""
                date = ""
                if fetch_text:
                    full_text = B.fetch_pdf_text(
                        client, item["url"],
                        cache_key=B.stable_id(SOURCE, item["url"]),
                        max_pages=40,
                    )
                    date = _date_from_text(full_text)
                if not date:
                    date = f"{item['year']}-01-01"
                rec = B.Record(
                    id=B.stable_id(SOURCE, item["url"]),
                    source=SOURCE,
                    source_url=item["page_url"],
                    title=item["title"][:280],
                    decision_date=date,
                    summary=B.truncate(full_text, 500) if full_text else "",
                    full_text=B.truncate(full_text, 8000),
                    doc_url=item["url"],
                    agency="NYC Commission on Human Rights",
                    scraped_at=B.now_iso(),
                )
                yield rec.to_dict()
                yielded += 1
                if yielded >= max_records:
                    return


if __name__ == "__main__":
    B.write_jsonl(SOURCE, scrape())
