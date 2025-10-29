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

# Database configuration - PostgreSQL (Docker)
#
# IMPORTANT: Superset runs in Docker, so we use Docker's PostgreSQL (superset_db container)
# 
# For loading data FROM YOUR MAC (scripts):
#   - Use host: localhost (connects from Mac to Docker port mapping)
#   - Use credentials: superset/superset
# 
# For Superset TO CONNECT (within Docker):
#   - Use host: superset_db (Docker internal network)
#   - Use credentials: superset/superset
#
POSTGRES_USER = os.getenv('POSTGRES_USER', 'superset')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'superset')
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')  # localhost for Mac, superset_db for Superset
POSTGRES_PORT = os.getenv('POSTGRES_PORT', '5432')
POSTGRES_DB = os.getenv('POSTGRES_DB', 'finsight')

DATABASE_URI = f'postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}'

# Note: This URI is for loading data from your Mac. 
# In Superset, use: postgresql://superset:superset@superset_db:5432/finsight

# API Keys (optional)
SEC_API_KEY = os.getenv('SEC_API_KEY', '')

# Rate limiting
RATE_LIMIT_DELAY = 1.0  # seconds between API calls
MAX_RETRIES = 3

# Ensure directories exist
DATA_RAW.mkdir(parents=True, exist_ok=True)
DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
DATA_REPORTS.mkdir(parents=True, exist_ok=True)

