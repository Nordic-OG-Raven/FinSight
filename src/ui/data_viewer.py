"""
Simple Streamlit data viewer for FinSight financial data warehouse.

This is a DATA VIEWER for exploration, not an elaborate dashboard.
Focus: Browse, filter, export data.
"""

import streamlit as st
import pandas as pd
import psycopg2
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from config import POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB


# Database connection
@st.cache_resource
def get_connection():
    """Get PostgreSQL connection."""
    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        database=POSTGRES_DB
    )


@st.cache_data(ttl=600)
def load_data(query, params=None):
    """Load data from PostgreSQL."""
    conn = get_connection()
    df = pd.read_sql_query(query, conn, params=params)
    return df


@st.cache_data(ttl=3600)
def get_companies():
    """Get list of companies."""
    query = "SELECT DISTINCT company FROM financial_facts ORDER BY company;"
    return load_data(query)['company'].tolist()


@st.cache_data(ttl=3600)
def get_normalized_labels():
    """Get list of normalized labels."""
    query = """
        SELECT DISTINCT normalized_label 
        FROM financial_facts 
        WHERE normalized_label IS NOT NULL 
        ORDER BY normalized_label;
    """
    return load_data(query)['normalized_label'].tolist()


@st.cache_data(ttl=3600)
def get_statement_types():
    """Get statement types from taxonomy mappings."""
    return ['All', 'income_statement', 'balance_sheet', 'cash_flow', 'other']


def main():
    st.set_page_config(
        page_title="FinSight Data Viewer",
        page_icon="📊",
        layout="wide"
    )
    
    st.title("📊 FinSight Data Viewer")
    st.markdown("**Simple data exploration tool for financial data warehouse**")
    
    # Sidebar - Filters
    st.sidebar.header("🔍 Filters")
    
    # Company filter
    companies = get_companies()
    selected_companies = st.sidebar.multiselect(
        "Companies",
        options=companies,
        default=companies  # Default to ALL companies
    )
    
    # Period filter
    st.sidebar.subheader("Period")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        start_date = st.date_input(
            "Start Date",
            value=datetime(2020, 1, 1)
        )
    with col2:
        end_date = st.date_input(
            "End Date",
            value=datetime.now()
        )
    
    # Normalized label filter
    normalized_labels = get_normalized_labels()
    selected_labels = st.sidebar.multiselect(
        "Normalized Labels (leave empty for all)",
        options=normalized_labels,
        default=[]
    )
    
    # Statement type filter
    statement_type = st.sidebar.selectbox(
        "Statement Type",
        options=get_statement_types()
    )
    
    # Concept search
    concept_search = st.sidebar.text_input(
        "Concept Search (partial match)",
        value=""
    )
    
    # Build query
    if not selected_companies:
        st.warning("Please select at least one company.")
        return
    
    # Main query - Handle NULL period_end by using fiscal_year_end as fallback
    query = """
        SELECT 
            company,
            fiscal_year_end,
            concept,
            normalized_label,
            value_text,
            value_numeric,
            period_type,
            period_end,
            unit_measure,
            taxonomy,
            filing_type
        FROM financial_facts
        WHERE company = ANY(%s)
          AND (
              (period_end IS NOT NULL AND period_end >= %s AND period_end <= %s)
              OR (period_end IS NULL AND fiscal_year_end >= %s AND fiscal_year_end <= %s)
          )
    """
    params = [selected_companies, start_date, end_date, start_date, end_date]
    
    # Add normalized label filter
    if selected_labels:
        query += " AND normalized_label = ANY(%s)"
        params.append(selected_labels)
    
    # Add concept search
    if concept_search:
        query += " AND concept ILIKE %s"
        params.append(f"%{concept_search}%")
    
    query += " ORDER BY company, period_end DESC, concept;"
    
    # Load data
    with st.spinner("Loading data..."):
        df = load_data(query, params)
    
    # Filter by statement type if needed
    if statement_type != 'All':
        # Load statement type mapping
        sys.path.insert(0, str(project_root / 'src' / 'utils'))
        from taxonomy_mappings import get_statement_type
        
        df['statement_type'] = df['normalized_label'].apply(
            lambda x: get_statement_type(x) if pd.notna(x) else None
        )
        df = df[df['statement_type'] == statement_type]
    
    # Display metrics
    st.markdown("---")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Facts", f"{len(df):,}")
    with col2:
        st.metric("Companies", len(df['company'].unique()) if len(df) > 0 else 0)
    with col3:
        st.metric("Concepts", len(df['concept'].unique()) if len(df) > 0 else 0)
    with col4:
        st.metric("Normalized", len(df[df['normalized_label'].notna()]) if len(df) > 0 else 0)
    
    if len(df) == 0:
        st.info("No data found for selected filters.")
        return
    
    # Tabs for different views
    tab1, tab2, tab3, tab4 = st.tabs(["📋 Data Table", "📈 Time Series", "📊 Cross-Company", "💾 Export"])
    
    # Tab 1: Data Table
    with tab1:
        st.subheader("Filtered Data")
        
        # Display options
        show_columns = st.multiselect(
            "Select columns to display",
            options=df.columns.tolist(),
            default=['company', 'concept', 'normalized_label', 'value_numeric', 'unit_measure', 'period_end']
        )
        
        if show_columns:
            display_df = df[show_columns].copy()
            
            # Format numeric values
            if 'value_numeric' in display_df.columns:
                display_df['value_numeric'] = display_df['value_numeric'].apply(
                    lambda x: f"{x:,.2f}" if pd.notna(x) else ""
                )
            
            st.dataframe(
                display_df,
                use_container_width=True,
                height=600
            )
    
    # Tab 2: Time Series
    with tab2:
        st.subheader("Time Series Analysis")
        
        # Select metric for time series
        numeric_df = df[df['value_numeric'].notna()].copy()
        
        if len(numeric_df) == 0:
            st.info("No numeric data available for time series.")
        else:
            available_labels = numeric_df['normalized_label'].dropna().unique().tolist()
            
            if not available_labels:
                st.info("No normalized labels available. Try different filters.")
            else:
                selected_metric = st.selectbox(
                    "Select metric for time series",
                    options=sorted(available_labels)
                )
                
                # Filter data
                ts_df = numeric_df[numeric_df['normalized_label'] == selected_metric].copy()
                ts_df['period_end'] = pd.to_datetime(ts_df['period_end'])
                
                if len(ts_df) > 0:
                    # Group by company and period, take max value
                    ts_pivot = ts_df.groupby(['company', 'period_end'])['value_numeric'].max().reset_index()
                    
                    # Create line chart
                    fig = px.line(
                        ts_pivot,
                        x='period_end',
                        y='value_numeric',
                        color='company',
                        title=f"{selected_metric} over time",
                        labels={'period_end': 'Period', 'value_numeric': 'Value'}
                    )
                    fig.update_layout(height=500)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info(f"No data for {selected_metric}")
    
    # Tab 3: Cross-Company Comparison
    with tab3:
        st.subheader("Cross-Company Comparison")
        
        numeric_df = df[df['value_numeric'].notna()].copy()
        
        if len(numeric_df) == 0:
            st.info("No numeric data available for comparison.")
        else:
            available_labels = numeric_df['normalized_label'].dropna().unique().tolist()
            
            if not available_labels:
                st.info("No normalized labels available. Try different filters.")
            else:
                compare_metric = st.selectbox(
                    "Select metric to compare",
                    options=sorted(available_labels),
                    key='compare_metric'
                )
                
                # Filter data
                comp_df = numeric_df[numeric_df['normalized_label'] == compare_metric].copy()
                
                # Use most recent period for each company
                comp_df = comp_df.sort_values('period_end').groupby('company').last().reset_index()
                
                if len(comp_df) > 0:
                    # Create bar chart
                    fig = px.bar(
                        comp_df,
                        x='company',
                        y='value_numeric',
                        title=f"{compare_metric} - Latest Period Comparison",
                        labels={'company': 'Company', 'value_numeric': 'Value'},
                        text='value_numeric'
                    )
                    fig.update_traces(texttemplate='%{text:.2s}', textposition='outside')
                    fig.update_layout(height=500)
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # Show data table
                    st.dataframe(
                        comp_df[['company', 'value_numeric', 'period_end', 'unit_measure']],
                        use_container_width=True
                    )
                else:
                    st.info(f"No data for {compare_metric}")
    
    # Tab 4: Export
    with tab4:
        st.subheader("💾 Export Data")
        
        st.markdown(f"**Current selection:** {len(df):,} facts")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("**CSV Export**")
            csv = df.to_csv(index=False)
            st.download_button(
                label="📥 Download CSV",
                data=csv,
                file_name=f"finsight_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
        
        with col2:
            st.markdown("**JSON Export**")
            json = df.to_json(orient='records', date_format='iso')
            st.download_button(
                label="📥 Download JSON",
                data=json,
                file_name=f"finsight_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json"
            )
        
        with col3:
            st.markdown("**Parquet Export**")
            # Convert to parquet
            import io
            buffer = io.BytesIO()
            df.to_parquet(buffer, index=False)
            buffer.seek(0)
            st.download_button(
                label="📥 Download Parquet",
                data=buffer,
                file_name=f"finsight_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.parquet",
                mime="application/octet-stream"
            )
    
    # Footer
    st.markdown("---")
    st.caption("FinSight Data Viewer | Data warehouse for financial reporting")


if __name__ == "__main__":
    main()

