# FinSight warehouse (medallion) — docs & lineage

The warehouse is a **bronze → silver → gold** medallion on Neon Postgres, with **dbt** owning the
silver/gold transforms. Project lives in [`../../dbt/`](../../dbt/).

## Layers

| Layer | Schema | Built by | Objects |
| --- | --- | --- | --- |
| **Bronze** | `bronze` | `src/ingestion/bronze.py`, `corporate_actions.py` | `raw_facts`, `raw_filings`, `corporate_actions` (raw as-ingested: 10-K + 10-Q + splits) |
| **Silver** | `silver` | dbt (views) | `stg_facts` (conform: USD, canonical labels, fiscal-year derivation, period_grain), `fct_financial_facts` (deduped conformed fact grain) |
| **Gold** | `gold` | dbt | **views** (serving): `v_facts_consolidated`, `v_facts_hierarchical`, `companies`, `company_financials`, `ratios`, `peers` · **tables** (forecasting): `company_quarterly`, `earnings` |
| seeds | `seeds` | dbt (`dbt/seeds/`) | `canonical_labels`, `fx_rates` (generated from the Python definitions) |

Serving objects are **views** so a newly-landed ticker is queryable immediately; the heavier
forecasting marts are **tables** rebuilt on the weekly schedule.

## View the lineage graph

```bash
./dbt/run_dbt.sh docs generate     # builds target/catalog.json + manifest + index.html
./dbt/run_dbt.sh docs serve        # opens the interactive lineage/catalog site
```

(The generated `dbt/target/` is gitignored; CI regenerates it on each run as an artifact.)

## Tests

`./dbt/run_dbt.sh build` runs the models + all data tests, including:
- **Balance-sheet identity** (`tests/assert_balance_sheet_identity.sql`) — Assets = Liabilities +
  Equity within 1% per company-year (the loader's old hard gate).
- **Canonical reconciliation** — each canonical line resolves to exactly one fact per
  company+period (`fct_financial_facts` uniqueness).
- **Range checks** — revenue ≥ 0, net-margin sanity band.
- **Source freshness** — `./dbt/run_dbt.sh source freshness` warns if `bronze.raw_filings` is
  stale (> 8 days) vs the weekly ingestion cadence.
