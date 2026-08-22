#!/usr/bin/env python3
"""
Dependency Graph and Population Order

Defines the correct order for populating statement tables to avoid circular dependencies.

Dependency Graph:
1. fact_financial_metrics (raw facts) - NO dependencies
2. fact_balance_sheet - depends on fact_financial_metrics only
3. fact_income_statement - depends on fact_financial_metrics only
4. fact_comprehensive_income - depends on fact_financial_metrics only
5. fact_cash_flow - depends on fact_balance_sheet + fact_income_statement
6. fact_equity_statement - depends on fact_balance_sheet + fact_income_statement
   (comprehensive_income is LEFT JOINed optionally, not a hard dependency - see below)
"""

import sys
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import DATABASE_URI


# Define population order with dependencies
POPULATION_ORDER = [
    {
        'table': 'fact_financial_metrics',
        'dependencies': [],
        'populate_func': None,  # Handled by load_financial_data.py
        'description': 'Raw facts from XBRL extraction'
    },
    {
        'table': 'fact_balance_sheet',
        'dependencies': ['fact_financial_metrics'],
        'populate_func': 'balance_sheet',
        'description': 'Balance sheet facts (depends on raw facts only)'
    },
    {
        'table': 'fact_income_statement',
        'dependencies': ['fact_financial_metrics'],
        'populate_func': 'income_statement',
        'description': 'Income statement facts (depends on raw facts only)'
    },
    {
        'table': 'fact_comprehensive_income',
        'dependencies': ['fact_financial_metrics'],
        'populate_func': 'comprehensive_income',
        'description': 'Comprehensive income facts (depends on raw facts only)'
    },
    {
        'table': 'fact_cash_flow',
        'dependencies': ['fact_balance_sheet', 'fact_income_statement'],
        'populate_func': 'cash_flow',
        'description': 'Cash flow facts (depends on balance sheet and income statement)'
    },
    {
        'table': 'fact_equity_statement',
        'dependencies': ['fact_balance_sheet', 'fact_income_statement'],
        'populate_func': 'equity_statement',
        # NOT dependent on fact_comprehensive_income: populate_equity_statement()'s SQL
        # already LEFT JOINs against it for OCI-related rows, so it degrades gracefully
        # when comprehensive_income is empty (e.g. filers like Apple who report it
        # combined with the income statement — see docs/NVO_GOLDEN_PATH_2026-08.md item 5).
        # Treating it as a hard dependency was silently dropping all equity data whenever
        # comprehensive_income didn't populate, not just the OCI-specific rows.
        'description': 'Equity statement facts (depends on balance sheet and income statement; comprehensive income is joined optionally)'
    }
]


def get_population_order() -> List[Dict]:
    """Get the population order configuration"""
    return POPULATION_ORDER.copy()


def validate_dependencies() -> bool:
    """
    Validate that the dependency graph has no cycles.
    
    Returns:
        True if valid (no cycles), False otherwise
    """
    # Build dependency graph
    graph = {}
    for step in POPULATION_ORDER:
        graph[step['table']] = set(step['dependencies'])
    
    # Check for cycles using DFS
    visited = set()
    rec_stack = set()
    
    def has_cycle(node: str) -> bool:
        visited.add(node)
        rec_stack.add(node)
        
        for dep in graph.get(node, []):
            if dep not in visited:
                if has_cycle(dep):
                    return True
            elif dep in rec_stack:
                return True
        
        rec_stack.remove(node)
        return False
    
    for node in graph:
        if node not in visited:
            if has_cycle(node):
                return False
    
    return True


def get_population_order_for_table(table: str) -> Optional[Dict]:
    """Get population order configuration for a specific table"""
    for step in POPULATION_ORDER:
        if step['table'] == table:
            return step
    return None


def check_dependencies_met(
    table: str, 
    populated_tables: Set[str],
    engine=None
) -> Tuple[bool, List[str]]:
    """
    Check if all dependencies for a table are met.
    
    Args:
        table: Table name to check
        populated_tables: Set of tables that have been populated
        engine: Optional database engine (for checking fact_financial_metrics)
    
    Returns:
        Tuple of (all_dependencies_met, missing_dependencies)
    """
    step = get_population_order_for_table(table)
    if not step:
        return False, [f"Unknown table: {table}"]
    
    missing = []
    for dep in step['dependencies']:
        if dep == 'fact_financial_metrics':
            # Special case: check if fact_financial_metrics has data
            if engine:
                with engine.connect() as conn:
                    result = conn.execute(text("""
                        SELECT COUNT(*) FROM fact_financial_metrics LIMIT 1
                    """))
                    if result.fetchone()[0] == 0:
                        missing.append(dep)
            elif dep not in populated_tables:
                missing.append(dep)
        elif dep not in populated_tables:
            missing.append(dep)
    
    return len(missing) == 0, missing


def populate_all_statements(
    filing_id: Optional[int] = None,
    engine=None,
    show_warnings: bool = True
) -> Dict[str, any]:
    """
    Populate all statement tables in correct dependency order.
    
    Args:
        filing_id: Optional filing ID to populate (if None, populates all)
        engine: Optional database engine
        show_warnings: Whether to show warnings
    
    Returns:
        Dictionary with results:
        {
            'successful': [list of table names],
            'failed': {table_name: error_message},
            'skipped': [list of table names with unmet dependencies]
        }
    """
    from src.utils.populate_statement_facts import (
        populate_income_statement,
        populate_comprehensive_income,
        populate_balance_sheet,
        populate_cash_flow,
        populate_equity_statement
    )
    
    if engine is None:
        from sqlalchemy import create_engine
        engine = create_engine(DATABASE_URI)
    
    # Validate dependency graph
    if not validate_dependencies():
        raise ValueError("Dependency graph has cycles!")
    
    # Map statement types to their populate functions
    populate_functions = {
        'income_statement': populate_income_statement,
        'comprehensive_income': populate_comprehensive_income,
        'balance_sheet': populate_balance_sheet,
        'cash_flow': populate_cash_flow,
        'equity_statement': populate_equity_statement
    }
    
    populated = set()
    results = {
        'successful': [],
        'failed': {},
        'skipped': []
    }
    
    # Note: fact_financial_metrics is populated by load_financial_data.py, not here
    # So we start from the statement tables
    
    with engine.begin() as conn:
        # Determine which filings to process
        if filing_id:
            filings_to_process = [filing_id]
        else:
            from sqlalchemy import text
            filings_query = text("SELECT DISTINCT filing_id FROM rel_statement_items")
            result = conn.execute(filings_query)
            filings_to_process = [row[0] for row in result.fetchall()]
        
        for current_filing_id in filings_to_process:
            if show_warnings:
                print(f"   Populating statement facts for filing_id: {current_filing_id}")
            
            # Track populated tables for dependency checking
            populated_tables = set()
            populated_tables.add('fact_financial_metrics')  # Always populated by loader
            
            # Process each statement type in dependency order
            for step in POPULATION_ORDER:
                table = step['table']
                statement_type = step.get('populate_func')
                
                # Skip fact_financial_metrics (handled by loader)
                if table == 'fact_financial_metrics':
                    populated_tables.add(table)
                    continue
                
                # Skip if no populate function defined
                if not statement_type:
                    continue
                
                # Check dependencies are met
                deps_met, missing = check_dependencies_met(table, populated_tables, engine)
                if not deps_met:
                    if show_warnings:
                        print(f"   ⚠️  Skipping {table}: missing dependencies {missing}")
                    results['skipped'].append(table)
                    continue
                
                # Populate this table
                try:
                    # Get the populate function for this statement type
                    populate_func = populate_functions.get(statement_type)
                    if not populate_func:
                        if show_warnings:
                            print(f"   ⚠️  No populate function found for {statement_type}")
                        continue
                    
                    if show_warnings:
                        print(f"   🔧 Populating {table}...")
                    
                    # Call the populate function
                    rows_inserted = populate_func(conn, current_filing_id, show_warnings)
                    
                    if rows_inserted > 0:
                        populated_tables.add(table)
                        results['successful'].append(table)
                        if show_warnings:
                            print(f"      ✅ Populated {rows_inserted} facts for {statement_type}")
                    else:
                        if show_warnings:
                            print(f"   ⚠️  No facts found for {statement_type}")
                        results['skipped'].append(table)
                        
                except Exception as e:
                    if show_warnings:
                        print(f"   ❌ Failed to populate {table}: {e}")
                    results['failed'][table] = str(e)
                    # Re-raise to rollback transaction
                    raise
    
    return results


def get_dependency_tree() -> Dict[str, List[str]]:
    """
    Get dependency tree for visualization.
    
    Returns:
        Dictionary mapping table to list of dependencies
    """
    return {
        step['table']: step['dependencies']
        for step in POPULATION_ORDER
    }

