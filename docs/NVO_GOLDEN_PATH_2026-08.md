# NVO Golden Path — Completion Plan (2026-08)

**Goal**: get Novo Nordisk (NVO) fully correct end-to-end — extraction → validation →
star schema → API → frontend — with a real automated test guarding it, so "correct" is a
checkable fact, not a feeling. NVO was chosen as the original reference company
deliberately (see below); this plan finishes that strategy rather than replacing it.

**If this file goes stale**: update it in place rather than leaving it and writing a new
one. A dated filename doesn't help if nobody trusts old plan docs enough to open them —
this project has ~15 archived docs that suffered exactly that fate
(`docs/archive/validation-design-history/`). Mark items done as you do them.

**Session status (2026-08-22, end of session)**: items 1-5 done and independently verified.
Item 6 found and fixed three real root causes, all independently confirmed: an
invalid-SQL-syntax bug in `schema.sql` (likely why `dim_statement_templates` was never
deployed), a period-deduplication bug (two date conventions fragmenting one real period
into two incomplete ones), and — traced from the "phantom period" investigation — a filing
identity bug in `post_load_gap_filling.py` that created a separate, wrong `dim_filings`
row per comparative year instead of attaching supplementary facts to the one filing they
belong to. That third fix is verified: `dim_filings` now stays at exactly 1 row for NVO
across repeated runs.

**Still open, and now the clearest next foothold**: a full clean pipeline run remains
non-reproducible, but the remaining cause is narrowed, not mysterious —
`fact_comprehensive_income`/`fact_equity_statement` intermittently populate empty because
`rel_statement_items` (what those tables actually join against, not `fact_financial_metrics`
directly) intermittently gets zero comprehensive_income/equity_statement classifications
from `populate_statement_items.py`, even though the underlying facts are always correctly
present. Most plausible common cause: item 3's still-open empty-presentation-hierarchy gap
(`pres_rels` for NVO's filing) — `populate_statement_items.py`'s classification logic
hasn't been read in detail yet to confirm this, but it's now a specific, falsifiable
hypothesis rather than an unexplained phantom.

Item 7 has 9 tests (up from 1 before today), including one that correctly fails right now
because it's honestly catching the remaining reproducibility gap rather than being hidden
or weakened. **Next session should start by reading `populate_statement_items.py`'s
classification logic** and confirming or ruling out the presentation-hierarchy hypothesis
above — that's a bounded, specific next step, not a fresh investigation. The database was
left in a clean baseline (NVO: 0 facts, 1 filing record) at end of session.

---

## Why NVO, and why the hardcoded UI test wasn't a bug

The strategy was: make one company perfect first, including what the frontend renders,
because every other company should get incrementally easier once the hard cases (IFRS
taxonomy, DKK currency, Danish-language statement structure, side-by-side income statement
+ comprehensive income layout) are handled correctly. `UITest.py`'s hardcoded
`EXPECTED_NOVO_*` constants were step one of that plan, not an oversight.

What actually happened: a generalized successor (`src/validation/ui_test.py`,
`UniversalUITest` — queries `rel_statement_items` dynamically, no hardcoding) was built one
day later and correctly wired into the real validation gate. `run_pipeline.sh`'s Step 4
never got updated to stop calling the old one. So the "perfect NVO first" plan is further
along than it looked — the generalization work is done, it's just not fully plugged in.
This plan finishes plugging it in and closes out what's still actually broken for NVO
specifically.

---

## Definition of done

NVO 2024 20-F, run through `./run_pipeline.sh NVO 2024 20-F` end to end:

1. ✅ **Done.** Extraction succeeds without falling back to stale cached JSON (item 3).
2. ⚠️ **Partially done, not reliably reproducible.** The transactional-purge fix (item 1),
   cross-company scoping fix (item 5), and schema fix (item 6) are each independently real
   and verified. A clean pipeline run DID achieve zero critical issues once — but a repeat
   clean run hit a different failure (the phantom income-statement period, see below), so
   "loads with zero critical issues" is not yet a dependable outcome, only a demonstrated
   possibility. Don't cite this as closed until that's resolved.
3. ✅ **Done, verified 2026-08-22.** Balance sheet, income statement, cash flow,
   comprehensive income, and equity statement all populate with real data (item 5) — true
   independent of item 2's reproducibility gap.
4. ⚠️ **Not yet.** `/api/statements/NVO/2024` runs and returns data, but `UniversalUITest`
   still reports real discrepancies (extra/missing items, ordering) against every
   statement type — likely downstream of item 3's still-open presentation-hierarchy gap
   (empty `pres_rels` for NVO's filing). Not investigated yet.
5. ✅ **Done for the extraction/gap-fill layer** (8 tests, `tests/test_nvo_golden_path.py`).
   A full pipeline+DB integration test was added too
   (`TestFullPipelineIntegration`) — it correctly fails right now, which is accurate: it's
   catching the exact non-reproducibility in item 2, not a broken test.
6. ⚠️ **Schema fix and period-dedup fix both done and verified independently** — but see
   item 2: a full successful run isn't reliably reproducible yet, so don't treat this as
   fully closed until the phantom-period issue is resolved.

**2 of 6 cleanly done (items 3 and 5), the rest have real, verified progress but an open
reproducibility gap.** Items 1/5/6's individual fixes are each independently solid and
verified — the phantom-period issue found at the end of today's session is a new, distinct
problem, not evidence any of today's fixes were wrong. Item 4 (API-level display
correctness) remains genuinely un-investigated.

---

## Work items, in order

Ordering matters here: items 1-3 are prerequisites because they affect whether you can
trust the signal from everything after them.

### 1. Make the hard-fail gate actually atomic
**Why first**: every other item's "did this fix work" signal depends on validation
failures actually preventing bad data from landing. Right now they don't (confirmed:
`database/load_financial_data.py` commits ~20 times before the validation gate at line
1454 — see `docs/PIPELINE_AND_VALIDATION_MAP.md` §3). Without this, a broken NVO run looks
identical in the database to a fixed one until you go looking.
**Fix shape**: wrap `load_json_file()`'s writes in one transaction, commit only after the
validation gate passes. Or, cheaper short-term: on validation failure, explicitly
`DELETE FROM ... WHERE filing_id = X` across the fact tables before returning.
**Status**: done, 2026-08-22. Went with the cheaper short-term shape rather than a full
transaction refactor — the intermediate `conn.commit()` calls are scattered across this
file and `populate_statement_items.py`, and unwinding all of them was a bigger, riskier
change than the actual problem needed. Added `_clear_filing_data()` (reused by both the
pre-load clear and the new failure-path purge) and call it in both `except` blocks in
`load_json_file()` before re-raising. Verified: re-ran the AAPL load (still fails
validation on items 5/6 below) — confirmed 152/43/21 facts that previously persisted
after a "failed" load are now genuinely purged (`fact_balance_sheet`/`fact_income_statement`/
`fact_cash_flow`/`fact_financial_metrics` all show 0 rows for filing_id 3 post-failure).

### 2. Retire the stale UI test call
**Why**: cheap, and removes noise from every subsequent test run.
**Fix**: `run_pipeline.sh` Step 4 — stop calling root `UITest.py`. The check it was meant
to do already happens correctly inside Step 2 via the aggregator → `UniversalUITest`. Once
confirmed redundant, delete `UITest.py` outright rather than leaving it as an unused 2848-line
file that looks load-bearing.
**Status**: done, 2026-08-22. `run_pipeline.sh` Step 4 now calls
`python -m src.validation.ui_test` (same CLI args as before, `--keep-api` added so it
doesn't tear down the API the rest of the script relies on). Verified against AAPL (correctly
reports no data — its filing was purged testing item 1 above) and NVO (runs cleanly, real
per-item feedback instead of blanket false positives — e.g. flags actual header/ordering
mismatches in the balance sheet and cash flow, which is legitimate signal for item 5 below,
not test noise). Root `UITest.py` deleted (`git rm`) — confirmed nothing in the live
pipeline path imports it; only the already-dead `xbrl_validator.py`'s internal standalone
test block referenced it, and that file is unreferenced from anywhere itself.

### 3. Fix XBRL parsing for pure inline-XBRL filings
**Why**: NVO's 2024 20-F may hit this — confirm first. `Arelle` errored on AAPL with
`ModelRelationshipSet has no attribute modelConcepts` for a filing with no separate
linkbase files (modern SEC filings are commonly this format). If NVO's filing has the same
structure, extraction is currently silently falling back to stale cached JSON rather than
actually re-extracting, which undermines everything downstream.
**Fix shape**: update `src/parsing/parse_xbrl.py`'s inline-XBRL discovery to match the
installed Arelle version's current API.
**Status**: crash fixed and verified, 2026-08-22, but a related issue surfaced. Confirmed
NVO's actual filing (`nvo-20241231_htm.xml`) hits the identical crash AAPL did — not
AAPL-specific, this was genuinely blocking the golden path. Root cause: `arelle-release`
2.37.68's `ModelRelationshipSet.modelConcepts` doesn't exist (renamed/removed upstream);
the correct current API is `fromModelObjects()`, a method (not a property) returning
`dict[concept, list[ModelRelationship]]`. Fixed all 3 call sites
(`src/parsing/parse_xbrl.py:209,1744,1922`). Verified: NVO's filing now extracts 2951
facts cleanly with no crash (previously returned `None`).

**Follow-up issue found, not yet fixed**: presentation/calculation relationships still
come back empty for NVO specifically. Two compounding causes: (1) the loose
`nvo-20241231_{pre,cal,def,lab}.xml` files visible in `data/raw/` sit at that directory's
top level, not inside `data/raw/NVO_2024_20F_000162828025003920/` — they're leftovers from
an earlier/different download attempt, not part of this filing's actual package, so the
manual-linkbase-loading fallback (`parse_xbrl.py:210-256`) finds referenced filenames in
the HTML but `lb_path.exists()` is always false and it silently does nothing; (2)
separately, `_extract_presentation_relationships()` (`parse_xbrl.py:1973`) catches and
logs (rather than propagating) an `invalid Element proxy` error — a stale lxml/Arelle
element reference, exact trigger not yet isolated. Net effect: NVO's statement hierarchy
will fall back to the standard-order heuristic (`populate_standard_presentation_order.py`)
rather than NVO's true filed order — which matters more for NVO than most companies, since
respecting actual filing order for a non-trivial IFRS layout was part of why NVO was
chosen as the hard reference case. Not fixed now — didn't want to chase an open-ended lxml
lifecycle bug without a bound, the same shape of problem that cost months before. Worth
revisiting: try re-downloading NVO's filing fresh (confirm whether SEC's actual filed
package includes separate linkbases at all, or whether this is another pure-inline-XBRL
filing like AAPL's) before spending more time on the stale-proxy error itself.

### 4. Resolve the 2022 balance-sheet completeness gap
**Why**: this is the original unsolved bug, and NVO is the company it's about — it's
directly in scope for "done."
**Leading hypothesis** (documented, not yet verified): 20-F balance sheets typically show
only 2 comparative years, unlike income statement/cash flow which show 3. FY2022 Assets may
genuinely not exist in the FY2024 filing — it would only be tagged in the FY2023 filing.
**Next step**: pull the actual FY2023 20-F and check whether Assets-as-of-Dec-2022 is
tagged there. Cheap to check, and it directly settles months of inconclusive debugging (see
`docs/archive/2022-completeness-investigation/` for the full trail, including the Grok
exchange that didn't resolve it).
**If confirmed**: fix is architectural but bounded — pull balance-sheet instant facts from
the prior year's filing rather than assuming one filing carries 3 years of everything.
Affects `src/validation/completeness.py`'s gap-fill year range logic.
**Status**: confirmed, 2026-08-22 — this was a real filing-structure limitation, not a
parsing bug, and it's now precisely characterized rather than just hypothesized. Directly
inspected the parsed facts (using the now-working parser from item 3) for NVO's FY2024
20-F:

| Concept | Instant dates present | Years |
|---|---|---|
| `Assets` | Dec 2023, Dec 2024 | 2 |
| `Liabilities` | Dec 2023, Dec 2024 | 2 |
| `Equity` | Dec 2021, Dec 2022, Dec 2023, Dec 2024 | 4 |
| `CashAndCashEquivalents` | Dec 2021, Dec 2022, Dec 2023, Dec 2024 | 4 |
| `Inventories` | Dec 2022, Dec 2023, Dec 2024 | 3 |

`Assets` and `Liabilities` — the primary balance sheet's top-line aggregates — genuinely
only get 2 comparative columns in a single 20-F. `Equity` and `Cash` get extra history
because they're *also* reported in the Statement of Changes in Equity and the Cash Flow
reconciliation respectively (both of which roll forward multiple years by convention), and
`Inventories` (a balance sheet component) does carry Dec 2022 data even though the `Assets`
total it rolls up into doesn't. Revenue (income statement, duration-type) cleanly spans all
3 fiscal years as expected, confirming this is specifically a balance-sheet-aggregate
pattern, not a general extraction gap.

**Fix implemented and verified, 2026-08-22**: went with path (a) — pull from the company's
own adjacent filing rather than recomputing from components, since it uses NVO's actual
reported total rather than a sum that could miss a component. Added
`CompletenessTracker.fill_missing_instant_facts_from_comparative_filing()` in
`src/validation/completeness.py`: for any comparative year missing instant facts, it
downloads/parses that year's *own* filing (year + 1, whose 2-comparative-column balance
sheet would include the missing year) and copies over any instant facts not already
present, tagged `source='COMPARATIVE_FILING'` for provenance. Wired into both pipeline
entrypoints in `src/main.py` (both `run_pipeline()` and CLI `main()`), running after the
existing SEC-API fill, scoped to years strictly before the primary filing year.

Verified in isolation (parsed facts only, not yet through a full DB load): ran it against
NVO's FY2024 20-F facts for missing_year=2022 — filled 81 instant facts from the FY2023
20-F, including `Assets` (241,257,000,000 DKK — the exact value the original investigation
was chasing) and `Liabilities`. Not yet verified through a full pipeline run into the
database (that requires items 5-6 to also be fixed, since validation currently still fails
on unrelated equity/comprehensive-income gaps and would purge the load per item 1's new
behavior) — confirm this holds once those land.

### 5. Fix the equity-statement / comprehensive-income gaps
**Why**: needed for definition-of-done item 3.
- `fact_equity_statement` has a spurious hard dependency on `fact_comprehensive_income`
  populating first — confirmed real equity data exists in extraction and gets silently
  dropped. Find and remove that dependency gate (`src/utils/populate_statement_facts.py` /
  `population_order.py`).
- No `statement_type` distinguishes comprehensive income from income statement for filers
  who report them combined. **NVO reports them side-by-side in one document**
  (`docs/archive/validation-design-history/STATEMENT_STRUCTURE_ANALYSIS.md` has the actual
  layout) — this is exactly the kind of "hard case" NVO was chosen to force a real solution
  for, rather than a company where it's simple enough to fudge.
**Status**: done and verified end-to-end, 2026-08-22 — turned out to be three separate bugs,
not one:

1. **Equity dependency gate** (`src/utils/population_order.py`): removed the hard
   dependency of `fact_equity_statement` on `fact_comprehensive_income` populating first —
   `populate_equity_statement()`'s SQL already `LEFT JOIN`s against it, so it degrades
   gracefully when empty. The hard dependency was dropping ALL equity data whenever
   comprehensive_income didn't populate.
2. **Comprehensive income misclassification** (`src/parsing/parse_xbrl.py`,
   `_infer_statement_type`): added a dedicated `comprehensive_income` branch, checked
   before the general income-statement branch, matching NVO's real OCI line items
   (remeasurements, cash flow hedges, translation adjustments, reclassification
   adjustments) — these were falling into `income_statement` because they contain
   "income" as a substring and no comprehensive-income branch existed at all. Excludes
   "accumulated" variants (the cumulative balance-sheet reserve, not the current-period
   flow). Verified: 111 facts now correctly classified for NVO (previously 0).
3. **Post-load gap-fill was clobbering the primary load** (`database/load_financial_data.py`,
   `src/utils/post_load_gap_filling.py`) — a bug unrelated to comprehensive income/equity
   specifically, discovered while testing the above two fixes end-to-end. Post-load
   gap-filling calls `load_json_file()` a second time with a small supplementary batch of
   SEC-API facts; `load_json_file()`'s default behavior clears all existing data for that
   `filing_id` before loading and demands full statement coverage — both wrong for a
   handful of supplementary facts, and this was silently destroying the primary load's
   complete data on every run that found anything to gap-fill, for every company, not
   just NVO. Added an `is_incremental` parameter that skips the clear step and the
   full-coverage validation gate for supplementary loads; wired into
   `post_load_gap_filling.py`'s call site.

Also found and fixed in the same pass: `_check_multiple_consolidated_facts`
(`src/validation/input_check.py`) crashed on raw `datetime.date` objects (assumed strings,
called `[:7]` directly) — always latent, only reached once items 1-4 got extraction far
enough to hit it. And confirmed the aggregator's hard-fail gate was itself checking the
WHOLE DATABASE, not just the filing being loaded — `company_has_data_<ticker>` fires
per-company by design, and `unit_consistency`/`cash_flow_reconciliation` (and likely every
other `AccountingIdentitiesValidator`/`DataQualityValidator` check) return one
`ValidationResult` whose `violations` list spans every company. NVO's load was failing
because of PFE's stale pre-decimals-fix data, nothing to do with NVO. Fixed generically in
`src/validation/aggregator.py`: filter any violations list to the current filing's ticker
before treating it as blocking; results with no company-keyed violations at all
(`missing_data_matrix`, `universal_metrics_completeness` — inherently whole-database
comparisons) are excluded from the per-filing gate entirely. PFE needs reloading separately
to get its stale data current — not done here, out of scope for the NVO path.

**Verified end-to-end**: `run_pipeline(ticker='NVO', year=2024, filing_type='20-F')` →
`SUCCESS`. All five statement tables populated (balance_sheet: 64, income_statement: 18,
comprehensive_income: 17, cash_flow: 169, equity_statement: 202 — plus 175 more via
post-load gap-fill, correctly additive this time). Hard-fail gate passed with zero critical
issues. Remaining signal is exactly the non-blocking tier it's designed to be: consistency
warnings (equity continuity, retained earnings rollforward, balance sheet equation — likely
downstream of item 3's still-open presentation-hierarchy gap, worth re-checking once that's
fixed) and UI test warnings (missing/extra items, ordering — same likely cause).

### 6. Close the schema drift
**Why**: `dim_statement_templates` is referenced by `populate_statement_items.py` but
doesn't exist in the deployed schema — the ETL→ELT template migration
(`docs/ARCHITECTURE_MIGRATION.md`) was started and left unfinished. Cheap, mechanical fix:
run the missing migration, confirm old denormalized tables are either in active use or
actually retired (the migration doc's own rollback plan kept both — check which is true
now).
**Status**: root cause found and fixed, 2026-08-22, but surfaced two new NVO-specific
issues not yet resolved. Diffing `schema.sql`'s declared tables against the live database
showed exactly 2 missing (`dim_statement_templates`, `rel_statement_overrides`) and,
reassuringly, zero stale tables present in the DB that aren't in `schema.sql` — the earlier
concern about old/new schema layers coexisting doesn't hold; the DB was otherwise in sync.

Root cause of the missing tables: `schema.sql` itself has invalid PostgreSQL syntax —
`UNIQUE(statement_type, framework_id, item_order) WHERE framework_id IS NOT NULL` as an
inline table constraint, which Postgres rejects (partial uniqueness requires a separate
`CREATE UNIQUE INDEX ... WHERE ...`, not an inline `UNIQUE(...)`). This is very likely
*why* the table was never deployed at all — anyone applying `schema.sql` fresh would hit
this exact syntax error on this exact statement. Fixed in `database/schema.sql` (split
into a normal `UNIQUE(...)` plus a separate partial `CREATE UNIQUE INDEX`), then created
both missing tables + their indexes directly in the live DB from the corrected definition.
Verified: the "relation dim_statement_templates does not exist" error is completely gone.

**New issues surfaced by re-running with the schema fixed, then fully resolved**
(2026-08-22): `income_statement_math` and `balance_sheet_displayed_math` both traced to
the same root cause — `get_or_create_period()` (`database/load_financial_data.py`) matched
periods on exact `(start_date, end_date, instant_date)` only, with no fallback. XBRL and
SEC-API report the same fiscal year with different date conventions (XBRL:
start=2023-01-01/end=2024-01-01; SEC-API gap-fill: end=2023-12-31, no start) — these
became two *different* `period_id`s for the same real-world period, each holding a partial
subset of that period's facts (confirmed directly: one period had
`income_before_tax`+`net_income` but not `income_tax_expense`; the math check naturally
fails when it can only see half a period's facts). Same pattern for instant/balance-sheet
periods. Fixed by adding a same-`period_type`+same-`fiscal_year` fallback match to
`get_or_create_period()`, mirroring the fallback `get_or_create_filing()` already had.
Also had to clean up ~58 orphaned duplicate period rows accumulated in `dim_time_periods`
from testing across today's session before the fix landed — the exact-match query finds
old duplicates first, so the new fallback only prevents *future* duplicates, it doesn't
retroactively merge existing ones.

**Correction, same day**: initially verified as a full clean-state `SUCCESS` with zero
critical issues — that was real, but turned out not to be reproducible. A second clean run
hit a *different* failure: `income_statement_math` and `balance_sheet_displayed_math`
again, this time traced to a genuinely new, distinct cause — see "Known open issue:
phantom income-statement period" below. The period-dedup fix itself is still confirmed
correct (verified directly: the 2022/2023 periods are clean singletons in both runs, no
regression there) — but it wasn't sufficient to guarantee a clean pipeline run on its own.
**Do not treat item 6 as fully closed for "pipeline succeeds end-to-end" purposes** — the
schema fix and the period-dedup fix are both real and done, but a full successful run is
not yet reliably reproducible.

---

## Known open issue: phantom income-statement period (found 2026-08-22, not yet diagnosed)

A second clean pipeline run (same code, same starting DB state as the one that reported
`SUCCESS`) failed instead on a period with `fiscal_year=2025`, `end_date=2025-12-31`,
`period_type=duration`, holding a full set of `fact_income_statement` rows — revenue
309,064,000,000, income tax split into `current_tax_expense_income` (30,239,000,000) and
`deferred_tax_expense_income` (-1,179,000,000) rather than the single
`income_tax_expense_continuing_operations` label `income_statement_math`'s query looks
for.

What's confirmed:
- This is **not** the same bug as the period-dedup fix above. The 2022/2023 periods stayed
  clean singletons in this same run.
- The revenue figure (309,064,000,000) matches **no** fact anywhere in `fact_financial_metrics`
  or in the raw XBRL extraction — the real, correctly-tagged FY2024 consolidated Revenue
  (period `2024-01-01` to `2025-01-01`) is 290,403,000,000, confirmed directly against the
  raw parsed facts. So this period's data in `fact_income_statement` isn't a
  differently-dated copy of real data; it doesn't trace back to any single known source row.
- `fact_financial_metrics` has zero rows for `fiscal_year=2025`/`duration` at all, yet
  `fact_income_statement` has 18 rows for that period — meaning whatever populated it did
  not go through the normal `fact_financial_metrics` → `fact_income_statement` path.

What's not yet known: where this period and its values actually come from. Candidates not
yet checked: `src/utils/calculate_missing_totals.py` (computes derived totals — worth
checking whether it can synthesize an entire phantom period rather than just filling one
missing total), a dimensional/segment fact being aggregated into what should be a
consolidated-only figure, or something in `populate_statement_facts.py`'s income-statement
population query. Start by checking whether this reproduces on a second company (would
suggest a general bug) or is NVO-specific (would suggest something about NVO's particular
XBRL structure, e.g. a forward-looking or restated-figures section).

**Fixed and verified, 2026-08-22 (later same session)**: the `dim_filings` duplication
mechanism was real and is now fixed. `fill_missing_from_database()` /
`run_post_load_gap_filling()` (`src/utils/post_load_gap_filling.py`) built each
supplementary batch's temp JSON using the loop's comparative-year variable as `'year'` /
`fiscal_year_end` — but `filing_id` identifies one filed *document*, which legitimately
contains multiple *periods* (current year + comparatives). Using the data year as if it
were the filing year meant `get_or_create_filing()` created a separate, wrong filing
record per comparative year instead of attaching supplementary facts to the one filing
they belong to. Added `primary_year`/`filing_type` parameters threaded through from
`src/main.py` (which already knows the actual filing's year) so the temp JSON always
targets the correct filing regardless of which comparative year's data is being added.
Verified: `dim_filings` now stays at exactly 1 row for NVO across multiple runs, including
one that failed for an unrelated reason (see below) — this fix holds independent of that.

**Separately confirmed the same session**: the intermittent empty
`fact_comprehensive_income`/`fact_equity_statement` (the exact symptom item 5 was supposed
to have fixed) is a *different*, still-open issue, not a regression of this fix or of item
5 — logically ruled out because it occurs inside the primary load (Step 5), before Step 6
(where the filing-scoping fix lives) ever executes. Traced one layer further than before:
`rel_statement_items` — populated by `populate_statement_items.py`, and what
`populate_comprehensive_income()`/`populate_equity_statement()` actually join against, NOT
`fact_financial_metrics` directly — had zero `comprehensive_income`/`equity_statement`
rows on the failing run, despite the underlying facts being correctly present and
classified in `fact_financial_metrics` (confirmed: 28 comprehensive-income-related
concepts with real data). So the break is specifically in how
`populate_statement_items.py` classifies concepts into `rel_statement_items` — and that
classification most plausibly depends on the still-broken presentation hierarchy (item 3's
still-open `pres_rels` gap), which would explain why it works sometimes (when some fallback
path succeeds) and not others. **Not yet fixed** — `populate_statement_items.py`'s
classification logic hasn't been read in detail. This is now the most concrete next
foothold: item 3's presentation-hierarchy gap is very likely the common root cause behind
both this and item 4's original UI-test ordering warnings, not a cosmetic issue as it
first looked.

**Update, continued investigation same day — down to 1 of the original 3 remaining
issues**:

- **`fact_comprehensive_income` empty: fixed.** The actual root cause was neither a
  duplicate period nor a phantom filing — `dim_concepts` is a shared, persistent
  dimension table, and `get_or_create_concept()` (`database/load_financial_data.py`) only
  updated `statement_type` when the existing stored value was `NULL`, never when it was
  already set to something wrong. ~70 comprehensive-income concepts had been permanently
  locked at `statement_type='income_statement'` from testing earlier in this same
  session, *before* item 5's classification fix landed — so every run after that fix
  still saw the stale value, making the fix look like it wasn't working. Changed the
  update condition to correct `statement_type` whenever the newly-extracted value differs
  from what's stored, not just when it's `NULL`. Verified: `comprehensive_income` dropped
  out of the failure list entirely on the next run, self-healing all ~70 already-poisoned
  concepts with no separate data migration needed (concept_id stays stable, so existing
  fact rows pick up the correction automatically via the join).
- **`populate_standard_presentation_order`'s blanket gate: fixed.** Separately, the outer
  `if existing_count == 0` check in `load_json_file()` (deciding whether to run the
  standard-order fallback at all) skipped the fallback whenever a filing had *any* real
  XBRL presentation relationships — even if only for some statement types, leaving others
  (comprehensive_income) with zero coverage and no fallback. Removed the gate — the
  function is safe to call unconditionally (its own per-concept `NOT EXISTS` check already
  avoids touching concepts with real coverage). Also extended its statement_type filter to
  include `comprehensive_income` (real `STANDARD_TEMPLATES` entries already existed for
  it, just weren't reachable due to this filter).
- **`income_statement_math` violated: fixed.** Confirmed NVO never reports a single
  combined income-tax-expense figure — only `current_tax_expense_income` +
  `deferred_tax_expense_income` separately. The check's SQL only recognized the combined
  label, so it always computed "calculated net income" using zero tax, producing a
  spurious multi-billion-DKK "violation" every single period. Added a `COALESCE` fallback
  in `check_income_statement_math()` (`src/validation/displayed_math.py`) summing the two
  components when the combined label is absent. Manually verified the correct arithmetic
  holds within tolerance for all three of NVO's fiscal years once tax is properly summed
  (e.g. FY2024: within ~0.3% of reported net income); the rule dropped out of the failure
  list on the next run.
- **`fact_equity_statement` empty: still open, and architecturally different from the
  comprehensive_income fix above** — do not assume the same fix pattern applies.
  Equity-statement line items (share capital, retained earnings, treasury shares) are
  *also*, and primarily, balance-sheet concepts — `dim_concepts.statement_type` is a
  single value per concept, so it can only ever say `balance_sheet` for these, never
  `equity_statement`, no matter how classification logic improves. Whether a given fact
  belongs in the equity rollforward is inherently contextual (which section of the filing
  it's presented in), which only genuine XBRL presentation-hierarchy data can determine —
  confirmed there's no `STANDARD_TEMPLATES['equity_statement']` entry at all, unlike the
  other four statement types. This means `fact_equity_statement` is fully dependent on
  item 3's still-open, non-deterministic Arelle presentation-relationship extraction bug,
  with no safety net. Fixing this properly requires either resolving item 3's root cause
  or building a genuinely new mechanism (not a concept-based template) — bigger scope than
  today's fixes, deliberately not started.

**Net result this session**: down from 6 critical issues (original diagnosis) to 1
(`fact_equity_statement`, architecturally distinct, scoped above). Every other concrete
issue found today has a confirmed root cause and a verified fix.

### 7. Build the first real regression test
**Why last, but non-negotiable**: this is the piece that was missing the whole time. Every
item above should ship with (or be immediately followed by) a fixture-based test that
fails loudly if it regresses — not another hand-run verification script. Concretely:
- A pinned set of known-correct values for NVO 2024 (a handful of balance sheet, income
  statement, and cash flow figures, hand-verified against the actual filing)
- A pytest test that loads NVO's data and asserts those values are present and correct in
  `fact_financial_metrics` after a pipeline run
- Wire it into a real `pytest` invocation that's actually run before considering any of the
  above "done" — not just written and forgotten like `tests/test_extraction_completeness.py`
  was (referenced by the stale `.pytest_cache`, file no longer exists anywhere)
**Status**: first pass done, 2026-08-22 — `tests/test_nvo_golden_path.py`, 8 tests, all
passing. Deliberately extraction/gap-fill-level rather than full-pipeline+DB, so it runs in
~5 seconds with no Postgres/Docker dependency (SEC filings are cached locally after the
first run). Covers: extraction doesn't crash (item 3), consolidated Revenue is the right
order of magnitude — catches a regression of the decimals-scale bug (initial fix), the
2022 Assets gap is genuinely absent from the primary filing and correctly recoverable via
comparative-filing fill with the exact expected value 241,257,000,000 (item 4),
comprehensive-income concepts classify correctly including the accumulated-vs-flow
distinction (item 5), and the equity-statement population dependency no longer includes
comprehensive_income (item 5). Project-wide collectible test count went from 1 (a live-API
integration test with no fixture data) to 9.

**Deliberately not covered yet**: a full pipeline+DB integration test, since the pipeline
doesn't yet pass its own hard-fail gate end-to-end (item 6's two new math-check issues are
still open) — writing that test now would either be permanently red or would need to
assert around known-broken behavior, neither of which is good sanity-check hygiene. Add it
once item 6 closes.

---

## After NVO: what "incrementally easier" should mean for company #2

Some of today's fixes already benefit every company, not just NVO — the XBRL `decimals`
scale bug and the generic UI test both apply universally, and AAPL's data loaded
reasonably cleanly today even before this plan starts (152/43/21 facts across balance
sheet/income statement/cash flow, no equity or comprehensive income — same gaps NVO has).
So progress on NVO and progress on breadth aren't purely sequential anymore.

Once NVO passes definition-of-done: rerun the same check against AAPL (already has cached
data, US-GAAP not IFRS, single-table income+comprehensive-income layout instead of NVO's
side-by-side — a genuinely different structural case) and see whether it passes with
little or no new work. That's the real test of whether the original "each company gets
easier" hypothesis holds, now that it's actually checkable instead of assumed.
