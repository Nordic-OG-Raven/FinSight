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
    st.markdown("**Star Schema Design** • Proper Dimensional Modeling • Cross-Company Analysis")
    
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
    
    # View mode
    view_mode = st.sidebar.radio(
        "View Mode",
        ["Consolidated Facts", "Dimensional Breakdowns"],
        help="Consolidated = totals only • Dimensional = segment/product/geography breakdowns"
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
    
    # Concept filter (for consolidated only)
    if view_mode == "Consolidated Facts":
        all_concepts = get_normalized_labels()
        selected_concepts = st.sidebar.multiselect(
            "Normalized Labels",
            options=all_concepts,
            default=[]
        )
    else:
        selected_concepts = None
    
    # Load data
    with st.spinner("Loading data from warehouse..."):
        if view_mode == "Consolidated Facts":
            df = load_consolidated_data(
                companies=selected_companies if selected_companies else None,
                start_year=year_range[0],
                end_year=year_range[1],
                concepts=selected_concepts if selected_concepts else None
            )
        else:
            df = load_dimensional_data(
                companies=selected_companies if selected_companies else None,
                start_year=year_range[0],
                end_year=year_range[1]
            )
    
    if df.empty:
        st.warning("No data found for selected filters")
        return
    
    st.success(f"✅ Loaded {len(df):,} facts from warehouse")
    
    # Data table
    st.subheader("📋 Data Table")
    
    # Format numeric values
    display_df = df.copy()
    if 'value_numeric' in display_df.columns:
        display_df['value_numeric_formatted'] = display_df['value_numeric'].apply(
            lambda x: f"{x:,.2f}" if pd.notnull(x) else ""
        )
    
    st.dataframe(display_df, use_container_width=True, height=400)
    
    # Visualizations
    if not df.empty and 'value_numeric' in df.columns:
        st.markdown("---")
        st.subheader("📈 Visualizations")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if view_mode == "Consolidated Facts" and 'normalized_label' in df.columns:
                # Time series by normalized label
                if len(selected_companies) == 1 and selected_concepts:
                    st.markdown("**Time Series by Concept**")
                    fig = px.line(
                        df[df['normalized_label'].isin(selected_concepts[:5])],
                        x='fiscal_year',
                        y='value_numeric',
                        color='normalized_label',
                        title="Metrics Over Time"
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Select 1 company and some concepts for time series")
            else:
                # Dimensional breakdown
                if 'axis_name' in df.columns:
                    st.markdown("**Dimensional Breakdown**")
                    top_dims = df.nlargest(10, 'value_numeric')
                    fig = px.bar(
                        top_dims,
                        x='member_name',
                        y='value_numeric',
                        color='company',
                        title="Top 10 Dimensional Values"
                    )
                    st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            if view_mode == "Consolidated Facts" and len(selected_companies) > 1:
                # Cross-company comparison
                if selected_concepts and len(selected_concepts) == 1:
                    st.markdown("**Cross-Company Comparison**")
                    concept_df = df[df['normalized_label'] == selected_concepts[0]]
                    fig = px.bar(
                        concept_df,
                        x='company',
                        y='value_numeric',
                        color='fiscal_year',
                        title=f"{selected_concepts[0]} by Company"
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Select 1 concept for cross-company comparison")
    
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

