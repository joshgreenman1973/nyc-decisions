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

# (module name, source key, display label, coverage description, scraper kwargs)
SOURCES = [
    ("scrapers.oath_trials", "oath-trials", "OATH Trials (incl. NYPD discipline)", "Last 5 years (capped 20,000)", {}),
    ("scrapers.oath", "oath-hearings", "OATH Hearings (summons)", "Last 180 days (capped 10,000)", {}),
    ("scrapers.ccrb", "ccrb", "CCRB Complaints", "Last 2 years (capped 15,000)", {}),
    ("scrapers.ccrb_penalties", "ccrb-penalties", "CCRB Penalty Recommendations", "All available (capped 20,000)", {}),
    ("scrapers.coib", "coib", "COIB Ethics", "All published PDFs", {}),
    ("scrapers.cchr", "cchr", "Commission on Human Rights", "All decisions, 2015–present", {}),
    ("scrapers.tlc", "tlc", "TLC Chairperson Review", "All currently linked PDFs", {}),
    ("scrapers.dcwp", "dcwp", "DCWP Final Decisions", "All currently linked PDFs", {}),
    ("scrapers.perb", "perb", "PERB Labor Decisions", "All, 1974–present", {}),
    ("scrapers.crol", "crol", "City Record Online", "Last 365 days, substantive notices only (capped 15,000)", {}),
    ("scrapers.hpd", "hpd-violations", "HPD Class C Violations", "Last 90 days (capped 15,000); live lookup by address covers all classes", {}),
    ("scrapers.doh", "doh", "DOH Official Notices", "All currently linked PDFs", {}),
    ("scrapers.claims", "claims", "Claims Against NYC", "Last 5 years (capped 25,000)", {}),
    ("scrapers.council_legislation", "council-legislation", "City Council Legislation", "All bills + local laws since 1998", {}),
    ("scrapers.rezoning", "rezoning", "Rezoning Tracker", "All projects", {}),
    ("scrapers.dohmh_indoor", "dohmh-indoor", "DOHMH Indoor Complaints", "Last 5 years (capped 20,000)", {}),
    ("scrapers.dcwp_complaints", "dcwp-complaints", "DCWP Consumer Complaints", "Last 5 years (capped 25,000)", {}),
    ("scrapers.doi", "doi", "DOI Reports", "All reports, 2002–present (via Wayback CDX)", {}),
    ("scrapers.comptroller", "nyc-comptroller", "NYC Comptroller", "Most recent 500 reports", {}),
    ("scrapers.public_advocate", "public-advocate", "Public Advocate", "Full corpus from advocate.nyc.gov/reports", {}),
]

ROOT = Path(__file__).resolve().parent
SITE_DIR = ROOT / "site"
INDEX_DIR = SITE_DIR / "index"
FEED_DIR = SITE_DIR / "feeds"


def run_scrapers(only: set[str] | None) -> None:
    for module_name, key, label, _coverage, kwargs in SOURCES:
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
    for _, key, _, _, _ in SOURCES:
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
    """Build per-source shards and a small meta.json. The frontend lazy-loads
    each shard on demand instead of pulling the whole 32 MB blob upfront."""
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    SHARD_DIR = INDEX_DIR / "sources"
    SHARD_DIR.mkdir(parents=True, exist_ok=True)

    # Clamp impossible future dates. Source datasets — especially OATH —
    # occasionally have typo'd dates like 2030-08-20 or 2099-12-31. A
    # decision/complaint cannot legitimately be dated more than today + a
    # small grace window for clock skew.
    import datetime as _dt
    _max_date = (_dt.date.today() + _dt.timedelta(days=14)).isoformat()
    dropped_future = 0
    for r in records:
        d = r.get("decision_date") or ""
        if d and d > _max_date:
            r["decision_date"] = ""
            dropped_future += 1
    if dropped_future:
        print(f"[index] cleared {dropped_future} impossible future dates")

    # Dedupe by id
    by_id = {}
    for r in records:
        rid = r.get("id")
        if rid:
            by_id[rid] = r
    records = list(by_id.values())

    def _slim(r: dict) -> dict:
        return {
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
        }

    # Group by source, write one shard per source
    by_source_recs: dict[str, list[dict]] = {}
    by_source_count: dict[str, int] = {}
    by_agency: dict[str, int] = {}
    for r in records:
        s = r.get("source", "")
        by_source_recs.setdefault(s, []).append(_slim(r))
        by_source_count[s] = by_source_count.get(s, 0) + 1
        agency = r.get("agency", "")
        if agency:
            by_agency[agency] = by_agency.get(agency, 0) + 1

    shard_sizes = {}
    for src_key, docs in by_source_recs.items():
        if not src_key:
            continue
        # Sort newest-first so default-no-query results show recent records
        docs.sort(key=lambda d: d.get("decision_date", ""), reverse=True)
        out = SHARD_DIR / f"{src_key}.json"
        out.write_text(json.dumps(docs, ensure_ascii=False))
        shard_sizes[src_key] = out.stat().st_size
        print(f"[index] {src_key}: {len(docs)} docs ({shard_sizes[src_key] // 1024} KB)")

    # Remove old monolithic file if it exists from prior builds
    legacy = INDEX_DIR / "documents.json"
    if legacy.exists():
        legacy.unlink()

    meta = {
        "total": len(records),
        "updated_at": B.now_iso(),
        "sources": [
            {
                "key": key,
                "label": label,
                "count": by_source_count.get(key, 0),
                "shard_bytes": shard_sizes.get(key, 0),
                "coverage": coverage,
            }
            for _, key, label, coverage, _ in SOURCES
            if by_source_count.get(key, 0) > 0
        ],
        "top_agencies": sorted(by_agency.items(), key=lambda kv: -kv[1])[:30],
    }
    (INDEX_DIR / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"[index] meta total={meta['total']}, shards={len(meta['sources'])}")

    # Highlights: top N newest per source, merged + sorted, for the initial
    # landing-page view. Lets the page show real records before any shard
    # downloads.
    HIGHLIGHTS_PER_SOURCE = 10
    highlights = []
    for src_key, docs in by_source_recs.items():
        # docs are already sorted newest-first
        highlights.extend(docs[:HIGHLIGHTS_PER_SOURCE])
    highlights.sort(key=lambda d: d.get("decision_date", ""), reverse=True)
    (INDEX_DIR / "highlights.json").write_text(
        json.dumps(highlights, ensure_ascii=False)
    )
    print(f"[index] highlights: {len(highlights)} records")

    # Address index: BBL -> [{id, source}]. Lets the frontend resolve an
    # autocompleted address to every record at that property across sources.
    address_index: dict[str, list[dict]] = {}
    for r in records:
        bbl = (r.get("bbl") or "").strip()
        if not bbl or len(bbl) != 10 or not bbl.isdigit():
            continue
        address_index.setdefault(bbl, []).append({
            "id": r["id"],
            "source": r.get("source", ""),
        })
    (INDEX_DIR / "address-index.json").write_text(
        json.dumps(address_index, ensure_ascii=False)
    )
    print(f"[index] address index: {len(address_index)} BBLs covering "
          f"{sum(len(v) for v in address_index.values())} records")


def build_feeds(records: list[dict]) -> None:
    from feedgen.feed import FeedGenerator
    import re as _re
    FEED_DIR.mkdir(parents=True, exist_ok=True)

    # XML 1.0 forbids most control chars; strip them from any string we feed
    # to feedgen.
    _BAD_CTRL = _re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
    def _xml_safe(s: str) -> str:
        return _BAD_CTRL.sub(" ", s or "")

    def _rss(records, title, key):
        fg = FeedGenerator()
        fg.id(f"https://joshgreenman1973.github.io/nyc-decisions/feeds/{key}.xml")
        fg.title(title)
        fg.link(href=f"https://joshgreenman1973.github.io/nyc-decisions/feeds/{key}.xml", rel="self")
        fg.description(f"The Rest of the Record feed: {title}")
        fg.language("en")
        # newest first, cap to 50
        recs_sorted = sorted(
            (r for r in records if r.get("decision_date") and r.get("title") and r.get("id")),
            key=lambda r: r["decision_date"], reverse=True,
        )[:50]
        for r in recs_sorted:
            fe = fg.add_entry()
            fe.id(_xml_safe(r["id"]))
            fe.title(_xml_safe(r["title"])[:200])
            fe.link(href=r.get("doc_url") or r.get("source_url") or f"https://joshgreenman1973.github.io/nyc-decisions/?q={r['id']}")
            desc = r.get("summary") or r.get("full_text", "")[:500]
            if r.get("outcome"): desc = f"Outcome: {r['outcome']}\n\n" + desc
            fe.description(_xml_safe(desc))
            try:
                fe.pubDate(f"{r['decision_date']}T12:00:00Z")
            except Exception:
                pass
        out = FEED_DIR / f"{key}.xml"
        fg.rss_file(str(out))
        print(f"[feed] {key}.xml ({len(recs_sorted)} items)")

    _rss(records, "The Rest of the Record — All Sources", "all")
    for _, key, label, _, _ in SOURCES:
        subset = [r for r in records if r.get("source") == key]
        if subset:
            _rss(subset, f"The Rest of the Record — {label}", key)


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
