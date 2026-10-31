"""
FinSight API
Flask backend for financial data extraction and analysis.

Statements are served warehouse-direct from fact_financial_metrics by
GET /api/financials/<ticker> (see get_financials_v2). The old statement-reconstruction
endpoints and their fact_income_statement / fact_balance_sheet / fact_cash_flow tables were
retired in the edgartools re-architecture — see docs/REARCHITECTURE.md.
"""

import os
import sys
import json
import re
import math
from datetime import datetime
from pathlib import Path
from flask import Flask, jsonify, request
from flask_cors import CORS
import signal
from contextlib import contextmanager

# Add parent directory to path to import from src/
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.concept_label_mapping import get_humanized_label
from src.utils.edgar_url import edgar_filing_url
from src.provenance.layers import all_layers
from config import DATABASE_URL, NP2SQL_DATABASE_URL, NP2SQL_QUERY_TIMEOUT, NP2SQL_MAX_ROWS

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend

# Configuration
MAX_CUSTOM_REQUESTS = int(os.getenv('MAX_CUSTOM_REQUESTS_PER_MONTH', 10))
MAX_DB_SIZE_MB = int(os.getenv('MAX_DB_SIZE_MB', 900))
QUOTA_FILE = Path(__file__).parent / 'data' / 'quota.json'
QUOTA_FILE.parent.mkdir(exist_ok=True)

# Company name mapping (for display)
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

def get_preloaded_companies_from_db():
    """Dynamically query database for available companies, years, and quarters"""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(DATABASE_URL)
        
        with engine.connect() as conn:
            # Query for companies, years, and quarters
            # Gold serving view (medallion). One row per annual filing per company.
            query = text("""
                SELECT ticker,
                       fiscal_year AS year,
                       fiscal_quarter,
                       filing_type,
                       reporting_frequency
                FROM gold.companies
                ORDER BY ticker, year DESC, fiscal_quarter NULLS LAST
            """)
            
            result = conn.execute(query)
            rows = result.fetchall()
            
            # Group by ticker and year
            companies_dict = {}
            for ticker, year, quarter, filing_type, reporting_freq in rows:
                if ticker not in companies_dict:
                    companies_dict[ticker] = {}
                if year not in companies_dict[ticker]:
                    companies_dict[ticker][year] = {
                        "quarters": set(),
                        "filing_types": set(),
                        "reporting_frequencies": set()
                    }
                if quarter is not None:
                    companies_dict[ticker][year]["quarters"].add(int(quarter))
                if filing_type:
                    companies_dict[ticker][year]["filing_types"].add(filing_type)
                if reporting_freq:
                    companies_dict[ticker][year]["reporting_frequencies"].add(reporting_freq)
            
            # Format as list with company names, years, and quarters
            companies_list = []
            for ticker in sorted(companies_dict.keys()):
                years_data = []
                for year in sorted(companies_dict[ticker].keys(), reverse=True):
                    year_info = companies_dict[ticker][year]
                    quarters = sorted(year_info["quarters"]) if year_info["quarters"] else None
                    years_data.append({
                        "year": year,
                        "quarters": quarters,
                        "filing_types": sorted(year_info["filing_types"]),
                        "reporting_frequencies": sorted(year_info["reporting_frequencies"])
                    })
                companies_list.append({
                    "ticker": ticker,
                    "name": COMPANY_NAMES.get(ticker, ticker),
                    "years": sorted(companies_dict[ticker].keys(), reverse=True),  # Keep for backward compatibility
                    "years_detail": years_data  # New detailed structure
                })
            
            return companies_list
            
    except Exception as e:
        # Fallback to empty list if database query fails
        print(f"Error querying companies from database: {e}")
        return []

# Test tickers that don't count against quota
TEST_TICKERS = ['TEST', 'DEMO']

@contextmanager
def timeout(seconds):
    """Timeout context manager - kills process if exceeded"""
    def timeout_handler(signum, frame):
        raise TimeoutError(f"Processing exceeded {seconds}s limit")
    
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)

def check_monthly_quota():
    """Check if monthly custom analysis quota exceeded"""
    current_month = datetime.now().strftime('%Y-%m')
    
    if not QUOTA_FILE.exists():
        return True, 0, "0/10 used this month"
    
    with open(QUOTA_FILE, 'r') as f:
        quota_data = json.load(f)
    
    if quota_data.get('month') != current_month:
        # New month, reset
        return True, 0, "0/10 used this month"
    
    count = quota_data.get('count', 0)
    if count >= MAX_CUSTOM_REQUESTS:
        return False, count, f"Quota exceeded ({count}/{MAX_CUSTOM_REQUESTS})"
    
    return True, count, f"{count}/{MAX_CUSTOM_REQUESTS} used this month"

def increment_quota():
    """Increment monthly quota counter"""
    current_month = datetime.now().strftime('%Y-%m')
    
    if QUOTA_FILE.exists():
        with open(QUOTA_FILE, 'r') as f:
            quota_data = json.load(f)
    else:
        quota_data = {}
    
    if quota_data.get('month') != current_month:
        quota_data = {'month': current_month, 'count': 1, 'requests': []}
    else:
        quota_data['count'] = quota_data.get('count', 0) + 1
    
    # Track individual requests
    if 'requests' not in quota_data:
        quota_data['requests'] = []
    quota_data['requests'].append({
        'timestamp': datetime.now().isoformat(),
        'ticker': request.json.get('ticker') if request.json else 'unknown'
    })
    
    with open(QUOTA_FILE, 'w') as f:
        json.dump(quota_data, f, indent=2)

def check_db_size():
    """Check PostgreSQL database size"""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT pg_database_size(current_database()) as size;"))
            size_bytes = result.fetchone()[0]
            size_mb = size_bytes / (1024 * 1024)
            
            if size_mb > MAX_DB_SIZE_MB:
                return False, size_mb, f"Storage limit reached ({size_mb:.0f}MB / 1000MB)"
            
            return True, size_mb, f"{size_mb:.0f}MB / 1000MB used"
    except Exception as e:
        return True, 0, f"Could not check DB size: {e}"

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "environment": os.getenv('ENVIRONMENT', 'development')
    })

@app.route('/api/init-db', methods=['POST'])
def init_database():
    """DEPRECATED. Schema is owned by the dbt medallion warehouse (bronze/silver/gold on Neon);
    there is no app-managed table to create."""
    return jsonify({
        "error": "gone",
        "message": "Schema is managed by the dbt medallion warehouse; this endpoint is retired.",
    }), 410

@app.route('/api/populate-statements', methods=['POST'])
def populate_statements():
    """DEPRECATED. The statement-specific fact tables were retired in the edgartools
    re-architecture (see docs/REARCHITECTURE.md); statements are served from the warehouse by
    GET /api/financials/<ticker>."""
    return jsonify({
        "error": "gone",
        "message": "Statement sub-tables were retired. Statements are served from the warehouse "
                   "by GET /api/financials/<ticker>.",
    }), 410


@app.route('/api/companies', methods=['GET'])
def get_companies():
    """Get list of pre-loaded companies and quota status"""
    quota_ok, count, quota_msg = check_monthly_quota()
    db_ok, db_size, db_msg = check_db_size()
    
    # Dynamically fetch companies from database
    preloaded_companies = get_preloaded_companies_from_db()
    
    return jsonify({
        "preloaded": preloaded_companies,
        "quota": {
            "custom_requests_used": count,
            "custom_requests_limit": MAX_CUSTOM_REQUESTS,
            "quota_available": quota_ok,
            "message": quota_msg,
            "resets_on": f"{datetime.now().strftime('%Y-%m')}-01T00:00:00Z"
        },
        "storage": {
            "size_mb": round(db_size, 1),
            "limit_mb": 1000,
            "available": db_ok,
            "message": db_msg
        }
    })

@app.route('/api/analyze/<ticker>/<int:year>', methods=['GET'])
def analyze_preloaded(ticker, year):
    """
    Get pre-loaded company data (instant)
    Returns financial facts from database
    """
    ticker = ticker.upper()
    
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(DATABASE_URL)
        
        with engine.connect() as conn:
            # Existence check (gold serving view, medallion)
            query = text("""
                SELECT COUNT(*) as count
                FROM gold.v_facts_hierarchical
                WHERE ticker = :ticker AND fiscal_year = :year AND is_dimensioned = false
            """)
            result = conn.execute(query, {"ticker": ticker, "year": year})
            count = result.fetchone()[0]

            if count == 0:
                return jsonify({
                    "error": "not_found",
                    "message": f"No data for {ticker} {year}. Try custom analysis or select a pre-loaded company."
                }), 404

            # Annual snapshot: undimensioned, annual durations + fiscal-year-end instants.
            # (hierarchy_level is retired/NULL; statement_type drives the ordering.)
            metrics_query = text("""
                SELECT normalized_label,
                       value_numeric            as value,
                       unit_measure             as unit,
                       COALESCE(end_date, instant_date) as period_end,
                       period_type,
                       statement_type,
                       hierarchy_level
                FROM gold.v_facts_hierarchical
                WHERE ticker = :ticker
                  AND fiscal_year = :year
                  AND is_dimensioned = false
                  AND value_numeric IS NOT NULL
                  AND period_grain IN ('annual', 'instant')
                ORDER BY
                    CASE statement_type
                        WHEN 'income_statement' THEN 1
                        WHEN 'balance_sheet' THEN 2
                        WHEN 'cash_flow' THEN 3
                        ELSE 4
                    END,
                    normalized_label
            """)

            metrics_result = conn.execute(metrics_query, {"ticker": ticker, "year": year})
            
            metrics = {}
            for row in metrics_result:
                try:
                    # Handle NULL values safely - ensure all values are JSON-serializable
                    normalized_label = str(row[0]) if row[0] is not None else 'unknown'
                    value = float(row[1]) if row[1] is not None else None
                    unit = str(row[2]) if row[2] is not None else ''
                    period_end = row[3].isoformat() if row[3] is not None else None
                    period_type = str(row[4]) if row[4] is not None else None
                    stmt_type = str(row[5]) if row[5] is not None else 'other'
                    hierarchy = int(row[6]) if row[6] is not None else None
                    
                    metrics[normalized_label] = {
                        "value": value,
                        "unit": unit,
                        "period_end": period_end,
                        "period_type": period_type,
                        "statement_type": stmt_type,
                        "hierarchy_level": hierarchy
                    }
                except Exception as e:
                    # Skip rows with errors, log them
                    print(f"Error processing row: {e}, row: {row}")
                    continue
            
            return jsonify({
                "company": ticker,
                "year": year,
                "metrics": metrics,
                "fact_count": count,
                "processing_time": 0.1,
                "source": "preloaded",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        return jsonify({
            "error": "database_error",
            "message": str(e)
        }), 500

@app.route('/api/analyze/custom', methods=['POST'])
def analyze_custom():
    """
    Run full ETL pipeline for custom ticker
    ~2-5 minutes processing time
    Enforces quota limits
    """
    data = request.json
    ticker = data.get('ticker', '').upper()
    year = data.get('year')
    
    if not ticker or not year:
        return jsonify({"error": "Missing ticker or year"}), 400
    
    # Skip quota check for test tickers
    if ticker not in TEST_TICKERS:
        # Check monthly quota
        quota_ok, count, quota_msg = check_monthly_quota()
        if not quota_ok:
            return jsonify({
                "error": "quota_exceeded",
                "message": quota_msg,
                "quota_used": count,
                "quota_limit": MAX_CUSTOM_REQUESTS,
                "resets_on": f"{datetime.now().strftime('%Y-%m')}-01T00:00:00Z"
            }), 429
        
        # Check database storage
        db_ok, db_size, db_msg = check_db_size()
        if not db_ok:
            return jsonify({
                "error": "storage_quota_exceeded",
                "message": db_msg,
                "contact": "jonas.haahr@aol.com"
            }), 507
    
    # Check if already present in the warehouse (gold serving view, medallion)
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            exists = conn.execute(text(
                "SELECT 1 FROM gold.v_facts_hierarchical WHERE ticker = :t AND fiscal_year = :y LIMIT 1"
            ), {"t": ticker, "y": year}).fetchone()
        if exists:
            return analyze_preloaded(ticker, year)
    except Exception:
        pass

    # Land the ticker into the medallion BRONZE layer (latest annual + recent quarters) plus its
    # stock splits. Serving is view-based (silver/gold are views over bronze), so the data is
    # queryable through gold immediately — no dbt run per request. The materialized forecasting
    # marts (earnings/company_quarterly) pick it up on the next scheduled dbt build.
    try:
        print(f"Landing {ticker} into the medallion bronze layer...")
        with timeout(600):  # 10 minute max
            from src.ingestion.bronze import ingest as bronze_ingest
            from src.ingestion.corporate_actions import ingest as ca_ingest
            bronze_ingest([ticker], quarters=4)
            try:
                ca_ingest([ticker])
            except Exception as e:  # noqa: BLE001 — splits are best-effort
                print(f"corporate-actions skip for {ticker}: {e}")

        # Confirm something landed for the requested year
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            landed = conn.execute(text(
                "SELECT 1 FROM gold.v_facts_hierarchical WHERE ticker = :t LIMIT 1"
            ), {"t": ticker}).fetchone()
        if not landed:
            return jsonify({
                "error": "pipeline_failed",
                "message": f"Failed to process {ticker}. Filing may not exist or be in an unsupported format."
            }), 500

        # Increment quota (only on success)
        if ticker not in TEST_TICKERS:
            increment_quota()

        # Return processed data
        return analyze_preloaded(ticker, year)

    except TimeoutError:
        return jsonify({
            "error": "timeout",
            "message": "Processing exceeded 10 minute limit. Company data may be too large."
        }), 504
    except Exception as e:
        return jsonify({
            "error": "processing_error",
            "message": str(e)
        }), 500

@app.route('/api/quota', methods=['GET'])
def get_quota():
    """Get current quota status"""
    quota_ok, count, quota_msg = check_monthly_quota()
    db_ok, db_size, db_msg = check_db_size()
    
    return jsonify({
        "quota": {
            "used": count,
            "limit": MAX_CUSTOM_REQUESTS,
            "available": quota_ok,
            "message": quota_msg
        },
        "storage": {
            "used_mb": round(db_size, 1),
            "limit_mb": 1000,
            "available": db_ok,
            "message": db_msg
        }
    })

@app.route('/api/query', methods=['POST'])
def natural_language_query():
    """
    Natural language to SQL query endpoint.
    
    Accepts: {"query": "natural language question"}
    Returns: {
        "result_type": "table|chart|number|list",
        "data": [...],
        "columns": [...],
        "sql": "generated SQL",
        "detected_companies": ["AAPL"],
        "execution_time": 0.123,
        "error": null
    }
    """
    try:
        data = request.json
        if not data or 'query' not in data:
            return jsonify({"error": "Missing 'query' field in request body"}), 400
        
        natural_query = data['query'].strip()
        if not natural_query:
            return jsonify({"error": "Query cannot be empty"}), 400
        
        # Import NP2SQL modules
        from src.np2sql.schema_metadata import get_schema_metadata
        from src.np2sql.np2sql_service import (
            generate_sql,
            validate_sql,
            detect_companies_in_query,
            execute_query,
            detect_result_type,
        )
        
        # Load schema metadata (cache it in production)
        schema_metadata = get_schema_metadata()
        
        # Detect companies in query
        detected_companies = detect_companies_in_query(natural_query)
        
        # Generate SQL
        try:
            sql = generate_sql(natural_query, schema_metadata)
        except ValueError as e:
            return jsonify({
                "error": f"I don't understand your question. {str(e)}",
                "detected_companies": detected_companies,
            }), 400
        
        # Validate SQL
        is_valid, error_message = validate_sql(sql)
        if not is_valid:
            return jsonify({
                "error": f"Invalid query: {error_message}",
                "sql": sql,
                "detected_companies": detected_companies,
            }), 400
        
        # Execute query
        try:
            # Use NP2SQL database URL (read-only) if available, otherwise fall back to regular
            from config import NP2SQL_DATABASE_URL, NP2SQL_QUERY_TIMEOUT, NP2SQL_MAX_ROWS
            # Always use DATABASE_URL for now (NP2SQL_DATABASE_URL requires separate read-only user setup)
            db_url = DATABASE_URL
            result = execute_query(sql, db_url, timeout=NP2SQL_QUERY_TIMEOUT, max_rows=NP2SQL_MAX_ROWS)
        except Exception as e:
            return jsonify({
                "error": f"Query execution failed: {str(e)}",
                "sql": sql,
                "detected_companies": detected_companies,
            }), 500
        
        # Detect result type
        result_type = detect_result_type(result)
        
        # Return success response
        response = {
            "result_type": result_type,
            "data": result["data"],
            "columns": result["columns"],
            "row_count": result["row_count"],
            "sql": sql,
            "detected_companies": detected_companies,
            "execution_time": result["execution_time"],
            "error": None,
        }
        
        if result.get("warning"):
            response["warning"] = result["warning"]
        
        return jsonify(response)
        
    except Exception as e:
        return jsonify({
            "error": f"Unexpected error: {str(e)}",
            "detected_companies": [],
        }), 500

@app.route('/api/metrics', methods=['POST'])
def get_available_metrics():
    """
    Get available normalized labels (metrics) for selected companies
    """
    data = request.json or {}
    companies = data.get('companies', [])
    start_year = data.get('start_year')
    end_year = data.get('end_year')
    
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(DATABASE_URL)
        
        with engine.begin() as conn:  # Use begin() for proper transaction handling
            # Gold serving view (medallion).
            query_str = """
                SELECT DISTINCT COALESCE(f.standard_label, f.normalized_label) AS normalized_label
                FROM gold.v_facts_hierarchical f
                WHERE 1=1
            """
            ticker_col = "f.ticker"
            year_col = "f.fiscal_year"

            params = {}
            
            if companies:
                query_str += f" AND {ticker_col} = ANY(:companies)"
                params['companies'] = companies
            
            if start_year is not None:
                query_str += f" AND {year_col} >= :start_year"
                params['start_year'] = start_year
            if end_year is not None:
                query_str += f" AND {year_col} <= :end_year"
                params['end_year'] = end_year
            
            query_str += " ORDER BY normalized_label"
            
            query = text(query_str)
            result = conn.execute(query, params)
            metrics = [row[0] for row in result if row[0]]
            
            return jsonify({
                "success": True,
                "metrics": metrics,
                "count": len(metrics)
            })
            
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/data', methods=['POST'])
def get_data():
    """
    Query data warehouse with filters
    Returns financial facts for visualization and analysis
    """
    data = request.json or {}
    companies = data.get('companies', [])
    start_year = data.get('start_year')
    end_year = data.get('end_year')
    concepts = data.get('concepts', [])  # normalized_label list
    show_segments = data.get('show_segments', False)
    min_hierarchy_level = data.get('min_hierarchy_level', 3)  # 1=all, 2=specific, 3=universal
    show_all_concepts = data.get('show_all_concepts', False)  # auditor view
    
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(DATABASE_URL)
        
        with engine.begin() as conn:  # Use begin() for proper transaction handling
            # Gold serving view (medallion) — dimensions embedded, no dim join needed.
            # normalized_label = edgartools standard concept where available (so different filers'
            # equivalent line items land on one comparable row), else the raw label. Auditor view
            # (show_all_concepts) uses the raw normalized_label instead.
            label_expr = "f.normalized_label" if show_all_concepts else "COALESCE(f.standard_label, f.normalized_label)"
            query_str = f"""
                SELECT
                    f.ticker as company,
                    f.concept_name as concept,
                    {label_expr} as normalized_label,
                    f.fiscal_year,
                    f.value_numeric,
                    f.value_text,
                    f.unit_measure,
                    f.hierarchy_level,
                    f.axis_name,
                    f.member_name,
                    CASE WHEN f.is_dimensioned THEN 'Segment' ELSE 'Total' END as data_type,
                    f.period_label,
                    COALESCE(f.end_date, f.instant_date) as period_end,
                    f.statement_type
                FROM gold.v_facts_hierarchical f
                WHERE 1=1
            """
            company_col = "f.ticker"
            fiscal_year_col = "f.fiscal_year"
            normalized_label_col = label_expr

            params = {}

            # Company filter
            if companies:
                query_str += f" AND {company_col} = ANY(:companies)"
                params['companies'] = companies

            # Year range
            if start_year is not None:
                query_str += f" AND {fiscal_year_col} >= :start_year"
                params['start_year'] = start_year
            if end_year is not None:
                query_str += f" AND {fiscal_year_col} <= :end_year"
                params['end_year'] = end_year

            # Concept filter
            if concepts:
                query_str += f" AND {normalized_label_col} = ANY(:concepts)"
                params['concepts'] = concepts

            # Granularity: "universal" (>=3) restricts to concepts edgartools standardizes, i.e.
            # the rows that are actually comparable across companies (few/no blanks). Lower levels
            # ("all line items") return everything, including the un-standardized long tail.
            if not show_all_concepts and min_hierarchy_level >= 3:
                query_str += " AND f.standard_label IS NOT NULL"

            # Segment filter
            if not show_segments:
                query_str += " AND f.is_dimensioned = false"

            query_str += " ORDER BY company, fiscal_year, normalized_label"
            
            query = text(query_str)
            result = conn.execute(query, params)
            rows = result.fetchall()
            
            # Convert to list of dicts
            data_rows = []
            for row in rows:
                data_rows.append({
                    "company": row[0],
                    "concept": row[1],
                    "normalized_label": row[2],
                    "fiscal_year": int(row[3]) if row[3] else None,
                    "value_numeric": float(row[4]) if row[4] is not None else None,
                    "value_text": row[5],
                    "unit_measure": row[6],
                    "hierarchy_level": row[7] if len(row) > 7 else None,
                    "axis_name": row[8] if len(row) > 8 else None,
                    "member_name": row[9] if len(row) > 9 else None,
                    "data_type": row[10] if len(row) > 10 else None,
                    "period_label": row[11] if len(row) > 11 else None,
                    "period_end": row[12].isoformat() if len(row) > 12 and row[12] else None,
                    "statement_type": row[13] if len(row) > 13 else None,
                })
            
            return jsonify({
                "success": True,
                "data": data_rows,
                "count": len(data_rows)
            })
            
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

_STATEMENTS_CACHE = {}
_LIAB_EQUITY_HEADER = re.compile(
    r"(LiabilitiesAndStockholdersEquityAbstract|LiabilitiesAndEquityAbstract|EquityAndLiabilitiesAbstract|EquityAndLiabilities$)")


def _stmt_num(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _stmt_unit(concept, label, currency):
    c, l = (concept or "").lower(), (label or "").lower()
    if "pershare" in c or "per share" in l:
        return f"{currency}/share"
    if "sharesoutstanding" in c or "in shares" in l or c.endswith("shares"):
        return "shares"
    return currency


def _stmt_items(df, period_type, currency, balance=False):
    """Turn an edgartools statement dataframe into the flat StatementItem[] the UI expects:
    ordered, labelled, level-nested (parent via the level stack), balance-sheet side-split."""
    df = df[df["dimension"] == False]  # non-dimensional statement lines only  # noqa: E712
    year_cols = [c for c in df.columns if re.match(r"\d{4}-\d{2}-\d{2}", str(c))]
    col_year = {c: int(str(c)[:4]) for c in year_cols}
    items, stack, side = [], [], ("assets" if balance else None)
    for order, (_, r) in enumerate(df.iterrows()):
        concept = str(r["concept"])
        label = r["label"] if isinstance(r["label"], str) else concept
        lvl = r["level"]
        level = 0 if (isinstance(lvl, float) and math.isnan(lvl)) else int(lvl)
        abstract = bool(r["abstract"])
        if balance and _LIAB_EQUITY_HEADER.search(concept):
            side = "liabilities_equity"
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1] if stack else None
        stack.append((level, concept))
        unit = _stmt_unit(concept, label, currency)
        for c in year_cols:
            items.append({
                "normalized_label": concept, "concept_name": concept, "preferred_label": label,
                "value": None if abstract else _stmt_num(r[c]), "unit": unit,
                "period_date": str(c), "period_year": col_year[c], "period_type": period_type,
                "hierarchy_level": level, "parent_normalized_label": parent,
                "presentation_order_index": order, "presentation_source": "xbrl",
                "is_header": abstract, "side": side,
            })
    return items, sorted(col_year.values(), reverse=True), (max(year_cols) if year_cols else None)


def _build_statements(ticker):
    import edgar
    from src.extraction.edgartools_adapter import EdgarToolsExtractor  # noqa: F401 (sets identity)
    EdgarToolsExtractor()  # edgar.set_identity(...)
    company = edgar.Company(ticker)
    filing = next((company.latest(f) for f in ("10-K", "20-F", "40-F") if company.latest(f)), None)
    if filing is None:
        return None
    xb = filing.xbrl()
    # reporting currency = modal 3-letter currency across the filing's facts
    currency = "USD"
    try:
        fdf = xb.facts.to_dataframe()
        cur = [v for v in fdf.get("currency", []) if isinstance(v, str) and len(v) == 3 and v.isupper()]
        if cur:
            currency = max(set(cur), key=cur.count)
    except Exception:
        pass
    specs = [("income_statement", "income_statement", "duration", False),
             ("comprehensive_income", "comprehensive_income", "duration", False),
             ("balance_sheet", "balance_sheet", "instant", True),
             ("cash_flow", "cash_flow_statement", "duration", False)]
    statements, years, fye = {}, [], None
    for key, method, ptype, bal in specs:
        try:
            df = getattr(xb.statements, method)().to_dataframe()
            items, yrs, last = _stmt_items(df, ptype, currency, bal)
            if items:
                statements[key] = items
                years = yrs or years
                if bal and last:
                    fye = last  # balance-sheet date = fiscal year end
        except Exception:
            continue
    std = "IFRS" if any("ifrs" in i["concept_name"].lower()
                        for v in statements.values() for i in v) else "US-GAAP"
    return {
        "company": getattr(company, "name", ticker), "ticker": ticker,
        "year": years[0] if years else None, "years": years,
        "accounting_standard": std, "fiscal_year_end": fye,
        "statements": statements, "count": sum(len(v) for v in statements.values()),
        "source": "edgartools",
    }


@app.route('/api/statements/<ticker>/<int:year>', methods=['GET'])
def get_financial_statements(ticker, year):
    """Full income / comprehensive-income / balance-sheet / cash-flow statements for the UI,
    rendered from edgartools' presentation structure (ordered, labelled, level-nested, with the
    balance sheet split into assets vs liabilities & equity). Cached per ticker. `year` is
    accepted for the legacy route but the latest annual filing is used."""
    ticker = ticker.upper()
    try:
        if ticker not in _STATEMENTS_CACHE:
            built = _build_statements(ticker)
            if built is None:
                return jsonify({"error": "not_found", "message": f"No annual report for {ticker}"}), 404
            _STATEMENTS_CACHE[ticker] = built
        return jsonify(_STATEMENTS_CACHE[ticker])
    except Exception as e:
        return jsonify({"error": "server_error", "message": str(e)}), 500


@app.route('/api/admin/migrate-schema', methods=['POST'])
def migrate_schema():
    """DEPRECATED. The legacy star-schema migrations it ran are retired; schema is now owned by
    the dbt medallion warehouse (bronze/silver/gold on Neon)."""
    return jsonify({
        "error": "gone",
        "message": "Legacy schema migrations are retired; schema is managed by dbt.",
    }), 410

@app.route('/api/admin/load-companies', methods=['POST'])
def admin_load_companies():
    """Admin endpoint to load companies without quota (for pre-loading)"""
    # Simple auth check - can be improved later
    auth_key = request.headers.get('X-Admin-Key')
    if auth_key != os.getenv('ADMIN_KEY', 'change-me-in-production'):
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    companies = data.get('companies', [])
    
    from src.ingestion.bronze import ingest as bronze_ingest
    from src.ingestion.corporate_actions import ingest as ca_ingest

    results = []
    for company_data in companies:
        ticker = company_data.get('ticker', '').upper()
        year = company_data.get('year')
        try:
            # Land into the medallion bronze layer (annual + quarters); serving views pick it up.
            bronze_ingest([ticker])
            try:
                ca_ingest([ticker])
            except Exception as e:  # noqa: BLE001 — splits are best-effort
                print(f"corporate-actions skip for {ticker}: {e}")
            results.append({"ticker": ticker, "year": year, "success": True})
        except Exception as e:
            results.append({"ticker": ticker, "year": year, "success": False, "error": str(e)})

    return jsonify({"results": results})


@app.route('/api/financials/<ticker>', methods=['GET'])
def get_financials_v2(ticker):
    """Phase-2 endpoint over the edgartools-backed warehouse: multi-year income / balance /
    cash-flow statements plus revenue-by-segment, read directly from fact_financial_metrics
    (the retired statement sub-tables and reconstruction layer are gone). Dashboard-ready."""
    ticker = ticker.upper()
    years_n = int(request.args.get('years', 3))
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            meta = conn.execute(text("""
                SELECT (SELECT company_name FROM gold.companies WHERE ticker=:t LIMIT 1) AS company_name,
                       MAX(COALESCE(end_date, instant_date)) AS fye
                FROM gold.v_facts_hierarchical
                WHERE ticker=:t AND period_grain IN ('annual','instant')
            """), {"t": ticker}).fetchone()
            if not meta or meta[0] is None:
                return jsonify({"error": "not_found", "message": f"No data for {ticker}"}), 404

            rows = conn.execute(text("""
                SELECT statement_type, normalized_label, preferred_label AS label,
                       fiscal_year, value_numeric, unit_measure, value_usd
                FROM gold.v_facts_hierarchical
                WHERE ticker=:t AND is_dimensioned=false AND value_numeric IS NOT NULL
                  AND statement_type IN ('income_statement','balance_sheet','cash_flow')
                  AND period_grain IN ('annual','instant')
            """), {"t": ticker}).fetchall()

            all_years = sorted({r[3] for r in rows if r[3]}, reverse=True)[:years_n]
            yset, cur = set(all_years), None
            stmts = {"income_statement": {}, "balance_sheet": {}, "cash_flow": {}}
            for st, nl, label, fy, val, unit, val_usd in rows:
                if fy not in yset:
                    continue
                if cur is None and unit and len(unit) == 3 and unit.isupper():
                    cur = unit  # a real currency code (USD/DKK/…), not 'shares'/'pure'
                line = stmts[st].setdefault(nl, {"label": label, "values": {}, "values_usd": {}})
                line["values"][fy] = float(val)
                if val_usd is not None:
                    line["values_usd"][fy] = float(val_usd)
            statements = {st: sorted(items.values(), key=lambda x: x["label"]) for st, items in stmts.items()}

            seg_rows = conn.execute(text("""
                SELECT fiscal_year, dimension_json->>'srt_ProductOrServiceAxis' AS member, value_numeric
                FROM gold.v_facts_hierarchical
                WHERE ticker=:t
                  AND split_part(concept_name, ':', 2) IN ('RevenueFromContractWithCustomerExcludingAssessedTax',
                                                           'RevenueFromContractWithCustomerIncludingAssessedTax')
                  AND dimension_json ? 'srt_ProductOrServiceAxis'
                  AND (SELECT count(*) FROM jsonb_object_keys(dimension_json))=1
                  AND period_grain='annual'
            """), {"t": ticker}).fetchall()
            segments = {}
            for fy, member, val in seg_rows:
                if fy in yset and member:
                    segments.setdefault(fy, {})[member.split(':')[-1].replace('Member', '')] = float(val)

            return jsonify({
                "ticker": ticker, "company": meta[0], "currency": cur,
                "fiscal_year_end": str(meta[1]) if meta[1] else None,
                "years": all_years, "statements": statements,
                "revenue_by_segment": segments, "source": "edgartools",
            })
    except Exception as e:
        return jsonify({"error": "server_error", "message": str(e)}), 500


@app.route('/api/ratios/<ticker>', methods=['GET'])
def get_ratios(ticker):
    """Multi-year financial ratios (margins, ROE/ROA, leverage, FCF, growth) for one company,
    computed from the warehouse in USD. See src/analysis/ratios.py."""
    try:
        from src.analysis.ratios import company_ratios
        years = int(request.args.get('years', 3))
        data = company_ratios(DATABASE_URL, ticker, years=years)
        if not data["years"]:
            return jsonify({"error": "not_found", "message": f"No data for {ticker.upper()}"}), 404
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": "server_error", "message": str(e)}), 500


@app.route('/api/forecast/<ticker>', methods=['GET'])
def get_forecast(ticker):
    """Next-quarter earnings forecast + live track record for a company, read from the forecast
    ledger (leakage-safe, logged before each print). Returns the current pending forecast(s),
    graded history, and running accuracy vs analyst consensus. Pure read — no backtest."""
    try:
        from src.analysis.forecast_log import read_forecast
        data = read_forecast(DATABASE_URL, ticker)
        if not data["pending"] and not data["history"]:
            return jsonify({"error": "not_found",
                            "message": f"No forecast for {ticker.upper()}. Tracked: "
                                       "NVDA, AMZN, AVGO, MSFT, GOOGL, AAPL, JPM."}), 404
        return jsonify(data)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": "server_error", "message": str(e)}), 500


@app.route('/api/track-record', methods=['GET'])
def get_track_record():
    """Cross-company forecast scorecard from the live ledger: per (ticker, metric) realized
    accuracy (our MAPE vs analyst-consensus MAPE over graded quarters), plus per-metric overall
    and the count of pending (logged-but-not-yet-reported) forecasts. Pure read."""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT ticker, metric,
                       COUNT(*) FILTER (WHERE graded_at IS NOT NULL) AS n,
                       AVG(our_ape) FILTER (WHERE graded_at IS NOT NULL) AS our_mape,
                       AVG(consensus_ape) FILTER (WHERE graded_at IS NOT NULL
                                                  AND consensus_ape IS NOT NULL) AS cons_mape
                FROM forecasts.forecast_log
                GROUP BY ticker, metric
                HAVING COUNT(*) FILTER (WHERE graded_at IS NOT NULL) > 0
                ORDER BY ticker, metric
            """)).fetchall()
            pending = conn.execute(text("""
                SELECT COUNT(*) FROM forecasts.forecast_log WHERE graded_at IS NULL
            """)).scalar()
            overall = conn.execute(text("""
                SELECT metric,
                       AVG(our_ape) AS our_mape,
                       AVG(consensus_ape) FILTER (WHERE consensus_ape IS NOT NULL) AS cons_mape,
                       COUNT(*) AS n
                FROM forecasts.forecast_log
                WHERE graded_at IS NOT NULL
                GROUP BY metric ORDER BY metric
            """)).fetchall()
        def pct(x):
            return round(float(x) * 100, 1) if x is not None else None
        scorecard = [{
            "ticker": r[0], "metric": r[1], "n": r[2],
            "our_mape": pct(r[3]), "consensus_mape": pct(r[4]),
        } for r in rows]
        return jsonify({
            "pending_count": pending or 0,
            "overall": [{"metric": o[0], "our_mape": pct(o[1]),
                         "consensus_mape": pct(o[2]), "n": o[3]} for o in overall],
            "scorecard": scorecard,
        })
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": "server_error", "message": str(e)}), 500


@app.route('/api/peers', methods=['GET'])
def get_peers():
    """Latest-year peer comparison across all loaded companies: headline USD figures + key
    ratios, revenue-sorted. Currency-normalized so foreign filers (e.g. NVO) line up."""
    try:
        from src.analysis.ratios import peer_comparison
        return jsonify({"as_of": "latest_filed", "currency": "USD",
                        "companies": peer_comparison(DATABASE_URL)})
    except Exception as e:
        return jsonify({"error": "server_error", "message": str(e)}), 500


# ---------------------------------------------------------------------------
# Data provenance / lineage (the transparency surface). All read-only. These let the UI
# browse the raw bronze filings and trace any served number back to its source SEC filing.
# ---------------------------------------------------------------------------

@app.route('/api/filings/<ticker>', methods=['GET'])
def get_filings(ticker):
    """Bronze filings browser: every SEC filing ingested for a company, newest first, with a
    raw-fact count and a direct EDGAR link. Reads bronze.raw_filings only."""
    ticker = ticker.upper()
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT rf.accession, rf.cik, rf.company_name, rf.form,
                       rf.filing_date, rf.period_of_report,
                       (SELECT COUNT(*) FROM bronze.raw_facts WHERE accession = rf.accession) AS fact_count
                FROM bronze.raw_filings rf
                WHERE rf.ticker = :t
                ORDER BY rf.filing_date DESC NULLS LAST, rf.accession DESC
            """), {"t": ticker}).fetchall()
        if not rows:
            return jsonify({"error": "not_found", "message": f"No filings for {ticker}"}), 404
        filings = [{
            "accession": r[0], "cik": r[1], "company_name": r[2], "form": r[3],
            "filing_date": str(r[4]) if r[4] else None,
            "period_of_report": str(r[5]) if r[5] else None,
            "fact_count": r[6],
            "edgar_url": edgar_filing_url(r[1], r[0]),
        } for r in rows]
        return jsonify({"ticker": ticker, "count": len(filings), "filings": filings})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": "server_error", "message": str(e)}), 500


@app.route('/api/raw-facts/<ticker>', methods=['GET'])
def get_raw_facts(ticker):
    """Bronze drill-down: the raw XBRL facts as ingested for one filing, exactly as filed
    (native currency, raw concept, dimensions as JSON). Requires ?accession=."""
    ticker = ticker.upper()
    accession = request.args.get('accession')
    if not accession:
        return jsonify({"error": "bad_request", "message": "accession query param is required"}), 400
    limit = min(int(request.args.get('limit', 500)), 5000)
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            header = conn.execute(text("""
                SELECT accession, cik, company_name, form, filing_date, period_of_report
                FROM bronze.raw_filings WHERE accession = :a AND ticker = :t
            """), {"a": accession, "t": ticker}).fetchone()
            if not header:
                return jsonify({"error": "not_found",
                                "message": f"No filing {accession} for {ticker}"}), 404
            rows = conn.execute(text("""
                SELECT fact_id, concept, label, standard_label, value_numeric, value_text, unit,
                       period_type, period_start, period_end, instant_date,
                       fiscal_year, fiscal_period, statement_type, dimensions, is_dimensioned
                FROM bronze.raw_facts
                WHERE ticker = :t AND accession = :a
                ORDER BY statement_type NULLS LAST, concept
                LIMIT :lim
            """), {"t": ticker, "a": accession, "lim": limit}).fetchall()
        facts = [{
            "fact_id": r[0], "concept": r[1], "label": r[2], "standard_label": r[3],
            "value_numeric": float(r[4]) if r[4] is not None else None, "value_text": r[5],
            "unit": r[6], "period_type": r[7],
            "period_start": str(r[8]) if r[8] else None, "period_end": str(r[9]) if r[9] else None,
            "instant_date": str(r[10]) if r[10] else None,
            "fiscal_year": r[11], "fiscal_period": r[12], "statement_type": r[13],
            "dimensions": r[14], "is_dimensioned": r[15],
        } for r in rows]
        return jsonify({
            "ticker": ticker,
            "filing": {
                "accession": header[0], "cik": header[1], "company_name": header[2],
                "form": header[3], "filing_date": str(header[4]) if header[4] else None,
                "period_of_report": str(header[5]) if header[5] else None,
                "edgar_url": edgar_filing_url(header[1], header[0]),
            },
            "count": len(facts), "truncated": len(facts) >= limit, "facts": facts,
        })
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": "server_error", "message": str(e)}), 500


@app.route('/api/canonical-facts/<ticker>', methods=['GET'])
def get_canonical_facts(ticker):
    """Silver view: the conformed fact grain, one row per economic fact (deduped to the latest
    filing), with the canonical label resolved so synonymous concepts reconcile 1:1. Reads
    silver.fct_financial_facts directly."""
    ticker = ticker.upper()
    limit = min(int(request.args.get('limit', 1000)), 5000)
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT accession, concept, canonical_label, standard_label,
                       value_usd, value_numeric, unit, fiscal_year, fiscal_period,
                       period_type, statement_type
                FROM silver.fct_financial_facts
                WHERE ticker = :t AND is_dimensioned = false AND canonical_label IS NOT NULL
                ORDER BY fiscal_year DESC NULLS LAST, canonical_label, fiscal_period
                LIMIT :lim
            """), {"t": ticker, "lim": limit}).fetchall()
        if not rows:
            return jsonify({"error": "not_found", "message": f"No canonical facts for {ticker}"}), 404
        facts = [{
            "accession": r[0], "concept": r[1], "canonical_label": r[2], "standard_label": r[3],
            "value_usd": float(r[4]) if r[4] is not None else None,
            "value_numeric": float(r[5]) if r[5] is not None else None,
            "unit": r[6], "fiscal_year": r[7], "fiscal_period": r[8],
            "period_type": r[9], "statement_type": r[10],
        } for r in rows]
        return jsonify({"ticker": ticker, "count": len(facts),
                        "truncated": len(facts) >= limit, "facts": facts})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": "server_error", "message": str(e)}), 500


@app.route('/api/lineage/layers', methods=['GET'])
def get_lineage_layers():
    """Plain-English explanation + a faithful code excerpt for each medallion layer
    (bronze -> silver -> gold). Curated, read-only. See src/provenance/layers.py."""
    return jsonify({"layers": all_layers()})


@app.route('/api/lineage/<ticker>', methods=['GET'])
def get_lineage(ticker):
    """Trace one reported number back to its source SEC filing. Identify the fact either by
    ?fact_id=<n> (from the raw-facts drill-down) or by ?concept=<xbrl concept>&fiscal_year=<y>
    [&fiscal_period=<p>] (the identity the statements views carry). Returns the layered chain
    gold -> silver -> bronze -> filing, plus the EDGAR url."""
    ticker = ticker.upper()
    fact_id = request.args.get('fact_id')
    concept = request.args.get('concept')
    fy = request.args.get('fiscal_year')
    fp = request.args.get('fiscal_period')  # optional; None matches any
    if not fact_id and not (concept and fy):
        return jsonify({"error": "bad_request",
                        "message": "provide fact_id, or concept + fiscal_year"}), 400
    # The statements UI carries the concept as edgartools emits it ("us-gaap_Revenues" or
    # "us-gaap:Revenues" or a bare local name); gold stores "taxonomy:LocalName". Match on the
    # local part so the trace resolves regardless of the taxonomy-prefix separator.
    local = concept.split(':')[-1].split('_')[-1] if concept else None
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            # Anchor on a bronze fact if a fact_id was given; otherwise on the gold serving row.
            gold = None
            if fact_id:
                bf = conn.execute(text("""
                    SELECT accession, concept, value_numeric, unit, fiscal_year, fiscal_period
                    FROM bronze.raw_facts WHERE fact_id = :fid AND ticker = :t
                """), {"fid": int(fact_id), "t": ticker}).fetchone()
                if not bf:
                    return jsonify({"error": "not_found",
                                    "message": f"No fact {fact_id} for {ticker}"}), 404
                accession, concept = bf[0], bf[1]
                bronze_value, bronze_unit = bf[2], bf[3]
            else:
                try:
                    gold = conn.execute(text("""
                        SELECT ticker, concept_name, normalized_label, standard_label, preferred_label,
                               statement_type, fiscal_year, fiscal_period, period_label,
                               value_numeric, value_usd, unit_measure, is_dimensioned, accession
                        FROM gold.v_facts_hierarchical
                        WHERE ticker = :t AND fiscal_year = :fy
                          AND (concept_name = :c OR split_part(concept_name, ':', 2) = :local)
                          AND (:fp IS NULL OR fiscal_period = :fp)
                          AND is_dimensioned = false
                        -- prefer the annual-report fact (what the statements view shows) over a
                        -- same-year quarterly row; exact concept match wins over a local-name match
                        ORDER BY (concept_name = :c) DESC,
                                 (period_grain IN ('annual', 'instant')) DESC,
                                 fiscal_year DESC
                        LIMIT 1
                    """), {"t": ticker, "c": concept, "local": local,
                           "fy": int(fy), "fp": fp}).fetchone()
                except Exception as col_err:  # noqa: BLE001
                    msg = str(col_err).lower()
                    if "accession" in msg and "column" in msg:
                        return jsonify({"error": "warming_up",
                                        "message": "lineage is being prepared; try again shortly"}), 503
                    raise
                if not gold:
                    return jsonify({"error": "not_found",
                                    "message": f"No {concept} for {ticker} {fy}"}), 404
                accession = gold[13]
                concept = gold[1]  # canonicalize to the gold concept_name (matches bronze format)
                # the matching bronze fact (exact source) = same accession+concept, value matches gold
                bronze_value, bronze_unit = gold[9], gold[11]
                bf = conn.execute(text("""
                    SELECT value_numeric, unit FROM bronze.raw_facts
                    WHERE accession = :a AND concept = :c AND is_dimensioned = false
                    ORDER BY (value_numeric = :v) DESC NULLS LAST LIMIT 1
                """), {"a": accession, "c": concept, "v": gold[9]}).fetchone()
                if bf:
                    bronze_value, bronze_unit = bf[0], bf[1]

            filing = conn.execute(text("""
                SELECT accession, cik, company_name, form, filing_date, period_of_report
                FROM bronze.raw_filings WHERE accession = :a
            """), {"a": accession}).fetchone()

        resp = {
            "ticker": ticker,
            "gold": None if gold is None else {
                "normalized_label": gold[2], "standard_label": gold[3], "preferred_label": gold[4],
                "statement_type": gold[5], "fiscal_year": gold[6], "fiscal_period": gold[7],
                "period_label": gold[8],
                "value_numeric": float(gold[9]) if gold[9] is not None else None,
                "value_usd": float(gold[10]) if gold[10] is not None else None,
                "unit": gold[11],
            },
            "silver": {
                "note": "deduped to the latest filing vintage; canonical label resolved so "
                        "synonymous concepts reconcile 1:1",
            },
            "bronze": {
                "accession": accession, "concept": concept,
                "value_numeric": float(bronze_value) if bronze_value is not None else None,
                "unit": bronze_unit,
            },
            "filing": None if not filing else {
                "accession": filing[0], "cik": filing[1], "company_name": filing[2],
                "form": filing[3], "filing_date": str(filing[4]) if filing[4] else None,
                "period_of_report": str(filing[5]) if filing[5] else None,
            },
            "edgar_url": edgar_filing_url(filing[1], filing[0]) if filing else None,
        }
        return jsonify(resp)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": "server_error", "message": str(e)}), 500


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('ENVIRONMENT') != 'production')

