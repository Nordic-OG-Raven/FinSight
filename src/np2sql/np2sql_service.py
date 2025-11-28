"""
Natural Language to SQL service.

Core functions for converting natural language queries to SQL,
validating SQL, detecting companies, executing queries, and detecting result types.
"""

import os
import re
import time
from typing import Optional, Tuple, List, Dict, Any
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from .schema_metadata import get_schema_metadata, format_schema_for_llm


# Company name mappings (from api/main.py)
COMPANY_NAMES = {
    "NVO": "Novo Nordisk",
    "NVDA": "NVIDIA",
    "AAPL": "Apple",
    "GOOGL": "Alphabet",
    "MSFT": "Microsoft",
    "JNJ": "Johnson & Johnson",
    "PFE": "Pfizer",
    "LLY": "Eli Lilly",
    "MRNA": "Moderna",
    "SNY": "Sanofi",
    "KO": "Coca-Cola",
    "AMZN": "Amazon",
    "ASML": "ASML",
    "BAC": "Bank of America",
    "CAT": "Caterpillar",
    "JPM": "JPMorgan Chase",
    "WMT": "Walmart",
}

# Reverse mapping: company name -> ticker
COMPANY_NAME_TO_TICKER = {}
for ticker, name in COMPANY_NAMES.items():
    COMPANY_NAME_TO_TICKER[name.lower()] = ticker
    COMPANY_NAME_TO_TICKER[ticker.lower()] = ticker
    # Add variations
    if "&" in name:
        COMPANY_NAME_TO_TICKER[name.replace("&", "and").lower()] = ticker
    if " " in name:
        COMPANY_NAME_TO_TICKER[name.split()[0].lower()] = ticker  # First word


# Allowed tables (whitelist)
ALLOWED_TABLES = {
    "fact_financial_metrics",
    "fact_income_statement",
    "fact_balance_sheet",
    "fact_cash_flow",
    "fact_comprehensive_income",
    "fact_equity_statement",
    "dim_companies",
    "dim_concepts",
    "dim_time_periods",
    "dim_filings",
    "dim_xbrl_dimensions",
    "dim_taxonomies",
    "dim_reporting_frameworks",
    "dim_currencies",
    "dim_segments",
    "dim_consolidation_levels",
    "dim_fiscal_periods",
    "v_facts_consolidated",
    "v_facts_with_dimensions",
    "v_data_quality_summary",
}

# Dangerous SQL keywords to block
DANGEROUS_KEYWORDS = {
    "DROP", "DELETE", "INSERT", "UPDATE", "CREATE", "ALTER", "TRUNCATE",
    "EXECUTE", "EXEC", "GRANT", "REVOKE", "COMMIT", "ROLLBACK",
    "COPY", "\\copy", "VACUUM", "ANALYZE", "REINDEX",
}

# Allowed SQL keywords (only SELECT statements)
ALLOWED_STATEMENT_TYPES = {"SELECT"}


def get_openai_client() -> Optional[Any]:
    """Get OpenAI client if API key is available."""
    if OpenAI is None:
        return None
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    
    return OpenAI(api_key=api_key)


def generate_sql(natural_language_query: str, schema_metadata: dict, database_url: Optional[str] = None) -> str:
    """
    Generate SQL from natural language query using OpenAI GPT-3.5.
    
    Args:
        natural_language_query: User's natural language question
        schema_metadata: Schema metadata dictionary
        database_url: Optional database URL for context
        
    Returns:
        Generated SQL query string
        
    Raises:
        ValueError: If OpenAI API is not available or query generation fails
    """
    client = get_openai_client()
    if client is None:
        raise ValueError("OpenAI API key not configured. Set OPENAI_API_KEY environment variable.")
    
    # Format schema for LLM
    schema_text = format_schema_for_llm(schema_metadata)
    
    # Build system prompt
    system_prompt = f"""You are a SQL expert for a financial data warehouse. Convert natural language questions into PostgreSQL SQL queries.

{schema_text}

CRITICAL RULES:
1. Always use v_facts_consolidated view for consolidated queries (avoids duplicate segment data)
2. Use normalized_label for filtering by metric type (e.g., 'revenue', 'net_income', 'total_assets')
3. Use ticker for company filtering (e.g., ticker = 'AAPL' for Apple)
4. Use fiscal_year for year filtering
5. Use period_type = 'duration' for income statement and cash flow queries
6. Use period_type = 'instant' for balance sheet queries
7. Use proper JOINs when querying fact_financial_metrics directly
8. Filter by dimension_id IS NULL when querying fact_financial_metrics for consolidated data

OUTPUT FORMAT:
- Return ONLY valid PostgreSQL SQL starting with SELECT
- NO explanations, NO apologies, NO markdown code blocks
- NO text before or after the SQL
- If you cannot generate SQL, return: SELECT 1 WHERE 1=0"""

    user_prompt = f"Convert this question to SQL: {natural_language_query}"
    
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,  # Low temperature for consistent SQL generation
            max_tokens=500,
        )
        
        sql = response.choices[0].message.content.strip()
        
        # Clean up SQL (remove markdown code blocks if present)
        sql = re.sub(r'^```sql?\s*', '', sql, flags=re.IGNORECASE)
        sql = re.sub(r'^```\s*', '', sql)
        sql = re.sub(r'\s*```\s*$', '', sql)
        sql = sql.strip()
        
        return sql
        
    except Exception as e:
        raise ValueError(f"Failed to generate SQL: {str(e)}")


def validate_sql(sql: str) -> Tuple[bool, str]:
    """
    Validate SQL query for security and correctness.
    
    Args:
        sql: SQL query string to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    sql_upper = sql.upper().strip()
    
    # Check for dangerous keywords
    for keyword in DANGEROUS_KEYWORDS:
        if keyword in sql_upper:
            return False, f"Dangerous SQL keyword detected: {keyword}"
    
    # Must start with SELECT
    if not sql_upper.startswith("SELECT"):
        return False, "Only SELECT statements are allowed"
    
    # Check for allowed statement types only
    for stmt_type in ALLOWED_STATEMENT_TYPES:
        if sql_upper.startswith(stmt_type):
            break
    else:
        return False, "Only SELECT statements are allowed"
    
    # Extract table names from SQL (simple regex - may not catch all cases)
    # Look for FROM and JOIN clauses, but exclude function calls
    # Pattern: FROM/JOIN followed by table name (not function calls like CURRENT_DATE, EXTRACT, etc.)
    table_pattern = r'(?:FROM|JOIN)\s+([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)?)'
    matches = re.findall(table_pattern, sql, re.IGNORECASE)
    
    # Filter out SQL functions and system functions
    sql_functions = {'current_date', 'current_timestamp', 'extract', 'date', 'now', 'cast', 'coalesce'}
    
    # Check if all tables are in whitelist
    for table in matches:
        table_lower = table.lower().split('.')[-1]  # Handle schema.table format
        if table_lower in sql_functions:
            continue  # Skip SQL functions
        if table_lower not in [t.lower() for t in ALLOWED_TABLES]:
            return False, f"Table '{table}' is not in allowed list"
    
    # Block UNION (can be used for injection)
    if "UNION" in sql_upper:
        return False, "UNION statements are not allowed"
    
    # Block subqueries with dangerous operations (basic check)
    if re.search(r'\(.*(?:DROP|DELETE|INSERT|UPDATE|CREATE|ALTER)', sql_upper):
        return False, "Subqueries with dangerous operations are not allowed"
    
    return True, ""


def detect_companies_in_query(query: str) -> List[str]:
    """
    Detect company names/tickers mentioned in natural language query.
    
    Args:
        query: Natural language query string
        
    Returns:
        List of detected ticker symbols
    """
    query_lower = query.lower()
    detected = []
    
    # Check for ticker symbols (uppercase)
    for ticker in COMPANY_NAMES.keys():
        if ticker.lower() in query_lower or ticker in query:
            detected.append(ticker)
    
    # Check for company names
    for name, ticker in COMPANY_NAME_TO_TICKER.items():
        if name in query_lower:
            if ticker not in detected:
                detected.append(ticker)
    
    return list(set(detected))  # Remove duplicates


def execute_query(sql: str, database_url: str, timeout: int = 30, max_rows: int = 10000) -> Dict[str, Any]:
    """
    Execute validated SQL query and return results.
    
    Args:
        sql: Validated SQL query string
        database_url: Database connection URL
        timeout: Query timeout in seconds
        max_rows: Maximum number of rows to return
        
    Returns:
        Dictionary with 'data', 'columns', 'row_count', 'execution_time'
        
    Raises:
        SQLAlchemyError: If query execution fails
        TimeoutError: If query exceeds timeout
    """
    engine = create_engine(database_url, connect_args={"connect_timeout": timeout})
    
    start_time = time.time()
    
    try:
        with engine.connect() as conn:
            # Add LIMIT if not present and query might return many rows
            sql_with_limit = sql
            if "LIMIT" not in sql.upper():
                sql_with_limit = f"{sql} LIMIT {max_rows + 1}"
            
            result = conn.execute(text(sql_with_limit))
            rows = result.fetchall()
            
            # Check if we hit the limit
            if len(rows) > max_rows:
                rows = rows[:max_rows]
                warning = f"Results limited to {max_rows} rows"
            else:
                warning = None
            
            # Get column names
            columns = list(result.keys()) if hasattr(result, 'keys') else []
            if not columns and rows:
                columns = [f"column_{i}" for i in range(len(rows[0]))]
            
            # Convert rows to dictionaries
            data = []
            for row in rows:
                if hasattr(row, '_asdict'):
                    data.append(row._asdict())
                else:
                    data.append(dict(zip(columns, row)))
            
            execution_time = time.time() - start_time
            
            return {
                "data": data,
                "columns": columns,
                "row_count": len(data),
                "execution_time": execution_time,
                "warning": warning,
            }
            
    except SQLAlchemyError as e:
        raise SQLAlchemyError(f"Database error: {str(e)}")
    except Exception as e:
        raise Exception(f"Query execution failed: {str(e)}")
    finally:
        engine.dispose()


def detect_result_type(result: Dict[str, Any]) -> str:
    """
    Detect the appropriate result type for display.
    
    Args:
        result: Result dictionary from execute_query
        
    Returns:
        Result type: 'number', 'single_row', 'time_series', 'table', or 'list'
    """
    data = result.get("data", [])
    columns = result.get("columns", [])
    
    if not data:
        return "table"  # Empty result, show as table
    
    if len(data) == 1:
        # Single row
        if len(columns) == 1:
            # Single column, single row = number
            value = data[0].get(columns[0])
            if isinstance(value, (int, float)) or (isinstance(value, str) and value.replace('.', '').replace('-', '').isdigit()):
                return "number"
        return "single_row"
    
    # Multiple rows
    # Check if it's a time series (has fiscal_year or date column)
    time_columns = ["fiscal_year", "year", "date", "period_label", "fiscal_quarter"]
    has_time_column = any(col.lower() in time_columns for col in columns)
    
    if has_time_column and len(columns) == 2:
        # Likely time series: one time column, one value column
        return "time_series"
    
    if len(columns) == 1:
        # Single column, multiple rows = list
        return "list"
    
    # Default: table
    return "table"

