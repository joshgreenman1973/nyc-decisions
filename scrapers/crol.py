"""City Record Online (CROL) — official daily journal of NYC government.

Dataset: https://data.cityofnewyork.us/City-Government/City-Record-Online/dg92-zbpx
Volume: 1.08M records total. We filter aggressively:
  - Skip "Changes in Personnel" (948K poll-worker / hire-fire notices)
  - Last 365 days only
  - Substantive sections: procurement, hearings, agency rules, court
    notices, property disposition, special materials.
"""
from __future__ import annotations

import datetime as dt
import html
import re
from typing import Iterator

from . import _base as B

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean(s: str) -> str:
    if not s:
        return ""
    # Drop HTML tags, decode entities, collapse whitespace.
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", s))).strip()

DATASET = "dg92-zbpx"
ENDPOINT = f"https://data.cityofnewyork.us/resource/{DATASET}.json"
SOURCE = "crol"

KEEP_SECTIONS = (
    "Procurement",
    "Contract Award Hearings",
    "Public Hearings and Meetings",
    "Special Materials",
    "Agency Rules",
    "Public Comment on Contract Awards",
    "Property Disposition",
    "Court Notices",
)


def scrape(days_back: int = 365, page_size: int = 5000, max_records: int = 15000) -> Iterator[dict]:
    cutoff = (dt.date.today() - dt.timedelta(days=days_back)).isoformat()
    sections_clause = ", ".join(f"'{s}'" for s in KEEP_SECTIONS)
    where = (
        f"start_date >= '{cutoff}T00:00:00.000' "
        f"AND section_name IN ({sections_clause})"
    )
    offset = 0
    yielded = 0
    seen = set()
    with B.http_client() as client:
        while yielded < max_records:
            params = {
                "$where": where,
                "$order": "start_date DESC",
                "$limit": page_size,
                "$offset": offset,
            }
            r = client.get(ENDPOINT, params=params)
            r.raise_for_status()
            rows = r.json()
            if not rows:
                break
            for row in rows:
                rid = row.get("request_id") or ""
                if not rid or rid in seen:
                    continue
                seen.add(rid)
                section = row.get("section_name") or ""
                short = (row.get("short_title") or "").strip()
                agency = row.get("agency_name") or ""
                date = (row.get("start_date") or "")[:10]
                desc_parts = [_clean(row.get(k, "")) for k in (
                    "additional_description_1",
                    "additional_description_2",
                    "additional_description_3",
                ) if row.get(k)]
                summary_text = " ".join(p for p in desc_parts if p)
                title = f"{section}: {short}" if short else section
                if agency:
                    title = f"{agency} — {title}"
                detail_url = f"https://a856-cityrecord.nyc.gov/RequestDetail/{rid}"
                # Address: CROL records sometimes include building_name + street.
                addr_parts = [p for p in (
                    row.get("building_name") or "",
                    row.get("street_address_1") or "",
                    row.get("street_address_2") or "",
                ) if p]
                addr_line = ", ".join(addr_parts)
                locality = ", ".join(p for p in (
                    row.get("city") or "",
                    row.get("state") or "",
                    row.get("zip_code") or "",
                ) if p)
                addr = (f"{addr_line}, {locality}" if addr_line and locality else (addr_line or locality)).strip(", ")
                rec = B.Record(
                    id=B.stable_id(SOURCE, rid),
                    source=SOURCE,
                    source_url=detail_url,
                    title=title[:280],
                    decision_date=date,
                    summary=summary_text[:600],
                    full_text=summary_text[:8000],
                    doc_url=detail_url,
                    agency=agency,
                    outcome=section,
                    address=addr,
                    scraped_at=B.now_iso(),
                )
                yield rec.to_dict()
                yielded += 1
                if yielded >= max_records:
                    return
            offset += page_size
            print(f"[{SOURCE}] fetched {yielded} so far…")


if __name__ == "__main__":
    B.write_jsonl(SOURCE, scrape())
