-- v_facts_hierarchical: denormalized convenience view over the star schema, used by the
-- Streamlit data viewer (src/ui/data_viewer_v2.py) and handy for ad-hoc SQL.
--
-- Joins facts to company + concept so a reader gets ticker / concept_name / normalized_label
-- without writing the joins, and exposes period_id / dimension_id for optional further joins
-- to dim_time_periods / dim_xbrl_dimensions.
--
-- hierarchy_level and parent_normalized_label are exposed as NULL: the presentation-linkbase
-- hierarchy of the retired Arelle pipeline is no longer computed (see docs/REARCHITECTURE.md),
-- but the columns are kept so consumers that reference them keep working.

DROP VIEW IF EXISTS v_facts_hierarchical;
CREATE VIEW v_facts_hierarchical AS
SELECT
    f.fact_id,
    c.ticker,
    c.company_id,
    co.concept_name,
    co.taxonomy,
    co.concept_id,
    f.normalized_label,
    f.fiscal_year,
    f.period_type,
    f.value_numeric,
    f.value_usd,
    f.value_text,
    f.unit_measure,
    NULL::integer AS hierarchy_level,
    NULL::text    AS parent_normalized_label,
    f.dimension_id,
    f.period_id,
    f.filing_id,
    f.context_id,
    f.is_primary,
    f.source
FROM fact_financial_metrics f
JOIN dim_companies c ON f.company_id = c.company_id
JOIN dim_concepts  co ON f.concept_id = co.concept_id;
