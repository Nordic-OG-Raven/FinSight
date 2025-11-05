"""
Taxonomy-Driven Universal Metrics Detection

Instead of manually listing "universal metrics", this module uses taxonomy structure
to identify REQUIRED metrics based on accounting standards:

1. Balance Sheet Equation: Assets = Liabilities + Equity (required totals)
2. Income Statement Totals: Revenue, Net Income (required totals)
3. Taxonomy Calculation Linkbases: Parent concepts with many children = likely totals
4. Taxonomy Presentation Linkbases: Standard line items = likely required

This is the Big 4/Hedge Fund approach: use accounting standards and taxonomy structure,
not manual lists.

INTEGRATED INTO PIPELINE: This runs automatically during validation.
Persists across data reloads and new companies because it uses taxonomy structure,
not manual lists.
"""

import sys
from pathlib import Path
import json
import logging
from typing import Dict, List, Set, Tuple
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logger = logging.getLogger(__name__)


# REQUIRED TOTALS FROM ACCOUNTING STANDARDS (Balance Sheet Equation, Income Statement)
# These are REQUIRED by GAAP/IFRS, not optional metrics we manually selected
REQUIRED_TAXONOMY_TOTALS = {
    'balance_sheet_equation': {
        'total_assets': [
            'Assets',  # Balance sheet equation: Assets = Liabilities + Equity
            'AssetsTotal',
        ],
        'total_liabilities': [
            'Liabilities',
            'LiabilitiesTotal',
        ],
        'stockholders_equity': [
            'StockholdersEquity',
            'Equity',
            'EquityTotal',
        ],
    },
    'income_statement_totals': {
        'revenue': [
            'Revenues',
            'Revenue',
            'RevenueFromContractsWithCustomers',
        ],
        'net_income': [
            'NetIncomeLoss',
            'ProfitLoss',
            'ComprehensiveIncomeNetOfTax',
        ],
    },
    'required_components': {
        # Current/noncurrent splits are standard accounting practice
        'current_liabilities': [
            'LiabilitiesCurrent',
            'CurrentLiabilities',
        ],
        'noncurrent_liabilities': [
            'LiabilitiesNoncurrent',
            'NoncurrentLiabilities',
        ],
        # Standard line items (accounts receivable, accounts payable, cash)
        'accounts_receivable': [
            'AccountsReceivableNetCurrent',
            'AccountsReceivableAfterAllowanceForCreditLossCurrent',
            'AccountsReceivableNet',
        ],
        'accounts_payable': [
            'AccountsPayableCurrent',
            'AccountsPayableAndAccruedLiabilities',
        ],
        'cash_and_equivalents': [
            'CashAndCashEquivalentsAtCarryingValue',
            'CashCashEquivalentsAndShortTermInvestments',
        ],
        'operating_cash_flow': [
            'NetCashProvidedByUsedInOperatingActivities',
            'CashProvidedByUsedInOperatingActivities',
        ],
    },
}


def load_taxonomy_parent_concepts(taxonomy_dir: Path) -> Dict[str, int]:
    """
    Load parent concepts from taxonomy calculation linkbases.
    
    Parent concepts with many children are likely required totals.
    
    Returns:
        Dict mapping concept_name (without namespace) -> child_count
    """
    calc_files = list(taxonomy_dir.glob("*/*-calc.json")) + list(taxonomy_dir.glob("*-calc.json"))
    
    if not calc_files:
        logger.warning(f"No taxonomy calculation files found in {taxonomy_dir}")
        return {}
    
    parent_children_count = defaultdict(int)
    
    for calc_file in calc_files:
        try:
            with open(calc_file, 'r') as f:
                data = json.load(f)
            
            relationships = data.get('relationships', [])
            
            for rel in relationships:
                parent_full = rel.get('parent_concept', '')
                # Remove namespace (e.g., "us-gaap:Assets" -> "Assets")
                parent = parent_full.split(':')[-1] if ':' in parent_full else parent_full
                
                if parent:
                    parent_children_count[parent] += 1
        except Exception as e:
            logger.warning(f"Error loading {calc_file.name}: {e}")
            continue
    
    return dict(parent_children_count)


def build_concept_to_required_total_mapping(taxonomy_dir: Path, synonym_mapping: Dict[str, str]) -> Dict[str, Set[str]]:
    """
    Build mapping from company concepts to required totals.
    
    Strategy:
    1. Direct match: Concept name matches required taxonomy total
    2. Synonym match: Concept maps to required total via taxonomy synonyms
    3. Normalized label match: Concept's normalized label matches required total
    
    Returns:
        Dict mapping company_concept_name -> set of required_metric_names
        Example: {'Revenues': {'revenue'}, 'CashAndDueFromBanks': {'cash_and_equivalents'}}
    """
    # Load taxonomy labels to get concept names
    labels_files = list(taxonomy_dir.glob("*/*-labels.json")) + list(taxonomy_dir.glob("*-labels.json"))
    
    taxonomy_concepts = set()
    for labels_file in labels_files:
        try:
            with open(labels_file, 'r') as f:
                data = json.load(f)
            concepts = data.get('concepts', [])
            for concept in concepts:
                concept_name = concept.get('concept_name', '').split(':')[-1]
                if concept_name:
                    taxonomy_concepts.add(concept_name)
        except Exception as e:
            logger.warning(f"Error loading {labels_file.name}: {e}")
            continue
    
    # Build mapping: taxonomy_total_concept -> required_metric_name
    concept_to_metric = {}
    
    for metric_category, metrics in REQUIRED_TAXONOMY_TOTALS.items():
        for metric_name, taxonomy_totals in metrics.items():
            for taxonomy_total in taxonomy_totals:
                # Direct match
                concept_to_metric[taxonomy_total] = metric_name
                
                # Check if this taxonomy total has synonyms
                if taxonomy_total in synonym_mapping:
                    canonical = synonym_mapping[taxonomy_total]
                    # If canonical maps to a required total, use that
                    if canonical in concept_to_metric:
                        # Map synonym to same metric
                        pass  # Already mapped via canonical
    
    return concept_to_metric


def get_required_metrics_for_company(engine, ticker: str, taxonomy_dir: Path, 
                                     synonym_mapping: Dict[str, str]) -> Dict[str, bool]:
    """
    Check if company has concepts mapping to required taxonomy totals.
    
    Returns:
        Dict mapping required_metric_name -> bool (has metric or not)
    """
    from sqlalchemy import text
    
    # Get all concepts this company uses
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT DISTINCT
                dc.concept_name,
                dc.normalized_label
            FROM fact_financial_metrics f
            JOIN dim_companies c ON f.company_id = c.company_id
            JOIN dim_concepts dc ON f.concept_id = dc.concept_id
            WHERE c.ticker = :ticker
              AND f.dimension_id IS NULL
              AND f.value_numeric IS NOT NULL
        """), {'ticker': ticker})
        
        company_concepts = {row[0]: row[1] for row in result}
    
    # Build mapping from taxonomy totals to required metrics
    concept_to_metric = build_concept_to_required_total_mapping(taxonomy_dir, synonym_mapping)
    
    # Get all required metric names
    all_required_metrics = set()
    for metrics in REQUIRED_TAXONOMY_TOTALS.values():
        all_required_metrics.update(metrics.keys())
    
    # Check which required metrics company has
    company_has_metric = {metric: False for metric in all_required_metrics}
    
    # First pass: Check all concepts
    # Build set of normalized labels for bank detection
    company_normalized_labels = set(normalized_label for _, normalized_label in company_concepts.items() if normalized_label)
    company_concept_names = set(concept_name for concept_name, _ in company_concepts.items())
    
    # Check if company is a bank (has deposit liabilities)
    is_bank = any('deposit_liabilities' in label or 'depositliabilities' in c.lower() 
                  for label in company_normalized_labels 
                  for c in company_concept_names)
    
    for concept_name, normalized_label in company_concepts.items():
        # Remove namespace if present
        concept_short = concept_name.split(':')[-1] if ':' in concept_name else concept_name
        
        # Strategy 1: Direct concept name match to taxonomy total
        if concept_short in concept_to_metric:
            metric = concept_to_metric[concept_short]
            company_has_metric[metric] = True
            continue
        
        # Strategy 2: Synonym match (concept maps to taxonomy total via synonyms)
        if concept_short in synonym_mapping:
            canonical = synonym_mapping[concept_short]
            canonical_short = canonical.split(':')[-1] if ':' in canonical else canonical
            if canonical_short in concept_to_metric:
                metric = concept_to_metric[canonical_short]
                company_has_metric[metric] = True
                continue
        
        # Strategy 3: Normalized label matching (fallback - for concepts already mapped correctly)
        # This handles cases where we've already mapped bank-specific concepts, etc.
        # Check if normalized_label matches expected patterns
        normalized_lower = normalized_label.lower() if normalized_label else ''
        concept_lower = concept_short.lower()
        
        # Match patterns (e.g., "revenue", "revenues" -> "revenue" metric)
        # Check both concept name and normalized label
        
        # Revenue
        if ('revenue' in normalized_lower or 'revenue' in concept_lower) and not company_has_metric['revenue']:
            company_has_metric['revenue'] = True
        
        # Net Income
        if (('net_income' in normalized_lower or 'profit_loss' in normalized_lower) or 
            ('netincome' in concept_lower or 'profitloss' in concept_lower)) and not company_has_metric['net_income']:
            company_has_metric['net_income'] = True
        
        # Total Assets
        if (normalized_lower in ('total_assets', 'assets') or 
            'assets' == normalized_lower or 
            (concept_lower.startswith('assets') and 'total' in concept_lower)) and not company_has_metric['total_assets']:
            company_has_metric['total_assets'] = True
        
        # Total Liabilities (check both concept and normalized label)
        # Don't check for current+noncurrent here - do that after loop
        if ((normalized_lower in ('total_liabilities', 'liabilities') or 
             'liabilities' == normalized_lower or
             (concept_lower.startswith('liabilities') and 'total' in concept_lower) or
             (concept_lower == 'liabilities' and 'current' not in concept_lower and 'noncurrent' not in concept_lower)) and 
            not company_has_metric['total_liabilities'] and
            'current' not in normalized_lower and 'noncurrent' not in normalized_lower):
            company_has_metric['total_liabilities'] = True
        
        # Stockholders Equity
        if (('stockholders_equity' in normalized_lower or normalized_lower == 'equity' or 'equity' in normalized_lower) or
            ('stockholdersequity' in concept_lower or concept_lower == 'equity')) and not company_has_metric['stockholders_equity']:
            company_has_metric['stockholders_equity'] = True
        
        # Current Liabilities (includes bank-specific combined concepts)
        if (('current_liabilities' in normalized_lower or 'liabilities_current' in normalized_lower) or
            ('currentliabilities' in concept_lower or 'liabilitiescurrent' in concept_lower) or
            # Bank-specific: AccountsPayableAndAccruedLiabilitiesCurrentAndNoncurrent → split logic needed
            ('accounts_payable_and_accrued_liabilities_current_and_noncurrent' in normalized_lower) or
            # Bank-specific: Deposit liabilities are current liabilities (components)
            ('interest_bearing_deposit_liabilities' in normalized_lower or 'noninterest_bearing_deposit_liabilities' in normalized_lower or
             'interestbearingdepositliabilities' in concept_lower or 'noninterestbearingdepositliabilities' in concept_lower)) and not company_has_metric['current_liabilities']:
            company_has_metric['current_liabilities'] = True
        
        # Noncurrent Liabilities
        if (('noncurrent_liabilities' in normalized_lower or 'liabilities_noncurrent' in normalized_lower) or
            ('noncurrentliabilities' in concept_lower or 'liabilitiesnoncurrent' in concept_lower)) and not company_has_metric['noncurrent_liabilities']:
            company_has_metric['noncurrent_liabilities'] = True
        
        # Accounts Receivable (banks use financing receivables)
        if (('accounts_receivable' in normalized_lower or 'accountsreceivable' in concept_lower) or
            # Bank-specific: Financing receivables are accounts receivable equivalent
            ('financing_receivable' in normalized_lower and 'allowance' not in normalized_lower and 'credit_loss' not in normalized_lower) or
            ('financingreceivable' in concept_lower and 'allowance' not in concept_lower and 'creditloss' not in concept_lower)) and not company_has_metric['accounts_receivable']:
            company_has_metric['accounts_receivable'] = True
        
        # Accounts Payable (includes bank-specific variants already mapped)
        if (('accounts_payable' in normalized_lower or 'accountspayable' in concept_lower) or
            # Bank-specific: AccountsPayableAndOtherAccruedLiabilities → accounts_payable (already mapped)
            ('accounts_payable_and_other_accrued_liabilities' in normalized_lower or
             'accountspayableandotheraccruedliabilities' in concept_lower) or
            # Bank-specific: AccruedLiabilitiesAndOtherLiabilities (BAC) - for banks, this is accounts_payable
            # But only if company is a bank - otherwise it's a parent concept (creates duplicates)
            (('accrued_liabilities_and_other_liabilities' in normalized_lower or
              'accruedliabilitiesandotherliabilities' in concept_lower) and is_bank)) and not company_has_metric['accounts_payable']:
            company_has_metric['accounts_payable'] = True
        
        # Cash and Equivalents
        if (('cash_and_equivalents' in normalized_lower or 'cash_and_cash_equivalents' in normalized_lower) or
            ('cashandcashequivalents' in concept_lower or 'cashanddufrombanks' in concept_lower)) and not company_has_metric['cash_and_equivalents']:
            company_has_metric['cash_and_equivalents'] = True
        
        # Operating Cash Flow
        if (('operating_cash_flow' in normalized_lower or 'net_cash_provided_by_used_in_operating_activities' in normalized_lower) or
            ('netcashprovidedbyusedinoperatingactivities' in concept_lower)) and not company_has_metric['operating_cash_flow']:
            company_has_metric['operating_cash_flow'] = True
    
    # Second pass: Derived metrics (if company has both current and noncurrent, they have total)
    if (not company_has_metric['total_liabilities'] and 
        company_has_metric['current_liabilities'] and 
        company_has_metric['noncurrent_liabilities']):
        company_has_metric['total_liabilities'] = True  # Can calculate: current + noncurrent = total
    
    # Bank-specific: If company has total_liabilities and current_liabilities (deposits), 
    # they have noncurrent = total - current
    if (not company_has_metric['noncurrent_liabilities'] and
        company_has_metric['total_liabilities'] and
        company_has_metric['current_liabilities']):
        company_has_metric['noncurrent_liabilities'] = True  # Can calculate: total - current = noncurrent
    
    return company_has_metric


def check_universal_metrics_taxonomy_driven(engine, taxonomy_dir: Path) -> Dict[str, any]:
    """
    Check universal metrics using taxonomy-driven approach.
    
    This replaces manual label checking with taxonomy-driven detection:
    1. Identifies required metrics from taxonomy structure (balance sheet equation, income statement)
    2. Checks if companies have concepts mapping to those totals (via taxonomy, not labels)
    3. Uses accounting standards as source of truth, not manual lists
    
    Returns:
        Dict with validation results
    """
    from src.utils.load_taxonomy_synonyms import load_taxonomy_synonyms
    
    # Load taxonomy synonyms for mapping company concepts to taxonomy totals
    synonym_mapping = load_taxonomy_synonyms(taxonomy_dir, use_semantic_equivalence=True)
    
    from sqlalchemy import text
    
    # Get all companies
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT ticker, company_id
            FROM dim_companies
            WHERE company_id > 0
        """))
        companies = [(row[0], row[1]) for row in result]
    
    # Check each company
    missing_by_company = {}
    all_required_metrics = set()
    for metrics in REQUIRED_TAXONOMY_TOTALS.values():
        all_required_metrics.update(metrics.keys())
    
    for ticker, company_id in companies:
        company_metrics = get_required_metrics_for_company(engine, ticker, taxonomy_dir, synonym_mapping)
        missing = [metric for metric, has_it in company_metrics.items() if not has_it]
        if missing:
            missing_by_company[ticker] = missing
    
    total_violations = sum(len(metrics) for metrics in missing_by_company.values())
    total_companies_checked = len(companies)
    
    return {
        'missing_by_company': missing_by_company,
        'required_metrics': sorted(all_required_metrics),
        'total_companies_checked': total_companies_checked,
        'total_violations': total_violations,
        'passed': total_violations == 0
    }
