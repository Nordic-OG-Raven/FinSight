"""Curated description of each medallion layer: a plain-English explanation plus the FULL,
faithful code for that layer, for the transparency UI (/api/lineage/layers).

This is a CURATED MIRROR of the real pipeline, not a live read of it. We deliberately do not
read dbt/models/**.sql from disk at request time: the deployed API image is not guaranteed to
ship the dbt sources, and raw dbt Jinja ({{ ref() }}, macros) is not readable to an end user.
The code below reproduces the real modules faithfully — dbt Jinja is resolved to the
schema-qualified tables it compiles to, and secrets (identity email, DSN, API keys) are shown
as placeholders — so the UI can say "here is exactly how this layer works." KEEP IN SYNC when
the real code changes:
  bronze       -> src/ingestion/bronze.py + src/extraction/edgartools_adapter.py
  silver       -> dbt/models/silver/stg_facts.sql, dbt/models/silver/fct_financial_facts.sql
  gold         -> dbt/models/gold/company_quarterly.sql
  intelligence -> src/analysis/pit.py, src/analysis/forecasting_v2.py

Each LAYERS entry carries: id, title, source, explanation, code (full faithful code), and
highlight (2-4 exact substrings present in `code`, marking the most important line(s); the
frontend highlights any code line containing one of them). all_layers() is returned verbatim
by the API, so any new field flows through automatically.
"""
from __future__ import annotations

LAYERS = [
    {
        "id": "bronze",
        "title": "Bronze — extract + load from SEC EDGAR",
        "source": "bronze.raw_filings, bronze.raw_facts",
        "explanation": (
            "Pulled straight from SEC EDGAR into the untouched landing zone. We resolve a ticker "
            "to its company, pull the filing's inline XBRL (the machine-readable data behind every "
            "annual 10-K and quarterly 10-Q), and store every fact exactly as it was tagged: the "
            "original concept name, the value in its native currency, the exact reporting dates, "
            "and any segment dimensions as raw JSON. Nothing is cleaned, converted, or combined "
            "here — that starts in Silver. Each fact points at the filing it came from (its "
            "accession number), which is what makes every number downstream traceable back to "
            "source. Landing is idempotent per accession: an accession is an immutable SEC "
            "artifact, so re-landing it replaces its facts in place rather than duplicating them. "
            "The facts land in bronze.raw_filings + bronze.raw_facts."
        ),
        "code": '''# ============================================================================
# src/extraction/edgartools_adapter.py  —  EXTRACT: pull XBRL facts from EDGAR
# ============================================================================
# This is the SEAM: it turns edgartools output into FinSight's own ExtractionResult,
# so the warehouse/loader never depends on edgartools internals.

import edgar


class EdgarToolsExtractor:
    """Extract one filing's facts (with dimensions) into an ExtractionResult."""

    def __init__(self, identity: str = "Your Name <you@example.com>"):
        # SEC requires a descriptive User-Agent identity on every request.
        edgar.set_identity(identity)

    # Annual-report forms, in preference order: domestic 10-K, then foreign-filer 20-F / 40-F.
    _ANNUAL_FORMS = ("10-K", "20-F", "40-F")

    def extract_filings(self, ticker: str, forms=("10-Q",), limit: int = 8,
                        skip_accessions=frozenset()) -> list:
        """Extract up to `limit` most-recent filings per form (newest first) for `ticker`.

        Builds quarterly history (10-Q) for the forecasting marts; also pulls annual
        back-history. Filings whose accession is in `skip_accessions` are skipped BEFORE
        the (expensive) XBRL parse — the incremental path (only land genuinely-new filings).
        A filing whose XBRL fails to parse is skipped with a note, not aborting the run."""
        company = edgar.Company(ticker)                 # resolve ticker -> CIK
        results = []
        for form in forms:
            try:
                filings = company.get_filings(form=form)
            except Exception as e:                      # surface and continue
                print(f"  [extract_filings] {ticker} {form}: no filings ({e})")
                continue
            chosen = filings.latest(limit) if hasattr(filings, "latest") else list(filings)[:limit]
            if chosen is None:
                continue
            # .latest(1) returns a single Filing; .latest(n>1) a Filings collection — normalize.
            if hasattr(chosen, "xbrl"):
                chosen = [chosen]
            else:
                chosen = list(chosen)
            for filing in chosen:
                acc = getattr(filing, "accession_no", "?")
                if acc in skip_accessions:
                    continue                            # already landed (incremental)
                try:
                    results.append(self._result_from_filing(company, ticker, filing, form))
                except Exception as e:                  # one bad filing shouldn't kill the batch
                    print(f"  [extract_filings] skip {ticker} {form} {acc}: {e}")
        return results

    def _result_from_filing(self, company, ticker, filing, form_hint=None):
        """Turn one edgartools Filing into an ExtractionResult (the XBRL -> facts seam)."""
        xb = filing.xbrl()                              # the filing's inline XBRL
        df = xb.facts.to_dataframe()                    # ~1,500 facts in one 10-K
        std_map = _standard_concept_map(xb)             # {raw concept -> standard concept}

        dim_cols = [c for c in df.columns if c.startswith("dim_")]

        facts = []
        for row in df.to_dict("records"):
            # segment dimensions (e.g. business segment, geography) kept as {axis: member}
            dims = {
                c[len("dim_"):]: row[c]
                for c in dim_cols
                if row.get(c) not in (None, "") and str(row.get(c)) != "nan"
            }
            nv = row.get("numeric_value")
            try:
                nv = float(nv) if nv is not None and str(nv) != "nan" else None
            except Exception:
                nv = None
            pt = row.get("period_type")
            # Instants carry their date in `period_instant` (period_start/period_end are NaN);
            # durations carry period_start/period_end. Read the right column per period type.
            instant = _as_date(row.get("period_instant")) if pt == "instant" else None
            facts.append(Fact(
                concept=row.get("concept"),             # raw tag, e.g. "us-gaap:Revenues"
                label=row.get("label") or row.get("original_label"),
                value_numeric=nv,
                value_text=None if nv is not None else row.get("value"),
                unit=row.get("currency") or row.get("unit_ref"),
                period_start=_as_date(row.get("period_start")),
                period_end=_as_date(row.get("period_end")),
                instant_date=instant,
                period_type=pt,
                fiscal_year=int(row["fiscal_year"]) if row.get("fiscal_year") not in (None, "", "nan") else None,
                fiscal_period=row.get("fiscal_period"),
                statement_type=_statement_type(row.get("statement_type")),
                dimensions=dims or None,
                is_dimensioned=bool(row.get("is_dimensioned")),
                standard_label=std_map.get(row.get("concept")),
            ))

        meta = CompanyMeta(
            cik=str(getattr(company, "cik", "")),
            ticker=ticker,
            name=getattr(company, "name", ticker),
            currency=None,
            is_financial_institution=bool(company.is_financial_institution()),
        )
        fmeta = FilingMeta(
            accession=getattr(filing, "accession_no", ""),
            form=getattr(filing, "form", form_hint),
            filing_date=_as_date(getattr(filing, "filing_date", None)),
            # Authoritative fiscal-year-end = dei:DocumentPeriodEndDate (edgartools'
            # period_of_report). Do NOT derive it from max(period_end) — forward-looking
            # disclosures (lease maturities, remaining-performance-obligation timing) carry
            # dates past the year-end and would overstate it.
            period_end=(_as_date(getattr(filing, "period_of_report", None))
                        or max((f.period_end for f in facts if f.period_end), default=None)),
        )
        # derive reporting currency from the modal currency unit of numeric facts
        cur = {}
        for f in facts:
            if f.value_numeric is not None and f.unit and len(str(f.unit)) <= 4:
                cur[f.unit] = cur.get(f.unit, 0) + 1
        if cur:
            meta.currency = max(cur, key=cur.get)
        return ExtractionResult(company=meta, filing=fmeta, facts=facts)


# ============================================================================
# src/ingestion/bronze.py  —  LOAD: land every fact exactly as filed
# ============================================================================
# No conformance, no USD normalization, no canonical labels — that is silver's job.

import json
import os

import psycopg2
from psycopg2.extras import execute_values


def land(conn, r: "ExtractionResult") -> int:
    """Upsert one filing + replace its raw facts. Returns the number of facts landed."""
    acc = r.filing.accession
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bronze.raw_filings
              (accession, ticker, cik, company_name, form, filing_date, period_of_report,
               source_currency, is_financial_institution, source)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (accession) DO UPDATE SET loaded_at = now()
            """,
            (acc, r.company.ticker, r.company.cik, r.company.name, r.filing.form,
             r.filing.filing_date, r.filing.period_end, r.company.currency,
             r.company.is_financial_institution, r.source),
        )
        # idempotent: an accession is immutable -> replace its facts in place
        cur.execute("DELETE FROM bronze.raw_facts WHERE accession = %s", (acc,))
        rows = [(
            acc, r.company.ticker, f.concept, f.label, f.standard_label,
            f.value_numeric, f.value_text, f.unit, f.period_type,
            f.period_start, f.period_end, f.instant_date, f.fiscal_year, f.fiscal_period,
            f.statement_type, json.dumps(f.dimensions) if f.dimensions else None,
            _dim_hash(f.dimensions), f.is_dimensioned,
        ) for f in r.facts]
        if rows:
            execute_values(
                cur,
                """
                INSERT INTO bronze.raw_facts
                  (accession, ticker, concept, label, standard_label, value_numeric, value_text,
                   unit, period_type, period_start, period_end, instant_date, fiscal_year,
                   fiscal_period, statement_type, dimensions, dimension_hash, is_dimensioned)
                VALUES %s
                """,
                rows,
            )
    conn.commit()
    return len(rows)


def ingest(tickers, annual: bool = True, quarters: int = 8, only_new: bool = False,
           annual_count: int = 1, dsn: str | None = None) -> None:
    # DDL + bulk writes hit the Neon DIRECT endpoint (not the transaction pooler).
    dsn = dsn or os.getenv("DATABASE_URL")
    ex = EdgarToolsExtractor()
    conn = psycopg2.connect(dsn)
    try:
        ensure_schema(conn)
        total_filings = total_facts = 0
        for tk in tickers:
            # Incremental: skip accessions already landed (so weekly runs only fetch new filings).
            skip = _existing_accessions(conn, tk) if only_new else frozenset()
            results = []
            if annual:
                # annual_count>1 lands historical 10-Ks too — needed for a point-in-time Q4 series
                # (Q4 = annual minus 9-month YTD, dated to its own original 10-K).
                results.extend(ex.extract_filings(
                    tk, forms=EdgarToolsExtractor._ANNUAL_FORMS, limit=annual_count, skip_accessions=skip))
            if quarters:
                results.extend(ex.extract_filings(
                    tk, forms=("10-Q",), limit=quarters, skip_accessions=skip))
            for r in results:
                n = land(conn, r)
                total_filings += 1
                total_facts += n
                print(f"  landed {tk} {r.filing.form} {r.filing.accession} "
                      f"period_end={r.filing.period_end} facts={n}")
        print(f"DONE: {total_filings} filings, {total_facts} facts into bronze")
    finally:
        conn.close()
''',
        "highlight": [
            "company = edgar.Company(ticker)",
            "xb = filing.xbrl()",
            "INSERT INTO bronze.raw_facts",
            "ON CONFLICT (accession) DO UPDATE SET loaded_at = now()",
        ],
    },
    {
        "id": "silver",
        "title": "Silver — conform, convert to USD, dedupe to one row per fact",
        "source": "silver.stg_facts, silver.fct_financial_facts",
        "explanation": (
            "The clean-up layer, built as two dbt models. stg_facts attaches each fact to its "
            "filing, converts foreign-currency values to USD using the exchange rate on the fact's "
            "reporting date (so foreign filers line up with US ones), and derives a RELIABLE fiscal "
            "year from the period-end date — because the as-filed year tag is unreliable for "
            "companies whose year does not end in December. fct_financial_facts then does two "
            "things: (1) the same period's numbers appear in many filings (a 10-K repeats last "
            "year's figures; each 10-Q repeats the prior-year comparative quarter), so it keeps "
            "exactly one row per economic fact, from the most recently filed source; and (2) it "
            "resolves a single canonical label so synonymous concepts — several XBRL tags that all "
            "mean 'revenue' — reconcile one-to-one, while deriving a reliable fiscal quarter for "
            "52/53-week filers whose as-filed quarter tag is blank. The source filing (accession) "
            "is carried through untouched."
        ),
        "code": '''-- ============================================================================
-- silver.stg_facts  (dbt/models/silver/stg_facts.sql)
-- ============================================================================
-- materialized as a view
--
-- Conform bronze.raw_facts: type-cast, attach the filing's form + as-of date, derive the
-- reporting currency and a USD value (ECB rates via the fx_rates seed, "latest rate on or
-- before the fact's period date"), tag core lines with a canonical-label candidate, and derive
-- a RELIABLE fiscal year.
--
-- Why derive fiscal year: edgartools' per-filing `fiscal_year` tag is unreliable for the annual
-- comparatives inside a 10-K for off-December filers (e.g. NVDA's Jan year-end 10-K tagged two
-- different year-ends as "2026"). We instead derive it from the period-end date relative to the
-- company's fiscal-year-end month: FY = year(end) + (1 if month(end) > FYE_month else 0). That
-- is correct for annual periods AND quarters across Sep (AAPL), Jun (MSFT), Jan (NVDA) and Dec
-- filers alike.

with f as (
    select
        rf.ticker,
        rf.accession,
        fl.form,
        fl.period_of_report,
        rf.concept,
        split_part(rf.concept, ':', 1)                          as taxonomy,
        rf.label,
        rf.standard_label,
        rf.value_numeric,
        rf.value_text,
        rf.unit,
        rf.period_type,
        rf.period_start,
        rf.period_end,
        rf.instant_date,
        rf.fiscal_year                                          as fiscal_year_reported,
        rf.fiscal_period,
        rf.statement_type,
        rf.dimensions,
        rf.dimension_hash,
        rf.is_dimensioned,
        case when rf.period_type = 'duration'
             then (rf.period_end - rf.period_start) end         as period_days,
        case when rf.unit ~ '^[A-Z]{3}$' then rf.unit end       as currency,
        coalesce(rf.period_end, rf.instant_date)                as fx_date,
        coalesce(rf.period_end, rf.instant_date)                as fy_anchor_date
    from bronze.raw_facts rf
    join bronze.raw_filings fl using (accession)
),

-- fiscal-year-end month per company = the modal month of its full-year period ends
fye as (
    select ticker,
           mode() within group (order by extract(month from period_end)::int) as fye_month
    from f
    where period_type = 'duration' and period_days between 330 and 380
    group by ticker
),

with_fx as (
    select
        f.*,
        case
            when f.value_numeric is null then null
            when f.currency is null or f.currency = 'USD' then f.value_numeric
            else f.value_numeric * fx.rate_to_usd
        end as value_usd,
        (f.currency is not null and f.currency <> 'USD' and fx.rate_to_usd is null) as fx_unconvertible
    from f
    left join lateral (
        select r.rate_to_usd
        from silver.fx_rates r                      -- {{ ref('fx_rates') }}: the ECB rate seed
        where r.currency = f.currency
          and r.rate_date <= f.fx_date
        order by r.rate_date desc
        limit 1
    ) fx on (f.currency is not null and f.currency <> 'USD')
)

select
    wf.*,
    fye.fye_month,
    case when wf.fy_anchor_date is not null then
        extract(year from wf.fy_anchor_date)::int
        + case when extract(month from wf.fy_anchor_date) > fye.fye_month then 1 else 0 end
    end as fiscal_year,
    cl.canonical_label as canonical_candidate,
    cl.priority        as canonical_priority
from with_fx wf
left join fye on fye.ticker = wf.ticker
left join silver.canonical_labels cl on cl.concept = wf.concept   -- {{ ref('canonical_labels') }}


-- ============================================================================
-- silver.fct_financial_facts  (dbt/models/silver/fct_financial_facts.sql)
-- ============================================================================
-- materialized as a view
--
-- The conformed fact grain. Two conformance steps:
--  1. Dedup across filings. The same period's facts recur in multiple filings (a 10-K carries
--     prior-year comparatives; each 10-Q carries the prior-year comparative quarter). Keep one
--     row per economic fact, from the most-recently-filed source.
--  2. Resolve the canonical label. A core economic line (e.g. "revenue") can be tagged with
--     several synonymous concepts; assign the canonical label to the single highest-priority
--     UNDIMENSIONED concept per (company, period) so the line reconciles 1:1. Everyone else
--     keeps raw (canonical_label = NULL) — nothing is dropped.

with staged as (
    select * from silver.stg_facts
),

deduped as (
    select *,
        row_number() over (
            partition by ticker, concept, period_type, period_start, period_end, instant_date,
                         coalesce(dimension_hash, '')
            order by period_of_report desc nulls last, accession desc
        ) as rn
    from staged
),

one_per_fact as (
    select * from deduped where rn = 1
),

canonical_ranked as (
    select *,
        -- is_dimensioned is in the partition key so undimensioned facts rank only against each
        -- other; dimensioned (segment) facts never claim a canonical line.
        case when canonical_candidate is not null then
            row_number() over (
                partition by ticker, canonical_candidate, is_dimensioned,
                             period_type, period_start, period_end, instant_date
                order by canonical_priority asc, concept
            )
        end as canon_rank
    from one_per_fact
),

-- fiscal-year-end date per (company, year) from the annual income/cash-flow durations, so an
-- instant can be tagged as the YEAR-END balance vs a quarter-end balance (10-Qs contribute the
-- latter, and all of a year's quarter-end instants share that fiscal_year).
fye as (
    -- a TRUE annual period is ~1y AND ends in the company's fiscal-year-end month; this excludes
    -- trailing-twelve-month (TTM/LTM) durations 10-Qs report (e.g. AMZN's 364-day period ending
    -- in June), which are ~1y but aren't the fiscal year.
    select ticker, fiscal_year, max(period_end) as fye_date
    from canonical_ranked
    where period_type = 'duration' and period_days between 330 and 380
      and extract(month from period_end)::int = fye_month
    group by ticker, fiscal_year
)

select
    cr.ticker,
    cr.accession,
    cr.form,
    cr.period_of_report,
    cr.concept,
    cr.taxonomy,
    cr.label,
    cr.standard_label,
    case when cr.canon_rank = 1 and cr.is_dimensioned = false then cr.canonical_candidate end as canonical_label,
    cr.value_numeric,
    cr.value_text,
    cr.currency,
    cr.value_usd,
    cr.fx_unconvertible,
    cr.unit,
    cr.period_type,
    cr.period_start,
    cr.period_end,
    cr.instant_date,
    cr.period_days,
    cr.fiscal_year,
    cr.fiscal_year_reported,
    -- Derive the quarter label for quarter-grain facts instead of trusting the raw filing tag,
    -- which is BLANK ('NaN') for 52/53-week filers' 14-week quarters (e.g. AAPL/AVGO fiscal-Q1 of
    -- a 53-week year). Same rationale as deriving fiscal_year above. The quarter = how many 3-month
    -- steps the period_end sits before the fiscal-year-end month, rounded to absorb week drift
    -- (a quarter can end a few days into the next month). Validated to reproduce 100% of the
    -- 28,060 already-labeled quarters with zero changes; it only fills the blanks. Non-quarter
    -- facts (annual / YTD / instants) keep the raw fiscal_period.
    case
        when cr.period_type = 'duration' and cr.period_days between 80 and 100
             and cr.fye_month is not null
        then 'Q' || least(4, greatest(1,
             (4 - round(((cr.fye_month - extract(month from cr.period_end)::int + 12) % 12) / 3.0))::int))
        else cr.fiscal_period
    end as fiscal_period,
    cr.statement_type,
    -- period grain: annual flows, single quarters, YTD rollups, fiscal-year-end vs quarter-end instants
    case
        when cr.period_type = 'duration' and cr.period_days between 330 and 380
             and extract(month from cr.period_end)::int = cr.fye_month then 'annual'
        when cr.period_type = 'duration' and cr.period_days between 80 and 100 then 'quarter'
        when cr.period_type = 'duration' then 'ytd_or_other'  -- incl. TTM/LTM and YTD rollups
        when cr.period_type = 'instant' and cr.instant_date = fye.fye_date then 'instant'
        when cr.period_type = 'instant' then 'quarter_instant'
    end as period_grain,
    cr.dimensions,
    cr.dimension_hash,
    cr.is_dimensioned
from canonical_ranked cr
left join fye on fye.ticker = cr.ticker and fye.fiscal_year = cr.fiscal_year
''',
        "highlight": [
            "order by period_of_report desc nulls last, accession desc",
            "(4 - round(((cr.fye_month - extract(month from cr.period_end)::int + 12) % 12) / 3.0))::int))",
            "case when cr.canon_rank = 1 and cr.is_dimensioned = false then cr.canonical_candidate end as canonical_label",
        ],
    },
    {
        "id": "gold",
        "title": "Gold — quarterly series with derived Q4",
        "source": "gold.company_quarterly",
        "explanation": (
            "The read-optimised serving mart the forecasting layer actually queries: a clean "
            "quarterly series per company, in USD. The star is how it handles Q4. Companies file "
            "Q1-Q3 as discrete ~90-day quarters in their 10-Qs, but Q4 is NEVER filed on its own — "
            "it only lives inside the annual 10-K as part of the full year. So Gold derives it: "
            "Q4 = annual total minus (Q1 + Q2 + Q3), for additive flow metrics like revenue and "
            "net income, and only when exactly those three quarters are present. It dates the "
            "derived Q4 to the fiscal year-end and flags it as derived (EPS Q4 is the same "
            "subtraction, which is an approximation since EPS isn't strictly additive). The result "
            "is a complete four-quarters-a-year series the models can train on."
        ),
        "code": '''-- ============================================================================
-- gold.company_quarterly  (dbt/models/gold/company_quarterly.sql)
-- ============================================================================
-- materialized as a table
--
-- Quarterly series per company (USD) for the forecasting marts.
--
-- 10-Qs report Q1-Q3 as discrete ~90-day periods; Q4 is never filed on its own (it lives in
-- the 10-K). So we take the reported quarters and DERIVE Q4 = annual - (Q1+Q2+Q3) for additive
-- flow metrics, only when exactly the three quarters are present. EPS Q4 is the same subtraction
-- (an approximation — EPS isn't strictly additive — hence is_derived flags it).

-- The additive flow metrics we derive Q4 for (inlined from a dbt {% set flow_metrics %} var):
--   ('revenue','net_income','operating_income','net_cash_from_operating_activities','eps_diluted')

with reported as (
    select
        ticker,
        fiscal_year,
        fiscal_period,
        canonical_label,
        period_end                           as quarter_end,
        value_usd,
        case fiscal_period when 'Q1' then 1 when 'Q2' then 2 when 'Q3' then 3 when 'Q4' then 4 end as quarter_num
    from silver.fct_financial_facts
    where canonical_label in ('revenue','net_income','operating_income','net_cash_from_operating_activities','eps_diluted')
      and is_dimensioned = false
      and period_type = 'duration'
      and period_days between 80 and 100
      and value_numeric is not null
      and fiscal_period in ('Q1', 'Q2', 'Q3', 'Q4')
),

fy_end as (  -- fiscal-year-end date per (company, fiscal year), for dating a derived Q4
    select ticker, fiscal_year, max(period_end) as fy_end_date
    from silver.fct_financial_facts
    where is_dimensioned = false and period_type = 'duration' and period_days between 330 and 380
    group by ticker, fiscal_year
),

annual as (
    select ticker, fiscal_year, canonical_label, value_usd as fy_value
    from gold.company_financials               -- {{ ref('company_financials') }}: annual totals
    where canonical_label in ('revenue','net_income','operating_income','net_cash_from_operating_activities','eps_diluted')
),

three_q as (
    select ticker, fiscal_year, canonical_label, sum(value_usd) as sum_q, count(*) as n_q
    from reported
    where quarter_num in (1, 2, 3)
    group by ticker, fiscal_year, canonical_label
),

derived_q4 as (
    select
        a.ticker,
        a.fiscal_year,
        'Q4'                      as fiscal_period,
        a.canonical_label,
        fe.fy_end_date            as quarter_end,
        a.fy_value - t.sum_q      as value_usd,
        4                         as quarter_num
    from annual a
    join three_q t on t.ticker = a.ticker and t.fiscal_year = a.fiscal_year
                   and t.canonical_label = a.canonical_label and t.n_q = 3
    left join fy_end fe on fe.ticker = a.ticker and fe.fiscal_year = a.fiscal_year
    -- don't double-count a quarter the filer happened to report directly as Q4
    where not exists (
        select 1 from reported r
        where r.ticker = a.ticker and r.fiscal_year = a.fiscal_year
          and r.canonical_label = a.canonical_label and r.quarter_num = 4
    )
)

select ticker, fiscal_year, fiscal_period, quarter_num, canonical_label, quarter_end,
       value_usd, false as is_derived
from reported
union all
select ticker, fiscal_year, fiscal_period, quarter_num, canonical_label, quarter_end,
       value_usd, true as is_derived
from derived_q4
''',
        "highlight": [
            "a.fy_value - t.sum_q      as value_usd,",
            "and t.canonical_label = a.canonical_label and t.n_q = 3",
            "true as is_derived",
        ],
    },
    {
        "id": "intelligence",
        "title": "Intelligence — leakage-safe forecasting + calibrated intervals",
        "source": "src/analysis/pit.py, src/analysis/forecasting_v2.py",
        "explanation": (
            "The forecasting layer, and the whole point is that it never cheats. A backtest that "
            "lets a model peek at data filed after the quarter it is 'predicting' will look "
            "brilliant and be worthless live. So every reconstruction of a company's history is "
            "point-in-time: we go back to Bronze (which keeps every filing vintage, unlike the "
            "deduped Silver/Gold), and for each quarter take the value from the latest filing dated "
            "ON OR BEFORE an `as_of` cutoff. Three models forecast next-quarter revenue: a "
            "seasonal-naive baseline (last year's same quarter, grown by the median recent "
            "year-over-year rate); trend+seasonal regressions; and the strongest signal for "
            "hyper-growth names — a guidance-beat model, where the forecast is the company's own "
            "forward guidance times (1 + the median amount it has historically beaten guidance). "
            "Everything is graded walk-forward, one quarter at a time, each forecast using only "
            "what was filed before that quarter's own 10-Q. The prediction interval is a "
            "bias-corrected Student-t band fit to those walk-forward residuals — calibrated so an "
            "'80% interval' actually covers about 80% of outcomes."
        ),
        "code": '''# ============================================================================
# src/analysis/pit.py  —  point-in-time (leakage-safe) series, read from BRONZE
# ============================================================================
# Silver/gold dedup every fact to its LATEST filing vintage (great for "what's true now",
# useless for point-in-time). For a leakage-safe backtest we must reconstruct each series
# *as it was known* at a given `as_of` date, so we go back to bronze.raw_facts (every vintage),
# join bronze.raw_filings.filing_date, and take the value from the LATEST filing dated
# on/before `as_of`.

from datetime import date
from functools import lru_cache

from sqlalchemy import text


# src/analysis/pit.py
def _fy_and_quarter(period_end: date, fye_month: int) -> tuple[int, int]:
    """Fiscal year (named by the year it ends in) + fiscal quarter number (1-4).

    Quarter = how many 3-month steps the period_end sits before the fiscal-year-end month,
    ROUNDED so a 52/53-week filer whose quarter-end drifts a few days into the next month still
    maps to the right quarter. Matches the warehouse's derivation exactly.
    """
    m = period_end.month
    fiscal_year = period_end.year + (1 if m > fye_month else 0)
    steps = ((fye_month - m + 12) % 12) / 3.0       # 0 at the fiscal-year-end, ~1 a quarter before
    quarter_num = max(1, min(4, 4 - round(steps)))
    return fiscal_year, quarter_num


# src/analysis/pit.py
@lru_cache(maxsize=8192)
def series_asof(database_url: str, ticker: str, metric: str, as_of: date) -> list:
    """Quarterly series for `metric` as it was known at `as_of`, newest-vintage-wins per quarter.

    metric: a canonical label (e.g. 'revenue') or 'segment:<name>'.
    """
    eng = _engine(database_url)
    ticker = ticker.upper()

    concepts = CANONICAL.get(metric)
    if not concepts:
        raise ValueError(f"unknown canonical metric: {metric}")
    sql = text("""
        SELECT DISTINCT ON (f.period_end)
               f.period_end, f.value_numeric, rf.filing_date, f.accession
        FROM bronze.raw_facts f
        JOIN bronze.raw_filings rf USING (accession)
        WHERE f.ticker = :t AND rf.filing_date <= :asof
          AND f.is_dimensioned = false
          AND f.concept = ANY(:concepts)
          AND f.period_type = 'duration'
          AND (f.period_end - f.period_start) BETWEEN 80 AND 100
          AND f.value_numeric IS NOT NULL
        -- newest vintage known by as_of; then canonical priority (earlier in list = preferred)
        ORDER BY f.period_end, rf.filing_date DESC, array_position(:concepts, f.concept)
    """)
    params = {"t": ticker, "asof": as_of, "concepts": concepts}

    with eng.connect() as conn:
        fye = _fye_month(conn, ticker, as_of)
        rows = conn.execute(sql, params).fetchall()

    out = []
    for period_end, value, filing_date, accession in rows:
        fy, qn = _fy_and_quarter(period_end, fye)
        out.append(Point(period_end, fy, qn, float(value), filing_date, accession))
    out.sort(key=lambda p: p.period_end)
    return out


# ============================================================================
# src/analysis/forecasting_v2.py  —  the models, the backtest, the interval
# ============================================================================

from datetime import timedelta

import numpy as np

from src.analysis import pit


# src/analysis/forecasting_v2.py
def seasonal_naive(points, t_fy, t_qn):
    """Baseline to beat: last year's same fiscal quarter, grown by the median recent YoY rate."""
    vals = {(p.fiscal_year, p.quarter_num): p.value for p in points}
    base = vals.get((t_fy - 1, t_qn))
    if base is None:
        return None
    yoy = [vals[(fy, qn)] / vals[(fy - 1, qn)] - 1
           for (fy, qn) in vals if (fy - 1, qn) in vals and vals[(fy - 1, qn)]]
    g = float(np.median(yoy[-4:])) if yoy else 0.0
    return base * (1.0 + g)


# src/analysis/forecasting_v2.py
def backtest(db, ticker, components, min_train=6) -> dict:
    """Walk-forward one-step-ahead revenue backtest with a strict point-in-time cutoff.

    For each target quarter, forecast using only filings dated before that quarter's own 10-Q,
    compare to the actual reported total. The signed % residuals feed the empirical interval.
    """
    ticker = ticker.upper()
    report_dates = pit.quarter_report_dates(db, ticker)
    # ground-truth target = latest-vintage consolidated revenue (the real reported total)
    actuals = pit.latest_series(db, ticker, "revenue")
    errs = {m: [] for m in MODELS}          # signed % errors (for residual intervals)
    apes = {m: [] for m in MODELS}
    n_eval = 0
    for tp in actuals:
        cutoff = report_dates.get(tp.period_end)
        if cutoff is None:
            continue
        as_of = cutoff - timedelta(days=1)       # strictly before this quarter's own filing
        comp_points = _series_asof(db, ticker, components, as_of)
        # need enough history known at as_of
        hist_len = max((len(p) for p in comp_points.values()), default=0)
        if hist_len < min_train:
            continue
        preds = _forecast_components(comp_points, tp.fiscal_year, tp.quarter_num)
        actual = tp.value
        if not actual:
            continue
        n_eval += 1
        for m, pred in preds.items():
            if pred is None:
                continue
            errs[m].append((actual - pred) / pred)   # signed rel. error: actual = pred*(1+err)
            apes[m].append(abs(pred - actual) / abs(actual))
    out = {}
    for m in MODELS:
        if apes[m]:
            resid = np.array(errs[m])
            out[m] = {
                "n": len(apes[m]),
                "mape": float(np.mean(apes[m]) * 100),
                "resid_std_pct": float(np.std(resid) * 100),
                "resid": resid,     # kept for empirical intervals
            }
        else:
            out[m] = {"n": 0, "mape": None, "resid_std_pct": None, "resid": np.array([])}
    out["_n_eval"] = n_eval
    return out


# src/analysis/forecasting_v2.py
def guidance_model(db, ticker):
    """Guidance-beat model: forecast = company's forward guidance x (1 + median historical beat).

    Leakage-safe: guidance for quarter T is issued at T-1's earnings (before T); the beat rate
    uses only quarters already reported. The single strongest signal for hyper-growth names.
    """
    from sqlalchemy import text

    from src.analysis import guidance as gd

    hist = gd.guidance_history(ticker)
    if len(hist) < 3:
        return None
    eng = pit._engine(db)
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT quarter_end, revenue_usd FROM gold.earnings "
            "WHERE ticker = :t AND revenue_usd IS NOT NULL ORDER BY quarter_end"
        ), {"t": ticker.upper()}).fetchall()
    acts = [(r[0].date() if hasattr(r[0], "date") else r[0], float(r[1])) for r in rows]

    def actual_after(d):
        nxt = [v for qe, v in acts if qe > d]
        return min(nxt) if nxt else None   # first quarter to END after the guidance date

    pairs = [(g.given_date, g.guided_revenue, actual_after(g.given_date)) for g in hist]
    pairs = [(d, gv, a, a / gv - 1.0) for d, gv, a in pairs if a]
    if len(pairs) < 3:
        return None
    apes, resid = [], []
    for i in range(2, len(pairs)):           # walk-forward: beat from prior pairs only
        beat = float(np.median([p[3] for p in pairs[:i]]))
        pred, act = pairs[i][1] * (1 + beat), pairs[i][2]
        apes.append(abs(pred - act) / act)
        resid.append((act - pred) / pred)   # signed rel. error: actual = pred*(1+err)
    beat = float(np.median([p[3] for p in pairs]))
    return {
        "n": len(apes),
        "mape": float(np.mean(apes) * 100) if apes else None,
        "resid": np.array(resid),
        "forecast": hist[-1].guided_revenue * (1 + beat),
        "guidance": hist[-1].guided_revenue,
        "median_beat_pct": beat * 100,
    }


# src/analysis/forecasting_v2.py
# Student-t upper-tail critical values by degrees of freedom, for the two interval levels we serve
# (80% -> 0.90 per-tail, 90% -> 0.95 per-tail). A small table keeps this dependency-free (scipy is
# not in the API/Modal images) while giving the fat small-sample tails an empirical quantile lacks.
_T_CRIT = {
    0.90: {1: 3.078, 2: 1.886, 3: 1.638, 4: 1.533, 5: 1.476, 6: 1.440, 7: 1.415, 8: 1.397,
           9: 1.383, 10: 1.372, 11: 1.363, 12: 1.356, 13: 1.350, 14: 1.345, 15: 1.341, 16: 1.337,
           17: 1.333, 18: 1.330, 19: 1.328, 20: 1.325},
    0.95: {1: 6.314, 2: 2.920, 3: 2.353, 4: 2.132, 5: 2.015, 6: 1.943, 7: 1.895, 8: 1.860,
           9: 1.833, 10: 1.812, 11: 1.796, 12: 1.782, 13: 1.771, 14: 1.761, 15: 1.753, 16: 1.746,
           17: 1.740, 18: 1.734, 19: 1.729, 20: 1.725},
}
_Z = {0.90: 1.282, 0.95: 1.645}   # normal limit (df > 20)


def _t_crit(df: int, level: float) -> float:
    tail = 0.90 if level <= 0.80 else 0.95
    if df <= 0:
        return _Z[tail]
    return _T_CRIT[tail].get(df, _Z[tail])


# src/analysis/forecasting_v2.py
def _empirical_interval(point: float, resid: np.ndarray, level=0.80):
    """Bias-corrected Student-t prediction interval on the walk-forward % residuals.

    point x (1 + mean(resid) +/- t_{df} * std(resid)). The t multiplier gives the fat tails a
    tiny empirical sample lacks, and centering on the mean residual folds in any systematic bias —
    so the band covers its nominal rate. Calibration check (n=70, seasonal tickers): nominal
    80% -> 82.9%, 90% -> 91.4% actual coverage.
    """
    if point is None or len(resid) < 3:
        return None
    r = np.asarray(resid, dtype=float)
    m, sd = float(np.mean(r)), float(np.std(r, ddof=1))
    t = _t_crit(len(r) - 1, level)
    lo = point * (1 + m - t * sd)
    hi = point * (1 + m + t * sd)
    return (float(min(lo, hi)), float(max(lo, hi)))
''',
        "highlight": [
            "WHERE f.ticker = :t AND rf.filing_date <= :asof",
            "as_of = cutoff - timedelta(days=1)       # strictly before this quarter's own filing",
            '"forecast": hist[-1].guided_revenue * (1 + beat),',
            "lo = point * (1 + m - t * sd)",
        ],
    },
]

_BY_ID = {layer["id"]: layer for layer in LAYERS}


def all_layers() -> list[dict]:
    """Return the ordered bronze -> silver -> gold -> intelligence layer descriptions."""
    return LAYERS


def layer_by_id(layer_id: str) -> dict | None:
    """Return one layer description by id ('bronze' | 'silver' | 'gold' | 'intelligence'), or None."""
    return _BY_ID.get(layer_id)


# Back-compat alias: the previous public name for layer_by_id.
get_layer = layer_by_id
