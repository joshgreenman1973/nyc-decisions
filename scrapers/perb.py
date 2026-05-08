"""NYS Public Employment Relations Board (PERB) Decisions.

Dataset: https://data.ny.gov/resource/vmn3-7znf.json (data.ny.gov, not city)

PERB resolves labor disputes for NY public employees including NYC public-
sector unions. Records start at 1974.
"""
from __future__ import annotations

from typing import Iterator

from . import _base as B

DATASET = "vmn3-7znf"
ENDPOINT = f"https://data.ny.gov/resource/{DATASET}.json"
SOURCE = "perb"


def scrape(page_size: int = 1000, max_records: int = 1000) -> Iterator[dict]:
    offset = 0
    yielded = 0
    with B.http_client() as client:
        while yielded < max_records:
            params = {
                "$order": "date DESC",
                "$limit": page_size,
                "$offset": offset,
            }
            r = client.get(ENDPOINT, params=params)
            r.raise_for_status()
            rows = r.json()
            if not rows:
                break
            for row in rows:
                title = row.get("title") or ""
                date = (row.get("date") or "")[:10]
                link = (row.get("link_to_board_decisions") or {}).get("url") or ""
                if not title:
                    continue
                rec = B.Record(
                    id=B.stable_id(SOURCE, f"{title}:{date}"),
                    source=SOURCE,
                    source_url="https://perb.ny.gov/board-decisions",
                    title=title[:280],
                    decision_date=date,
                    summary="",
                    doc_url=link,
                    agency="NY Public Employment Relations Board",
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
