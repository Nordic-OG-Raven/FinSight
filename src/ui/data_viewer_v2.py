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
    
    # Database statistics
    stats = get_database_stats()
    if stats:
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        col1.metric("Companies", f"{stats[0]}")
        col2.metric("Concepts", f"{stats[1]:,}")
        col3.metric("Periods", f"{stats[2]:,}")
        col4.metric("Total Facts", f"{stats[3]:,}")
        col5.metric("Consolidated", f"{stats[4]:,}")
        col6.metric("Dimensional", f"{stats[5]:,}")
    
    st.markdown("---")
    
    # Sidebar filters
    st.sidebar.header("🔍 Filters")
    
    # Show segments checkbox (simpler than "view mode")
    show_segments = st.sidebar.checkbox(
        "Show segment breakdowns",
        value=False,
        help="Include product, geography, and other segment-level data"
    )
    
    # Company filter
    all_companies = get_companies()
    selected_companies = st.sidebar.multiselect(
        "Companies",
        options=all_companies,
        default=all_companies[:5] if len(all_companies) > 5 else all_companies
    )
    
    # Year filter
    year_range = st.sidebar.slider(
        "Fiscal Year Range",
        min_value=2020,
        max_value=2025,
        value=(2023, 2024)
    )
    
    # Metric filter
    all_concepts = get_normalized_labels()
    selected_concepts = st.sidebar.multiselect(
        "Filter by Metrics",
        options=all_concepts,
        default=[],
        help="Leave empty to see all metrics, or select specific ones"
    )
    
    # Load data (unified query)
    with st.spinner("Loading data from warehouse..."):
        engine = create_engine(DATABASE_URI)
        
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
        
        params = {}
        
        # Filter by selected companies
        if selected_companies:
            query += " AND c.ticker = ANY(:companies)"
            params['companies'] = selected_companies
        
        # Filter by year range
        query += " AND t.fiscal_year >= :start_year AND t.fiscal_year <= :end_year"
        params['start_year'] = year_range[0]
        params['end_year'] = year_range[1]
        
        # Filter by selected concepts
        if selected_concepts:
            query += " AND co.normalized_label = ANY(:concepts)"
            params['concepts'] = selected_concepts
        
        # Exclude segments if not requested
        if not show_segments:
            query += " AND f.dimension_id IS NULL"
        
        # ALWAYS exclude text notes - users want numbers, not documentation
        query += " AND (co.normalized_label NOT LIKE '%_note' AND co.normalized_label NOT LIKE '%_disclosure%' AND co.normalized_label NOT LIKE '%_section_header')"
        query += " AND f.value_numeric IS NOT NULL"  # Only show numeric data
        
        query += " ORDER BY c.ticker, t.fiscal_year, co.normalized_label"
        
        with engine.connect() as conn:
            df = pd.read_sql(text(query), conn, params=params)
    
    if df.empty:
        st.warning("No data found for selected filters")
        return
    
    st.success(f"✅ Loaded {len(df):,} facts from warehouse")
    
    # Data table
    st.subheader("📋 Data Table")
    
    # Format data for display
    display_df = df.copy()
    
    # Fix normalized_label truncation (limit to 50 chars for display)
    if 'normalized_label' in display_df.columns:
        display_df['label'] = display_df['normalized_label'].apply(
            lambda x: x[:47] + '...' if pd.notnull(x) and len(str(x)) > 50 else x
        )
        # Keep full version for tooltips
        display_df = display_df.drop('normalized_label', axis=1)
    
    # Handle segment/dimension columns - HIDE them if all values are None (not showing segments)
    if 'member_name' in display_df.columns:
        # Check if all values are None/null
        if display_df['member_name'].isna().all() or (display_df['member_name'] == 'None').all():
            display_df = display_df.drop('member_name', axis=1)  # Hide column entirely
        else:
            display_df['segment'] = display_df['member_name'].apply(
                lambda x: x[:37] + '...' if pd.notnull(x) and len(str(x)) > 40 else x
            )
            display_df = display_df.drop('member_name', axis=1)
    
    if 'axis_name' in display_df.columns:
        # Check if all values are None/null
        if display_df['axis_name'].isna().all() or (display_df['axis_name'] == 'None').all():
            display_df = display_df.drop('axis_name', axis=1)  # Hide column entirely
        else:
            display_df['dimension'] = display_df['axis_name'].apply(
                lambda x: x[:37] + '...' if pd.notnull(x) and len(str(x)) > 40 else x
            )
            display_df = display_df.drop('axis_name', axis=1)
    
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
                metrics_to_plot = selected_concepts[:5] if selected_concepts else df['normalized_label'].value_counts().head(5).index.tolist()
                plot_df = df[df['normalized_label'].isin(metrics_to_plot)] if metrics_to_plot else df
                if not plot_df.empty and len(plot_df) > 0:
                    fig = px.line(
                        plot_df,
                        x='fiscal_year',
                        y='value_numeric',
                        color='normalized_label',
                        title="Metrics Over Time"
                    )
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Select 1 company to see time series chart")
        
        with col2:
            if len(selected_companies) > 1 and selected_concepts and len(selected_concepts) == 1:
                # Cross-company comparison
                st.markdown("**Cross-Company Comparison**")
                concept_df = df[df['normalized_label'] == selected_concepts[0]]
                if not concept_df.empty:
                    fig = px.bar(
                        concept_df,
                        x='company',
                        y='value_numeric',
                        color='fiscal_year',
                        title=f"{selected_concepts[0]} by Company"
                    )
                    st.plotly_chart(fig, use_container_width=True)
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

