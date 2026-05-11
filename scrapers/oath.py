"""OATH Hearings Division case status (Socrata).

Dataset: https://data.cityofnewyork.us/City-Government/OATH-Hearings-Division-Case-Status/jz4z-kudi

Volume is enormous (millions of summons cases), so we scope v1 to:
  - last 180 days of decisions
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


def _build_address(row: dict) -> tuple[str, str, str]:
    """Return (address_string, bbl, borough)."""
    house = (row.get("violation_location_house") or "").strip()
    street = (row.get("violation_location_street_name") or "").strip()
    city = (row.get("violation_location_city") or "").strip()
    boro = (row.get("violation_location_borough") or "").strip()
    zipc = (row.get("violation_location_zip_code") or "").strip()
    block = (row.get("violation_location_block_no") or "").strip()
    lot = (row.get("violation_location_lot_no") or "").strip()

    # Build a BBL from borough code + block + lot when all three are present
    # and look numeric. We map the borough name to a borough code (1-5).
    BORO_CODE = {
        "MANHATTAN": "1", "BRONX": "2", "BROOKLYN": "3", "QUEENS": "4",
        "STATEN IS": "5", "STATEN ISLAND": "5",
    }
    bbl = ""
    bc = BORO_CODE.get(boro.upper())
    if bc and block.isdigit() and lot.isdigit():
        bbl = f"{bc}{int(block):05d}{int(lot):04d}"

    parts = []
    if house: parts.append(house)
    if street: parts.append(street)
    addr_line = " ".join(parts)
    locality = ", ".join(p for p in (city or boro, zipc) if p)
    if addr_line and locality:
        addr = f"{addr_line}, {locality}"
    else:
        addr = addr_line or locality
    return addr, bbl, boro


def scrape(days_back: int = 180, page_size: int = 5000, max_records: int = 10000) -> Iterator[dict]:
    cutoff = (dt.date.today() - dt.timedelta(days=days_back)).isoformat()
    where = f"decision_date >= '{cutoff}T00:00:00.000'"
    select = (
        "ticket_number, issuing_agency, hearing_date, decision_date, hearing_result, "
        "penalty_imposed, total_violation_amount, violation_details, "
        "violation_location_house, violation_location_street_name, "
        "violation_location_city, violation_location_borough, "
        "violation_location_zip_code, violation_location_block_no, "
        "violation_location_lot_no, "
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
                addr, bbl, borough = _build_address(row)
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
                    address=addr,
                    bbl=bbl,
                    borough=borough,
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
