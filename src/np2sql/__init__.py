"""
Natural Language to SQL (NP2SQL) module for FinSight.

This module provides functionality to convert natural language queries
into SQL queries against the FinSight financial data warehouse.
"""

from .schema_metadata import get_schema_metadata
from .np2sql_service import (
    generate_sql,
    validate_sql,
    detect_companies_in_query,
    execute_query,
    detect_result_type,
)

__all__ = [
    'get_schema_metadata',
    'generate_sql',
    'validate_sql',
    'detect_companies_in_query',
    'execute_query',
    'detect_result_type',
]

