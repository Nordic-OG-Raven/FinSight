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

from src.main import run_pipeline
from src.utils.concept_label_mapping import get_humanized_label
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
            query = text("""
                SELECT DISTINCT
                    c.ticker,
                    EXTRACT(YEAR FROM f.fiscal_year_end)::INTEGER as year,
                    tp.fiscal_quarter,
                    f.filing_type,
                    f.reporting_frequency
                FROM fact_financial_metrics fm
                JOIN dim_companies c ON fm.company_id = c.company_id
                JOIN dim_filings f ON fm.filing_id = f.filing_id
                LEFT JOIN dim_time_periods tp ON fm.period_id = tp.period_id
                WHERE fm.dimension_id IS NULL
                ORDER BY c.ticker, year DESC, tp.fiscal_quarter NULLS LAST
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
    """Initialize database tables - one-time setup endpoint"""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(DATABASE_URL)
        
        with engine.connect() as conn:
            # Create financial_facts table
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS financial_facts (
                    id SERIAL PRIMARY KEY,
                    company VARCHAR(10) NOT NULL,
                    concept VARCHAR(500) NOT NULL,
                    normalized_label VARCHAR(500),
                    value NUMERIC,
                    unit VARCHAR(50),
                    period_start DATE,
                    period_end DATE,
                    fiscal_year_end DATE,
                    instant_date DATE,
                    context_id VARCHAR(500),
                    decimals INTEGER,
                    taxonomy VARCHAR(100),
                    filing_type VARCHAR(10),
                    filing_date DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT unique_fact UNIQUE (company, concept, context_id, period_end)
                )
            """))
            
            # Create indexes
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_company ON financial_facts(company)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_fiscal_year ON financial_facts(fiscal_year_end)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_normalized_label ON financial_facts(normalized_label)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_company_year ON financial_facts(company, fiscal_year_end)"))
            
            conn.commit()
            
            return jsonify({
                "status": "success",
                "message": "Database tables created successfully"
            })
            
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

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
            # Check if data exists
            query = text("""
                SELECT COUNT(*) as count
                FROM fact_financial_metrics fm
                JOIN dim_companies c ON fm.company_id = c.company_id
                JOIN dim_filings f ON fm.filing_id = f.filing_id
                WHERE c.ticker = :ticker 
                  AND EXTRACT(YEAR FROM f.fiscal_year_end) = :year
            """)
            result = conn.execute(query, {"ticker": ticker, "year": year})
            count = result.fetchone()[0]
            
            if count == 0:
                return jsonify({
                    "error": "not_found",
                    "message": f"No data for {ticker} {year}. Try custom analysis or select a pre-loaded company."
                }), 404
            
            # Fetch ALL metrics (not just hardcoded 9)
            # Use COALESCE to handle both duration (end_date) and instant (instant_date) periods
            # Check if hierarchy_level column exists (handle schema migration gracefully)
            try:
                check_col = text("SELECT hierarchy_level FROM dim_concepts LIMIT 1")
                conn.execute(check_col)
                has_hierarchy = True
            except:
                has_hierarchy = False
            
            if has_hierarchy:
                metrics_query = text("""
                    SELECT 
                        co.normalized_label, 
                        fm.value_numeric as value,
                        fm.unit_measure as unit,
                        COALESCE(p.end_date, p.instant_date) as period_end,
                        p.period_type,
                        co.statement_type,
                        co.hierarchy_level
                    FROM fact_financial_metrics fm
                    JOIN dim_companies c ON fm.company_id = c.company_id
                    JOIN dim_concepts co ON fm.concept_id = co.concept_id
                    JOIN dim_time_periods p ON fm.period_id = p.period_id
                    JOIN dim_filings f ON fm.filing_id = f.filing_id
                    LEFT JOIN rel_presentation_hierarchy ph ON 
                        ph.filing_id = f.filing_id 
                        AND ph.child_concept_id = co.concept_id
                        AND ph.parent_concept_id IS NOT DISTINCT FROM co.parent_concept_id
                    WHERE c.ticker = :ticker 
                      AND EXTRACT(YEAR FROM f.fiscal_year_end) = :year
                      AND fm.dimension_id IS NULL
                      AND fm.value_numeric IS NOT NULL
                    ORDER BY 
                        CASE 
                            WHEN co.statement_type IS NULL THEN 4
                            WHEN co.statement_type = 'income_statement' THEN 1
                            WHEN co.statement_type = 'balance_sheet' THEN 2
                            WHEN co.statement_type = 'cash_flow' THEN 3
                            ELSE 4
                        END,
                        -- Two-tier ordering: XBRL first, then standard templates
                        CASE 
                            WHEN ph.source = 'xbrl' THEN 1
                            WHEN ph.source = 'standard' THEN 2
                            ELSE 3
                        END,
                        COALESCE(ph.order_index, 999999),
                        COALESCE(co.hierarchy_level, 0) DESC,
                        co.normalized_label
                """)
            else:
                # Fallback for older schema without hierarchy_level
                metrics_query = text("""
                    SELECT 
                        co.normalized_label, 
                        fm.value_numeric as value,
                        fm.unit_measure as unit,
                        COALESCE(p.end_date, p.instant_date) as period_end,
                        p.period_type,
                        co.statement_type,
                        NULL as hierarchy_level
                    FROM fact_financial_metrics fm
                    JOIN dim_companies c ON fm.company_id = c.company_id
                    JOIN dim_concepts co ON fm.concept_id = co.concept_id
                    JOIN dim_time_periods p ON fm.period_id = p.period_id
                    JOIN dim_filings f ON fm.filing_id = f.filing_id
                    WHERE c.ticker = :ticker 
                      AND EXTRACT(YEAR FROM f.fiscal_year_end) = :year
                      AND fm.dimension_id IS NULL
                      AND fm.value_numeric IS NOT NULL
                    ORDER BY 
                        CASE WHEN co.statement_type = 'income_statement' THEN 1
                             WHEN co.statement_type = 'balance_sheet' THEN 2
                             WHEN co.statement_type = 'cash_flow' THEN 3
                             ELSE 4
                        END,
                        co.normalized_label
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
    
    # Check if already exists in DB
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(DATABASE_URL)
        
        with engine.connect() as conn:
            check_query = text("""
                SELECT COUNT(*) as count
                FROM financial_facts
                WHERE company = :ticker AND EXTRACT(YEAR FROM fiscal_year_end) = :year
            """)
            result = conn.execute(check_query, {"ticker": ticker, "year": year})
            count = result.fetchone()[0]
            
            if count > 0:
                # Already processed, return existing data
                return analyze_preloaded(ticker, year)
    except:
        pass
    
    # Run full ETL pipeline with timeout
    try:
        print(f"Starting ETL pipeline for {ticker} {year}...")
        
        with timeout(600):  # 10 minute max
            # Run pipeline from src/main.py
            success = run_pipeline(ticker=ticker, year=year)
            
            if not success:
                return jsonify({
                    "error": "pipeline_failed",
                    "message": f"Failed to process {ticker} {year}. Filing may not exist or be in unsupported format."
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
            # Check if view exists (use separate connection to avoid transaction issues)
            try:
                test_engine = create_engine(DATABASE_URL)
                with test_engine.connect() as test_conn:
                    test_query = text("SELECT 1 FROM v_facts_hierarchical LIMIT 1")
                    test_conn.execute(test_query)
                use_view = True
                test_engine.dispose()
            except:
                use_view = False
            
            if use_view:
                query_str = """
                    SELECT DISTINCT f.normalized_label
                    FROM v_facts_hierarchical f
                    WHERE 1=1
                """
                ticker_col = "f.ticker"
                year_col = "f.fiscal_year"
            else:
                query_str = """
                    SELECT DISTINCT co.normalized_label
                    FROM fact_financial_metrics f
                    JOIN dim_companies c ON f.company_id = c.company_id
                    JOIN dim_concepts co ON f.concept_id = co.concept_id
                    JOIN dim_time_periods t ON f.period_id = t.period_id
                    JOIN dim_filings fi ON f.filing_id = fi.filing_id
                    WHERE 1=1
                """
                ticker_col = "c.ticker"
                year_col = "EXTRACT(YEAR FROM fi.fiscal_year_end)"
            
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
            # Build query string
            if show_all_concepts:
                # Raw table query
                query_str = """
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
                        CASE WHEN f.dimension_id IS NULL THEN 'Total' ELSE 'Segment' END as data_type,
                        t.period_label,
                        t.end_date as period_end
                    FROM fact_financial_metrics f
                    JOIN dim_companies c ON f.company_id = c.company_id
                    JOIN dim_concepts co ON f.concept_id = co.concept_id
                    JOIN dim_time_periods t ON f.period_id = t.period_id
                    LEFT JOIN dim_xbrl_dimensions d ON f.dimension_id = d.dimension_id
                    WHERE 1=1
                """
                company_col = "c.ticker"
                fiscal_year_col = "t.fiscal_year"
                normalized_label_col = "co.normalized_label"
            else:
                # Try hierarchical view first, fallback to raw table if view doesn't exist
                # Check if view exists by trying to query it (use separate connection to avoid transaction issues)
                try:
                    test_engine = create_engine(DATABASE_URL)
                    with test_engine.connect() as test_conn:
                        test_query = text("SELECT 1 FROM v_facts_hierarchical LIMIT 1")
                        test_conn.execute(test_query)
                    use_view = True
                    test_engine.dispose()
                except:
                    use_view = False
                
                if use_view:
                    # Hierarchical view (deduplicated)
                    query_str = """
                        SELECT 
                            f.ticker as company,
                            f.concept_name as concept,
                            f.normalized_label,
                            f.fiscal_year,
                            f.value_numeric,
                            f.value_text,
                            f.unit_measure,
                            f.hierarchy_level,
                            d.axis_name,
                            d.member_name,
                            CASE WHEN f.dimension_id IS NULL THEN 'Total' ELSE 'Segment' END as data_type,
                            t.period_label,
                            COALESCE(t.end_date, t.instant_date) as period_end
                        FROM v_facts_hierarchical f
                        LEFT JOIN dim_xbrl_dimensions d ON f.dimension_id = d.dimension_id
                        LEFT JOIN dim_time_periods t ON f.period_id = t.period_id
                        WHERE 1=1
                    """
                    company_col = "f.ticker"
                    fiscal_year_col = "f.fiscal_year"
                    normalized_label_col = "f.normalized_label"
                else:
                    # Fallback to raw table with hierarchy_level from dim_concepts
                    query_str = """
                        SELECT 
                            c.ticker as company,
                            co.concept_name as concept,
                            co.normalized_label,
                            t.fiscal_year,
                            f.value_numeric,
                            f.value_text,
                            f.unit_measure,
                            co.hierarchy_level,
                            d.axis_name,
                            d.member_name,
                            CASE WHEN f.dimension_id IS NULL THEN 'Total' ELSE 'Segment' END as data_type,
                            t.period_label,
                            COALESCE(t.end_date, t.instant_date) as period_end
                        FROM fact_financial_metrics f
                        JOIN dim_companies c ON f.company_id = c.company_id
                        JOIN dim_concepts co ON f.concept_id = co.concept_id
                        JOIN dim_time_periods t ON f.period_id = t.period_id
                        LEFT JOIN dim_xbrl_dimensions d ON f.dimension_id = d.dimension_id
                        WHERE 1=1
                    """
                    company_col = "c.ticker"
                    fiscal_year_col = "t.fiscal_year"
                    normalized_label_col = "co.normalized_label"
            
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
            
            # Hierarchy level filter (only for hierarchical view)
            # Only apply if hierarchy_level column exists and has values
            if not show_all_concepts:
                if use_view:
                    query_str += " AND (f.hierarchy_level IS NULL OR f.hierarchy_level >= :min_hierarchy_level)"
                else:
                    query_str += " AND (co.hierarchy_level IS NULL OR co.hierarchy_level >= :min_hierarchy_level)"
                params['min_hierarchy_level'] = min_hierarchy_level
            
            # Segment filter
            if not show_segments:
                query_str += " AND f.dimension_id IS NULL"
            
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
    """Admin endpoint to run database schema migration"""
    auth_key = request.headers.get('X-Admin-Key')
    if auth_key != os.getenv('ADMIN_KEY', 'change-me-in-production'):
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(DATABASE_URL)
        
        migration_sql = """
        -- Add hierarchy_level if missing
        DO $$ 
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'dim_concepts' 
                AND column_name = 'hierarchy_level'
            ) THEN
                ALTER TABLE dim_concepts ADD COLUMN hierarchy_level INTEGER;
            END IF;
        END $$;
        
        -- Add parent_concept_id if missing
        DO $$ 
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'dim_concepts' 
                AND column_name = 'parent_concept_id'
            ) THEN
                ALTER TABLE dim_concepts ADD COLUMN parent_concept_id INTEGER REFERENCES dim_concepts(concept_id) ON DELETE SET NULL;
            END IF;
        END $$;
        
        -- Add is_calculated if missing
        DO $$ 
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'dim_concepts' 
                AND column_name = 'is_calculated'
            ) THEN
                ALTER TABLE dim_concepts ADD COLUMN is_calculated BOOLEAN DEFAULT FALSE;
            END IF;
        END $$;
        
        -- Add calculation_weight if missing
        DO $$ 
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'dim_concepts' 
                AND column_name = 'calculation_weight'
            ) THEN
                ALTER TABLE dim_concepts ADD COLUMN calculation_weight DECIMAL(10,4) DEFAULT 1.0;
            END IF;
        END $$;
        
        -- Add statement_type if missing
        DO $$ 
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'dim_concepts' 
                AND column_name = 'statement_type'
            ) THEN
                ALTER TABLE dim_concepts ADD COLUMN statement_type VARCHAR(50);
            END IF;
        END $$;
        
        CREATE INDEX IF NOT EXISTS idx_concepts_hierarchy_level ON dim_concepts(hierarchy_level);
        CREATE INDEX IF NOT EXISTS idx_concepts_parent ON dim_concepts(parent_concept_id);
        CREATE INDEX IF NOT EXISTS idx_concepts_statement ON dim_concepts(statement_type);
        """
        
        with engine.begin() as conn:  # Use begin() for autocommit
            conn.execute(text(migration_sql))
            
            # Verify columns
            verify_query = text("""
                SELECT column_name, data_type 
                FROM information_schema.columns
                WHERE table_name = 'dim_concepts'
                ORDER BY ordinal_position
            """)
            result = conn.execute(verify_query)
            columns = [{"name": row[0], "type": row[1]} for row in result]
            
            return jsonify({
                "success": True,
                "message": "Schema migration completed",
                "columns": columns
            })
            
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/admin/load-companies', methods=['POST'])
def admin_load_companies():
    """Admin endpoint to load companies without quota (for pre-loading)"""
    # Simple auth check - can be improved later
    auth_key = request.headers.get('X-Admin-Key')
    if auth_key != os.getenv('ADMIN_KEY', 'change-me-in-production'):
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    companies = data.get('companies', [])
    
    results = []
    for company_data in companies:
        ticker = company_data.get('ticker', '').upper()
        year = company_data.get('year')
        filing_type = company_data.get('filing_type', '10-K')
        
        try:
            success = run_pipeline(ticker=ticker, year=year, filing_type=filing_type)
            results.append({
                "ticker": ticker,
                "year": year,
                "success": success
            })
        except Exception as e:
            results.append({
                "ticker": ticker,
                "year": year,
                "success": False,
                "error": str(e)
            })
    
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
            meta = conn.execute(text(
                "SELECT c.company_name, MAX(f.fiscal_year_end) FROM dim_companies c "
                "JOIN dim_filings f ON f.company_id=c.company_id WHERE c.ticker=:t GROUP BY c.company_name"
            ), {"t": ticker}).fetchone()
            if not meta:
                return jsonify({"error": "not_found", "message": f"No data for {ticker}"}), 404

            rows = conn.execute(text("""
                SELECT dc.statement_type, dc.normalized_label,
                       COALESCE(dc.preferred_label, dc.concept_name) AS label,
                       f.fiscal_year, f.value_numeric, f.unit_measure, f.value_usd
                FROM fact_financial_metrics f
                JOIN dim_companies c ON c.company_id=f.company_id
                JOIN dim_concepts dc ON dc.concept_id=f.concept_id
                JOIN dim_time_periods dt ON dt.period_id=f.period_id
                WHERE c.ticker=:t AND f.dimension_id IS NULL AND f.value_numeric IS NOT NULL
                  AND dc.statement_type IN ('income_statement','balance_sheet','cash_flow')
                  AND (dt.period_type='instant' OR (dt.end_date-dt.start_date) BETWEEN 330 AND 380)
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
                SELECT f.fiscal_year, d.dimension_json->>'srt_ProductOrServiceAxis' AS member, f.value_numeric
                FROM fact_financial_metrics f
                JOIN dim_companies c ON c.company_id=f.company_id
                JOIN dim_concepts dc ON dc.concept_id=f.concept_id
                JOIN dim_xbrl_dimensions d ON d.dimension_id=f.dimension_id
                JOIN dim_time_periods dt ON dt.period_id=f.period_id
                WHERE c.ticker=:t
                  AND dc.concept_name IN ('RevenueFromContractWithCustomerExcludingAssessedTax',
                                          'RevenueFromContractWithCustomerIncludingAssessedTax')
                  AND d.dimension_json ? 'srt_ProductOrServiceAxis'
                  AND (SELECT count(*) FROM jsonb_object_keys(d.dimension_json))=1
                  AND (dt.end_date-dt.start_date) BETWEEN 330 AND 380
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


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('ENVIRONMENT') != 'production')

