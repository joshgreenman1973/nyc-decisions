"""NYC Department of Investigation (DOI) Public Reports.

Two-phase enumeration:
  1. Current page: scrape /site/doi/newsroom/public-reports-current.page for any
     PDFs that are linked from there (most recent reports).
  2. Historical: query the Wayback Machine CDX index for all archived URLs
     under /assets/doi/reports/pdf/* — DOI's filing convention is
     YYYY-MM-DD-Title.pdf, which we parse for date and title.

Fetches PDF text from the live URL (rewriting www1.nyc.gov → www.nyc.gov);
falls back silently if the live URL is gone.
"""
from __future__ import annotations

import re
from typing import Iterator

from selectolax.parser import HTMLParser

from . import _base as B

SOURCE = "doi"
INDEX_URL = "https://www.nyc.gov/site/doi/newsroom/public-reports-current.page"
CDX_URL = (
    "https://web.archive.org/cdx/search/cdx"
    "?url=www.nyc.gov/assets/doi/reports/pdf/*"
    "&output=json&fl=original&collapse=urlkey&from=20020101"
)

FILENAME_DATE = re.compile(r"/(\d{4})-(\d{2})-(\d{2})-([^/]+?)\.pdf$", re.IGNORECASE)
PATH_YEAR = re.compile(r"/pdf/(\d{4})/")


def _normalize(url: str) -> str:
    return url.replace("http://", "https://").replace("www1.nyc.gov", "www.nyc.gov")


def _title_from_filename(stem: str) -> str:
    # "Doireport_lcrcprocedures-2" → "Doireport Lcrcprocedures 2"
    s = re.sub(r"[_-]+", " ", stem).strip()
    return s.title()


def _enumerate_current(client) -> list[dict]:
    try:
        r = client.get(INDEX_URL)
        r.raise_for_status()
    except Exception as e:
        print(f"[{SOURCE}] current-page fetch fail: {e}")
        return []
    out = []
    seen = set()
    tree = HTMLParser(r.text)
    for a in tree.css("a"):
        href = (a.attributes.get("href") or "").strip()
        if not href.endswith(".pdf") or "/doi/" not in href:
            continue
        if href.startswith("/"):
            href = "https://www.nyc.gov" + href
        href = _normalize(href)
        if href in seen:
            continue
        seen.add(href)
        title = a.text(strip=True) or ""
        if title.lower() in ("", "read more", "press release", "report"):
            parent = a.parent
            title = (parent.text(strip=True) if parent else "")[:300]
        out.append({"url": href, "title": title})
    return out


def _enumerate_wayback(client) -> list[str]:
    try:
        r = client.get(CDX_URL, timeout=90)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[{SOURCE}] CDX fetch fail: {e}")
        return []
    seen = set()
    for row in data[1:]:
        u = _normalize(row[0])
        if u.lower().endswith(".pdf"):
            seen.add(u)
    return sorted(seen)


def scrape(fetch_text: bool = True, max_records: int = 500) -> Iterator[dict]:
    yielded = 0
    seen = set()
    with B.http_client() as client:
        # 1. Current-page links (with their natural titles)
        for item in _enumerate_current(client):
            seen.add(item["url"])
            yield from _emit(client, item["url"], item["title"], fetch_text)
            yielded += 1
            if yielded >= max_records:
                return

        # 2. Wayback CDX backfill (filename-derived titles)
        for url in _enumerate_wayback(client):
            if url in seen:
                continue
            seen.add(url)
            yield from _emit(client, url, "", fetch_text)
            yielded += 1
            if yielded >= max_records:
                return


def _emit(client, url: str, hint_title: str, fetch_text: bool) -> Iterator[dict]:
    m = FILENAME_DATE.search(url)
    if m:
        date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        if not hint_title:
            hint_title = _title_from_filename(m.group(4))
    else:
        my = PATH_YEAR.search(url)
        date = f"{my.group(1)}-01-01" if my else ""
        if not hint_title:
            hint_title = url.rsplit("/", 1)[-1].replace(".pdf", "")
    full_text = ""
    if fetch_text:
        full_text = B.fetch_pdf_text(
            client, url, cache_key=B.stable_id(SOURCE, url), max_pages=40
        )
    rec = B.Record(
        id=B.stable_id(SOURCE, url),
        source=SOURCE,
        source_url=INDEX_URL,
        title=hint_title[:300],
        decision_date=date,
        summary=B.truncate(full_text, 500) if full_text else "",
        full_text=B.truncate(full_text, 8000),
        doc_url=url,
        agency="DOI",
        scraped_at=B.now_iso(),
    )
    yield rec.to_dict()


if __name__ == "__main__":
    B.write_jsonl(SOURCE, scrape())
