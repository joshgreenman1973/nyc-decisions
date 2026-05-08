"""NYC Rezoning Tracker.

Dataset: https://data.cityofnewyork.us/City-Government/NYC-Rezoning-Tracker/fd95-5ihz

Every rezoning project tracked by City Planning, with a `narrative` field
describing the project. 1,963 records.
"""
from __future__ import annotations

from typing import Iterator

from . import _base as B

DATASET = "fd95-5ihz"
ENDPOINT = f"https://data.cityofnewyork.us/resource/{DATASET}.json"
SOURCE = "rezoning"


def scrape(page_size: int = 5000, max_records: int = 5000) -> Iterator[dict]:
    offset = 0
    yielded = 0
    seen = set()
    with B.http_client() as client:
        while yielded < max_records:
            params = {"$limit": page_size, "$offset": offset}
            r = client.get(ENDPOINT, params=params)
            r.raise_for_status()
            rows = r.json()
            if not rows:
                break
            for row in rows:
                area = row.get("rezoning_area") or ""
                title = row.get("commitment_title") or ""
                year = row.get("year") or ""
                key = f"{area}:{title}:{year}"
                if not area or key in seen:
                    continue
                seen.add(key)
                date = f"{year}-01-01" if year and year.isdigit() else ""
                narrative = row.get("narrative") or ""
                statement = row.get("statement_from_source_document_poa") or ""
                summary = (narrative or statement or "")[:600]
                full_text = "\n\n".join([p for p in (narrative, statement) if p])[:8000]
                rec = B.Record(
                    id=B.stable_id(SOURCE, key),
                    source=SOURCE,
                    source_url="https://www.nyc.gov/site/planning/index.page",
                    title=f"{area}: {title}"[:280] if title else area[:280],
                    decision_date=date,
                    summary=summary,
                    full_text=full_text,
                    agency=row.get("lead_agency") or "City Planning",
                    outcome=row.get("commitment_stage") or "",
                    scraped_at=B.now_iso(),
                )
                yield rec.to_dict()
                yielded += 1
                if yielded >= max_records:
                    return
            offset += page_size


if __name__ == "__main__":
    B.write_jsonl(SOURCE, scrape())
