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
- **Serve it** over a Flask REST API, warehouse-direct.

### Reference dataset (loaded & verified)

Eight filers across sectors and taxonomies load cleanly and pass the validation gates:
**AAPL, AVGO, AMZN, GOOGL, MSFT, NVDA** (US-GAAP tech/consumer), **JPM** (US-GAAP bank), and
**NVO** (IFRS, 20-F, DKK). Any other SEC filer can be ingested on demand with the same command.

## 🏗️ Architecture

```
SEC EDGAR → edgartools → FactExtractor adapter → slim loader → PostgreSQL star schema → REST API
            (extraction)   (our seam)             (+ validation gate)        (SQLAlchemy)   (Flask)
```

Extraction runs on [edgartools](https://github.com/dgunning/edgartools) (pinned) behind our own
`FactExtractor` adapter, so the warehouse never depends on the library's internals and the
extraction layer stays swappable. Rationale and the decision record are in
[`docs/REARCHITECTURE.md`](docs/REARCHITECTURE.md).

**Pipeline stages**

1. **Extraction** — `EdgarToolsExtractor` reads the latest annual filing's XBRL into a uniform
   `ExtractionResult` (facts with raw concepts, periods, units, dimensions).
2. **Validation** — hard integrity gates + soft warnings; produces the per-filing quality report.
3. **Load** — slim upsert into the star schema (idempotent; no gap-fill or statement
   reconstruction — edgartools hands over clean, correctly-periodized facts).
4. **Serving** — Flask REST API over the warehouse.

## 🛠️ Tech stack

Python 3.11 · [edgartools](https://github.com/dgunning/edgartools) (SEC XBRL extraction) ·
PostgreSQL · SQLAlchemy · Flask · Docker. A Next.js frontend exists
(`Website/portfolio/app/finsight`) but expects a deployed backend and isn't part of local
testing. *(The earlier Arelle-based custom parser was retired in the 2026-10 re-architecture;
see `docs/REARCHITECTURE.md`.)*

## 📦 Run it locally

```bash
# 1. Docker Desktop running, with a Postgres container named `superset_db`
#    (DB `finsight`, user/pass superset/superset — see .env / .env.template).
docker ps | grep superset_db

# 2. Python env (if not already present)
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 3. Extract + validate + load — pick any entrypoint (all run the edgartools path)
./run_pipeline.sh AVGO                                 # one filer, then start API + smoke-test
.venv/bin/python src/main.py --ticker NVO --filing-type 20-F   # single filer, CLI
.venv/bin/python database/load_from_edgartools.py              # the full reference set (batch)
```

Each filer prints a `GATE`/`QUAL` line and writes a quality report to `data/quality_reports/`.
The loader is idempotent — re-running reuses existing filing rows rather than duplicating.
`--year` is accepted for backward compatibility but ignored; the edgartools path always loads
the latest annual filing.

## 🤝 API endpoints

```
GET  /health
GET  /api/companies                  # loaded companies
GET  /api/financials/{ticker}        # multi-year statements + segment revenue, warehouse-direct
```

Additional endpoints exist (`/api/analyze/{ticker}/{year}`, `/api/statements/{ticker}/{year}`,
and the NP2SQL `/api/query`); `/api/financials/{ticker}` is the one wired directly to the
re-architected warehouse and the one the dashboard consumes.

## ⚠️ Known limitations (honest list)

- **Normalized-label vocabulary isn't consolidated yet.** Labels are currently ≈1:1 with raw
  XBRL concepts (snake-case fallback), so cross-company lines don't fully reconcile (e.g.
  "Total liabilities & equity" appears under several labels). A tested canonical mapping is the
  top roadmap item — until then, per-company figures are reliable but cross-company
  line-by-line comparison needs care.
- **Validation is integrity-gated, not fully audited.** The balance-sheet identity and
  unit/scale checks hard-fail; income-math and EPS are warnings. Explicit duplicate detection,
  cross-statement reconciliation, and outlier/anomaly flagging are on the roadmap. "Validated"
  means integrity-gated + quality-scored, not audited.
- **Currency is detected, not converted.** Facts keep their native currency (USD/DKK/EUR);
  normalization to a single reporting currency isn't done.
- **Not hosted.** Runs locally via Docker only; no live demo URL at this time.
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
