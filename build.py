"""Top-level build script.

Usage:
  python build.py            # scrape all sources, build index + feeds
  python build.py --sources oath,doi
  python build.py --skip-scrape    # rebuild index/feeds from existing JSONL
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

from scrapers import _base as B

# (module name, source key, display label, default cap)
SOURCES = [
    ("scrapers.oath_trials", "oath-trials", "OATH Trials (incl. NYPD discipline)", {}),
    ("scrapers.oath", "oath-hearings", "OATH Hearings (summons)", {}),
    ("scrapers.ccrb", "ccrb", "CCRB Complaints", {}),
    ("scrapers.ccrb_penalties", "ccrb-penalties", "CCRB Penalty Recommendations", {}),
    ("scrapers.coib", "coib", "COIB Ethics", {}),
    ("scrapers.cchr", "cchr", "Commission on Human Rights", {}),
    ("scrapers.tlc", "tlc", "TLC Chairperson Review", {}),
    ("scrapers.dcwp", "dcwp", "DCWP Final Decisions", {}),
    ("scrapers.perb", "perb", "PERB Labor Decisions", {}),
    ("scrapers.doi", "doi", "DOI Reports", {}),
    ("scrapers.comptroller", "nyc-comptroller", "NYC Comptroller", {}),
    ("scrapers.public_advocate", "public-advocate", "Public Advocate", {}),
]

ROOT = Path(__file__).resolve().parent
SITE_DIR = ROOT / "site"
INDEX_DIR = SITE_DIR / "index"
FEED_DIR = SITE_DIR / "feeds"


def run_scrapers(only: set[str] | None) -> None:
    for module_name, key, label, kwargs in SOURCES:
        if only and key not in only:
            continue
        print(f"\n=== {label} ({key}) ===")
        try:
            mod = importlib.import_module(module_name)
            B.write_jsonl(key, mod.scrape(**kwargs))
        except Exception as e:
            print(f"  ! {key} failed: {e}")


def load_all_records() -> list[dict]:
    records = []
    for _, key, _, _ in SOURCES:
        f = B.NORMALIZED_DIR / f"{key}.jsonl"
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    return records


def build_index(records: list[dict]) -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    # Dedupe by id (later record wins)
    by_id = {}
    for r in records:
        rid = r.get("id")
        if rid:
            by_id[rid] = r
    records = list(by_id.values())
    # Slim each record for the in-browser index (full_text gets truncated more
    # aggressively; raw PDF stays in JSONL for download).
    docs = []
    for r in records:
        docs.append({
            "id": r.get("id"),
            "source": r.get("source", ""),
            "source_url": r.get("source_url", ""),
            "title": r.get("title", "")[:400],
            "agency": r.get("agency", ""),
            "respondent": r.get("respondent", ""),
            "judge": r.get("judge", ""),
            "outcome": r.get("outcome", ""),
            "penalty": r.get("penalty", ""),
            "decision_date": r.get("decision_date", ""),
            "summary": r.get("summary", "")[:600],
            "full_text": r.get("full_text", "")[:3000],
            "doc_url": r.get("doc_url", ""),
        })
    out = INDEX_DIR / "documents.json"
    out.write_text(json.dumps(docs, ensure_ascii=False))
    print(f"[index] wrote {len(docs)} docs -> {out.relative_to(ROOT)}")

    # Meta
    by_source: dict[str, int] = {}
    by_agency: dict[str, int] = {}
    for r in records:
        by_source[r.get("source", "")] = by_source.get(r.get("source", ""), 0) + 1
        agency = r.get("agency", "")
        if agency:
            by_agency[agency] = by_agency.get(agency, 0) + 1
    meta = {
        "total": len(records),
        "updated_at": B.now_iso(),
        "sources": [
            {"key": key, "label": label, "count": by_source.get(key, 0)}
            for _, key, label, _ in SOURCES
        ],
        "top_agencies": sorted(by_agency.items(), key=lambda kv: -kv[1])[:30],
    }
    (INDEX_DIR / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"[index] meta total={meta['total']}")


def build_feeds(records: list[dict]) -> None:
    from feedgen.feed import FeedGenerator
    FEED_DIR.mkdir(parents=True, exist_ok=True)

    def _rss(records, title, key):
        fg = FeedGenerator()
        fg.id(f"https://nyc-decisions.example/feeds/{key}.xml")
        fg.title(title)
        fg.link(href=f"https://nyc-decisions.example/feeds/{key}.xml", rel="self")
        fg.description(f"NYC Decisions feed: {title}")
        fg.language("en")
        # newest first, cap to 50
        recs_sorted = sorted(
            (r for r in records if r.get("decision_date") and r.get("title") and r.get("id")),
            key=lambda r: r["decision_date"], reverse=True,
        )[:50]
        for r in recs_sorted:
            fe = fg.add_entry()
            fe.id(r["id"])
            fe.title(r["title"][:200])
            fe.link(href=r.get("doc_url") or r.get("source_url") or f"https://joshgreenman1973.github.io/nyc-decisions/?q={r['id']}")
            desc = r.get("summary") or r.get("full_text", "")[:500]
            if r.get("outcome"): desc = f"Outcome: {r['outcome']}\n\n" + desc
            fe.description(desc)
            try:
                fe.pubDate(f"{r['decision_date']}T12:00:00Z")
            except Exception:
                pass
        out = FEED_DIR / f"{key}.xml"
        fg.rss_file(str(out))
        print(f"[feed] {key}.xml ({len(recs_sorted)} items)")

    _rss(records, "NYC Decisions — All Sources", "all")
    for _, key, label, _ in SOURCES:
        subset = [r for r in records if r.get("source") == key]
        if subset:
            _rss(subset, f"NYC Decisions — {label}", key)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sources", help="comma-separated source keys to run")
    p.add_argument("--skip-scrape", action="store_true", help="only rebuild index + feeds")
    args = p.parse_args()

    only = set(args.sources.split(",")) if args.sources else None
    if not args.skip_scrape:
        run_scrapers(only)

    records = load_all_records()
    if only:
        records = [r for r in records if r.get("source") in only or r.get("source") not in only]
        # Actually: we want ALL records in the index even if we only re-scraped some.
    build_index(records)
    build_feeds(records)


if __name__ == "__main__":
    main()
