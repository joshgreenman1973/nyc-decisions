"""DCWP Consumer Complaints.

Dataset: https://data.cityofnewyork.us/Business/DCWP-Consumer-Complaints/nre2-6m2s

Complaints filed against NYC businesses with the Department of Consumer
and Worker Protection. 66,802 records — names the business, the complaint
type, and how it resolved.
"""
from __future__ import annotations

import datetime as dt
from typing import Iterator

from . import _base as B

DATASET = "nre2-6m2s"
ENDPOINT = f"https://data.cityofnewyork.us/resource/{DATASET}.json"
SOURCE = "dcwp-complaints"


def scrape(years_back: int = 5, page_size: int = 5000, max_records: int = 25000) -> Iterator[dict]:
    cutoff = (dt.date.today() - dt.timedelta(days=365 * years_back)).isoformat()
    where = f"intake_date >= '{cutoff}T00:00:00.000'"
    offset = 0
    yielded = 0
    with B.http_client() as client:
        while yielded < max_records:
            params = {
                "$where": where,
                "$order": "intake_date DESC",
                "$limit": page_size,
                "$offset": offset,
            }
            r = client.get(ENDPOINT, params=params)
            r.raise_for_status()
            rows = r.json()
            if not rows:
                break
            for row in rows:
                rid = row.get("record_id") or ""
                if not rid:
                    continue
                date = (row.get("intake_date") or "")[:10]
                business = row.get("business_name") or "Unknown business"
                bcat = row.get("business_category") or ""
                code = row.get("complaint_code") or ""
                result = row.get("result") or ""
                addr_parts = [p for p in (
                    row.get("building_nbr"), row.get("street1"),
                ) if p]
                addr = " ".join(addr_parts)
                if row.get("borough"):
                    addr += f", {row['borough']}"
                if row.get("postcode"):
                    addr += f" {row['postcode']}"
                rec = B.Record(
                    id=B.stable_id(SOURCE, rid),
                    source=SOURCE,
                    source_url=f"https://data.cityofnewyork.us/d/{DATASET}/explore?q={rid}",
                    title=f"DCWP complaint vs. {business}: {code}"[:280],
                    decision_date=date,
                    summary=" / ".join(p for p in (bcat, addr) if p)[:300],
                    agency="DCWP",
                    respondent=business,
                    outcome=result,
                    address=addr,
                    bbl=(row.get("bbl") or "") if (row.get("bbl") or "").isdigit() else "",
                    borough=row.get("borough") or "",
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
