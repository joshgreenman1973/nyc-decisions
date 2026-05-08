# NYC Decisions

A search index for New York City quasi-judicial decisions, oversight reports, and administrative rulings.

Aggregates public records from sources that are public but hard to track: OATH hearings, CCRB complaints, COIB ethics dispositions, DOI reports, NYC Comptroller audits, the Public Advocate's office, and (coming soon) more.

## What's here

- **`scrapers/`** — one Python module per source. Each exposes `scrape()` yielding normalized record dicts.
- **`build.py`** — runs scrapers, dedupes, builds the in-browser MiniSearch index, generates RSS feeds.
- **`site/`** — static site (HTML/CSS/JS, no framework). Hosted on GitHub Pages.
- **`data/normalized/`** — JSONL of every record we've scraped (committed; small enough). Raw PDFs in `data/cache/` and `data/raw/` are gitignored.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python build.py                  # scrape all + rebuild index/feeds
python build.py --skip-scrape    # just rebuild from existing JSONL
python build.py --sources oath,doi   # scrape only specific sources

python3 -m http.server --directory site 8847
open http://localhost:8847
```

## Sources currently indexed

| Source | Volume cap | Method |
|---|---|---|
| OATH Hearings | 10,000 records / 180 days | Socrata API |
| CCRB Complaints | 15,000 records / 730 days | Socrata API |
| COIB enforcement + advisory | All public PDFs | HTML scrape + PDF text |
| DOI Reports | All on current page | HTML scrape + PDF text |
| NYC Comptroller | Most recent ~50 reports | HTML scrape + PDF text |
| Public Advocate | All on reports page | HTML scrape + PDF text |

See [methodology page](site/methodology.html) for details and known gaps.

## Roadmap

- v1.1: NYC Commission on Human Rights (OCR), NYPD Trials, Health Department, City Council testimony (via citymeetings.nyc)
- v1.2: Saved-search email alerts (Postmark/Resend free tier)
- v2: Full-text PDF for OATH Trials Division written decisions
- Later: NY State court coverage (out of scope unless someone wants to fund it)

## Contributing

Adding a new source is a single Python file in `scrapers/` plus an entry in `build.py`'s `SOURCES` list. See `scrapers/doi.py` for a simple HTML-scrape example.
