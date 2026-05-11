"""DOHMH Indoor Environmental Complaints.

Dataset: https://data.cityofnewyork.us/Health/DOHMH-Indoor-Environmental-Complaints/9jgj-bmct

Public complaints handled by DOHMH about indoor air quality, asbestos,
mold, lead, and other environmental hazards inside buildings.
108,134 records.
"""
from __future__ import annotations

import datetime as dt
from typing import Iterator

from . import _base as B

DATASET = "9jgj-bmct"
ENDPOINT = f"https://data.cityofnewyork.us/resource/{DATASET}.json"
SOURCE = "dohmh-indoor"


def scrape(years_back: int = 5, page_size: int = 5000, max_records: int = 20000) -> Iterator[dict]:
    cutoff = (dt.date.today() - dt.timedelta(days=365 * years_back)).isoformat()
    where = f"date_received >= '{cutoff}T00:00:00.000' AND deleted = 'No'"
    offset = 0
    yielded = 0
    with B.http_client() as client:
        while yielded < max_records:
            params = {
                "$where": where,
                "$order": "date_received DESC",
                "$limit": page_size,
                "$offset": offset,
            }
            r = client.get(ENDPOINT, params=params)
            r.raise_for_status()
            rows = r.json()
            if not rows:
                break
            for row in rows:
                cid = row.get("complaint_number") or ""
                if not cid:
                    continue
                date = (row.get("date_received") or "")[:10]
                ctype = row.get("complaint_type_311") or ""
                desc = row.get("descriptor_1_311") or ""
                zipc = row.get("incident_address_3") or ""
                boro = row.get("incident_address_4") or ""
                status = row.get("complaint_status") or ""
                addr = ", ".join(p for p in (boro, zipc) if p)
                rec = B.Record(
                    id=B.stable_id(SOURCE, cid),
                    source=SOURCE,
                    source_url=f"https://data.cityofnewyork.us/d/{DATASET}/explore?q={cid}",
                    title=f"DOHMH indoor complaint #{cid}: {ctype}"[:280],
                    decision_date=date,
                    summary=" / ".join(p for p in (desc, addr) if p)[:300],
                    agency="NYC Department of Health",
                    respondent=addr,
                    outcome=status,
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
