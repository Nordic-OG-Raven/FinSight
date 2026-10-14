# FinSight — SEC XBRL Financial Data Pipeline

An ETL pipeline that ingests SEC 10-K filings, extracts and normalizes their XBRL
financial facts, validates them, and loads them into a PostgreSQL star schema for
analysis. A REST API serves the result.

> **What this is (and isn't).** v1.0 does one thing well: it turns a **US-GAAP 10-K** into
> a clean, queryable, validated set of annual financials. The broader ambition — IFRS/20-F
> parity, a large curated dataset, rigorous (non-heuristic) accounting validation, and a
> hosted demo — is real but not done; it lives in [`ROADMAP.md`](ROADMAP.md). This README
> describes **what actually works today**, verified end-to-end. Built primarily with
> AI-assisted development; the architecture, limitations, and trade-offs below are ones I can
> walk through.

---

## ✅ What works today (v1.0)

- **Ingest any US-GAAP 10-K on demand** from SEC EDGAR by ticker/year.
- **Extract annual XBRL facts** via Arelle (inline-XBRL supported), filtered to the filing's
  real reporting periods (~1,300–6,500 facts per 10-K after dropping interim/historical
  note-disclosure contexts).
- **Normalize** ~thousands of raw concepts → a shared label vocabulary, classify each fact to
  a statement (income / balance sheet / cash flow / comprehensive income), and load into a
  PostgreSQL **star schema** with provenance.
- **Validate on load** with hard integrity gates — the reported balance-sheet identity
  (Total assets = Total liabilities & equity, pinned to the fiscal-year-end) and unit-scaling
  sanity — plus softer reconciliation checks surfaced as warnings (see *Known limitations*).
- **Serve it** over a Flask REST API, and reconstruct the three primary statements for a UI.
- **One-command run:** `./run_pipeline.sh AVGO 2024 10-K` → extract → load → API → statement
  checks, ending in a clean pass.

### Reference dataset (loaded & verified)

Six US-GAAP companies load cleanly with correct latest-fiscal-year headline figures:
**AVGO, NVDA, AAPL, MSFT, GOOGL, AMZN**. Any other US-GAAP 10-K can be ingested on demand
with the same command.

## 🏗️ Architecture

```
SEC EDGAR → XBRL Parser → Normalizer → Validator → PostgreSQL star schema → REST API
  (Arelle)    (custom)      (custom)    (custom)      (SQLAlchemy)          (Flask)
```

**Pipeline stages**

1. **Ingestion** — download the filing's inline-XBRL instance + schema from SEC EDGAR.
2. **Parsing** — extract facts via Arelle; keep only real annual-report periods.
3. **Normalization** — map concepts to a shared label vocabulary; classify statement type;
   standardize units.
4. **Validation** — hard balance-sheet-identity + unit-scaling gates at load; reconciliation
   heuristics as warnings.
5. **Storage** — load into a 30+ table star schema (dimensions, facts, relationships) with
   provenance.
6. **Serving** — Flask REST API; statement-view reconstruction for a frontend.

## 🛠️ Tech stack

Python 3.11 · [Arelle](https://arelle.org/) (XBRL) · PostgreSQL · SQLAlchemy · Flask ·
Docker. A Next.js frontend exists (`Website/portfolio/app/finsight`) but expects a deployed
backend and isn't part of local testing.

## 📦 Run it locally

```bash
# 1. Docker Desktop running, with a Postgres container named `superset_db`
#    (DB `finsight`, user/pass superset/superset — see .env / .env.template).
docker ps | grep superset_db

# 2. Python env (if not already present)
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 3. Run the pipeline for one company (extract → load → API → statement checks)
./run_pipeline.sh AAPL 2024 10-K
```

Notes:
- The first run for a new US-GAAP taxonomy year downloads that taxonomy (~5–10 min, then
  cached). Subsequent runs are fast.
- The `--year` argument selects the latest 10-K at or before that year; filenames use the
  argument, while the data inside reflects the filing's actual fiscal years.
- For local data exploration, query Postgres directly or use `./start_viewer.sh` (Streamlit).

## 🤝 API endpoints

```
GET  /health
GET  /api/companies                 # loaded companies
GET  /api/analyze/{ticker}/{year}   # normalized facts for a loaded filing
GET  /api/statements/{ticker}/{year}# reconstructed income / balance / cash-flow statements
```

## ⚠️ Known limitations (honest list)

- **US-GAAP only in practice.** IFRS / 20-F filers (e.g. Novo Nordisk, Sanofi) are not
  verified to load cleanly and are excluded from the reference dataset. See roadmap.
- **Validation is partly heuristic.** The balance-sheet identity (reported totals) and
  unit-scaling checks are rigorous and hard-fail. The income-statement-math,
  cash-flow-reconciliation, and cross-company normalization-conflict checks key on specific
  normalized labels and produce false positives across filers, so they are **surfaced as
  warnings, not errors**. "Validated" today means "integrity-gated," not "fully audited."
- **Normalized-label vocabulary has inconsistencies** (e.g. the "Total liabilities & equity"
  line appears under more than one label across filers). Being consolidated on the roadmap.
- **Period assignment has a known bug.** Current-year headline figures are reliable, but some
  comparative-year / cross-filer facts can be linked to an incorrect fiscal period (a shared
  `period_id` across filers with different fiscal calendars). Multi-year/comparative queries
  may therefore show misassigned values. Prioritized on the roadmap.
- **Statement reconstruction depends on the presentation linkbase**, which inline-XBRL
  filings often omit; missing totals (e.g. beginning-of-year cash, total L&E) are derived
  with targeted calculations rather than read directly.
- **Not hosted.** Runs locally via Docker only; there is no live demo URL at this time.

## 📊 Database schema

A 30+ table star schema (dimension, fact, and relationship tables). See
[`docs/DATABASE.md`](docs/DATABASE.md) and [`docs/ERD.md`](docs/ERD.md).

## 🙏 Credits

Arelle (David vun Kannon & contributors) · US-GAAP Taxonomy (FASB) · IFRS Taxonomy (IFRS
Foundation) · SEC EDGAR (U.S. SEC).

## 📧 Contact

**Jonas Haahr** · [Portfolio](https://jonashaahr.com)

---

*Part of my data-engineering portfolio. See [`ROADMAP.md`](ROADMAP.md) for where this is
headed.*
