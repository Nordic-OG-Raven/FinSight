# FinSight Streamlit Data Viewer

## Overview

The FinSight Data Viewer is a simple Streamlit application for exploring the financial data warehouse. It provides filtering, visualization, and export capabilities.

**Philosophy:** This is a DATA VIEWER for exploration, not an elaborate dashboard. For production analytics, use Apache Superset.

## Quick Start

### 1. Launch the Viewer

```bash
cd /Users/jonas/FinSight
./start_viewer.sh
```

The viewer will open in your browser at `http://localhost:8502`

### 2. Alternative: Manual Launch

```bash
cd /Users/jonas/FinSight
/Users/jonas/Thesis/.venv/bin/streamlit run src/ui/data_viewer_v2.py --server.port 8502
```

## Features

### 🔍 Filter Panel (Sidebar)

- **Companies**: Select one or more companies to analyze
- **Period**: Date range filter for period_end dates
- **Normalized Labels**: Filter by normalized concept labels
- **Statement Type**: Filter by financial statement type (income statement, balance sheet, etc.)
- **Concept Search**: Search for specific XBRL concepts (partial match)

### 📋 Data Table Tab

- Browse all filtered financial facts
- Choose which columns to display
- Sortable columns
- Formatted numeric values

### 📈 Time Series Tab

- Select a normalized label (metric)
- View line chart showing the metric over time
- Compare multiple companies on the same chart
- Useful for trend analysis

### 📊 Cross-Company Tab

- Select a metric to compare
- Bar chart showing latest period comparison
- See which company has the highest/lowest values
- Data table with exact values and periods

### 💾 Export Tab

Export filtered data in three formats:

1. **CSV**: Universal format for Excel, Google Sheets
2. **JSON**: For programmatic access, APIs
3. **Parquet**: Compressed, efficient format for data analysis

## Usage Examples

### Example 1: Compare Revenue Across Tech Companies

1. Select companies: AAPL, GOOGL, MSFT
2. Set period: Last 3 years
3. Filter by normalized label: `revenue`
4. Go to "Cross-Company" tab
5. View comparison chart

### Example 2: Analyze Apple's Financial Trends

1. Select company: AAPL
2. Set period: Last 5 years
3. Go to "Time Series" tab
4. Select metrics: `revenue`, `net_income`, `operating_income`
5. View trends over time

### Example 3: Export Pension Data

1. Select companies: JNJ, PFE, KO
2. Filter by normalized labels: `pension_plan_assets`, `pension_benefit_obligation`
3. Go to "Export" tab
4. Download CSV

### Example 4: Explore Debt Details

1. Select companies: All
2. Filter by normalized labels starting with `debt_`
3. Go to "Data Table" tab
4. Select columns: company, concept, normalized_label, value_numeric, period_end
5. Sort by value_numeric

## Tips

- **Start Broad**: Begin with all companies, then narrow down
- **Use Normalized Labels**: They enable cross-company comparisons
- **Check Units**: Values may be in different scales (millions, billions)
- **Export Often**: Download data for deeper analysis in Excel/Python
- **Statement Types**: Use the statement type filter to focus on specific financial statements

## Performance

- **Cache**: Data is cached for 10 minutes to improve performance
- **Filters**: Apply filters before loading to reduce data size
- **Period**: Limit date ranges for faster loading

## Troubleshooting

### Connection Error

If you see "connection to server failed":

1. Verify Docker container is running: `docker ps | grep superset_db`
2. Check PostgreSQL port mapping: Should show `127.0.0.1:5432->5432/tcp`
3. Verify database exists: `docker exec superset_db psql -U superset -l | grep finsight`

### No Data Showing

1. Check filters - they may be too restrictive
2. Verify companies have been extracted: `docker exec superset_db psql -U superset -d finsight -c "SELECT DISTINCT company FROM financial_facts;"`
3. Check period filter - expand date range

### Slow Loading

1. Reduce number of selected companies
2. Narrow date range
3. Use normalized label filters
4. Clear cache: Click menu (top right) → Clear cache

## Keyboard Shortcuts

- `R`: Rerun the app
- `C`: Clear cache
- `Ctrl+K` or `Cmd+K`: Open command palette

## Next Steps

- **Production Dashboards**: Use Apache Superset for production-grade visualizations
- **Custom Analysis**: Export data and analyze in Jupyter, R, or other tools
- **API Integration**: Query PostgreSQL directly for programmatic access

## Related Documentation

- [TAXONOMY_NORMALIZATION.md](TAXONOMY_NORMALIZATION.md) - Understanding normalized labels
- [NORMALIZATION_SUMMARY.md](NORMALIZATION_SUMMARY.md) - Coverage statistics
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture (coming soon)

