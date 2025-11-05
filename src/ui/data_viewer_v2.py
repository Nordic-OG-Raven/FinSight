#!/usr/bin/env python3
"""
FinSight Data Viewer - Star Schema Version
Interactive Streamlit application for exploring financial data from the star schema warehouse.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
from sqlalchemy import create_engine, text
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import DATABASE_URI
import re


def humanize_label(label):
    """Convert snake_case to Title Case (e.g., 'total_assets' -> 'Total Assets')"""
    if not label:
        return label
    return label.replace('_', ' ').title()


def humanize_camel_case(text):
    """
    Add spaces to CamelCase and remove XBRL jargon suffixes.
    
    Example: 
        'GeographicalAreasAxis' -> 'Geographical Areas'
        'UnitedStatesMember' -> 'United States'
    """
    if not text:
        return text
    
    # Remove common XBRL jargon suffixes (case-sensitive)
    jargon_suffixes = [
        'Axis',           # Dimension type (e.g., GeographicalAreasAxis)
        'Member',         # Dimension value (e.g., UnitedStatesMember)
        'Domain',         # Dimension domain
        'LineItems',      # Presentation grouping
        'Table',          # Presentation table
        'Abstract',       # Abstract element
        'TextBlock',      # Text disclosure block
    ]
    
    for suffix in jargon_suffixes:
        if text.endswith(suffix):
            text = text[:-len(suffix)]
            break
    
    # Insert space before uppercase letters (except at start)
    spaced = re.sub(r'(?<!^)(?=[A-Z])', ' ', text)
    return spaced


@st.cache_data(ttl=600)
def get_database_stats():
    """Get database statistics"""
    engine = create_engine(DATABASE_URI)
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
                COUNT(DISTINCT c.company_id) as companies,
                COUNT(DISTINCT co.concept_id) as concepts,
                COUNT(DISTINCT t.period_id) as periods,
                COUNT(f.fact_id) as total_facts,
                COUNT(CASE WHEN f.dimension_id IS NULL THEN 1 END) as consolidated_facts,
                COUNT(CASE WHEN f.dimension_id IS NOT NULL THEN 1 END) as dimensional_facts
            FROM fact_financial_metrics f
            JOIN dim_companies c ON f.company_id = c.company_id
            JOIN dim_concepts co ON f.concept_id = co.concept_id
            JOIN dim_time_periods t ON f.period_id = t.period_id
        """))
        return result.fetchone()


@st.cache_data(ttl=600)
def get_companies():
    """Get list of companies"""
    engine = create_engine(DATABASE_URI)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT ticker FROM dim_companies ORDER BY ticker"))
        return [row[0] for row in result]


@st.cache_data(ttl=600)
def get_normalized_labels():
    """Get list of normalized labels"""
    engine = create_engine(DATABASE_URI)
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT DISTINCT normalized_label 
            FROM dim_concepts 
            WHERE normalized_label IS NOT NULL 
            ORDER BY normalized_label
        """))
        return [row[0] for row in result]


def get_normalized_labels_for_companies(companies, start_year=None, end_year=None):
    """
    Get only normalized labels that have at least 1 data point for the selected companies.
    CRITICAL: Prevents showing metrics in dropdown that have zero data for selected companies.
    """
    if not companies:
        return get_normalized_labels()  # No companies selected = show all
    
    engine = create_engine(DATABASE_URI)
    with engine.connect() as conn:
        query = """
        SELECT DISTINCT dc.normalized_label
        FROM fact_financial_metrics f
        JOIN dim_companies c ON f.company_id = c.company_id
        JOIN dim_concepts dc ON f.concept_id = dc.concept_id
        LEFT JOIN dim_time_periods t ON f.period_id = t.period_id
        WHERE c.ticker = ANY(:companies)
          AND dc.normalized_label IS NOT NULL
          AND f.dimension_id IS NULL
          AND f.value_numeric IS NOT NULL
          AND (dc.normalized_label NOT LIKE '%_note' AND dc.normalized_label NOT LIKE '%_disclosure%' AND dc.normalized_label NOT LIKE '%_section_header')
        """
        
        params = {'companies': companies}
        
        if start_year is not None and end_year is not None:
            query += " AND t.fiscal_year >= :start_year AND t.fiscal_year <= :end_year"
            params['start_year'] = start_year
            params['end_year'] = end_year
        
        query += " ORDER BY dc.normalized_label"
        
        result = conn.execute(text(query), params)
        return [row[0] for row in result]


@st.cache_data(ttl=600)
def load_consolidated_data(companies=None, start_year=None, end_year=None, concepts=None):
    """Load consolidated facts (no dimensional breakdowns)"""
    engine = create_engine(DATABASE_URI)
    
    query = """
    SELECT 
        c.ticker as company,
        co.concept_name as concept,
        co.normalized_label,
        t.fiscal_year,
        t.period_type,
        COALESCE(t.end_date, t.instant_date) as period_date,
        f.value_numeric,
        f.value_text,
        f.unit_measure,
        fi.filing_type,
        fi.fiscal_year_end
    FROM fact_financial_metrics f
    JOIN dim_companies c ON f.company_id = c.company_id
    JOIN dim_concepts co ON f.concept_id = co.concept_id
    JOIN dim_time_periods t ON f.period_id = t.period_id
    JOIN dim_filings fi ON f.filing_id = fi.filing_id
    WHERE f.dimension_id IS NULL
    """
    
    params = {}
    if companies:
        query += " AND c.ticker = ANY(:companies)"
        params['companies'] = companies
    if start_year:
        query += " AND t.fiscal_year >= :start_year"
        params['start_year'] = start_year
    if end_year:
        query += " AND t.fiscal_year <= :end_year"
        params['end_year'] = end_year
    if concepts:
        query += " AND co.normalized_label = ANY(:concepts)"
        params['concepts'] = concepts
    
    query += " ORDER BY c.ticker, t.fiscal_year, co.concept_name"
    
    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn, params=params)
    
    return df


@st.cache_data(ttl=600)
def load_dimensional_data(companies=None, start_year=None, end_year=None):
    """Load dimensional facts"""
    engine = create_engine(DATABASE_URI)
    
    query = """
    SELECT 
        c.ticker as company,
        co.concept_name as concept,
        co.normalized_label,
        t.fiscal_year,
        f.value_numeric,
        f.unit_measure,
        d.axis_name,
        d.member_name
    FROM fact_financial_metrics f
    JOIN dim_companies c ON f.company_id = c.company_id
    JOIN dim_concepts co ON f.concept_id = co.concept_id
    JOIN dim_time_periods t ON f.period_id = t.period_id
    JOIN dim_xbrl_dimensions d ON f.dimension_id = d.dimension_id
    WHERE f.dimension_id IS NOT NULL
    """
    
    params = {}
    if companies:
        query += " AND c.ticker = ANY(:companies)"
        params['companies'] = companies
    if start_year:
        query += " AND t.fiscal_year >= :start_year"
        params['start_year'] = start_year
    if end_year:
        query += " AND t.fiscal_year <= :end_year"
        params['end_year'] = end_year
    
    query += " ORDER BY c.ticker, t.fiscal_year, co.concept_name"
    
    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn, params=params)
    
    return df


def main():
    st.set_page_config(
        page_title="FinSight Data Viewer",
        page_icon="📊",
        layout="wide"
    )
    
    st.title("📊 FinSight Financial Data Warehouse")
    st.markdown("Cross-company financial analysis from SEC and ESEF filings")
    
    # Database statistics - simplified and clearer
    stats = get_database_stats()
    if stats:
        col1, col2, col3 = st.columns(3)
        col1.metric("Companies", f"{stats[0]}")
        col2.metric("Financial Metrics", f"{stats[1]:,}")
        col3.metric("Total Data Points", f"{stats[3]:,}")
    
    st.markdown("---")
    
    # Sidebar: Customize Your Analysis
    st.sidebar.header("🎯 Customize Your Analysis")
    
    # 1. Company filter
    all_companies = get_companies()
    selected_companies = st.sidebar.multiselect(
        "Companies",
        options=all_companies,
        default=all_companies[:5] if len(all_companies) > 5 else all_companies,
        help="Select one or more companies to analyze"
    )
    
    # 2. Fiscal Year filter
    year_range = st.sidebar.slider(
        "Fiscal Year Range",
        min_value=2020,
        max_value=2025,
        value=(2023, 2024),
        help="Select the range of fiscal years to analyze"
    )
    
    st.sidebar.markdown("---")
    
    # 3. Granularity selector (dropdown instead of radio) - BEFORE metrics for better UX flow
    st.sidebar.markdown("**Granularity**")
    
    granularity_options = {
        "Universal metrics": {
            "value": 3,
            "help": "Shows totals like 'Total Assets' - all companies report these, making cross-company comparison easy. (Only applies when browsing - selected metrics always show)"
        },
        "Specific metrics": {
            "value": 2,
            "help": "Adds section breakdowns like 'Accrued Liabilities' - some companies report these, others don't. (Only applies when browsing)"
        },
        "Very very specific metrics": {
            "value": 1,
            "help": "Shows every line item - details vary by company, so comparison may be limited. (Only applies when browsing)"
        }
    }
    
    selected_granularity_label = st.sidebar.selectbox(
        "",
        options=list(granularity_options.keys()),
        index=0,  # Default to "Universal metrics"
        label_visibility="collapsed",
        help=granularity_options["Universal metrics"]["help"]
    )
    
    # Update help text dynamically
    st.sidebar.caption(f"💡 {granularity_options[selected_granularity_label]['help']}")
    
    min_hierarchy_level = granularity_options[selected_granularity_label]["value"]
    
    st.sidebar.markdown("---")
    
    # 4. Metric filter (multiselect has built-in search)
    # CRITICAL: Only show metrics that have data for selected companies
    # This prevents "phantom" metrics in dropdown that would return zero results
    all_concepts_raw = get_normalized_labels_for_companies(
        selected_companies,
        start_year=year_range[0],
        end_year=year_range[1]
    )
    
    # Create human-readable options with mapping back to raw values
    concept_display_map = {humanize_label(c): c for c in all_concepts_raw}
    human_readable_options = sorted(concept_display_map.keys())
    
    # Show humanized labels in dropdown
    selected_concepts_human = st.sidebar.multiselect(
        "Metrics",
        options=human_readable_options,
        default=[],
        help=f"Select specific metrics to analyze. Leave empty to see all metrics. Only shows {len(human_readable_options)} metrics available for selected companies."
    )
    
    # Convert back to database format for querying
    selected_concepts = [concept_display_map[h] for h in selected_concepts_human]
    
    # 5. Show segment breakdowns
    st.sidebar.markdown("---")
    show_segments = st.sidebar.checkbox(
        "Show segment breakdowns",
        value=False,
        help="Include product, geography, and other segment-level data in the analysis"
    )
    
    st.sidebar.markdown("---")
    
    # 6. Advanced Options (at bottom)
    with st.sidebar.expander("⚙️ Advanced Options"):
        show_all_concepts = st.checkbox(
            "Auditor view",
            value=False,
            help="Shows all source XBRL concepts including duplicates (e.g., both 'Assets' and 'LiabilitiesAndStockholdersEquity' for the same value). Useful for validation and auditing."
        )
        
        st.markdown("---")
        st.markdown("#### 🔍 SQL Query Tools")
        
        # Show generated SQL query
        show_sql_query = st.checkbox(
            "SQL query view",
            value=False,
            help="View the SQL query that was automatically generated based on your filters"
        )
        
        # Custom SQL query input - will be executed after engine is created
        st.markdown("**Run custom SQL query:**")
        custom_sql = st.text_area(
            "SQL query",
            height=150,
            help="Enter your own SQL query. Use 'v_facts_hierarchical' for the main data view, or query any table directly.",
            placeholder="SELECT ticker, normalized_label, fiscal_year, value_numeric\nFROM v_facts_hierarchical\nWHERE ticker = 'AAPL'\nLIMIT 10;",
            key="custom_sql_input"
        )
        
        # Button to trigger custom query execution
        run_custom_query = False
        if custom_sql:
            run_custom_query = st.button("Run Query", key="run_custom_query_btn")
    
    # Load data (unified query)
    with st.spinner("Loading data from warehouse..."):
        engine = create_engine(DATABASE_URI)
        
        # Use deduplicated view by default, raw table for debug mode
        if show_all_concepts:
            # Debug mode: show ALL source concepts (including duplicates)
            query = """
        SELECT 
            c.ticker as company,
            co.concept_name as concept,
            co.normalized_label,
            t.fiscal_year,
            f.value_numeric,
            f.value_text,
            f.unit_measure,
            d.axis_name,
            d.member_name,
            CASE WHEN f.dimension_id IS NULL THEN 'Total' ELSE 'Segment' END as data_type
        FROM fact_financial_metrics f
        JOIN dim_companies c ON f.company_id = c.company_id
        JOIN dim_concepts co ON f.concept_id = co.concept_id
        JOIN dim_time_periods t ON f.period_id = t.period_id
        LEFT JOIN dim_xbrl_dimensions d ON f.dimension_id = d.dimension_id
        WHERE 1=1
            """
        else:
            # Default: use hierarchical view (with deduplication + hierarchy levels)
            # The view has concept_name, normalized_label, fiscal_year, hierarchy_level as columns
            query = """
        SELECT 
            f.ticker as company,
            f.concept_name as concept,
            f.normalized_label,
            f.fiscal_year,
            f.value_numeric,
            f.value_text,
            f.unit_measure,
            f.hierarchy_level,
            f.parent_normalized_label,
            d.axis_name,
            d.member_name,
            CASE WHEN f.dimension_id IS NULL THEN 'Total' ELSE 'Segment' END as data_type,
            t.period_label,
            t.start_date as period_start,
            t.end_date as period_end,
            t.instant_date as period_instant,
            t.period_type,
            f.context_id
        FROM v_facts_hierarchical f
        LEFT JOIN dim_xbrl_dimensions d ON f.dimension_id = d.dimension_id
        LEFT JOIN dim_time_periods t ON f.period_id = t.period_id
        WHERE 1=1
            """
        
        params = {}
        
        # Set up correct column references based on query type
        if show_all_concepts:
            # Raw table uses joined table aliases
            fiscal_year_col = "t.fiscal_year"
            normalized_label_col = "co.normalized_label"
        else:
            # Deduplicated view has these as direct columns
            fiscal_year_col = "f.fiscal_year"
            normalized_label_col = "f.normalized_label"
        
        # Filter by selected companies
        if selected_companies:
            company_col = "c.ticker" if show_all_concepts else "f.ticker"
            query += f" AND {company_col} = ANY(:companies)"
            params['companies'] = selected_companies
        
        # Filter by year range
        query += f" AND {fiscal_year_col} >= :start_year AND {fiscal_year_col} <= :end_year"
        params['start_year'] = year_range[0]
        params['end_year'] = year_range[1]
        
        # Filter by selected concepts
        if selected_concepts:
            query += f" AND {normalized_label_col} = ANY(:concepts)"
            params['concepts'] = selected_concepts
        
        # Filter by hierarchy level (only in hierarchical view)
        # CRITICAL FIX: If user explicitly selected metrics, show them regardless of hierarchy level
        # Hierarchy filter should only apply when showing ALL metrics (browsing mode)
        if not show_all_concepts:
            if selected_concepts:
                # User explicitly selected metrics - ignore hierarchy filter (they know what they want)
                # Still allow NULL hierarchy_level as fallback
                query += " AND (f.hierarchy_level IS NULL OR f.hierarchy_level >= 1)"
            else:
                # No metrics selected = browsing mode - apply hierarchy filter
                query += " AND (f.hierarchy_level >= :min_hierarchy OR f.hierarchy_level IS NULL)"
                params['min_hierarchy'] = min_hierarchy_level
        
        # Exclude segments if not requested
        if not show_segments:
            query += " AND f.dimension_id IS NULL"
        
        # ALWAYS exclude text notes - users want numbers, not documentation
        query += f" AND ({normalized_label_col} NOT LIKE '%_note' AND {normalized_label_col} NOT LIKE '%_disclosure%' AND {normalized_label_col} NOT LIKE '%_section_header')"
        query += " AND f.value_numeric IS NOT NULL"  # Only show numeric data
        
        # Order by company, year, metric
        ticker_col = "c.ticker" if show_all_concepts else "f.ticker"
        query += f" ORDER BY {ticker_col}, {fiscal_year_col}, {normalized_label_col}"
        
        with engine.connect() as conn:
            df = pd.read_sql(text(query), conn, params=params)
            
            # Check if segments were requested but none exist
            if show_segments and not df.empty:
                # Check for segment data using data_type column (or axis_name/member_name columns)
                has_segments = False
                if 'data_type' in df.columns:
                    has_segments = (df['data_type'] == 'Segment').any()
                elif 'axis_name' in df.columns or 'member_name' in df.columns:
                    # Check if any segment data exists
                    has_segments = df['axis_name'].notna().any() if 'axis_name' in df.columns else False
                
                if not has_segments:
                    st.info("ℹ️ **Note:** Segment breakdowns are enabled, but the selected metrics don't have segment-level data in the source filings. Showing consolidated totals only. Try selecting metrics like 'Revenue' or 'Operating Income' which typically have geographic/product breakdowns.")
            
            # Execute custom SQL query if provided (from Advanced Options)
            if custom_sql and run_custom_query:
                try:
                    custom_df = pd.read_sql(text(custom_sql), conn)
                    if not custom_df.empty:
                        st.success(f"✅ Custom query returned {len(custom_df)} rows")
                        st.dataframe(custom_df, use_container_width=True)
                    else:
                        st.warning("⚠️ Custom query returned no results")
                except Exception as e:
                    st.error(f"❌ Custom query error: {str(e)}")
    
    # Show SQL query view if requested (in main area, not sidebar)
    if show_sql_query:
        with st.expander("🔍 SQL Query View", expanded=True):
            st.code(query, language='sql')
            st.write("**Query Parameters:**")
            for k, v in params.items():
                st.write(f"- `{k}`: {v}")
            st.write(f"**Rows returned: {len(df)}**")
    
    if df.empty:
        # Show detailed error message
        st.error("⚠️ No data found for selected filters")
        with st.expander("🔍 Debug Info - Why no data?"):
            st.write("**Your Filters:**")
            st.write(f"- Companies: {selected_companies if selected_companies else 'All'}")
            st.write(f"- Fiscal Years: {year_range[0]} to {year_range[1]}")
            st.write(f"- Metrics: {selected_concepts if selected_concepts else 'All'}")
            st.write(f"- Show segments: {show_segments}")
            
            st.write("\n**Possible causes:**")
            st.write("1. Selected company doesn't have data for selected metrics")
            st.write("2. Selected fiscal year range is outside available data")
            st.write("3. Metric name mismatch (check spelling)")
            
            # Show what data IS available for selected company
            if selected_companies and len(selected_companies) == 1:
                with engine.connect() as conn:
                    check_query = text("""
                    SELECT MIN(fiscal_year) as min_year, MAX(fiscal_year) as max_year,
                           COUNT(DISTINCT normalized_label) as metric_count
                    FROM fact_financial_metrics f
                    JOIN dim_companies c ON f.company_id = c.company_id
                    JOIN dim_concepts co ON f.concept_id = co.concept_id
                    JOIN dim_time_periods t ON f.period_id = t.period_id
                    WHERE c.ticker = :ticker
                      AND f.value_numeric IS NOT NULL
                      AND co.normalized_label NOT LIKE '%_note';
                    """)
                    result = conn.execute(check_query, {'ticker': selected_companies[0]})
                    row = result.fetchone()
                    if row:
                        st.write(f"\n**{selected_companies[0]} has data:**")
                        st.write(f"- Years: {row[0]} to {row[1]}")
                        st.write(f"- Metrics: {row[2]} unique metrics available")
        return
    
    st.success(f"✅ Loaded {len(df):,} facts from warehouse")
    
    # Data table
    st.subheader("📋 Data Table")
    
    # Format data for display
    display_df = df.copy()
    
    # Drop internal/technical columns that users don't need to see
    columns_to_drop = ['hierarchy_level', 'parent_normalized_label']
    for col in columns_to_drop:
        if col in display_df.columns:
            display_df = display_df.drop(col, axis=1)
    
    # Humanize normalized_label (snake_case -> Title Case)
    if 'normalized_label' in display_df.columns:
        display_df['label'] = display_df['normalized_label'].apply(
            lambda x: humanize_label(x[:47] + '...') if pd.notnull(x) and len(str(x)) > 50 else humanize_label(x) if pd.notnull(x) else x
        )
        display_df = display_df.drop('normalized_label', axis=1)
    
    # Add period information if there are multiple periods for same metric (helps differentiate duplicates)
    show_period_column = False
    if 'period_label' in display_df.columns:
        # Only show period column if:
        # 1. There are multiple rows for same metric/company/year (suggests duplicates that need differentiation)
        # 2. AND period_label has actual data (not all None/null)
        has_period_data = display_df['period_label'].notna().any() and not (display_df['period_label'].astype(str) == 'None').all()
        
        if has_period_data:
            if 'fiscal_year' in display_df.columns and 'label' in display_df.columns:
                period_diff_needed = display_df.groupby(['company', 'label', 'fiscal_year']).size()
                if (period_diff_needed > 1).any():
                    show_period_column = True
    
    # Handle segment/dimension columns - Replace "None" with empty string for better readability
    # Only hide columns if ALL values are None (pure consolidated view)
    if 'member_name' in display_df.columns:
        # Check if all values are None/null
        if display_df['member_name'].isna().all() or (display_df['member_name'].astype(str) == 'None').all():
            display_df = display_df.drop('member_name', axis=1)  # Hide column entirely
        else:
            # Humanize CamelCase in segment names, replace None with empty string
            display_df['segment'] = display_df['member_name'].apply(
                lambda x: '' if pd.isna(x) or str(x) == 'None' else (humanize_camel_case(x[:37] + '...') if len(str(x)) > 40 else humanize_camel_case(x))
            )
            display_df = display_df.drop('member_name', axis=1)
    
    if 'axis_name' in display_df.columns:
        # Check if all values are None/null
        if display_df['axis_name'].isna().all() or (display_df['axis_name'].astype(str) == 'None').all():
            display_df = display_df.drop('axis_name', axis=1)  # Hide column entirely
        else:
            # Humanize CamelCase in dimension names, replace None with empty string
            display_df['dimension'] = display_df['axis_name'].apply(
                lambda x: '' if pd.isna(x) or str(x) == 'None' else (humanize_camel_case(x[:37] + '...') if len(str(x)) > 40 else humanize_camel_case(x))
            )
            display_df = display_df.drop('axis_name', axis=1)
    
    # Format period column if needed (only if we determined it should be shown)
    if show_period_column and 'period_label' in display_df.columns:
        display_df['period'] = display_df['period_label'].fillna('')
        display_df = display_df.drop('period_label', axis=1)
    elif 'period_label' in display_df.columns:
        # Drop period_label if all values are None or we determined it's not needed
        display_df = display_df.drop('period_label', axis=1)
    
    # Drop other period columns (users don't need raw dates)
    for col in ['period_start', 'period_end', 'period_instant', 'period_type', 'context_id']:
        if col in display_df.columns:
            display_df = display_df.drop(col, axis=1)
    
    # Always drop data_type column - internal use only
    if 'data_type' in display_df.columns:
        display_df = display_df.drop('data_type', axis=1)
    
    # Fix unit_measure display (remove curly braces from arrays)
    if 'unit_measure' in display_df.columns:
        display_df['unit'] = display_df['unit_measure'].apply(
            lambda x: str(x).replace('{', '').replace('}', '').replace('[', '').replace(']', '') if pd.notnull(x) else ''
        )
        display_df = display_df.drop('unit_measure', axis=1)
    
    # Format numeric values
    if 'value_numeric' in display_df.columns:
        display_df['value'] = display_df['value_numeric'].apply(
            lambda x: f"{x:,.0f}" if pd.notnull(x) and abs(x) >= 1000 else (f"{x:.2f}" if pd.notnull(x) else "")
        )
    
    # Remove redundant technical columns
    if 'concept' in display_df.columns:
        display_df = display_df.drop('concept', axis=1)  # User has normalized label, don't need raw concept
    if 'concept_name' in display_df.columns:
        display_df = display_df.drop('concept_name', axis=1)
    
    # Reorder columns for better display
    column_order = []
    if 'company' in display_df.columns:
        column_order.append('company')
    if 'label' in display_df.columns:
        column_order.append('label')
    if 'fiscal_year' in display_df.columns:
        column_order.append('fiscal_year')
    if 'period' in display_df.columns:  # Show period when multiple periods exist for same metric
        column_order.append('period')
    if 'value' in display_df.columns:
        column_order.append('value')
    if 'unit' in display_df.columns:
        column_order.append('unit')
    if 'dimension' in display_df.columns:  # Only present when showing segments
        column_order.append('dimension')
    if 'segment' in display_df.columns:  # Only present when showing segments
        column_order.append('segment')
    
    # Add remaining columns (but skip raw technical fields)
    skip_cols = ['value_numeric', 'value_text']  # Already have 'value' formatted
    for col in display_df.columns:
        if col not in column_order and col not in skip_cols:
            column_order.append(col)
    
    display_df = display_df[column_order]
    
    # Sort to group consolidated totals with their segment breakdowns
    # Sort by: company, metric (label), fiscal_year, then dimension (None/consolidated first), then segment
    sort_columns = []
    if 'company' in display_df.columns:
        sort_columns.append('company')
    if 'label' in display_df.columns:
        sort_columns.append('label')
    if 'fiscal_year' in display_df.columns:
        sort_columns.append('fiscal_year')
    if 'dimension' in display_df.columns:
        # Sort so empty/consolidated comes first, then segments
        display_df['_sort_dimension'] = display_df['dimension'].apply(
            lambda x: 0 if pd.isna(x) or x == '' else 1
        )
        sort_columns.append('_sort_dimension')
        sort_columns.append('dimension')
    if 'segment' in display_df.columns:
        sort_columns.append('segment')
    if 'period' in display_df.columns:
        sort_columns.append('period')
    
    if sort_columns:
        display_df = display_df.sort_values(by=sort_columns, na_position='first')
        # Drop temporary sort column
        if '_sort_dimension' in display_df.columns:
            display_df = display_df.drop('_sort_dimension', axis=1)
    
    # Display with custom column config
    st.dataframe(
        display_df, 
        use_container_width=True, 
        height=500,
        column_config={
            "company": st.column_config.TextColumn("Company", width="small"),
            "label": st.column_config.TextColumn("Metric", width="medium"),
            "fiscal_year": st.column_config.NumberColumn("Year", width="small"),
            "value": st.column_config.TextColumn("Value", width="medium"),
            "unit": st.column_config.TextColumn("Unit", width="small"),
            "dimension": st.column_config.TextColumn("Dimension", width="medium"),
            "segment": st.column_config.TextColumn("Segment", width="medium"),
        },
        hide_index=False
    )
    
    # Visualizations
    if not df.empty and 'value_numeric' in df.columns:
        st.markdown("---")
        st.subheader("📈 Visualizations")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if len(selected_companies) == 1 and 'normalized_label' in df.columns:
                # Time series
                st.markdown("**Time Series**")
                # Only show chart if metrics are explicitly selected
                if selected_concepts:
                    metrics_to_plot = selected_concepts[:5]  # Max 5 metrics for readability
                    plot_df = df[df['normalized_label'].isin(metrics_to_plot)].copy()
                    if not plot_df.empty and len(plot_df) > 0:
                        # Convert fiscal_year to string to prevent interpolation (2,023.5 issue)
                        plot_df['fiscal_year_str'] = plot_df['fiscal_year'].astype(str)
                        fig = px.line(
                            plot_df,
                            x='fiscal_year_str',
                            y='value_numeric',
                            color='normalized_label',
                            title="Metrics Over Time"
                        )
                        fig.update_xaxes(type='category')  # Ensure discrete axis
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("No data for selected metrics")
                else:
                    st.info("Select metrics from the filter to visualize")
            else:
                st.info("Select 1 company to see time series chart")
        
        with col2:
            if len(selected_companies) > 1 and selected_concepts and len(selected_concepts) == 1:
                # Cross-company comparison
                st.markdown("**Cross-Company Comparison**")
                concept_df = df[df['normalized_label'] == selected_concepts[0]].copy()
                if not concept_df.empty:
                    # Convert fiscal_year to string for discrete color mapping (prevents 2,023.5 issue)
                    concept_df['fiscal_year_str'] = concept_df['fiscal_year'].astype(str)
                    fig = px.bar(
                        concept_df,
                        x='company',
                        y='value_numeric',
                        color='fiscal_year_str',
                        title=f"{humanize_label(selected_concepts[0])} by Company"
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No data for selected companies and metric")
            else:
                st.info("Select multiple companies and 1 metric for comparison")
    
    # Export
    st.markdown("---")
    st.subheader("💾 Export Data")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        csv = df.to_csv(index=False)
        st.download_button(
            "📥 Download CSV",
            csv,
            "finsight_data.csv",
            "text/csv"
        )
    
    with col2:
        json_data = df.to_json(orient='records')
        st.download_button(
            "📥 Download JSON",
            json_data,
            "finsight_data.json",
            "application/json"
        )


if __name__ == "__main__":
    main()

