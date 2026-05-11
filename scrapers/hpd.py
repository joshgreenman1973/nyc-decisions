"""HPD Housing Maintenance Code Violations — Class C (immediately hazardous).

Dataset: https://data.cityofnewyork.us/Housing-Development/Housing-Maintenance-Code-Violations/wvxf-dwi5

Volume: 10.9M total violations. We scope to:
  - Class C only (immediately hazardous: lead, no heat, no hot water,
    inadequate heat in winter, vermin, broken boilers, etc.)
  - Last 90 days
  - Currently open or recently resolved
"""
from __future__ import annotations

import datetime as dt
from typing import Iterator

from . import _base as B

DATASET = "wvxf-dwi5"
ENDPOINT = f"https://data.cityofnewyork.us/resource/{DATASET}.json"
SOURCE = "hpd-violations"


def scrape(days_back: int = 90, page_size: int = 5000, max_records: int = 15000) -> Iterator[dict]:
    cutoff = (dt.date.today() - dt.timedelta(days=days_back)).isoformat()
    where = f"class = 'C' AND novissueddate >= '{cutoff}T00:00:00.000'"
    offset = 0
    yielded = 0
    with B.http_client() as client:
        while yielded < max_records:
            params = {
                "$where": where,
                "$order": "novissueddate DESC",
                "$limit": page_size,
                "$offset": offset,
            }
            r = client.get(ENDPOINT, params=params)
            r.raise_for_status()
            rows = r.json()
            if not rows:
                break
            for row in rows:
                vid = row.get("violationid") or ""
                if not vid:
                    continue
                date = (row.get("novissueddate") or "")[:10]
                house = row.get("housenumber") or ""
                street = row.get("streetname") or ""
                apt = row.get("apartment") or ""
                addr = f"{house} {street}".strip()
                if apt:
                    addr += f", Apt {apt}"
                if row.get("boro"):
                    addr += f", {row['boro']}"
                desc = (row.get("novdescription") or "")[:400]
                status = row.get("violationstatus") or row.get("currentstatus") or ""
                bbl = f"{row.get('boroid','')}{(row.get('block') or '').zfill(5)}{(row.get('lot') or '').zfill(4)}"
                rec = B.Record(
                    id=B.stable_id(SOURCE, vid),
                    source=SOURCE,
                    source_url=f"https://hpdonline.nyc.gov/hpdonline/?bbl={bbl}",
                    title=f"HPD Class C violation — {addr}"[:280],
                    decision_date=date,
                    summary=desc,
                    agency="HPD",
                    respondent=addr,
                    outcome=status or "Open",
                    address=addr,
                    bbl=bbl if len(bbl) == 10 and bbl.isdigit() else "",
                    borough=row.get("boro") or "",
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
