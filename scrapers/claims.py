"""NYC Claims Report — Settlements and Claims Filed.

Dataset: https://data.cityofnewyork.us/City-Government/Claims-Report-Underlying-Settlements-and-Claims-Filed-Data/ex6k-ym48

Every claim filed against the City — slip-and-fall, civil rights,
malpractice, false arrest, vehicle damage, you name it — with the
disposition (settled / dismissed / pending) and the dollar amount paid out.

Volume: 256,923 records. We pull recent years for the index.
"""
from __future__ import annotations

import datetime as dt
from typing import Iterator

from . import _base as B

DATASET = "ex6k-ym48"
ENDPOINT = f"https://data.cityofnewyork.us/resource/{DATASET}.json"
SOURCE = "claims"


def scrape(years_back: int = 5, page_size: int = 5000, max_records: int = 25000) -> Iterator[dict]:
    cutoff = (dt.date.today() - dt.timedelta(days=365 * years_back)).isoformat()
    where = f"filed_date >= '{cutoff}T00:00:00.000'"
    offset = 0
    yielded = 0
    with B.http_client() as client:
        while yielded < max_records:
            params = {
                "$where": where,
                "$order": "filed_date DESC",
                "$limit": page_size,
                "$offset": offset,
            }
            r = client.get(ENDPOINT, params=params)
            r.raise_for_status()
            rows = r.json()
            if not rows:
                break
            for row in rows:
                claim = row.get("claim") or ""
                if not claim:
                    continue
                filed = (row.get("filed_date") or "")[:10]
                occ = (row.get("occurrence_date") or "")[:10]
                disp = (row.get("disposition_date") or "")[:10]
                date = disp or filed or occ
                amount = row.get("disposition_amount") or ""
                ctype = row.get("claim_type") or ""
                action = row.get("claim_action") or ""
                agency = row.get("agency") or ""
                borough = row.get("borough") or ""
                summary_parts = [p for p in (
                    f"Filed: {filed}" if filed else "",
                    f"Occurred: {occ}" if occ else "",
                    f"Borough: {borough}" if borough else "",
                    f"Disposition: {action}" if action else "",
                ) if p]
                penalty = ""
                try:
                    if amount and float(amount) > 0:
                        penalty = f"${float(amount):,.0f}"
                except Exception:
                    pass
                rec = B.Record(
                    id=B.stable_id(SOURCE, f"{claim}:{filed}"),
                    source=SOURCE,
                    source_url=f"https://data.cityofnewyork.us/resource/{DATASET}.json?claim={claim}",
                    title=f"Claim against {agency}: {ctype}"[:280] if agency else f"Claim {claim}: {ctype}"[:280],
                    decision_date=date,
                    summary=" — ".join(summary_parts)[:500],
                    agency=agency,
                    outcome=action,
                    penalty=penalty,
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
