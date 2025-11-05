"""
Centralized Database Connection Management with Connection Pooling

This module provides a shared database engine with connection pooling
to avoid creating new connections for every query.

Usage:
    from src.db import ENGINE
    
    with ENGINE.connect() as conn:
        result = conn.execute(text("SELECT ..."), {"param": value})
        df = pd.read_sql(text(query), conn, params=params)
"""

from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
from config import DATABASE_URI
import logging

logger = logging.getLogger(__name__)

# Global engine with connection pooling
# This should be imported and reused across the entire application
ENGINE = create_engine(
    DATABASE_URI,
    poolclass=QueuePool,
    pool_size=5,          # Maximum 5 connections in pool
    max_overflow=10,      # Allow 10 additional connections if needed
    pool_pre_ping=True,   # Validate connections before use (handles stale connections)
    pool_recycle=3600,    # Recycle connections after 1 hour (prevents stale connections)
    echo=False,           # Set to True for SQL query logging (debug only)
    connect_args={
        "connect_timeout": 10,  # 10 second connection timeout
        "application_name": "finsight"  # Identifies app in PostgreSQL logs
    }
)


def get_engine():
    """
    Get the shared database engine.
    
    Returns:
        sqlalchemy.engine.Engine: Shared engine instance with connection pooling
    """
    return ENGINE


def test_connection():
    """
    Test database connection.
    
    Returns:
        bool: True if connection successful, False otherwise
    """
    try:
        with ENGINE.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
        logger.info("✅ Database connection test successful")
        return True
    except Exception as e:
        logger.error(f"❌ Database connection test failed: {e}")
        return False


# For backwards compatibility - direct import of ENGINE is preferred
__all__ = ['ENGINE', 'get_engine', 'test_connection']

