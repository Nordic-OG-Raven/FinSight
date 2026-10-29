# FinSight — Roadmap

Single honest status list for the whole PRD (`prd.md`), not just the quantitative MVP.
Grouped by the PRD's own phase structure (§1) and roughly ordered within each group by the
leverage it adds. Status: ✅ done · ◐ partial · ☐ not started.

The 2026-10 re-architecture (SEC/XBRL extraction flipped to **edgartools** behind an adapter
seam — see [`docs/REARCHITECTURE.md`](docs/REARCHITECTURE.md)) resolved several items that the
old custom-Arelle pipeline could not, and added the post-load validation layer. Those are
marked below so this file reflects what is actually true today.

---

## Medallion warehouse (bronze / silver / gold on dbt + Neon)

The warehouse is organized as an explicit medallion, with **dbt** owning the SQL transforms on
**Neon** Postgres (project `muddy-truth-56443165`). Lives in [`dbt/`](dbt/); run via
`dbt/run_dbt.sh` (parses the Neon DIRECT endpoint from `.env`).

- ✅ **Bronze — raw landing.** `src/ingestion/bronze.py` lands XBRL facts exactly as edgartools
  yields them (`bronze.raw_facts` / `bronze.raw_filings`) for annual **10-K/20-F** and quarterly
  **10-Q** filings, idempotent per accession; `src/ingestion/corporate_actions.py` lands stock
  splits (`bronze.corporate_actions`, yfinance).
- ✅ **Silver — conform/clean.** dbt views (`stg_facts`, `fct_financial_facts`): type-cast, USD
  normalization (ECB `fx_rates` seed), canonical labels (`canonical_labels` seed, priority-
  resolved so a line reconciles 1:1 — dbt-tested), cross-filing dedup to the most-recent source,
  and a **reliably derived fiscal year** (from period-end + each filer's FYE month — fixed a real
  NVDA mis-attribution that edgartools' per-filing tag got wrong).
- ✅ **Gold — serving marts.** dbt tables: `company_financials`, `ratios`, `peers` (reproduce the
  REST API surface — verified against the live endpoints, and *more* current than the legacy
  load), plus `company_quarterly` and `earnings` (quarterly series with derived Q4 and
  split-adjusted EPS) that power forecasting. 30 dbt tests pass.
- ✅ **Cutover complete.** The live Flask API reads the gold layer for every DB-backed endpoint
  (companies / analyze / financials / metrics / data / ratios / peers / NP2SQL), verified live;
  on-demand custom ingest lands into bronze. The legacy `public` star schema was **dropped** (a
  pre-cutover backup is in `database/backup_public_preCutover_*.csv.gz`) and the legacy loader /
  schema / migrations removed. One pipeline, one source of truth.

> The earlier single-layer Kimball star schema (`public`, loaded by the retired
> `database/load_from_edgartools.py`) was replaced by this medallion in the 2026-10 cutover.

---

## Phase 1 — Deterministic quantitative extraction (the MVP)

### Resolved by the re-architecture
- ✅ **Period assignment.** Periods are keyed by exact dates (edgartools), so cross-filer
  `period_id` collisions are structurally impossible. The instant-date fix also recovered
  prior-year balance-sheet comparatives that the old path silently deduped away.
- ✅ **IFRS / 20-F parity.** Foreign filers load cleanly — Novo Nordisk (IFRS, DKK) is in the
  reference set and its balance sheet validates (`Assets = EquityAndLiabilities`).
- ✅ **Multi-industry breadth.** Banks load (JPM, `is_financial_institution=True`); the
  reference set spans tech, pharma, consumer, and a bank.
- ✅ **Validation on load.** `src/validation/quality.py` runs automatically inside the loader:
  reported balance-sheet identity + unit/scale as hard gates; income-math and diluted-EPS as
  warnings; a per-filing data-quality report (completeness / accuracy / consistency /
  provenance → weighted score) in `data/quality_reports/`.

### Still open to truly close the MVP
- ✅ **Consolidated canonical labels for the core lines (PRD §2.3).**
  `src/extraction/canonical_labels.py` maps one canonical label per core income-statement /
  balance-sheet / cash-flow line across us-gaap + ifrs-full (priority-ordered, so co-occurring
  synonyms resolve deterministically and nothing is dropped). All core lines now reconcile to a
  single label across the 8-filer set; tested in `tests/test_canonical_labels.py`. *The long
  tail of note-disclosure concepts intentionally keeps its snake-case label — consolidating it
  isn't needed for reconciliation.*
- ✅ **Documented CLI/orchestration now runs the edgartools path (PRD §2.7).** `src/main.py`
  (`--ticker`) and `run_pipeline.sh` extract → validate → load via the edgartools loader; the
  old Arelle `run_pipeline()` was replaced (signature kept, so the Flask API still works) and
  `run_pipeline.sh` ends with an `/api/financials` smoke test instead of the legacy UI test.
- ✅ **Validation that audits, not just gates (PRD §2.4).** `src/validation/quality.py` ships
  hard gates (balance identity, unit/scale), soft reconciliation (income math, EPS),
  **cross-statement cash-flow reconciliation** (operating + investing + financing (± FX effect)
  = reported net change in cash — ties to the penny for all 8 filers, incl. JPM's FX term and
  NVO's before-FX IFRS convention), **duplicate/conflict detection**, and **sign/ratio/scale
  anomaly flagging**. Tested in `tests/test_quality_checks.py`; the 8-filer set produces zero
  false positives.
- ✅ **Streamlit viewer + exports verified against the new warehouse (PRD §2.8).** Loader now
  populates `axis_name`/`member_name` on `dim_xbrl_dimensions`; the viewer's missing
  `v_facts_hierarchical` convenience view was created
  (`database/migrations/create_v_facts_hierarchical.sql`); all viewer queries (stats,
  consolidated, dimensional, view-backed) run and CSV/JSON export works. `src/storage/
  export_queries.py` was rewritten off the dead flat table onto the star schema (canonical
  labels) and all seven queries verified.
- ✅ **Currency normalization to USD (PRD §2.3).** `database/fx_rates.py` converts
  foreign-currency facts at each fact's period date via ECB reference rates (cached in
  `database/fx_rates.json` — reproducible, offline after first fetch, no key); the loader stores
  `value_usd` beside the untouched native `value_numeric`, exposed via `v_facts_hierarchical`
  and `/api/financials` (`values_usd`). NVO FY2025 revenue 309.1B DKK → $48.6B; USD filers pass
  through unchanged. *Spot rates at period-end, not filer period-average — a consistent
  cross-company approximation, not a restatement.*
- ✅ **Killed the `staging_facts` ELT layer + statement-template/reconstruction machinery
  (PRD §2.5).** Dropped the eight empty tables (`staging_facts`, `dim_statement_templates`,
  `rel_statement_overrides`, `fact_income_statement` / `_balance_sheet` / `_cash_flow` /
  `_comprehensive_income` / `_equity_statement`) and their dependent presentation views
  (`database/migrations/drop_retired_statement_machinery.sql`); deprecated the two endpoints
  that read them (`/api/statements`, `/api/populate-statements`) to HTTP 410 → `/api/financials`.
  Also fixed `dim_concepts.normalized_label` drifting from the canonical labels on reload.
- ✅ **Dead-code sweep.** Removed the retired Arelle-path Python modules — the custom parser /
  downloader, old loader, statement/hierarchy population utils, the heuristic validator stack,
  the old data viewer, and their tests (59 files, computed as everything outside the live import
  closure of the edgartools entrypoints). Live imports, the test suite (30 passing), and an
  end-to-end load all verified after removal.

### NP2SQL (PRD §15 — marked delivered)
- ✅ **Natural-language-to-SQL — re-verified on the new warehouse.** Schema context repointed
  off the dropped statement sub-tables onto `fact_financial_metrics` + dims + the live views,
  now advertising the canonical labels and `value_usd` (added to `v_facts_consolidated`);
  `ALLOWED_TABLES` pruned to real objects; model bumped to `gpt-4o-mini` (override via
  `NP2SQL_MODEL`). `tests/test_np2sql.py` verifies the schema context names only live objects,
  every sample query executes read-only, a USD cross-currency comparison returns NVO + AAPL,
  and the SQL safety layer holds. **Live-verified end-to-end** against Groq
  (`openai/gpt-oss-120b`): "compare Novo Nordisk and Apple revenue in USD for 2025" →
  generated SQL selecting `value_usd` → NVO $48.6B, AAPL $416.2B. Provider auto-detects
  `GROQ_API_KEY` (OpenAI-compatible, preferred) or `OPENAI_API_KEY`; without a key the endpoint
  degrades gracefully to a clear error.

---

## Phase 2 — LLM-based qualitative extraction (PRD §1 / §2 Optional / §10 #1)
- ☐ **ESG & narrative metrics** — Scope 1/2/3 emissions, diversity ratios, sustainability
  targets, board/governance composition, from MD&A and sustainability reports.
- ☐ **Strategy statements, risk factors, management commentary** extraction.
- ☐ **PDF fallback** for non-XBRL reports (PyMuPDF / Camelot / docTR), ≥90% KPI accuracy.

---

## Phase 3 & beyond — visualization, analysis, serving, ML (PRD §10 / §15 Phase 3)
- ✅ **Common ratios + peer-comparison module.** `src/analysis/ratios.py` derives margins
  (gross/operating/net), ROE/ROA, debt-to-equity, current ratio, asset turnover, effective tax
  rate, free cash flow, and revenue growth from the canonical labels in USD, so companies
  compare across currencies (NVO shows $48.6B, not 309B DKK). Served at `/api/ratios/<ticker>`
  (multi-year) and `/api/peers` (latest-year, revenue-sorted); tested in `tests/test_ratios.py`.
  *Valuation ratios (P/E, P/B) are deferred — they need market price / cap, which SEC filings
  don't carry (a future market-data integration).*
- ☐ **Standardized visualization / dashboard templates** (Superset) and automated insight
  generation (YoY growth, peer comparison).
- ◐ **ML on the normalized facts** — **quarterly earnings forecasting shipped.**
  `src/analysis/forecasting.py` forecasts next-quarter revenue / diluted EPS from the gold
  quarterly series (`gold.earnings`) with three transparent, seasonality-aware models
  (seasonal-naive, OLS trend+seasonal, gradient-boosted lags) + an inverse-MAPE ensemble, walk-
  forward backtested per company, and benchmarked against analyst consensus + actuals from
  Yahoo Finance. Write-up: [`docs/forecasting/EARNINGS_FORECAST.md`](docs/forecasting/EARNINGS_FORECAST.md)
  (e.g. Apple FQ4-FY2026 EPS ensemble $2.03 vs consensus $1.98). Tested in
  `tests/test_forecasting.py`. The run also surfaced a real data-quality finding — stock splits
  (AVGO/NVDA 10:1, 2024) and one-time items distort the short EPS history, so EPS forecasts are
  gated by their own backtest reliability while **revenue** (unaffected) forecasts cleanly.
  The split half was then **fixed**: splits are landed as raw corporate actions in
  `bronze.corporate_actions` (yfinance) and gold computes a split-adjusted EPS
  (`gold.earnings.eps_diluted_adj`) on a current-share basis — backtest error fell sharply
  (AVGO 148%→30%, NVDA 38%→20%). *Still open: anomaly/outlier detection; non-GAAP/one-time-item
  normalization for EPS (the reported figure is correct but unrepresentative — not in the XBRL);
  longer history.*
- ☐ **GraphQL API**; webhook notifications for new filings.
- ✅ **Re-host** the API + database and restore a live demo (earlier Railway/Azure deployment
  retired — see `docs/archive/deployment-history/`). The Flask API is deployed on **Fly.io**
  (`finsight-api-verdant-log-1735.fly.dev`, scale-to-zero) against a managed **Neon** Postgres
  warehouse (project `muddy-truth-56443165`, branch `production`) with the 8-filer reference set
  loaded; `/health`, `/api/companies|financials|statements|ratios|peers|analyze|metrics|data|quota|query`
  all verified live. The Next.js frontend consumes it via a server-side proxy
  (`app/api/finsight/route.ts`) that defaults to the Fly URL (override with
  `NEXT_PUBLIC_FINSIGHT_API`); every endpoint the dashboard calls was verified end-to-end.
  *Optional polish left: a custom domain instead of the generated `*.fly.dev` host.*
- ☐ **Multi-language** EU/Asian filings; ESEF handling once ESAP provides unified access.
