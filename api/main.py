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

# Pre-loaded companies (from your processed data)
PRELOADED_COMPANIES = [
    {"ticker": "NVO", "name": "Novo Nordisk", "years": [2024]},
    {"ticker": "NVDA", "name": "NVIDIA", "years": [2023, 2024, 2025]},
    {"ticker": "AAPL", "name": "Apple", "years": [2023]},
    {"ticker": "GOOGL", "name": "Alphabet", "years": [2024]},
    {"ticker": "MSFT", "name": "Microsoft", "years": [2024]},
    {"ticker": "JNJ", "name": "Johnson & Johnson", "years": [2024]},
    {"ticker": "PFE", "name": "Pfizer", "years": [2023]},
    {"ticker": "LLY", "name": "Eli Lilly", "years": [2023]},
    {"ticker": "MRNA", "name": "Moderna", "years": [2023]},
    {"ticker": "SNY", "name": "Sanofi", "years": [2023]},
    {"ticker": "KO", "name": "Coca-Cola", "years": [2024]},
]

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
    
    return jsonify({
        "preloaded": PRELOADED_COMPANIES,
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
                FROM financial_facts
                WHERE company = :ticker AND EXTRACT(YEAR FROM fiscal_year_end) = :year
            """)
            result = conn.execute(query, {"ticker": ticker, "year": year})
            count = result.fetchone()[0]
            
            if count == 0:
                return jsonify({
                    "error": "not_found",
                    "message": f"No data for {ticker} {year}. Try custom analysis or select a pre-loaded company."
                }), 404
            
            # Fetch key metrics
            metrics_query = text("""
                SELECT normalized_label, value, unit, period_end
                FROM financial_facts
                WHERE company = :ticker 
                  AND EXTRACT(YEAR FROM fiscal_year_end) = :year
                  AND normalized_label IN (
                    'revenue', 'operating_income', 'net_income', 
                    'total_assets', 'total_liabilities', 'total_equity',
                    'operating_cashflow', 'eps_basic', 'eps_diluted'
                  )
                ORDER BY normalized_label
            """)
            
            metrics_result = conn.execute(metrics_query, {"ticker": ticker, "year": year})
            
            metrics = {}
            for row in metrics_result:
                metrics[row[0]] = {
                    "value": float(row[1]) if row[1] else None,
                    "unit": row[2],
                    "period_end": row[3].isoformat() if row[3] else None
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

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('ENVIRONMENT') != 'production')

