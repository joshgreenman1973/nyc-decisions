"""OATH Hearings Division case status (Socrata).

Dataset: https://data.cityofnewyork.us/City-Government/OATH-Hearings-Division-Case-Status/jz4z-kudi

Volume is enormous (millions of summons cases), so we scope v1 to:
  - last 365 days of decisions
  - cases where penalty_imposed > 0 OR hearing_result indicates a substantive outcome
"""
from __future__ import annotations

import datetime as dt
from typing import Iterator

from . import _base as B

DATASET = "jz4z-kudi"
ENDPOINT = f"https://data.cityofnewyork.us/resource/{DATASET}.json"
SOURCE = "oath-hearings"
SOURCE_LABEL = "OATH Hearings"


def _build_title(row: dict) -> str:
    agency = row.get("issuing_agency", "")
    ticket = row.get("ticket_number", "")
    descs = [
        row.get(f"charge_{i}_code_description", "").strip()
        for i in (1, 2, 3, 4)
        if row.get(f"charge_{i}_code_description")
    ]
    descs = [d for d in descs if d and d.lower() != "see attached nov"]
    charge = "; ".join(dict.fromkeys(descs))[:160] if descs else ""
    if charge:
        return f"{agency} v. {ticket}: {charge}"
    return f"{agency} hearing — ticket {ticket}"


def scrape(days_back: int = 180, page_size: int = 5000, max_records: int = 10000) -> Iterator[dict]:
    cutoff = (dt.date.today() - dt.timedelta(days=days_back)).isoformat()
    where = f"decision_date >= '{cutoff}T00:00:00.000'"
    select = (
        "ticket_number, issuing_agency, hearing_date, decision_date, hearing_result, "
        "penalty_imposed, total_violation_amount, violation_details, "
        "violation_location_borough, violation_location_zip_code, "
        "respondent_last_name, "
        "charge_1_code_description, charge_2_code_description, "
        "charge_3_code_description, charge_4_code_description"
    )
    offset = 0
    yielded = 0
    with B.http_client() as client:
        while yielded < max_records:
            params = {
                "$select": select,
                "$where": where,
                "$order": "decision_date DESC",
                "$limit": page_size,
                "$offset": offset,
            }
            r = client.get(ENDPOINT, params=params)
            r.raise_for_status()
            rows = r.json()
            if not rows:
                break
            for row in rows:
                ticket = row.get("ticket_number") or ""
                result = row.get("hearing_result") or ""
                agency = row.get("issuing_agency") or ""
                if not ticket or not agency or not result:
                    continue
                # Skip purely procedural/scheduling outcomes
                if any(s in result.lower() for s in ("adjourn", "scheduled", "rescheduled")):
                    continue
                date = (row.get("decision_date") or "")[:10]
                # OATH data contains bogus dates like 8999-... and 9997-...
                if not date or date < "2000-01-01" or date > "2030-12-31":
                    continue
                respondent = (row.get("respondent_last_name") or "").strip()
                penalty = row.get("penalty_imposed") or ""
                rec = B.Record(
                    id=B.stable_id(SOURCE, ticket),
                    source=SOURCE,
                    source_url=f"https://a836-citypay.nyc.gov/citypay/ecb?summonsNumber={ticket}",
                    title=_build_title(row),
                    decision_date=date,
                    summary=(row.get("violation_details") or "")[:500],
                    agency=row.get("issuing_agency", ""),
                    respondent=respondent,
                    outcome=row.get("hearing_result", ""),
                    penalty=f"${penalty}" if penalty and penalty != "0" else "",
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
