# FinSight — SEC XBRL Financial Data Pipeline

An ETL pipeline that ingests SEC annual filings, extracts and normalizes their XBRL
financial facts, validates them, and loads them into a PostgreSQL star schema for analysis.
A REST API serves the result.

> **What this is (and isn't).** The quantitative core does one thing well: it turns a public
> company's annual filing (domestic **10-K** or foreign **20-F/40-F**) into a clean, queryable,
> validated set of annual financials — for **every SEC filer**, including banks and IFRS
> filers. The broader ambition — a consolidated cross-company label vocabulary, audit-grade
> (non-heuristic) validation, LLM-based ESG/qualitative extraction, analytics, and a hosted
> demo — is real but not done; it lives in [`ROADMAP.md`](ROADMAP.md). This README describes
> **what actually works today**, verified end-to-end. Built primarily with AI-assisted
> development; the architecture, limitations, and trade-offs below are ones I can walk through.

---

## ✅ What works today

- **Ingest any SEC annual filing on demand** by ticker — domestic 10-K and foreign-filer
  20-F/40-F — straight from SEC EDGAR (no API key, no paid service).
- **Extract the full filing XBRL** — ~1,000–8,000 facts per filing, with **dimensions**
  (business/geographic segments, product lines) and correct period attribution.
- **Works for every filer, including the hard cases.** US-GAAP, **IFRS** (Novo Nordisk, in
  DKK), and **banks** (JPMorgan) all load cleanly — the cases that defeated the earlier custom
  pipeline.
- **Correct, collision-free periods.** Periods are keyed by exact dates, so filers with
  different fiscal calendars can't collide and prior-year comparatives are retained.
- **Validate on load** ([`src/validation/quality.py`](src/validation/quality.py)): the reported
  balance-sheet identity (`Assets = Liabilities + Equity`, pinned to the fiscal-year-end) and
  unit/scale sanity are **hard gates** that block a bad load; income-statement math and diluted
  EPS are **warnings**. Each filing gets a **data-quality report** (completeness / accuracy /
  consistency / provenance → weighted score) in `data/quality_reports/`.
- **Normalize currency to USD.** Foreign-currency facts (e.g. Novo Nordisk in DKK) are
  converted to USD at each fact's period date using ECB reference rates, stored in `value_usd`
  alongside the untouched native `value_numeric`. Rates are cached in `database/fx_rates.json`
  (reproducible, offline after first fetch, no API key).
- **Ratios & peer comparison.** Margins, ROE/ROA, leverage, current ratio, asset turnover,
  effective tax rate, free cash flow, and revenue growth, derived from the canonical labels in
  USD — so companies compare across currencies. Served per-company and as a revenue-sorted
  peer table.
- **Serve it** over a Flask REST API, warehouse-direct.
- **Hosted live.** The API runs on Fly.io backed by a managed Neon Postgres warehouse (the
  8-filer reference set is loaded there); a live demo URL is up. Scale-to-zero, so the first
  request after an idle period cold-starts (a few seconds).
- **Medallion warehouse (dbt).** The warehouse is an explicit **bronze → silver → gold** pipeline
  on Neon, with [dbt](https://www.getdbt.com) owning the silver/gold transforms (see [`dbt/`](dbt/)
  and the Medallion section of [`ROADMAP.md`](ROADMAP.md)). It adds **quarterly (10-Q)** ingestion
  and fixes a real fiscal-year mis-attribution the naive
  path had.
- **Quarterly earnings forecasting.** Next-quarter revenue / EPS forecast from the gold quarterly
  series, backtested and benchmarked against analyst consensus (Yahoo Finance) — write-up in
  [`docs/forecasting/EARNINGS_FORECAST.md`](docs/forecasting/EARNINGS_FORECAST.md).

### Reference dataset (loaded & verified)

Eight filers across sectors and taxonomies load cleanly and pass the validation gates:
**AAPL, AVGO, AMZN, GOOGL, MSFT, NVDA** (US-GAAP tech/consumer), **JPM** (US-GAAP bank), and
**NVO** (IFRS, 20-F, DKK). Any other SEC filer can be ingested on demand with the same command.

## 🏗️ Architecture

A **medallion warehouse** (bronze → silver → gold) on Neon Postgres, with **dbt** owning the
silver/gold transforms. (This replaced the earlier single-layer star schema in the 2026-10
cutover — see the Medallion section of [`ROADMAP.md`](ROADMAP.md).)

```
SEC EDGAR ─┐  (Python extractor, edgartools adapter)
           ├─► bronze.raw_facts / raw_filings    (10-K + 10-Q, raw as-ingested)
yfinance ──┘  bronze.corporate_actions           (stock splits)
                      │  dbt
                      ├─► silver  (views): conform — USD, canonical labels, dedup, fiscal-year derivation
                      └─► gold:
                            • views  (serving):   v_facts_consolidated, v_facts_hierarchical, companies,
                            │                      company_financials, ratios, peers   ← the REST API
                            • tables (forecasting): company_quarterly, earnings         ← the ML models
```

Extraction runs on [edgartools](https://github.com/dgunning/edgartools) (pinned) behind our own
`FactExtractor` adapter, so the warehouse never depends on the library's internals. Rationale and
the decision record are in [`docs/REARCHITECTURE.md`](docs/REARCHITECTURE.md).

**Pipeline stages**

1. **Bronze (land)** — `src/ingestion/bronze.py` + `corporate_actions.py` land raw edgartools facts
   (annual + quarterly) and yfinance splits, idempotent per accession.
2. **Silver (conform, dbt)** — USD normalization, canonical labels (priority-resolved so lines
   reconcile 1:1), cross-filing dedup, reliable fiscal-year derivation, validation tests.
3. **Gold (serve, dbt)** — serving views the API reads + quarterly/earnings marts the forecasting
   models read.
4. **Serving** — Flask REST API over gold; forecasting over `gold.earnings`.

## 🛠️ Tech stack

Python 3.12 · [edgartools](https://github.com/dgunning/edgartools) (SEC XBRL extraction) ·
[dbt](https://www.getdbt.com) (silver/gold transforms) · PostgreSQL
([Neon](https://neon.tech)) · SQLAlchemy · Flask · deployed on [Fly.io](https://fly.io) ·
scikit-learn + yfinance (forecasting). A Next.js frontend (`Website/portfolio/app/finsight`)
consumes the API (point it at the backend via `NEXT_PUBLIC_FINSIGHT_API`). *(The earlier
Arelle-based parser and the single-layer star schema were both retired; see
`docs/REARCHITECTURE.md` and the Medallion section of `ROADMAP.md`.)*

## 📦 Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# DATABASE_URL (Neon) in .env — the pipeline writes to the DIRECT endpoint, dbt reads it too.

# 1. Bronze: land raw facts (10-K + 10-Q) + splits
.venv/bin/python -m src.ingestion.bronze                 # all reference filers (annual + 8 quarters)
.venv/bin/python -m src.ingestion.corporate_actions      # stock splits

# 2. Silver + gold: build + test the medallion transforms
./dbt/run_dbt.sh build                                   # dbt run + dbt test

# 3. Serve / analyze
.venv/bin/python api/main.py                             # Flask API over gold
.venv/bin/python scripts/forecast_report.py              # earnings forecast write-up
```

Bronze landing is idempotent per accession (re-running replaces a filing's facts in place, or
skip already-landed filings with `--only-new`). `dbt build` runs the models + data tests (incl.
the balance-sheet-identity and canonical-reconciliation checks).

## 🤝 API endpoints

Live base URL: `https://finsight-api-verdant-log-1735.fly.dev` (scale-to-zero; first hit cold-starts).

```
GET  /health
GET  /api/companies                  # loaded companies + quota / storage status
GET  /api/financials/{ticker}        # multi-year statements + segment revenue, warehouse-direct
GET  /api/statements/{ticker}/{year} # full ordered, labelled, level-nested statements rendered
                                     #   from edgartools' presentation structure (dashboard view)
GET  /api/ratios/{ticker}            # multi-year ratios (margins, ROE/ROA, leverage, FCF, growth), USD
GET  /api/peers                      # latest-year cross-company comparison, revenue-sorted, USD
GET  /api/analyze/{ticker}/{year}    # per-company fact metrics for a given year
GET  /api/quota                      # monthly on-demand-ingest quota + storage headroom
POST /api/query                      # natural-language → SQL (NP2SQL), read-only
POST /api/metrics  ·  POST /api/data # data-warehouse explorer (available metrics + fact rows)
POST /api/analyze/custom             # on-demand ingest of a non-preloaded ticker (quota-limited)
```

`/api/financials/{ticker}` is the canonical, warehouse-direct endpoint; `/api/statements`
renders the same facts as presentation-ordered statements for the dashboard's statement view
(restored post-re-architecture off edgartools' presentation tree — see commit history). The only
retired endpoint is **`/api/populate-statements`** (HTTP 410): it depended on the
statement-reconstruction sub-tables that the re-architecture removed; statements now come
straight from the warehouse.

## ⚠️ Known limitations (honest list)

- **Normalized-label vocabulary isn't consolidated yet.** Labels are currently ≈1:1 with raw
  XBRL concepts (snake-case fallback), so cross-company lines don't fully reconcile (e.g.
  "Total liabilities & equity" appears under several labels). A tested canonical mapping is the
  top roadmap item — until then, per-company figures are reliable but cross-company
  line-by-line comparison needs care.
- **Validation = hard gates + warnings, not a signed audit.** The balance-sheet identity and
  unit/scale checks hard-fail; income math, EPS, cross-statement cash-flow reconciliation
  (op + inv + fin ± FX = net change in cash), duplicate/conflict detection, and
  sign/ratio/scale anomaly flagging all run as warnings feeding a per-filing quality score.
  Comprehensive for the primary statements, but not a line-by-line audit of every disclosure.
- **FX rates are fiscal-period-dated spot rates**, not the period-average rates a filer uses
  for its own income-statement translation — so `value_usd` is a consistent cross-company
  approximation, not a restatement of the filing. Native `value_numeric` is always preserved.
- **Hosted, but on a free tier.** The live API (Fly.io) + warehouse (Neon) run scale-to-zero,
  so the first request after idle cold-starts a few seconds, and the auto-generated `*.fly.dev`
  host isn't yet behind a custom domain. Local Docker + Postgres remains a fully supported way to
  run the whole pipeline offline.
- **Pure-ESMA EU filers are out of scope** (no SEC filing); EU companies on US exchanges work
  via their 20-F.
- **Qualitative/ESG and analytics are future phases** — LLM-based ESG/narrative extraction
  (Phase 2) and visualization templates / ML analytics (Phase 3) are not built; see
  [`ROADMAP.md`](ROADMAP.md).

## 📊 Database schema

A 30+ table star schema (dimension, fact, and relationship tables). See
[`docs/DATABASE.md`](docs/DATABASE.md) and [`docs/ERD.md`](docs/ERD.md).

## 🙏 Credits

[edgartools](https://github.com/dgunning/edgartools) (Dwight Gunning & contributors) · US-GAAP
Taxonomy (FASB) · IFRS Taxonomy (IFRS Foundation) · SEC EDGAR (U.S. SEC).

## 📧 Contact

**Jonas Haahr** · [Portfolio](https://jonashaahr.com)

---

*Part of my data-engineering portfolio. See [`ROADMAP.md`](ROADMAP.md) for where this is
headed.*
