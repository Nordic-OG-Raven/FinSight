# FinSight Pipeline & Validation Map

> **⚠️ SUPERSEDED (2026-10).** This document describes the retired custom-Arelle pipeline and
> its validator stack, which the edgartools re-architecture replaced and the dead-code sweep
> removed. For the current architecture see [`REARCHITECTURE.md`](REARCHITECTURE.md); validation
> now lives in `src/validation/quality.py`. Kept as historical record of the original design.

**Status: canonical.** This document reflects what the code actually does, verified by
reading control flow end-to-end and cross-checked against a real local pipeline run
(AAPL 2024 10-K, 2026-08-22). Where earlier docs (`FIX_PLAN.md`, `CRITICAL_FIX_SUMMARY.md`,
`VALIDATION_EVALUATION.md`, etc.) describe something differently, this document wins —
those are archived under `docs/archive/` as historical record, not current truth.

If you change pipeline structure or add/remove a validator, update this doc in the same
commit. A stale map is worse than no map.

---

## 1. There are two pipeline entrypoints, and they diverge

`src/main.py` contains **two separate implementations** that both claim to be "the
pipeline." This is the single most important thing to know before touching anything else.

| | `run_pipeline(ticker, year, filing_type)` | `main()` (CLI) |
|---|---|---|
| Who calls it | Flask API, for on-demand "custom analysis" | `run_pipeline.sh`, direct CLI use |
| Loads to database? | **Yes** — in-process `StarSchemaLoader.load_json_file()` | **No** — writes JSON/report files only, prints manual instructions afterward (which are themselves stale: they reference the old `financial_facts` flat table, not the star schema) |
| Runs `input_check.py`? | Yes (Step 4.75) | No — not called at all |
| Runs `consistency_check.py` / `ui_test.py`? | Yes (Steps 6.5, 7), both wrapped in try/except that swallows failures | No — these only run if something downstream (like `run_pipeline.sh`) separately triggers the loader |

`run_pipeline.sh` papers over the CLI path's missing load step by calling
`database/load_financial_data.py` as a **second, separate script** after `main()` finishes.
This mostly works but means the CLI path and the API path exercise different code at
different times, and a plain `python src/main.py --ticker X --year Y` run will silently
stop after extraction with no error — it just never loads anything.

**Recommendation**: pick one entrypoint as canonical (`run_pipeline()`, since it's the one
that's actually complete) and make the CLI `main()` call it, rather than maintaining two
separate stage sequences. Not urgent, but worth doing before adding anything new.

---

## 2. The actual stage sequence (via `run_pipeline()` / `run_pipeline.sh`, the complete path)

```
1. Download filing              src/ingestion/fetch_sec.py
2. Parse XBRL → facts            src/parsing/parse_xbrl.py  (Arelle)
3. In-memory validation          src/validation/checks.py            FinancialValidator      [informational — score only, never blocks]
4. Completeness scoring          src/validation/completeness.py      CompletenessTracker
4.5. SEC-API gap fill            src/validation/completeness.py      CompletenessTracker.fill_missing_with_sec_api
4.75. Pre-load validation        src/validation/input_check.py       InputValidator          [warn only]
5. Load to star schema           database/load_financial_data.py     StarSchemaLoader.load_json_file()
   5a. Stage + load facts (commits happen throughout, see §3)
   5b. Concept mapping check     src/validation/concept_checker.py   ConceptMappingValidator [runs inside 5, after fact_financial_metrics populated]
   5c. Populate statement tables (fact_balance_sheet, fact_income_statement, fact_cash_flow, fact_equity_statement, fact_comprehensive_income)
   5d. HARD-FAIL GATE            src/validation/aggregator.py        ValidationAggregator    [see §4 — this is the one that actually blocks]
6. Post-load gap fill            src/utils/post_load_gap_filling.py
6.5. Consistency validation      src/validation/consistency_check.py ConsistencyValidator    [soft — exceptions caught and logged, pipeline continues]
7. UI/functional test            src/validation/ui_test.py           UniversalUITest         [soft — same]
```

`run_pipeline.sh` additionally runs a **Step 4**, `UITest.py` (project root) against the
live API — see §5, this is the one that's currently broken.

---

## 3. The hard-fail gate doesn't actually prevent bad data from landing

`StarSchemaLoader.load_json_file()` (`database/load_financial_data.py:1016`) calls
`self.conn.commit()` at roughly 20 points while staging facts and populating statement
tables — e.g. lines 1074, 1096, 1173, 1188. The "hard fail on errors" validation gate
doesn't run until line 1454, *after* all of that has already committed. When it fails, it
calls `self.conn.rollback()` (line 1501) — but there's nothing left in the current
transaction to roll back; everything upstream is already permanent.

This was directly observed: loading AAPL's facts raised `ValueError: Validation failed: 6
critical issues`, and the loader printed a rollback message — yet querying the database
immediately afterward showed 152 balance sheet facts, 43 income statement facts, and 21
cash flow facts for that filing, all present.

**Effect**: a "failed" pipeline run still leaves its output in the warehouse. The next run
against the same company doesn't start from a clean slate, and cross-company/cross-filing
checks (like `unit_consistency`, see §4) can be comparing against data from a run that was
supposed to have been rejected. This is a strong candidate for the actual mechanism behind
much of the "fix one thing, break another" pattern — not because any individual validator
is wrong, but because failed state persists.

**Fix shape** (not yet done): wrap the whole `load_json_file()` write path in one
transaction and only commit after the validation gate passes, or explicitly clear
`filing_id`'s rows on validation failure before returning.

---

## 4. The hard-fail gate — what it actually checks

`ValidationAggregator.collect_all_issues(filing_id)` (`src/validation/aggregator.py:114`)
is what `load_json_file()` calls at the gate. It pulls from:

- `DatabaseValidator.validate_all()` (`src/validation/validator.py:372`) — see §6, filtered
  to `severity == 'ERROR'` issues only (warnings don't block)
- `UniversalUITest.test_company()` (`src/validation/ui_test.py`) — scoped to this filing
- Its own loading-error / actionability checks (`_check_loading_errors`,
  `_check_if_missing_values_are_actionable`, etc.) — these exist specifically to suppress
  false positives, e.g. don't flag a missing value as critical if it's genuinely absent
  from the source filing rather than a loading defect

A **separate, second** validation pass exists in `database/load_financial_data.py`'s own
`main()` (line 2065, only reached when running this file as a standalone script) —
`DatabaseValidator.validate_all()` run again, this time **database-wide** (not scoped to
one filing) and purely informational (prints, never raises). Two different scopes, two
different enforcement levels, same underlying validator class.

---

## 5. `run_pipeline.sh`'s Step 4 calls a deprecated, hardcoded test file

**Context, not just a bug**: NVO was deliberately chosen as the first company to get fully
correct end-to-end — including the frontend — on the theory that other companies would get
incrementally easier once NVO's hard cases (IFRS, DKK, Danish statement structure) were
handled. `UITest.py`'s NVO-specific hardcoding was step one of that plan, not an oversight.
See `docs/NVO_GOLDEN_PATH_2026-08.md` for the active plan finishing this.

`UITest.py` (project root, 2848 lines, last modified 2025-11-11) hardcodes its expected
statement line items to Novo Nordisk specifically — every constant is named
`EXPECTED_NOVO_*` (e.g. `EXPECTED_NOVO_BALANCE_SHEET_LIABILITIES_EQUITY` contains "Equity
and liabilities", "Share capital", "Treasury shares" — Danish/IFRS terms). Running it
against any other company reports dozens of "missing items" that were never going to exist.

`src/validation/ui_test.py` (`UniversalUITest`, last modified 2025-11-12 — **one day
later**) is the deliberate, correct replacement: `_get_expected_items()` queries
`rel_statement_items` dynamically per ticker/year, no hardcoding. It's already correctly
wired into the real hard-fail gate (§4) and into `run_pipeline()`'s Step 7.

The only place still calling the old file is `run_pipeline.sh`'s Step 4. This is very
likely why historical "data completeness" reports for any non-NVO company looked far worse
than reality — the tests were checking for the wrong company's line items.

**Fix**: change `run_pipeline.sh` Step 4 to stop calling root `UITest.py`. The correct
check already runs automatically inside Step 2 via the aggregator; a separate Step 4 against
the live API is redundant with it, not a distinct check that needs preserving.

---

## 6. `validator.py` (`DatabaseValidator`) — what's live vs. dead code

This file is 207KB and looks, at a glance, like it has 3-4 competing implementations of
the same checks. **Tracing actual execution shows this isn't true at runtime** — it's
leftover dead code from an in-progress modularization refactor that was never cleaned up.

`validate_all()` (line 372, the only method actually called) invokes:

| Check | Source | Rule name(s) |
|---|---|---|
| Normalization conflicts | inline | `normalization_conflicts` |
| User-facing duplicates | inline | `user_facing_duplicates` |
| Missing data matrix (company × metric × year) | inline | `missing_data_matrix` |
| Universal metrics completeness | inline, delegates to `taxonomy_driven_universal_metrics.py` (falls back to `check_universal_metrics.py` if taxonomy-driven fails) | `universal_metrics_completeness` |
| Balance sheet equation, retained earnings rollforward, cash flow reconciliation, gross profit margin, operating income calc | **`AccountingIdentitiesValidator`** (`accounting_identities.py`) | `balance_sheet_equation`, `retained_earnings_rollforward`, `cash_flow_reconciliation`, `gross_profit_margin`, `operating_income_calculation` |
| Calculation relationships (vs. XBRL calc linkbase) | inline | `calculation_relationships` |
| Displayed statement math (what the UI actually shows) | **`DisplayedMathValidator`** (`displayed_math.py`) | `income_statement_math`, `comprehensive_income_math`, `balance_sheet_displayed_math`, `cash_flow_displayed_math`, `equity_statement_math` |
| Data quality (normalization coverage, numeric ranges, unit consistency) | **`DataQualityValidator`** (`data_quality.py`) | `normalization_coverage`, `numeric_value_ranges`, `unit_consistency` |

**Confirmed dead code, never called from anywhere**: the `RawFactsValidator` class
(lines 87-305, its own separate `balance_sheet_equation`/`eps_calculation`/`no_duplicates`
implementation), and three private wrapper methods that predate the modularization —
`_check_accounting_identities()` (line 1133), `_check_displayed_statement_math()` (line
2566), `_check_data_quality()` (line 3448) — each containing an inline duplicate of what
`AccountingIdentitiesValidator` / `DisplayedMathValidator` / `DataQualityValidator` now do.
These should be deleted; they're not causing incorrect behavior today (they simply never
run), but they make the file look far more chaotic than it behaves, and they're a hazard
for the next person (human or AI) who reads this file without doing the tracing above.

Also dead: `xbrl_validator.py` (imported nowhere).

**Not wired into any automatic path, but not dead** — standalone tools meant to be run
manually: `validate_database.py` (CLI wrapper around `DatabaseValidator`), `analyze_conflicts.py`,
`analyze_missing_data.py`, `scan_zero_data_metrics.py`. These are diagnostic scripts, not
pipeline stages.

---

## 7. The other pre/post-load validators — what and why

Each of these has a docstring stating exactly where it sits in sequence — this was a
deliberately layered design, not accidental sprawl:

- **`checks.py` (`FinancialValidator`)** — oldest (Oct 31), in-memory, pre-load. Balance
  sheet equation, EPS calculation, cross-statement consistency, completeness, duplicates.
  Informational only in the CLI path.
- **`completeness.py` (`CompletenessTracker`)** — coverage scoring by statement type, plus
  the SEC-API gap-fill logic (`fill_missing_with_sec_api`). This is where the balance-sheet
  2022-gap issue (see `docs/archive/MISSING_DATA_NOVO.md`) lives — the gap-fill year range
  assumes 3 years of everything are in one filing, which may not hold for balance sheet
  items specifically (see that doc's unconfirmed hypothesis).
- **`input_check.py` (`InputValidator`)** — "runs after gap filling but before
  `StarSchemaLoader.load_json_file()`." Narrower, more specific reasonableness checks
  (gross margin 0-100%, equity 10-80% of assets, transaction sign conventions) than
  `checks.py`'s broader identity checks. Overlaps with `checks.py` on balance sheet
  equation specifically — both re-check it, at different stages, on what could be
  different data (gap-filled vs. not) — defensible as designed, but worth eventually
  sharing one arithmetic implementation between them.
- **`concept_checker.py` (`ConceptMappingValidator`)** — "runs after loading to
  `fact_financial_metrics`, before `populate_statement_facts()`." Catches wrong
  concept→label mappings, mapping conflicts, taxonomy consistency, synthetic dimension
  correctness.
- **`consistency_check.py` (`ConsistencyValidator`)** — "runs after
  `populate_statement_facts()`, before `validator.py`." Cross-period consistency (equity
  continuity, retained earnings rollforward — a *second* implementation of rollforward,
  this one cross-period rather than single-filing), ratio reasonableness, XBRL-vs-SEC-API
  consistency.

None of this layer is dead code — each is called from a distinct place in §2's sequence,
checking a genuinely different data state (raw facts → gap-filled facts → staged →
statement-populated → fully loaded).

---

## 8. Known bugs, current status

| Bug | Status | Where |
|---|---|---|
| XBRL `decimals` attribute treated as a scale multiplier (`decimals="-6"` → ×10⁶), corrupting essentially every XBRL-sourced dollar value by 1,000×–1,000,000× | **Fixed** 2026-08-22 | `database/load_financial_data.py:702` (block removed) |
| Loader commits ~20 times before the hard-fail gate runs; rollback on failure doesn't undo already-committed writes | Open | `database/load_financial_data.py:1016-1517` |
| `run_pipeline.sh` Step 4 calls deprecated hardcoded-to-NVO `UITest.py` instead of the already-correct `src/validation/ui_test.py` | Open | `run_pipeline.sh` |
| `fact_equity_statement` population has a spurious hard dependency on `fact_comprehensive_income` populating first, even though they're unrelated statements — real equity data gets silently dropped | Open | wherever statement population order is declared (`src/utils/populate_statement_facts.py` / `population_order.py`) |
| No `statement_type` classification distinguishes comprehensive income from income statement for filers (like Apple) who report them combined — `fact_comprehensive_income` will always be empty for such filers | Open | extraction/classification logic, `src/parsing/parse_xbrl.py` or `src/utils/normalize.py` |
| `dim_statement_templates` referenced by `populate_statement_items.py` but not present in the deployed schema | Open | schema/migration drift — check `database/schema.sql` vs `database/migrations/` |
| Arelle fails to parse pure inline-XBRL filings with no separate linkbase files (`ModelRelationshipSet` has no attribute `modelConcepts`) — modern SEC filings are commonly this format; pipeline silently falls back to stale cached JSON rather than surfacing the failure | Open | `src/parsing/parse_xbrl.py` |
| `unit_consistency` check (`data_quality.py:223`) flags any filing with more than one distinct `scale_int` among currency facts as an error — but that's normal XBRL (EPS carries different precision than total revenue). Premise needs revisiting, likely built around the now-fixed decimals bug's symptoms | Open | `src/validation/data_quality.py:223` |
| 2022 balance-sheet completeness gap for NVO — never resolved. Leading hypothesis: balance sheets in a 20-F typically show only 2 comparative years (not 3, unlike income statement/cash flow), so FY2022 Assets may genuinely not exist in the FY2024 filing at all | Open, needs verification against the actual FY2023 20-F | `docs/archive/MISSING_DATA_NOVO.md`, `docs/archive/GOFUCKYOURSELF.md` |

None of these require rebuilding the validation layer. They're independent, narrow,
fixable bugs in extraction, schema sync, transaction boundaries, and one script wiring
oversight — not a structural flaw in how validation is designed.
