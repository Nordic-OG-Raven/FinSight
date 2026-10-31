"""Curated description of each medallion layer: a plain-English explanation plus a short,
faithful code excerpt, for the transparency UI (/api/lineage/layers).

This is a CURATED MIRROR of the real pipeline, not a live read of it. We deliberately do not
read dbt/models/**.sql from disk at request time: the deployed API image is not guaranteed to
ship the dbt sources, and raw dbt Jinja ({{ ref() }}, macros) is not readable to an end user.
The excerpts below are trimmed from the real models — KEEP THEM IN SYNC when the models change:
  bronze -> src/ingestion/bronze.py (DDL)
  silver -> dbt/models/silver/stg_facts.sql, dbt/models/silver/fct_financial_facts.sql
  gold   -> dbt/models/gold/v_facts_hierarchical.sql
"""
from __future__ import annotations

LAYERS = [
    {
        "id": "bronze",
        "title": "Bronze — raw SEC filings",
        "source": "bronze.raw_filings, bronze.raw_facts",
        "explanation": (
            "The untouched landing zone. Every fact is stored exactly as it was tagged in the "
            "company's SEC filing (XBRL): the original concept name, the value in its native "
            "currency, the exact reporting dates, and any segment dimensions as raw JSON. Nothing "
            "is cleaned, converted, or combined here. Each fact points at the filing it came from "
            "(its accession), which is what makes every number downstream traceable back to source."
        ),
        "code": (
            "CREATE TABLE bronze.raw_filings (\n"
            "    accession        TEXT PRIMARY KEY,   -- the SEC filing id\n"
            "    ticker           TEXT NOT NULL,\n"
            "    cik              TEXT,               -- SEC company id (builds the EDGAR link)\n"
            "    form             TEXT NOT NULL,      -- 10-K, 10-Q, 8-K, ...\n"
            "    filing_date      DATE,\n"
            "    period_of_report DATE\n"
            ");\n\n"
            "CREATE TABLE bronze.raw_facts (\n"
            "    accession      TEXT REFERENCES bronze.raw_filings(accession),\n"
            "    concept        TEXT,          -- raw XBRL concept, e.g. us-gaap:Revenues\n"
            "    value_numeric  DOUBLE PRECISION,\n"
            "    unit           TEXT,          -- native currency / 'shares' / 'pure'\n"
            "    period_start   DATE, period_end DATE, instant_date DATE,\n"
            "    dimensions     JSONB          -- segment breakdowns, as filed\n"
            ");"
        ),
    },
    {
        "id": "silver",
        "title": "Silver — conformed facts",
        "source": "dbt silver: stg_facts, fct_financial_facts",
        "explanation": (
            "The clean-up layer. Three things happen. (1) Each fact is converted to a USD value "
            "using the exchange rate on its reporting date, so foreign filers line up with US ones. "
            "(2) A reliable fiscal year is derived from the period-end date (the as-filed tag is "
            "unreliable for companies whose year does not end in December). (3) The same period's "
            "numbers appear in many filings (a 10-K repeats last year's figures); we keep exactly "
            "one row per economic fact, from the most recently filed source, and resolve a single "
            "canonical label so synonymous concepts (several XBRL tags that all mean 'revenue') "
            "reconcile one-to-one. The source filing (accession) is carried through untouched."
        ),
        "code": (
            "-- stg_facts: attach the filing, convert to USD, derive a reliable fiscal year\n"
            "select rf.ticker, rf.accession, fl.form, rf.concept, rf.value_numeric,\n"
            "       case when currency = 'USD' then value_numeric\n"
            "            else value_numeric * fx.rate_to_usd end            as value_usd,\n"
            "       extract(year from period_end)\n"
            "         + (period_end's month > fiscal_year_end month)        as fiscal_year\n"
            "from bronze.raw_facts rf join bronze.raw_filings fl using (accession);\n\n"
            "-- fct_financial_facts: keep one row per economic fact (latest filing wins)\n"
            "row_number() over (\n"
            "    partition by ticker, concept, period_type, period_start, period_end,\n"
            "                 instant_date, coalesce(dimension_hash, '')\n"
            "    order by period_of_report desc, accession desc\n"
            ") = 1"
        ),
    },
    {
        "id": "gold",
        "title": "Gold — serving marts",
        "source": "dbt gold: v_facts_hierarchical (+ earnings, company_quarterly, segments)",
        "explanation": (
            "The read-optimised serving layer the apps actually query. Facts are denormalised into "
            "wide tables with segment dimensions pre-computed, so a page load is a single indexed "
            "read instead of a slow join. This view carries the accession, which is what powers the "
            "trace: every number the product shows can be followed straight back to the exact SEC "
            "filing it came from."
        ),
        "code": (
            "-- v_facts_hierarchical: denormalised serving table, one indexed read per request\n"
            "select\n"
            "    f.ticker,\n"
            "    f.accession,                 -- carried from silver: the trace anchor\n"
            "    f.concept          as concept_name,\n"
            "    f.value_numeric, f.value_usd, f.unit as unit_measure,\n"
            "    f.fiscal_year, f.fiscal_period, f.statement_type,\n"
            "    f.dimensions       as dimension_json\n"
            "from fct_financial_facts f;"
        ),
    },
]

_BY_ID = {layer["id"]: layer for layer in LAYERS}


def all_layers() -> list[dict]:
    """Return the ordered bronze -> silver -> gold layer descriptions."""
    return LAYERS


def get_layer(layer_id: str) -> dict | None:
    """Return one layer description by id ('bronze' | 'silver' | 'gold'), or None."""
    return _BY_ID.get(layer_id)
