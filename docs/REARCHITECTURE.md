# FinSight Re-architecture — Decision Record

**Status:** Decided (2026-10-14) · **Phase 0 (de-risk spike):** complete, evidence below.

## Problem

FinSight v1.0 extracts financials the hardest possible way: download inline XBRL →
parse with Arelle → reconstruct statements from presentation linkbases (often absent in
inline filings) → a hand-maintained normalization dictionary → custom period resolution →
then patch gaps with the SEC companyfacts API. Every one of those layers is a source of
per-company bugs.

Loading 6 companies surfaced **3 distinct load-blocking bug classes**:
- **Period mis-attribution** — a global `dim_time_periods` keyed by fiscal-year let Apple's
  Sept-ending FY2024 and NVIDIA's Jan-ending FY2025 (both derive to "fiscal_year 2024")
  collide, stamping one company's facts onto another's dates.
- **Silent fact drops** — a query referenced a non-existent `dim_companies.currency` column,
  so large-value facts without an explicit unit were dropped (this is how MSFT's cash-flow
  line items went missing and `fact_cash_flow` came up empty at the validation gate).
- **Dual-source conflict** — companyfacts bolted on as a *secondary patch over* the Arelle
  parse created XBRL-vs-SEC_API period/overwrite conflicts.

The requirement is "works for every public SEC filer." A 3-in-6 bug rate on the current
architecture is **non-convergent** — these are the well-documented hard problems of XBRL
(cross-company tag inconsistency, extension tags, period-context matching), not one-offs.

## Options evaluated

| Option | Summary | Verdict |
|---|---|---|
| **Status quo** | Keep fixing per-company bugs in the Arelle-primary pipeline | Non-convergent; unbounded time; never "all filers" |
| **B — flip it ourselves** | SEC structured data as skeleton + our XBRL as enrichment, built from scratch | Correct architecture, but ~2–3× the effort — it *reimplements* what edgartools already is |
| **A — adopt edgartools** | Use [edgartools](https://github.com/dgunning/edgartools) (2.8k★, MIT) behind a thin adapter; keep our warehouse/API/validation/dashboard | **Chosen** |

Key reframe: **edgartools already *is* the flipped architecture** — companyfacts as the
clean skeleton + filing-XBRL for statement/dimensional detail — hardened across the whole
EDGAR corpus for years. "Flip it ourselves" = reimplement a mature library.

Control is kept the cheap way: **pin the dependency, wrap it behind our own adapter
interface**, upgrade deliberately. Do not hard-fork (that trades one maintenance burden for a
worse one). The adapter seam also makes the choice reversible — the extraction layer can be
swapped later without touching the warehouse/API/dashboard.

## Phase-0 evidence (why this isn't speculation)

edgartools 5.62.0, 5 deliberately-hard filers, ~2 minutes:

| Filer | Case | Result |
|---|---|---|
| AAPL | clean US-GAAP | rev $416.16B, NI $112.01B, assets $359.24B — correct |
| AVGO | **Nov fiscal-year** (caused our period collisions) | rev $63.89B, NI $23.13B — **exactly our verified numbers** |
| JPM | **bank** (different structure) | `is_financial_institution=True`, assets $4.4T, NI $57B — loads clean |
| NVO | **IFRS 20-F** (we had to *remove* this filer) | loads with **currency auto-detected (kr/DKK)**, rev 309B kr |
| PLTR | small / newer / extensions | loads clean |

**Zero failures, zero period bugs, zero currency bugs** — including the three cases that beat
the custom pipeline.

**Dimensional granularity (the frontfill concern):** edgartools' filing-level XBRL
(`filing.xbrl()`) returns the same ~1,710 facts our Arelle parse produced, **with full
dimensions** (`srt:ProductOrServiceAxis`, `us-gaap:StatementBusinessSegmentsAxis`,
`srt:StatementGeographicalAxis`) and a `query().by_concept().by_dimension()` API. It pulled
AVGO's **Products $44.85B / Subscriptions & Services $19.04B** — matching our dashboard to the
decimal. So edgartools delivers *both* the clean skeleton *and* the dimensional detail;
companyfacts' granularity limit does not apply to edgartools as a whole.

## Target architecture

```
edgartools
  ├── companyfacts  → clean skeleton: core financials, periods, currency (every filer)
  └── filing XBRL   → detail: 1,710-fact-level data + dimensions + footnotes (query API)
        │
        ▼
  FactExtractor adapter (our seam)  →  ExtractionResult(facts[])
        │
        ▼
  slim loader  →  PostgreSQL star schema  →  Flask API  →  dashboard
                        ▲
                   validation (hard integrity gates + soft warnings)
```

## Keep vs retire

**Keep (the real assets):** the PostgreSQL star schema, the Flask API, the dashboard, the
concept→label mapping (repurposed), and the two *sound* validators (reported balance-sheet
identity; unit-scaling). Keep the principle: hard integrity gates, fragile heuristics as
warnings only.

**Retire (the bug sources):** `post_load_gap_filling.py` (nothing to gap-fill), the
`get_or_create_period` fiscal-year fallback (periods arrive pre-attributed), the
`populate_statement_facts.py` statement reconstruction, the Arelle-primary parse + the
inline-XBRL downloader as the primary path, and the cross-company heuristic validators.
Phase-4 custom XBRL enrichment is **largely unnecessary** — edgartools' filing-XBRL query
layer already provides dimensions.

**Today's uncommitted period-session fixes:** drop them — they fix problems that disappear
with this architecture. Keep the honest README + ROADMAP + v1.0.0 tag (already shipped);
ROADMAP item #1 (period bug) becomes "resolved by architecture."

## Migration plan

| Phase | What | Est. |
|---|---|---|
| 0 — de-risk spike | ✅ done — evidence above | — |
| 1 — adapter + slim loader | `EdgarToolsExtractor → ExtractionResult`; slim upsert into existing star schema; load the 6 + JPM + NVO | 4–6 h |
| 2 — wire API + dashboard | point Flask at new data; confirm dashboard renders | ✅ done |
| 3 — validation | ✅ done — `src/validation/quality.py`: balance-sheet identity + unit/scale as hard gates, income-math/EPS as warnings, per-filing quality report (`data/quality_reports/`), run automatically on load | ✅ done |
| 4 — dimensional detail | via edgartools filing-XBRL query layer (not custom Arelle) | incremental |
| 5 — bulk backbone (later) | SEC Financial Statement Data Sets for batch/commercial scale | — |

**"Works for every filer + dimensions + dashboard" ≈ 8–12 hrs** — bounded, vs the
unbounded per-company whack-a-mole of the status quo.

### Phase-3 result & two correctness fixes it surfaced

All 8 reference filers pass the hard gates; 7 score a perfect 1.00, AMZN 0.95 (it genuinely
doesn't tag a standalone `us-gaap:Liabilities` subtotal — correctly surfaced as a warning,
not a failure). The balance-sheet identity verifies across taxonomies, e.g. NVO (IFRS):
`Assets = EquityAndLiabilities = 542,902M DKK`.

Building the validator surfaced two real extraction bugs, now fixed:
- **Instant dates were dropped.** edgartools carries instant-fact dates in `period_instant`
  (not `period_end`, which is NaN for instants); the adapter read the wrong column, so every
  instant fact landed on a single NULL-dated period. That collapsed all balance-sheet years
  onto one `period_id`, silently deduping prior-year comparatives away. Fixed → fact counts
  rose (AVGO 1357→1707) as comparatives returned, and the balance gate can pin the year-end.
- **Fiscal-year-end came from forward-looking disclosures.** Deriving it from `max(period_end)`
  picked up lease-maturity / revenue-remaining-performance-obligation dates past the year-end.
  Now taken from `dei:DocumentPeriodEndDate` (edgartools `period_of_report`).
- **Loader made idempotent** on the `dim_filings` unique key, so reloads reuse the filing row
  instead of aborting.

## Honest caveats

- **Bank "revenue" is a product decision** — banks have no single revenue line; edgartools
  gives correct facts, you define the composite.
- **Be explicit about period** — getters default to the latest annual.
- **Dimensional data has hierarchy** — axis members include sub-totals; navigate the dimension
  combinations to separate a clean total from its breakdown (a query concern, supported).
- **Dependency discipline** — pin the version, wrap behind the adapter, upgrade deliberately.
- **Residual long tail** — messy extensions, restatements, odd small-caps still need
  data-quality polish, but that is no longer *does-it-load-at-all*.
