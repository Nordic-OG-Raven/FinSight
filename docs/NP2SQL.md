# Natural Language to SQL (NP2SQL) Feature

## Overview

FinSight includes a Natural Language to SQL (NP2SQL) feature that allows users to query the financial data warehouse using plain English questions. The system uses OpenAI GPT-3.5 to convert natural language queries into PostgreSQL SQL, executes them safely with validation, and returns results in appropriate formats (tables, charts, numbers, or lists).

## Features

- **Natural Language Interface**: Ask questions in plain English
- **Auto-Detection**: Automatically detects company mentions and result types
- **Multiple Display Formats**: Results shown as tables, charts, numbers, or lists
- **User-Selectable Format**: Users can choose display format after query execution
- **SQL Transparency**: View generated SQL for transparency and learning
- **Security**: Strict SQL validation and read-only database access

## Usage Examples

### Simple Queries

- "Show me Apple's revenue in 2024"
- "What is Microsoft's total assets in 2023?"
- "Compare net income across all companies in 2024"

### Time Series Queries

- "Show revenue trend for NVIDIA over the last 3 years"
- "Display operating cash flow for Apple from 2020 to 2024"

### Aggregation Queries

- "Which company has the highest revenue in 2024?"
- "What is the average net income for tech companies?"
- "Show total assets by company"

### Comparative Queries

- "Compare revenue between Apple and Microsoft in 2024"
- "Show me all pharma companies' R&D spending"

## How It Works

### 1. Query Processing

1. User enters natural language question
2. System detects company mentions (e.g., "Apple" → "AAPL")
3. OpenAI GPT-3.5 generates SQL query based on schema metadata
4. SQL is validated for security (whitelist tables, SELECT only)
5. Query executes with read-only database connection
6. Results are formatted based on detected type

### 2. Result Type Detection

The system automatically detects the appropriate display format:

- **Number**: Single value (e.g., "What is Apple's revenue?")
- **Table**: Multiple rows and columns
- **Chart**: Time series data (automatically creates line/bar charts)
- **List**: Single column, multiple rows

### 3. Security

- **SQL Validation**: Only SELECT statements allowed
- **Table Whitelist**: Only allowed tables can be queried
- **Read-Only Access**: Separate database user with SELECT-only permissions
- **Query Timeout**: 30-second default timeout
- **Result Limits**: Maximum 10,000 rows per query

## API Endpoint

### POST `/api/query`

**Request:**
```json
{
  "query": "Show me Apple's revenue in 2024"
}
```

**Response:**
```json
{
  "result_type": "number",
  "data": [
    {
      "value_numeric": 383285000000,
      "unit_measure": "USD"
    }
  ],
  "columns": ["value_numeric", "unit_measure"],
  "row_count": 1,
  "sql": "SELECT value_numeric, unit_measure FROM v_facts_consolidated WHERE ticker = 'AAPL' AND normalized_label = 'revenue' AND fiscal_year = 2024 AND period_type = 'duration'",
  "detected_companies": ["AAPL"],
  "execution_time": 0.123,
  "error": null
}
```

## Configuration

### Environment Variables

- `OPENAI_API_KEY`: Required - OpenAI API key for GPT-3.5
- `NP2SQL_DB_USER`: Optional - Read-only database user (defaults to regular user)
- `NP2SQL_DB_PASSWORD`: Optional - Read-only database password
- `NP2SQL_QUERY_TIMEOUT`: Optional - Query timeout in seconds (default: 30)
- `NP2SQL_MAX_ROWS`: Optional - Maximum rows to return (default: 10,000)

### Database Setup

Create a read-only database user:

```sql
-- Run as database superuser
CREATE USER finsight_readonly WITH PASSWORD 'secure-password';
GRANT CONNECT ON DATABASE finsight TO finsight_readonly;
GRANT USAGE ON SCHEMA public TO finsight_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO finsight_readonly;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO finsight_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO finsight_readonly;
```

See `database/create_readonly_user.sql` for complete script.

## Schema Metadata

The system uses comprehensive schema metadata to help the LLM generate accurate SQL:

- **Table Descriptions**: All tables with column descriptions
- **Normalized Labels**: Mapping of financial metrics (e.g., "revenue", "net_income")
- **Business Rules**: Important constraints (e.g., use `dimension_id IS NULL` for consolidated data)
- **Sample Queries**: Example SQL for common patterns
- **Company Mappings**: Company name → ticker mappings

Metadata is generated from:
- Database schema (`database/schema.sql`)
- Taxonomy mappings (`src/utils/taxonomy_mappings.py`)
- Company names (`api/main.py`)

## Best Practices

### For Users

1. **Be Specific**: Include company names/tickers and years when possible
2. **Use Metric Names**: Use common financial terms (revenue, net income, assets, etc.)
3. **Check SQL**: Review generated SQL to understand what's being queried
4. **Try Different Formats**: Switch between table/chart/number formats to find best view

### For Developers

1. **Monitor Queries**: Log queries for debugging and optimization
2. **Update Metadata**: Keep schema metadata up-to-date when schema changes
3. **Test Edge Cases**: Test with various query types and edge cases
4. **Cache Metadata**: Consider caching schema metadata in production

## Limitations

- **OpenAI API Required**: Requires valid OpenAI API key and internet connection
- **Query Complexity**: Very complex queries may not generate correctly
- **Result Size**: Limited to 10,000 rows per query
- **Timeout**: Queries exceeding 30 seconds will timeout
- **Read-Only**: Cannot modify data (by design)

## Future Enhancements

- Query history and saved queries
- Query suggestions and autocomplete
- Multi-step queries (follow-up questions)
- Export results (CSV, JSON)
- Query explanation (why this SQL for this question)
- Support for more complex analytical queries

## Troubleshooting

### "I don't understand your question"

- Try rephrasing with more specific terms
- Include company ticker or name
- Specify the year or time period
- Use common financial metric names

### "Invalid query"

- Check that you're not trying to modify data
- Ensure query only uses allowed tables
- Review generated SQL to see what went wrong

### "Query execution failed"

- Check database connection
- Verify read-only user has proper permissions
- Check query timeout settings
- Review database logs for errors

### No Results

- Verify company/year exists in database
- Check that metric name is correct
- Try querying with different time periods
- Review normalized label mappings

