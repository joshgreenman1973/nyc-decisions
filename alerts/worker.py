"""Saved-search email alerts (skeleton — not yet wired into CI).

Reads alerts/subscriptions.json (list of {email, query, source?}), runs each
query against the freshly built MiniSearch documents, diffs against the prior
day's matches, and emails the new hits to the subscriber.

Sending is deferred to v1.2. For now this just prints what it would send.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "site" / "index" / "documents.json"
SUBS = ROOT / "alerts" / "subscriptions.json"
LAST = ROOT / "alerts" / "last-seen.json"


def matches(doc: dict, query: str) -> bool:
    """Naive AND-of-terms substring match (placeholder until we adopt
    MiniSearch in Python or shell out to Node)."""
    blob = " ".join(str(doc.get(k, "")) for k in (
        "title", "summary", "full_text", "agency", "respondent", "outcome"
    )).lower()
    terms = [t for t in re.split(r"\s+", query.strip().lower()) if t]
    return all(t in blob for t in terms)


def main() -> None:
    if not INDEX.exists():
        print("No index built yet")
        return
    if not SUBS.exists():
        print("No subscriptions yet")
        return
    docs = json.loads(INDEX.read_text())
    subs = json.loads(SUBS.read_text())
    last = json.loads(LAST.read_text()) if LAST.exists() else {}

    sent = {}
    for sub in subs:
        key = f"{sub['email']}::{sub['query']}::{sub.get('source','')}"
        prev_ids = set(last.get(key, []))
        hits = [d for d in docs if matches(d, sub["query"])
                and (not sub.get("source") or d["source"] == sub["source"])]
        new = [h for h in hits if h["id"] not in prev_ids]
        if new:
            print(f"\nWould email {sub['email']} ({len(new)} new for query '{sub['query']}'):")
            for h in new[:10]:
                print(f"  - [{h['source']}] {h['title'][:120]}  {h.get('decision_date','')}")
        sent[key] = [h["id"] for h in hits]

    LAST.write_text(json.dumps(sent, indent=2))


if __name__ == "__main__":
    main()
