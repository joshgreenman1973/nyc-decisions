"""NYC City Council Legislation — Bills and Local Laws.

Dataset: https://data.cityofnewyork.us/City-Government/City-Council-Legislation-Bills-and-Local-Laws/6ctv-n46c

Every bill introduced in the City Council, with title, summary, status,
sponsor, committee, intro date, and law number (if enacted). 11,622 records.
"""
from __future__ import annotations

from typing import Iterator

from . import _base as B

DATASET = "6ctv-n46c"
ENDPOINT = f"https://data.cityofnewyork.us/resource/{DATASET}.json"
SOURCE = "council-legislation"


def scrape(page_size: int = 5000, max_records: int = 12000) -> Iterator[dict]:
    offset = 0
    yielded = 0
    with B.http_client() as client:
        while yielded < max_records:
            params = {
                "$order": "intro_date DESC",
                "$limit": page_size,
                "$offset": offset,
            }
            r = client.get(ENDPOINT, params=params)
            r.raise_for_status()
            rows = r.json()
            if not rows:
                break
            for row in rows:
                mid = row.get("matter_id") or ""
                file_num = row.get("file_num") or ""
                if not mid:
                    continue
                date = (row.get("intro_date") or row.get("modified_date") or "")[:10]
                title = row.get("name") or row.get("title") or ""
                summary = row.get("summary") or ""
                law_no = row.get("law_number") or ""
                sponsor = row.get("primary_sponsor") or ""
                committee = row.get("committee") or ""
                status = row.get("status") or ""
                outcome = f"Local Law {law_no}" if law_no else status
                # Build a portal URL for the matter
                portal = f"https://legistar.council.nyc.gov/LegislationDetail.aspx?ID={mid}"
                rec = B.Record(
                    id=B.stable_id(SOURCE, mid),
                    source=SOURCE,
                    source_url=portal,
                    title=f"{file_num}: {title}"[:280] if file_num else title[:280],
                    decision_date=date,
                    summary=summary[:600],
                    full_text=summary[:8000],
                    agency="NYC City Council",
                    respondent=sponsor,
                    judge=committee,
                    outcome=outcome,
                    doc_url=portal,
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
