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
- ◐ **Point the documented CLI/orchestration at the new path (PRD §2.7).** `run_pipeline.sh`
  and `src/main.py` still drive the retired Arelle pipeline; the working path is
  `database/load_from_edgartools.py`. Make the documented entrypoint *be* the edgartools
  pipeline.
- ◐ **Validation that audits, not just gates (PRD §2.4).** The sound checks exist; still to add:
  explicit duplicate-fact detection, cross-statement reconciliation against the statement as
  filed, and outlier/anomaly flagging. Goal: "validated" means audited.
- ☐ **Verify / rebuild the Streamlit viewer + CSV/Parquet export (PRD §2.8)** against the
  rebuilt warehouse (built for the old schema; unconfirmed).
- ☐ **Currency normalization to a common reporting currency (PRD §2.3).** Currency is detected
  (USD/DKK/EUR); conversion to a common currency needs an FX source.
- ☐ **Decide keep-or-kill: `staging_facts` ELT layer and the `dim_statement_templates` /
  `get_income_statement()` presentation machinery (PRD §2.5).** Largely redundant after the
  re-architecture and unused by the new path — decide, then delete or wire.

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
