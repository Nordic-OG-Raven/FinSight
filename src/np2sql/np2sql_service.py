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

from .schema_metadata import get_schema_metadata, format_schema_for_llm, get_enumerations, COMPANIES


# Display names + detection aliases come from the curated entity dictionary (COMPANIES), which is
# grounded in the warehouse's real coverage — not a hardcoded list that drifts out of date.
COMPANY_NAMES = {ticker: info["name"] for ticker, info in COMPANIES.items()}

# Reverse map: lowercase ticker / name / alias -> ticker, for detecting a company in free text.
COMPANY_NAME_TO_TICKER: Dict[str, str] = {}
for _ticker, _info in COMPANIES.items():
    COMPANY_NAME_TO_TICKER[_ticker.lower()] = _ticker
    COMPANY_NAME_TO_TICKER[_info["name"].lower()] = _ticker
    for _alias in _info["aliases"]:
        COMPANY_NAME_TO_TICKER[_alias.lower()] = _ticker


# Allowed tables (whitelist). The medallion gold serving objects; the connection's search_path
# is set to `gold, public` so bare names resolve to gold.
ALLOWED_TABLES = {
    # gold serving views
    "v_facts_consolidated",
    "v_facts_hierarchical",
    "companies",
    # gold analytical marts
    "company_financials",
    "ratios",
    "peers",
    "company_quarterly",
    "earnings",
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
    """Return an OpenAI-compatible client. Prefers Groq (GROQ_API_KEY → Groq's OpenAI-compatible
    endpoint), else OpenAI (OPENAI_API_KEY). None if neither key or the SDK is available."""
    if OpenAI is None:
        return None
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        return OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    return OpenAI(api_key=api_key)


def _default_model() -> str:
    """Model id to use. Override with NP2SQL_MODEL; otherwise a sensible default per provider."""
    if os.getenv("NP2SQL_MODEL"):
        return os.getenv("NP2SQL_MODEL")
    return "openai/gpt-oss-120b" if os.getenv("GROQ_API_KEY") else "gpt-4o-mini"


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
        raise ValueError("No LLM API key configured. Set GROQ_API_KEY (preferred) or OPENAI_API_KEY.")
    
    # Format schema for LLM, grounded in the warehouse's live coverage (companies + year range).
    enumerations = get_enumerations(database_url)
    schema_text = format_schema_for_llm(schema_metadata, enumerations)

    # Build system prompt. The detailed rules live in the schema block above; here we keep only the
    # output contract and the few reminders that most affect correctness.
    system_prompt = f"""You are a careful SQL analyst for a financial data warehouse (PostgreSQL). Convert the user's question into ONE read-only SELECT query.

{schema_text}

GUIDANCE:
- Use only the tables, columns, metric labels, companies and years described above. Never invent a column, metric, ticker or year.
- Filter companies with ticker and metrics with the canonical labels; use value_usd for any cross-company comparison.
- Prefer a mart (ratios, peers, earnings, company_quarterly, company_financials) when it already serves the figure; use v_facts_consolidated for anything else.

OUTPUT FORMAT:
- Return ONLY valid PostgreSQL starting with SELECT. No explanations, no markdown code blocks, no text before or after.
- If the question cannot be answered from the schema above, return: SELECT 1 WHERE 1=0"""

    user_prompt = f"Convert this question to SQL: {natural_language_query}"
    
    try:
        response = client.chat.completions.create(
            model=_default_model(),
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
    detected: List[str] = []

    # Match each ticker/name/alias at a word boundary, so 'meta' fires on "Meta" but not
    # "metadata", and short tickers ('amd','crm') don't match inside other words.
    for term, ticker in COMPANY_NAME_TO_TICKER.items():
        if ticker in detected:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", query_lower):
            detected.append(ticker)

    return detected


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
    # search_path=gold,public so the LLM's bare table names resolve to the medallion gold layer.
    # Neon's pooler rejects the search_path startup option, so use the DIRECT (unpooled) endpoint.
    engine = create_engine(
        database_url.replace("-pooler", ""),
        connect_args={"connect_timeout": timeout, "options": "-c search_path=gold,public"},
    )

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

