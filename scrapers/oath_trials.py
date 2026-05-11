"""OATH Trials Division — case statuses and dispositions (Socrata).

Dataset: https://data.cityofnewyork.us/City-Government/OATH-Trials-Division-Case-Status/y3hw-z6bm

Distinct from the Hearings Division (summons court) dataset: this covers the
Trials Division, where NYPD disciplinary trials (post-2021), Loft Board,
TLC, DCWP, and other agency adjudications produce written decisions and
agency-head determinations. Much smaller volume (thousands), much more
editorially substantive.
"""
from __future__ import annotations

import datetime as dt
from typing import Iterator

from . import _base as B

DATASET = "y3hw-z6bm"
ENDPOINT = f"https://data.cityofnewyork.us/resource/{DATASET}.json"
SOURCE = "oath-trials"


def scrape(years_back: int = 5, page_size: int = 5000, max_records: int = 20000) -> Iterator[dict]:
    cutoff = (dt.date.today() - dt.timedelta(days=365 * years_back)).isoformat()
    offset = 0
    yielded = 0
    with B.http_client() as client:
        while yielded < max_records:
            params = {
                "$where": f"opened >= '{cutoff}T00:00:00.000'",
                "$order": "opened DESC",
                "$limit": page_size,
                "$offset": offset,
            }
            r = client.get(ENDPOINT, params=params)
            r.raise_for_status()
            rows = r.json()
            if not rows:
                break
            for row in rows:
                case = row.get("case_number") or row.get("filing_agency_case_id") or ""
                if not case:
                    continue
                opened = (row.get("opened") or "")[:10]
                report = (row.get("report_issued") or "")[:10]
                date = report or opened
                title = row.get("name") or f"OATH Trials case {case}"
                category = row.get("category") or ""
                subcat = row.get("subcategory") or ""
                agency = category or "OATH Trials"
                outcome = row.get("agency_head_decision") or row.get("dispo_code") or ""
                summary_parts = [p for p in (subcat, row.get("premises")) if p]
                rec = B.Record(
                    id=B.stable_id(SOURCE, f"{case}:{row.get('filing_agency_case_id','')}"),
                    source=SOURCE,
                    source_url=f"https://data.cityofnewyork.us/d/{DATASET}/explore?q={case}",
                    title=title[:280],
                    decision_date=date,
                    summary=" — ".join(summary_parts)[:300],
                    agency=agency,
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
