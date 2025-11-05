"""
FinSight API
Flask backend for financial data extraction and analysis
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path
from flask import Flask, jsonify, request
from flask_cors import CORS
import signal
from contextlib import contextmanager

# Add parent directory to path to import from src/
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.main import run_pipeline
from config import DATABASE_URL

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
    """Dynamically query database for available companies and years"""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(DATABASE_URL)
        
        with engine.connect() as conn:
            # Query for companies and their available years
            query = text("""
                SELECT 
                    c.ticker,
                    EXTRACT(YEAR FROM f.fiscal_year_end)::INTEGER as year
                FROM fact_financial_metrics fm
                JOIN dim_companies c ON fm.company_id = c.company_id
                JOIN dim_filings f ON fm.filing_id = f.filing_id
                WHERE fm.dimension_id IS NULL
                GROUP BY c.ticker, EXTRACT(YEAR FROM f.fiscal_year_end)
                ORDER BY c.ticker, year DESC
            """)
            
            result = conn.execute(query)
            rows = result.fetchall()
            
            # Group by ticker
            companies_dict = {}
            for ticker, year in rows:
                if ticker not in companies_dict:
                    companies_dict[ticker] = []
                companies_dict[ticker].append(year)
            
            # Format as list with company names
            companies_list = []
            for ticker in sorted(companies_dict.keys()):
                years = sorted(set(companies_dict[ticker]))
                companies_list.append({
                    "ticker": ticker,
                    "name": COMPANY_NAMES.get(ticker, ticker),
                    "years": years
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
                WHERE c.ticker = :ticker 
                  AND EXTRACT(YEAR FROM f.fiscal_year_end) = :year
                  AND fm.dimension_id IS NULL
                  AND fm.value_numeric IS NOT NULL
                ORDER BY 
                    CASE co.statement_type
                        WHEN 'income_statement' THEN 1
                        WHEN 'balance_sheet' THEN 2
                        WHEN 'cash_flow' THEN 3
                        ELSE 4
                    END,
                    co.hierarchy_level DESC,
                    co.normalized_label
            """)
            
            metrics_result = conn.execute(metrics_query, {"ticker": ticker, "year": year})
            
            metrics = {}
            for row in metrics_result:
                metrics[row[0]] = {
                    "value": float(row[1]) if row[1] else None,
                    "unit": row[2],
                    "period_end": row[3].isoformat() if row[3] else None,
                    "period_type": row[4],
                    "statement_type": row[5],
                    "hierarchy_level": int(row[6]) if row[6] else None
                }
            
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
        
        with engine.connect() as conn:
            # Check if view exists
            try:
                test_query = text("SELECT 1 FROM v_facts_hierarchical LIMIT 1")
                conn.execute(test_query)
                use_view = True
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
        
        with engine.connect() as conn:
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
                # Check if view exists by trying to query it
                try:
                    test_query = text("SELECT 1 FROM v_facts_hierarchical LIMIT 1")
                    conn.execute(test_query)
                    use_view = True
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
            if not show_all_concepts:
                if use_view:
                    query_str += " AND f.hierarchy_level >= :min_hierarchy_level"
                else:
                    query_str += " AND co.hierarchy_level >= :min_hierarchy_level"
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

@app.route('/api/statements/<ticker>/<int:year>', methods=['GET'])
def get_financial_statements(ticker, year):
    """
    Get full financial statements (Income Statement, Balance Sheet, Cash Flow)
    Organized by statement type and hierarchy level
    """
    ticker = ticker.upper()
    
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(DATABASE_URL)
        
        with engine.connect() as conn:
            # Get all metrics organized by statement type
            query = text("""
                SELECT 
                    co.statement_type,
                    co.normalized_label,
                    co.concept_name,
                    fm.value_numeric,
                    fm.unit_measure,
                    COALESCE(p.end_date, p.instant_date) as period_date,
                    p.period_type,
                    co.hierarchy_level,
                    co.parent_concept_id,
                    CASE 
                        WHEN co.parent_concept_id IS NULL THEN NULL
                        ELSE (
                            SELECT normalized_label 
                            FROM dim_concepts 
                            WHERE concept_id = co.parent_concept_id
                        )
                    END as parent_normalized_label
                FROM fact_financial_metrics fm
                JOIN dim_companies c ON fm.company_id = c.company_id
                JOIN dim_concepts co ON fm.concept_id = co.concept_id
                JOIN dim_time_periods p ON fm.period_id = p.period_id
                JOIN dim_filings f ON fm.filing_id = f.filing_id
                WHERE c.ticker = :ticker 
                  AND EXTRACT(YEAR FROM f.fiscal_year_end) = :year
                  AND fm.dimension_id IS NULL
                  AND fm.value_numeric IS NOT NULL
                  AND co.statement_type IN ('income_statement', 'balance_sheet', 'cash_flow')
                ORDER BY 
                    CASE co.statement_type
                        WHEN 'income_statement' THEN 1
                        WHEN 'balance_sheet' THEN 2
                        WHEN 'cash_flow' THEN 3
                    END,
                    co.hierarchy_level DESC,
                    co.normalized_label
            """)
            
            result = conn.execute(query, {"ticker": ticker, "year": year})
            rows = result.fetchall()
            
            # Organize by statement type
            statements = {
                "income_statement": [],
                "balance_sheet": [],
                "cash_flow": []
            }
            
            for row in rows:
                stmt_type = row[0] or 'other'
                if stmt_type in statements:
                    statements[stmt_type].append({
                        "normalized_label": row[1],
                        "concept_name": row[2],
                        "value": float(row[3]) if row[3] else None,
                        "unit": row[4],
                        "period_date": row[5].isoformat() if row[5] else None,
                        "period_type": row[6],
                        "hierarchy_level": int(row[7]) if row[7] else None,
                        "parent_normalized_label": row[10]
                    })
            
            return jsonify({
                "company": ticker,
                "year": year,
                "statements": statements,
                "count": sum(len(v) for v in statements.values())
            })
            
    except Exception as e:
        return jsonify({
            "error": "database_error",
            "message": str(e)
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

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('ENVIRONMENT') != 'production')

