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
    
    # Expected critical concepts per statement type
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
        
        # Calculate completeness scores
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
    
    def _calculate_overall_completeness(self, facts: List[Dict[str, Any]]) -> float:
        """
        Calculate overall completeness score
        
        Based on:
        - Presence of critical concepts
        - Data quality (numeric values, periods, units)
        - Dimensional coverage
        """
        if not facts:
            return 0.0
        
        # Check for critical concepts across all statements
        all_critical = []
        for concepts in self.EXPECTED_CONCEPTS.values():
            all_critical.extend(concepts)
        
        found_critical = self._count_found_concepts(facts, all_critical)
        concept_score = found_critical / len(all_critical)
        
        # Data quality score (what % of facts have complete metadata)
        quality_score = (
            sum(1 for f in facts if f.get('value_numeric') and f.get('period_end') and f.get('unit_measure'))
            / len(facts)
        )
        
        # Dimensional coverage (bonus for detailed breakdowns)
        dimensional_score = min(1.0, sum(
            1 for f in facts if f.get('dimensions') and len(f.get('dimensions', {})) > 0
        ) / (len(facts) * 0.5))  # Expect at least 50% to have dimensions
        
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
        """Calculate completeness for a specific financial statement"""
        expected = self.EXPECTED_CONCEPTS.get(statement_type, [])
        if not expected:
            return 0.0
        
        found = self._count_found_concepts(facts, expected)
        return round(found / len(expected), 3)
    
    def _count_found_concepts(
        self,
        facts: List[Dict[str, Any]],
        expected_concepts: List[str]
    ) -> int:
        """Count how many expected concepts are present in facts"""
        found = 0
        fact_concepts = set(f.get('concept', '').lower() for f in facts)
        
        for expected in expected_concepts:
            expected_lower = expected.lower()
            # Check if any fact concept contains the expected concept
            if any(expected_lower in fc for fc in fact_concepts):
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

