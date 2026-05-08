"""CCRB officer penalty recommendations (Socrata).

Dataset: https://data.cityofnewyork.us/Public-Safety/Civilian-Complaint-Review-Board-Penalties/keep-pkmh

Records the CCRB's recommended discipline for substantiated allegations,
plus the board's ultimate disposition. Joins to CCRB complaints by
complaint_id when both are present.
"""
from __future__ import annotations

from typing import Iterator

from . import _base as B

DATASET = "keep-pkmh"
ENDPOINT = f"https://data.cityofnewyork.us/resource/{DATASET}.json"
SOURCE = "ccrb-penalties"


def scrape(page_size: int = 5000, max_records: int = 20000) -> Iterator[dict]:
    offset = 0
    yielded = 0
    seen = set()
    with B.http_client() as client:
        while yielded < max_records:
            params = {
                "$order": "as_of_date DESC",
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
                tax = row.get("tax_id") or ""
                if not cid:
                    continue
                key = f"{cid}:{tax}"
                if key in seen:
                    continue
                seen.add(key)
                date = (row.get("as_of_date") or "")[:10]
                ccrb_dispo = row.get("ccrb_substantiated_officer_disposition") or ""
                board_rec = row.get("board_discipline_recommendation") or ""
                outcome = board_rec or ccrb_dispo
                rec = B.Record(
                    id=B.stable_id(SOURCE, key),
                    source=SOURCE,
                    source_url="https://www.nyc.gov/site/ccrb/index.page",
                    title=f"CCRB penalty recommendation — complaint #{cid}, officer tax #{tax}",
                    decision_date=date,
                    summary=f"CCRB: {ccrb_dispo}" + (f" / Board: {board_rec}" if board_rec and board_rec != ccrb_dispo else ""),
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
