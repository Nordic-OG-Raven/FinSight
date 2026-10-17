# FinSight — Roadmap

Single honest status list for the whole PRD (`prd.md`), not just the quantitative MVP.
Grouped by the PRD's own phase structure (§1) and roughly ordered within each group by the
leverage it adds. Status: ✅ done · ◐ partial · ☐ not started.

The 2026-10 re-architecture (SEC/XBRL extraction flipped to **edgartools** behind an adapter
seam — see [`docs/REARCHITECTURE.md`](docs/REARCHITECTURE.md)) resolved several items that the
old custom-Arelle pipeline could not, and added the post-load validation layer. Those are
marked below so this file reflects what is actually true today.

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
- ◐ **Validation that audits, not just gates (PRD §2.4).** Hard gates (balance identity,
  unit/scale) plus soft reconciliation (income math, EPS), **duplicate/conflict detection**
  (synonym concepts disagreeing on a line) and **sign/ratio/scale anomaly flagging** all ship
  in `src/validation/quality.py` (tested in `tests/test_quality_checks.py`; the 8-filer set
  produces zero false positives). *Still to add: cross-statement reconciliation against the
  statement as the filer reports it (e.g. net income tying into the cash-flow statement).*
- ✅ **Streamlit viewer + exports verified against the new warehouse (PRD §2.8).** Loader now
  populates `axis_name`/`member_name` on `dim_xbrl_dimensions`; the viewer's missing
  `v_facts_hierarchical` convenience view was created
  (`database/migrations/create_v_facts_hierarchical.sql`); all viewer queries (stats,
  consolidated, dimensional, view-backed) run and CSV/JSON export works. `src/storage/
  export_queries.py` was rewritten off the dead flat table onto the star schema (canonical
  labels) and all seven queries verified.
- ☐ **Currency normalization to a common reporting currency (PRD §2.3).** Currency is detected
  (USD/DKK/EUR); conversion to a common currency needs an FX source.
- ✅ **Killed the `staging_facts` ELT layer + statement-template/reconstruction machinery
  (PRD §2.5).** Dropped the eight empty tables (`staging_facts`, `dim_statement_templates`,
  `rel_statement_overrides`, `fact_income_statement` / `_balance_sheet` / `_cash_flow` /
  `_comprehensive_income` / `_equity_statement`) and their dependent presentation views
  (`database/migrations/drop_retired_statement_machinery.sql`); deprecated the two endpoints
  that read them (`/api/statements`, `/api/populate-statements`) to HTTP 410 → `/api/financials`.
  Also fixed `dim_concepts.normalized_label` drifting from the canonical labels on reload.
  *Remaining: the retired Arelle-path Python modules (`load_financial_data.py`, `parse_xbrl.py`,
  `fetch_sec.py`, `populate_statement_facts.py`, the old heuristic validators) are now dead code
  and can be removed in a dedicated sweep — ~15 interdependent files + their tests.*

### NP2SQL (PRD §15 — marked delivered)
- ◐ **Natural-language-to-SQL — built, needs re-verification.** The `/natural_language_query`
  endpoint and `src/np2sql/` exist and are wired. But its schema context still describes the
  now-empty `fact_income_statement` / `fact_balance_sheet` / `fact_cash_flow` tables, and it
  runs on `gpt-3.5-turbo`. Repoint the schema metadata at the live tables
  (`fact_financial_metrics` + dims), update the model, and test end-to-end.

---

## Phase 2 — LLM-based qualitative extraction (PRD §1 / §2 Optional / §10 #1)
- ☐ **ESG & narrative metrics** — Scope 1/2/3 emissions, diversity ratios, sustainability
  targets, board/governance composition, from MD&A and sustainability reports.
- ☐ **Strategy statements, risk factors, management commentary** extraction.
- ☐ **PDF fallback** for non-XBRL reports (PyMuPDF / Camelot / docTR), ≥90% KPI accuracy.

---

## Phase 3 & beyond — visualization, analysis, serving, ML (PRD §10 / §15 Phase 3)
- ☐ **Multi-year comparative analysis + common ratios** (P/E, ROE, debt-to-equity) and a
  peer-comparison module.
- ☐ **Standardized visualization / dashboard templates** (Superset) and automated insight
  generation (YoY growth, peer comparison).
- ☐ **ML on the normalized facts** — anomaly/outlier detection, time-series forecasting
  (ARIMA/Prophet), margin-trend detection; later, a finance-tuned extraction model.
- ☐ **GraphQL API**; webhook notifications for new filings.
- ☐ **Re-host** the API + database and restore a live demo (earlier Railway/Azure deployment
  retired — see `docs/archive/deployment-history/`); wire up and verify the Next.js frontend
  against it.
- ☐ **Multi-language** EU/Asian filings; ESEF handling once ESAP provides unified access.
