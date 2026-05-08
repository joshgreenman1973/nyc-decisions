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
from typing import Iterator

from . import _base as B

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
                desc_parts = [p for p in (
                    row.get("additional_description_1"),
                    row.get("additional_description_2"),
                    row.get("additional_description_3"),
                ) if p]
                summary = " ".join(desc_parts)[:600]
                title = f"{section}: {short}" if short else section
                if agency:
                    title = f"{agency} — {title}"
                rec = B.Record(
                    id=B.stable_id(SOURCE, rid),
                    source=SOURCE,
                    source_url="https://a856-cityrecord.nyc.gov/",
                    title=title[:280],
                    decision_date=date,
                    summary=summary,
                    agency=agency,
                    outcome=section,
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
