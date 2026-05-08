"""NYC Comptroller — Audits and reports.

Enumerates via the WordPress sitemap (`wp-sitemap-posts-report-N.xml`), which
lists every report URL. For each, fetches the report page, extracts title +
publication date + linked PDF, and pulls PDF text.

Capped at the 500 most recent reports to keep build time reasonable.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterator
from xml.etree import ElementTree as ET

from selectolax.parser import HTMLParser

from . import _base as B

SOURCE = "nyc-comptroller"
SITEMAP_URLS = [
    "https://comptroller.nyc.gov/wp-sitemap-posts-report-1.xml",
    "https://comptroller.nyc.gov/wp-sitemap-posts-report-2.xml",
]


def _enumerate(client) -> list[tuple[str, str]]:
    out = []
    for sm in SITEMAP_URLS:
        try:
            r = client.get(sm)
            r.raise_for_status()
        except Exception as e:
            print(f"[{SOURCE}] sitemap fail {sm}: {e}")
            continue
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        try:
            root = ET.fromstring(r.text)
        except ET.ParseError as e:
            print(f"[{SOURCE}] parse fail {sm}: {e}")
            continue
        for url_el in root.findall("sm:url", ns):
            loc = (url_el.findtext("sm:loc", default="", namespaces=ns) or "").strip()
            lastmod = (url_el.findtext("sm:lastmod", default="", namespaces=ns) or "").strip()
            if loc:
                out.append((loc, lastmod))
    # Newest first by lastmod
    out.sort(key=lambda t: t[1], reverse=True)
    return out


DATE_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),\s+(\d{4})"
)
MONTHS = {m: i for i, m in enumerate(
    ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], start=1)}


def _scrape_detail(client, url: str) -> dict:
    """Fetch a single report page and return {title, date, doc_url, full_text}."""
    try:
        r = client.get(url)
        r.raise_for_status()
    except Exception as e:
        return {"error": str(e)}
    tree = HTMLParser(r.text)

    # Title: prefer h1, fallback to og:title
    title = ""
    h1 = tree.css_first("h1")
    if h1:
        title = h1.text(strip=True)
    if not title:
        og = tree.css_first('meta[property="og:title"]')
        if og:
            title = og.attributes.get("content", "")

    # Date: look for visible "Month DD, YYYY" anywhere on the page
    date = ""
    body = tree.body.text(strip=True) if tree.body else ""
    m = DATE_RE.search(body)
    if m:
        try:
            date = f"{m.group(3)}-{MONTHS[m.group(1)[:3]]:02d}-{int(m.group(2)):02d}"
        except Exception:
            pass

    # PDF: first .pdf link inside the report page
    doc_url = ""
    pdfa = tree.css_first("a[href$='.pdf']")
    if pdfa:
        doc_url = pdfa.attributes.get("href", "") or ""
        if doc_url.startswith("/"):
            doc_url = "https://comptroller.nyc.gov" + doc_url

    return {"title": title, "date": date, "doc_url": doc_url}


def scrape(max_records: int = 500, fetch_text: bool = True) -> Iterator[dict]:
    yielded = 0
    with B.http_client() as client:
        urls = _enumerate(client)
        print(f"[{SOURCE}] sitemap lists {len(urls)} reports; processing up to {max_records}")
        for loc, lastmod in urls[:max_records]:
            info = _scrape_detail(client, loc)
            if info.get("error"):
                continue
            full_text = ""
            if fetch_text and info.get("doc_url"):
                full_text = B.fetch_pdf_text(
                    client, info["doc_url"],
                    cache_key=B.stable_id(SOURCE, info["doc_url"]),
                    max_pages=20,
                )
            date = info.get("date") or lastmod[:10]
            rec = B.Record(
                id=B.stable_id(SOURCE, loc),
                source=SOURCE,
                source_url=loc,
                title=(info.get("title") or loc.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title())[:300],
                decision_date=date,
                summary=B.truncate(full_text, 500),
                full_text=B.truncate(full_text, 8000),
                doc_url=info.get("doc_url") or loc,
                agency="NYC Comptroller",
                scraped_at=B.now_iso(),
            )
            yield rec.to_dict()
            yielded += 1
            if yielded % 50 == 0:
                print(f"[{SOURCE}] {yielded} reports processed…")


if __name__ == "__main__":
    B.write_jsonl(SOURCE, scrape())
