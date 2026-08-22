"""
Completeness Tracking

Tracks data coverage by statement type and calculates completeness scores.
"""
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from collections import Counter

from src.utils.normalize import identify_statement_type
from src.utils.logging_utils import truncate_log_message
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CompletenessReport:
    """Report on data completeness and coverage"""
    company: str
    filing_type: str
    fiscal_year_end: str
    
    # Fact counts
    total_facts: int = 0
    facts_by_statement: Dict[str, int] = field(default_factory=dict)
    facts_by_taxonomy: Dict[str, int] = field(default_factory=dict)
    
    # Coverage metrics
    unique_concepts: int = 0
    facts_with_numeric_values: int = 0
    facts_with_periods: int = 0
    facts_with_units: int = 0
    facts_with_dimensions: int = 0
    
    # Completeness scores (0-1)
    overall_completeness: float = 0.0
    income_statement_completeness: float = 0.0
    balance_sheet_completeness: float = 0.0
    cash_flow_completeness: float = 0.0
    
    # Metadata
    calculation_timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'company': self.company,
            'filing_type': self.filing_type,
            'fiscal_year_end': self.fiscal_year_end,
            'total_facts': self.total_facts,
            'unique_concepts': self.unique_concepts,
            'facts_by_statement': self.facts_by_statement,
            'facts_by_taxonomy': self.facts_by_taxonomy,
            'coverage': {
                'numeric_values': self.facts_with_numeric_values,
                'periods': self.facts_with_periods,
                'units': self.facts_with_units,
                'dimensions': self.facts_with_dimensions
            },
            'completeness_scores': {
                'overall': self.overall_completeness,
                'income_statement': self.income_statement_completeness,
                'balance_sheet': self.balance_sheet_completeness,
                'cash_flow': self.cash_flow_completeness
            },
            'calculation_timestamp': self.calculation_timestamp.isoformat()
        }


class CompletenessTracker:
    """Track data completeness and coverage"""
    
    # Expected critical normalized labels (universal metrics) per statement type
    # These are taxonomy-agnostic and work for both IFRS and US-GAAP companies
    # Source: src/utils/taxonomy_mappings.py STATEMENT_TYPES
    EXPECTED_NORMALIZED_LABELS = {
        'income_statement': [
            'revenue', 'cost_of_revenue', 'gross_profit', 'operating_income',
            'income_before_tax', 'income_tax_expense', 'net_income',
            'eps_basic', 'eps_diluted'
        ],
        'balance_sheet': [
            'total_assets', 'current_assets', 'cash_and_equivalents',
            'accounts_receivable', 'inventory', 'property_plant_equipment',
            'total_liabilities', 'current_liabilities', 'accounts_payable',
            'long_term_debt', 'stockholders_equity', 'retained_earnings'
        ],
        'cash_flow': [
            'operating_cash_flow', 'investing_cash_flow', 'financing_cash_flow',
            'capex', 'dividends_paid'
        ]
    }
    
    # Legacy: Keep for backward compatibility, but prefer EXPECTED_NORMALIZED_LABELS
    EXPECTED_CONCEPTS = {
        'income_statement': [
            'Revenue', 'Revenues', 'SalesRevenueNet',
            'GrossProfit', 'OperatingIncomeLoss',
            'NetIncomeLoss', 'ProfitLoss',
            'CostOfGoodsAndServicesSold', 'CostOfRevenue',
            'OperatingExpenses', 'ResearchAndDevelopmentExpense',
            'SellingGeneralAndAdministrativeExpense',
            'IncomeTaxExpenseBenefit'
        ],
        'balance_sheet': [
            'Assets', 'AssetsCurrent', 'AssetsNoncurrent',
            'Cash', 'CashAndCashEquivalentsAtCarryingValue',
            'AccountsReceivable', 'Inventory',
            'PropertyPlantAndEquipmentNet',
            'Liabilities', 'LiabilitiesCurrent', 'LiabilitiesNoncurrent',
            'AccountsPayable', 'DebtCurrent', 'DebtNoncurrent',
            'StockholdersEquity', 'RetainedEarnings',
            'CommonStock', 'AdditionalPaidInCapital'
        ],
        'cash_flow': [
            'NetCashProvidedByUsedInOperatingActivities',
            'NetCashProvidedByUsedInInvestingActivities',
            'NetCashProvidedByUsedInFinancingActivities',
            'DepreciationDepletionAndAmortization',
            'PaymentsToAcquirePropertyPlantAndEquipment',
            'DividendsPaid', 'ProceedsFromIssuanceOfDebt',
            'RepaymentsOfDebt'
        ]
    }
    
    def __init__(self):
        self.stats = {
            'filings_analyzed': 0,
            'total_facts_analyzed': 0
        }
    
    def analyze_completeness(
        self,
        facts: List[Dict[str, Any]],
        company: str,
        filing_type: str,
        fiscal_year_end: str
    ) -> CompletenessReport:
        """
        Analyze completeness of extracted data
        
        Args:
            facts: List of financial facts
            company: Company ticker
            filing_type: Filing type (10-K, 20-F, etc.)
            fiscal_year_end: Fiscal year end date
            
        Returns:
            CompletenessReport with coverage metrics
        """
        report = CompletenessReport(
            company=company,
            filing_type=filing_type,
            fiscal_year_end=fiscal_year_end
        )
        
        # Basic counts
        report.total_facts = len(facts)
        report.unique_concepts = len(set(f.get('concept') for f in facts if f.get('concept')))
        
        # Count facts with specific attributes
        report.facts_with_numeric_values = sum(
            1 for f in facts if f.get('value_numeric') is not None
        )
        report.facts_with_periods = sum(
            1 for f in facts if f.get('period_end') or f.get('instant_date')
        )
        report.facts_with_units = sum(
            1 for f in facts if f.get('unit_measure')
        )
        report.facts_with_dimensions = sum(
            1 for f in facts 
            if f.get('dimensions') and len(f.get('dimensions', {})) > 0
        )
        
        # Classify facts by statement type
        statement_counts = Counter()
        for fact in facts:
            stmt_type = identify_statement_type(fact.get('concept', ''))
            if stmt_type:
                statement_counts[stmt_type] += 1
        
        report.facts_by_statement = dict(statement_counts)
        
        # Count by taxonomy
        taxonomy_counts = Counter(f.get('taxonomy') for f in facts if f.get('taxonomy'))
        report.facts_by_taxonomy = dict(taxonomy_counts)
        
        # Calculate completeness scores (using normalized labels - works for both IFRS and US-GAAP)
        report.overall_completeness = self._calculate_overall_completeness(facts)
        report.income_statement_completeness = self._calculate_statement_completeness(
            facts, 'income_statement'
        )
        report.balance_sheet_completeness = self._calculate_statement_completeness(
            facts, 'balance_sheet'
        )
        report.cash_flow_completeness = self._calculate_statement_completeness(
            facts, 'cash_flow'
        )
        
        # Update stats
        self.stats['filings_analyzed'] += 1
        self.stats['total_facts_analyzed'] += len(facts)
        
        return report
    
    def fill_missing_with_sec_api(
        self,
        facts: List[Dict[str, Any]],
        company: str,
        year: int,
        taxonomy: str = 'ifrs-full',
        cache_dir: Optional[Path] = None
    ) -> List[Dict[str, Any]]:
        """
        Fill missing concepts using SEC Company Facts API
        
        This is a workaround for extraction gaps. It identifies missing concepts
        and fills them from the SEC API, marking them with source='SEC_API'.
        
        RATE LIMIT AWARENESS:
        - Makes ONE API call per company/year (fetches all facts at once)
        - Caches responses to disk to avoid repeated calls
        - Only adds SEC_API data for MISSING concepts (not all concepts)
        
        Args:
            facts: Existing facts list
            company: Company ticker symbol
            year: Fiscal year to fill
            taxonomy: Taxonomy to use (default: 'ifrs-full' for IFRS companies)
            cache_dir: Optional directory to cache SEC API responses
            
        Returns:
            Updated facts list with gap-filled data
        """
        try:
            from scripts.sec_api_validator import fetch_sec_facts, get_cik_from_ticker
        except ImportError:
            logger.warning("SEC API validator not available, skipping gap filling")
            return facts
        
        # Get CIK
        cik = get_cik_from_ticker(company)
        if not cik:
            logger.warning(f"CIK not found for {company}, skipping SEC API gap filling")
            return facts
        
        # Check cache first (avoid API calls if we have cached data)
        sec_facts = None
        cache_file = None
        if cache_dir:
            cache_dir = Path(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = cache_dir / f"sec_api_{company}_{year}_{taxonomy}.json"
            if cache_file.exists():
                try:
                    import json
                    with open(cache_file, 'r') as f:
                        sec_facts = json.load(f)
                    logger.debug(truncate_log_message(f"Using cached SEC API data for {company} {year}"))
                except Exception as e:
                    logger.debug(f"Cache read failed: {e}, fetching from API")
        
        # Fetch from API if not cached
        if sec_facts is None:
            logger.info(truncate_log_message(f"Fetching SEC API data for {company} {year}..."))
            sec_facts = fetch_sec_facts(cik, year, taxonomy)
            
            # Cache the response
            if sec_facts and cache_file:
                try:
                    import json
                    with open(cache_file, 'w') as f:
                        json.dump(sec_facts, f, indent=2)
                    logger.debug(truncate_log_message(f"Cached SEC API response"))
                except Exception as e:
                    logger.debug(f"Cache write failed: {e}")
        
        if not sec_facts:
            logger.warning("Failed to fetch SEC API data, skipping gap filling")
            return facts
        
        # Fill ALL missing concepts from SEC API - check every SEC API fact
        # Build sets of concepts AND normalized labels we already have for THIS SPECIFIC YEAR
        # CRITICAL: Check both concept names AND normalized labels to catch cases where
        # SEC API uses different concept name but same normalized label (e.g., PropertyPlantAndEquipment vs PropertyPlantAndEquipmentIncludingRightofuseAssets)
        # CRITICAL FIX: Only check for THIS year, not all years - we need to fill missing years!
        existing_concepts_for_year = set()
        existing_normalized_for_year = set()
        for fact in facts:
            fact_year = None
            period_end = fact.get('period_end')
            instant_date = fact.get('instant_date')
            if period_end:
                fact_year = period_end[:4] if isinstance(period_end, str) else str(period_end.year)
            elif instant_date:
                fact_year = instant_date[:4] if isinstance(instant_date, str) else str(instant_date.year)
            
            # CRITICAL: Only check facts for THIS specific year
            # Previous bug: Was checking all years, so if PPE existed for 2021, it wouldn't fill for 2024
            if fact_year == str(year):
                concept = fact.get('concept', '')
                normalized = fact.get('normalized_label', '')
                if concept:
                    existing_concepts_for_year.add(concept.lower())
                if normalized:
                    existing_normalized_for_year.add(normalized.lower())
        
        # Fill ALL missing concepts from SEC API
        filled_count = 0
        filled_concepts = []
        from src.utils.taxonomy_mappings import get_normalized_label
        
        for key, facts_list in sec_facts.items():
            for sec_fact in facts_list:
                concept_name = sec_fact.get('concept', '')
                if not concept_name:
                    continue
                
                # Get normalized label for this SEC API concept
                sec_normalized = get_normalized_label(concept_name) if concept_name else None
                
                # RATE LIMIT OPTIMIZATION: Only add SEC_API data for MISSING concepts
                # Don't add if we already have this concept for this year (even if XBRL)
                # The loader's ON CONFLICT logic will prefer SEC_API over XBRL when both exist,
                # but we should only fetch/add SEC_API when there's an actual gap
                if (concept_name.lower() in existing_concepts_for_year or 
                    (sec_normalized and sec_normalized.lower() in existing_normalized_for_year)):
                    continue
                
                # Extract period
                period = sec_fact.get('period', {})
                # SEC API uses 'end' for balance sheet items (instant) and duration periods
                # Check if it's an instant period (balance sheet) by looking at the frame or form
                # For balance sheet items, use instant_date; for income/cash flow, use period_end
                period_end = period.get('end') or period.get('instant', f'{year}-12-31')
                is_instant = 'instant' in period or (period.get('frame', '').endswith('I') and 'end' in period)
                
                # Try to get normalized label
                normalized_label = get_normalized_label(concept_name) if concept_name else None
                
                # Determine if this is a balance sheet item (instant) based on normalized label
                # Balance sheet items: assets, liabilities, equity
                is_balance_sheet = normalized_label and any(bs_term in normalized_label.lower() for bs_term in [
                    'assets', 'liabilities', 'equity', 'property_plant_equipment', 'inventory',
                    'accounts_receivable', 'cash_and_equivalents', 'accounts_payable', 'debt'
                ])
                
                # Create new fact
                new_fact = {
                    'concept': concept_name,
                    'value': sec_fact.get('value'),
                    'value_numeric': sec_fact.get('value'),
                    'period_end': period_end if not is_balance_sheet and 'end' in period else None,
                    'instant_date': period_end if (is_balance_sheet or is_instant) else None,
                    'unit_measure': sec_fact.get('unit', ''),
                    'normalized_label': normalized_label,
                    'source': 'SEC_API',
                    'is_gap_filled': True,
                    'taxonomy': sec_fact.get('taxonomy', taxonomy)
                }
                
                facts.append(new_fact)
                filled_count += 1
                filled_concepts.append(concept_name)
                # Only log at DEBUG level to reduce noise
                logger.debug(f"Filled gap: {concept_name} = {sec_fact.get('value')} {sec_fact.get('unit', '')} ({year})")
        
        if filled_count > 0:
            msg = f"✅ Filled {filled_count} missing concepts from SEC API for year {year}"
            logger.info(truncate_log_message(msg))
            # Log critical concepts that were filled (for debugging)
            critical_filled = [c for c in filled_concepts if any(kw in c.lower() for kw in ['assets', 'liabilities', 'equity', 'revenue', 'income', 'property', 'plant', 'equipment'])]
            if critical_filled:
                logger.debug(truncate_log_message(f"   Critical concepts: {', '.join(critical_filled[:3])}"))
        else:
            logger.debug(truncate_log_message(f"ℹ️  No missing concepts found in SEC API for year {year}"))
        
        return facts

    def fill_missing_instant_facts_from_comparative_filing(
        self,
        facts: List[Dict[str, Any]],
        company: str,
        missing_year: int,
        filing_type: str = '20-F',
        cache_dir: Optional[Path] = None
    ) -> List[Dict[str, Any]]:
        """
        Fill missing balance-sheet (instant-type) facts for a comparative year by pulling
        them from that year's own filing, rather than SEC-API — which is unreliable for
        foreign private issuers filing 20-F (SEC's companyfacts endpoint 404s for NVO's
        CIK; see docs/NVO_GOLDEN_PATH_2026-08.md item 4 for the full investigation).

        Confirmed pattern (2026-08-22, verified against real NVO filings): a filing only
        carries 2 comparative years of top-line balance-sheet aggregates (Assets,
        Liabilities), so a filing 2 years out from `missing_year` won't have it — but the
        filing for `missing_year + 1` will, since `missing_year` is *its* prior-year
        comparative column. Example: NVO's FY2024 20-F has no Assets fact for Dec-2022;
        NVO's FY2023 20-F does (241,257,000,000, matching SEC-API's own reported value).

        Args:
            facts: existing facts list
            company: ticker
            missing_year: fiscal year whose instant facts are missing (e.g. 2022)
            filing_type: filing type to fetch for missing_year + 1 (e.g. '20-F')
            cache_dir: unused currently, accepted for interface symmetry with the
                SEC-API gap-fill method

        Returns:
            Updated facts list with any newly-found instant facts appended, tagged
            source='COMPARATIVE_FILING'
        """
        # A fact's instant_date may be stored as either Dec-31 of the fiscal year or
        # Jan-1 of the following year, depending on how the source context was tagged —
        # both conventions appear in practice. Match either explicitly rather than
        # relying on a single global year-extraction convention.
        target_dates = {f'{missing_year}-12-31', f'{missing_year + 1}-01-01'}

        existing_instant_keys = set()
        for fact in facts:
            instant_date = str(fact.get('instant_date') or '')
            if instant_date in target_dates:
                concept = (fact.get('concept') or '').lower()
                if concept:
                    existing_instant_keys.add(concept)

        try:
            from src.ingestion.fetch_sec import SECFilingDownloader
            from src.parsing.parse_xbrl import ComprehensiveXBRLParser
            from config import DATA_RAW
        except ImportError as e:
            logger.warning(f"Could not import ingestion/parsing modules for comparative-filing fill: {e}")
            return facts

        adjacent_year = missing_year + 1
        try:
            downloader = SECFilingDownloader(output_dir=DATA_RAW)
            filing_path = downloader.download_filing(company, adjacent_year, filing_type)
            if not filing_path:
                logger.debug(f"No {filing_type} filing found for {company} {adjacent_year}, skipping comparative-filing fill for {missing_year}")
                return facts

            parser = ComprehensiveXBRLParser()
            result = parser.parse_filing(filing_path)
            if not result:
                logger.debug(f"Could not parse {company} {adjacent_year} filing for comparative-filing fill")
                return facts

            adjacent_facts = result['facts']
        except Exception as e:
            logger.warning(f"Comparative-filing fill failed for {company} {missing_year}: {e}")
            return facts

        filled_count = 0
        filled_concepts = []
        for fact in adjacent_facts:
            if fact.get('period_type') != 'instant':
                continue
            instant_date = str(fact.get('instant_date') or '')
            if instant_date not in target_dates:
                continue
            concept = (fact.get('concept') or '').lower()
            if not concept or concept in existing_instant_keys:
                continue

            new_fact = dict(fact)
            new_fact['source'] = 'COMPARATIVE_FILING'
            new_fact['is_gap_filled'] = True
            facts.append(new_fact)
            existing_instant_keys.add(concept)
            filled_count += 1
            filled_concepts.append(fact.get('concept'))

        if filled_count > 0:
            logger.info(f"✅ Filled {filled_count} instant facts for {company} {missing_year} from its {adjacent_year} {filing_type} comparative column")
            critical = [c for c in filled_concepts if c and c.lower() in ('assets', 'liabilities', 'equity')]
            if critical:
                logger.info(f"   Includes: {', '.join(critical)}")
        else:
            logger.debug(f"No new instant facts found for {company} {missing_year} in its {adjacent_year} {filing_type}")

        return facts

    def _calculate_overall_completeness(self, facts: List[Dict[str, Any]]) -> float:
        """
        Calculate overall completeness score
        
        Based on:
        - Presence of critical normalized labels (universal metrics)
        - Data quality (numeric values, periods, units)
        - Dimensional coverage
        """
        if not facts:
            return 0.0
        
        # Check for critical normalized labels across all statements (taxonomy-agnostic)
        all_critical_labels = []
        for labels in self.EXPECTED_NORMALIZED_LABELS.values():
            all_critical_labels.extend(labels)
        
        found_critical = self._count_found_normalized_labels(facts, all_critical_labels)
        concept_score = found_critical / len(all_critical_labels) if all_critical_labels else 0.0
        
        # Data quality score (what % of facts have complete metadata)
        # Balance sheet items use instant_date, income/cash flow use period_end
        quality_score = (
            sum(1 for f in facts if f.get('value_numeric') and f.get('unit_measure') and 
                (f.get('period_end') or f.get('instant_date')))
            / len(facts)
        )
        
        # Dimensional coverage (bonus for detailed breakdowns)
        # NOTE: Many companies don't report many dimensions, so this threshold may be too strict
        # Adjusted to be more lenient - only expect 10% to have dimensions (many facts are consolidated totals)
        facts_with_dims = sum(1 for f in facts if f.get('dimensions') and len(f.get('dimensions', {})) > 0)
        dimensional_score = min(1.0, facts_with_dims / max(len(facts) * 0.1, 1))  # Expect at least 10% to have dimensions
        
        # Weighted average
        overall_score = (
            concept_score * 0.5 +    # 50% weight on critical concepts
            quality_score * 0.3 +     # 30% weight on data quality
            dimensional_score * 0.2   # 20% weight on dimensions
        )
        
        return round(overall_score, 3)
    
    def _calculate_statement_completeness(
        self,
        facts: List[Dict[str, Any]],
        statement_type: str
    ) -> float:
        """
        Calculate completeness for a specific financial statement
        
        Uses normalized labels (universal metrics) which work for both IFRS and US-GAAP companies.
        """
        # Prefer normalized labels (taxonomy-agnostic)
        expected_labels = self.EXPECTED_NORMALIZED_LABELS.get(statement_type, [])
        if expected_labels:
            found = self._count_found_normalized_labels(facts, expected_labels)
            return round(found / len(expected_labels), 3)
        
        # Fallback to legacy concept names (for backward compatibility)
        expected = self.EXPECTED_CONCEPTS.get(statement_type, [])
        if not expected:
            return 0.0
        
        found = self._count_found_concepts(facts, expected)
        return round(found / len(expected), 3)
    
    def _count_found_normalized_labels(
        self,
        facts: List[Dict[str, Any]],
        expected_labels: List[str]
    ) -> int:
        """
        Count how many expected normalized labels (universal metrics) are present in facts.
        
        This is taxonomy-agnostic and works for both IFRS and US-GAAP companies.
        """
        found = 0
        
        # Collect all normalized labels from facts
        fact_normalized_labels = set()
        for fact in facts:
            normalized = fact.get('normalized_label')
            if normalized:
                fact_normalized_labels.add(normalized.lower())
        
        # Check for each expected normalized label
        for expected_label in expected_labels:
            if expected_label.lower() in fact_normalized_labels:
                found += 1
        
        return found
    
    def _count_found_concepts(
        self,
        facts: List[Dict[str, Any]],
        expected_concepts: List[str]
    ) -> int:
        """
        Count how many expected concepts are present in facts (legacy method).
        
        This is a fallback for backward compatibility. Prefer _count_found_normalized_labels.
        """
        found = 0
        
        # Collect normalized labels and raw concept names
        fact_normalized_labels = set()
        fact_concepts = set()
        
        for fact in facts:
            # Prefer normalized_label (taxonomy-agnostic)
            normalized = fact.get('normalized_label')
            if normalized:
                fact_normalized_labels.add(normalized.lower())
            # Also check raw concept name as fallback
            concept = fact.get('concept', '')
            if concept:
                fact_concepts.add(concept.lower())
        
        # Map expected US-GAAP concept names to normalized labels
        # This allows completeness to work for both IFRS and US-GAAP companies
        normalized_mapping = {
            'revenue': ['revenue', 'revenues'],
            'grossprofit': ['gross_profit'],
            'operatingincomeloss': ['operating_income'],
            'netincomeloss': ['net_income'],
            'profitloss': ['net_income'],
            'costofgoodsandservicessold': ['cost_of_revenue'],
            'costofrevenue': ['cost_of_revenue'],
            'operatingexpenses': ['operating_expenses'],
            'researchanddevelopmentexpense': ['research_and_development'],
            'sellinggeneralandadministrativeexpense': ['selling_general_and_administrative'],
            'incometaxexpensebenefit': ['income_tax_expense'],
            'assets': ['total_assets'],
            'assetscurrent': ['current_assets'],
            'assetsnoncurrent': ['noncurrent_assets'],
            'cash': ['cash_and_cash_equivalents'],
            'cashandcashequivalentsatcarryingvalue': ['cash_and_cash_equivalents'],
            'accountsreceivable': ['accounts_receivable'],
            'inventory': ['inventory'],
            'propertyplantandequipmentnet': ['property_plant_and_equipment'],
            'liabilities': ['total_liabilities'],
            'liabilitiescurrent': ['current_liabilities'],
            'liabilitiesnoncurrent': ['noncurrent_liabilities'],
            'accountspayable': ['accounts_payable'],
            'debtcurrent': ['current_debt'],
            'debtnoncurrent': ['noncurrent_debt'],
            'stockholdersequity': ['stockholders_equity'],
            'retainedearnings': ['retained_earnings'],
            'commonstock': ['common_stock'],
            'additionalpaidincapital': ['additional_paid_in_capital'],
            'netcashprovidedbyusedinoperatingactivities': ['operating_cash_flow'],
            'netcashprovidedbyusedininvestingactivities': ['investing_cash_flow'],
            'netcashprovidedbyusedinfinancingactivities': ['financing_cash_flow'],
            'depreciationdepletionandamortization': ['depreciation_amortization'],
            'paymentstoacquirepropertyplantandequipment': ['capex'],
            'dividendspaid': ['dividends_paid'],
            'proceedsfromissuanceofdebt': ['debt_issued'],
            'repaymentsofdebt': ['debt_repaid'],
        }
        
        for expected in expected_concepts:
            expected_lower = expected.lower()
            found_match = False
            
            # First, try to find via normalized label (works for both IFRS and US-GAAP)
            if expected_lower in normalized_mapping:
                for normalized_key in normalized_mapping[expected_lower]:
                    if normalized_key in fact_normalized_labels:
                        found_match = True
                        break
            
            # Fallback: check raw concept name (for US-GAAP companies)
            if not found_match:
                if any(expected_lower in fc for fc in fact_concepts):
                    found_match = True
            
            if found_match:
                found += 1
        
        return found
    
    def get_stats(self) -> Dict[str, int]:
        """Get tracker statistics"""
        return self.stats.copy()


def main():
    """Test completeness tracking"""
    import json
    
    # Test with mock data
    test_facts = [
        {'concept': 'Revenue', 'value_numeric': 100000, 'period_end': '2024-12-31', 'unit_measure': 'USD', 'taxonomy': 'US-GAAP'},
        {'concept': 'NetIncomeLoss', 'value_numeric': 10000, 'period_end': '2024-12-31', 'unit_measure': 'USD', 'taxonomy': 'US-GAAP'},
        {'concept': 'Assets', 'value_numeric': 500000, 'instant_date': '2024-12-31', 'unit_measure': 'USD', 'taxonomy': 'US-GAAP'},
        {'concept': 'Liabilities', 'value_numeric': 300000, 'instant_date': '2024-12-31', 'unit_measure': 'USD', 'taxonomy': 'US-GAAP'},
        {'concept': 'StockholdersEquity', 'value_numeric': 200000, 'instant_date': '2024-12-31', 'unit_measure': 'USD', 'taxonomy': 'US-GAAP', 'dimensions': {'Segment': 'Total'}},
    ]
    
    tracker = CompletenessTracker()
    report = tracker.analyze_completeness(
        facts=test_facts,
        company='TEST',
        filing_type='10-K',
        fiscal_year_end='2024-12-31'
    )
    
    print("Completeness Report:")
    print(json.dumps(report.to_dict(), indent=2))
    print(f"\nTracker Stats: {tracker.get_stats()}")


if __name__ == '__main__':
    main()

