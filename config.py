"""
Configuration for FinSight Financial Data Pipeline
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Project paths
PROJECT_ROOT = Path(__file__).parent
DATA_RAW = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"
DATA_REPORTS = PROJECT_ROOT / "data" / "reports"
SRC_DIR = PROJECT_ROOT / "src"
CONFIG_DIR = PROJECT_ROOT / "config"

# Database configuration - PostgreSQL
#
# Supports three environments:
# 1. Railway (production): Uses RAILWAY_POSTGRES_* env vars
# 2. Local Docker (dev): Uses localhost with superset credentials
# 3. Superset (analytics): Uses superset_db internal hostname
#

# Check if DATABASE_URL is already set (Railway, Heroku, etc.)
if os.getenv('DATABASE_URL'):
    DATABASE_URL = os.getenv('DATABASE_URL')
    DATABASE_URI = DATABASE_URL
else:
    # Local or Docker - build from components
    POSTGRES_USER = os.getenv('POSTGRES_USER', 'superset')
    POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'superset')
    POSTGRES_HOST = os.getenv('POSTGRES_HOST', '127.0.0.1')
    POSTGRES_PORT = os.getenv('POSTGRES_PORT', '5432')
    POSTGRES_DB = os.getenv('POSTGRES_DB', 'finsight_dev')
    
    # Build connection string
    if POSTGRES_PASSWORD:
        DATABASE_URI = f'postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}'
    else:
        DATABASE_URI = f'postgresql://{POSTGRES_USER}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}'
    
    DATABASE_URL = DATABASE_URI

# API Keys (optional)
SEC_API_KEY = os.getenv('SEC_API_KEY', '')

# Rate limiting
RATE_LIMIT_DELAY = 1.0  # seconds between API calls
MAX_RETRIES = 3

# Ensure directories exist
DATA_RAW.mkdir(parents=True, exist_ok=True)
DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
DATA_REPORTS.mkdir(parents=True, exist_ok=True)

