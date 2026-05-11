"""CCRB Civilian Complaints Against Police (Socrata)."""
from __future__ import annotations

import datetime as dt
from typing import Iterator

from . import _base as B

DATASET = "2mby-ccnw"
ENDPOINT = f"https://data.cityofnewyork.us/resource/{DATASET}.json"
SOURCE = "ccrb"


def scrape(days_back: int = 730, page_size: int = 5000, max_records: int = 15000) -> Iterator[dict]:
    cutoff = (dt.date.today() - dt.timedelta(days=days_back)).isoformat()
    offset = 0
    yielded = 0
    seen = set()
    with B.http_client() as client:
        while yielded < max_records:
            params = {
                "$where": f"ccrb_received_date >= '{cutoff}T00:00:00.000'",
                "$order": "ccrb_received_date DESC",
                "$limit": page_size,
                "$offset": offset,
            }
            r = client.get(ENDPOINT, params=params)
            r.raise_for_status()
            rows = r.json()
            if not rows:
                break
            for row in rows:
                cid = row.get("complaint_id") or ""
                if not cid or cid in seen:
                    continue
                seen.add(cid)  # one row per complaint (multiple allegations collapse)
                date = (row.get("ccrb_received_date") or row.get("incident_date") or "")[:10]
                outcome = row.get("ccrb_complaint_disposition") or ""
                reason = row.get("reason_for_police_contact") or ""
                rec = B.Record(
                    id=B.stable_id(SOURCE, cid),
                    source=SOURCE,
                    source_url=f"https://data.cityofnewyork.us/d/{DATASET}/explore?q={cid}",
                    title=f"CCRB complaint #{cid} — {reason or 'civilian complaint'}"[:200],
                    decision_date=date,
                    summary=(row.get("location_type_of_incident") or "")[:200],
                    agency="NYPD",
                    outcome=outcome,
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
