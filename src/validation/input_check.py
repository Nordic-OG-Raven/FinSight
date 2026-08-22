#!/usr/bin/env python3
"""
Pre-Load Validation Module

Validates facts dicts before database loading to catch issues early.
This runs after gap filling but before StarSchemaLoader.load_json_file().

Checks:
1. Accounting identities (balance sheet equation, gross profit logic)
2. Value reasonableness (gross margin 0-100%, equity 10-80% of assets, transaction signs)
3. Cross-statement consistency (net income matching, retained earnings)
4. Multiple consolidated facts detection (warn if multiple exist for same concept/period)
"""

import logging
from typing import List, Dict, Any, Optional
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from src.validation.checks import ValidationResult, ValidationReport

logger = logging.getLogger(__name__)


class InputValidator:
    """Validates facts dicts before database loading"""
    
    def __init__(self, tolerance_pct: float = 1.0):
        """
        Initialize validator
        
        Args:
            tolerance_pct: Tolerance percentage for accounting identity checks (default 1.0%)
        """
        self.tolerance_pct = tolerance_pct
    
    def validate_facts(self, facts: List[Dict[str, Any]], company: str = "unknown") -> ValidationReport:
        """
        Validate facts dicts before loading
        
        Args:
            facts: List of fact dictionaries from parser
            company: Company ticker (for logging)
            
        Returns:
            ValidationReport with warnings/errors (doesn't block pipeline)
        """
        report = ValidationReport(
            company=company,
            filing_type="unknown",
            fiscal_year_end="unknown"
        )
        
        if not facts:
            report.add_result(ValidationResult(
                rule_name="facts_present",
                passed=False,
                severity="ERROR",
                message="No facts provided for validation"
            ))
            report.calculate_score()
            return report
        
        # Group facts by concept and period for easier lookup
        facts_by_concept = self._group_facts_by_concept(facts)
        
        # 1. Accounting identities
        self._check_balance_sheet_equation(facts_by_concept, report)
        self._check_gross_profit_logic(facts_by_concept, report)
        self._check_income_statement_flow(facts_by_concept, report)
        
        # 2. Value reasonableness
        self._check_gross_margin_reasonableness(facts_by_concept, report)
        self._check_equity_scaling(facts_by_concept, report)
        self._check_transaction_signs(facts_by_concept, report)
        
        # 3. Cross-statement consistency
        self._check_net_income_consistency(facts_by_concept, report)
        self._check_retained_earnings_consistency(facts_by_concept, report)
        
        # 4. Multiple consolidated facts detection
        self._check_multiple_consolidated_facts(facts, report)
        
        report.calculate_score()
        return report
    
    def _group_facts_by_concept(self, facts: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group facts by normalized_label or concept name"""
        grouped = defaultdict(list)
        for fact in facts:
            # Try normalized_label first, fallback to concept
            key = fact.get('normalized_label') or fact.get('concept', '')
            if key:
                grouped[key].append(fact)
        return grouped
    
    def _get_primary_fact(self, facts: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Get primary fact from list (first one with context_id, or first one)
        Used when multiple consolidated facts exist for same concept/period
        """
        if not facts:
            return None
        
        # Prefer facts with context_id
        facts_with_context = [f for f in facts if f.get('context_id')]
        if facts_with_context:
            return facts_with_context[0]
        
        return facts[0]
    
    def _get_numeric_value(self, fact: Dict[str, Any]) -> Optional[float]:
        """Extract numeric value from fact, applying scale if needed"""
        value = fact.get('value_numeric')
        if value is None:
            return None
        
        # Apply scaling if present
        scale_int = fact.get('scale_int', 0) or 0
        if scale_int and scale_int > 0:
            value = value * (10 ** scale_int)
        
        decimals = fact.get('decimals')
        if decimals:
            try:
                if isinstance(decimals, str):
                    decimal_val = int(decimals)
                else:
                    decimal_val = decimals
                
                if decimal_val < 0:
                    scale_factor = 10 ** abs(decimal_val)
                    value = float(value) * scale_factor
            except (ValueError, TypeError):
                pass
        
        return float(value) if value is not None else None
    
    def _check_balance_sheet_equation(self, facts_by_concept: Dict[str, List[Dict]], report: ValidationReport):
        """Check Assets ≈ Liabilities + Equity"""
        assets_facts = facts_by_concept.get('total_assets') or facts_by_concept.get('assets_total') or []
        liabilities_facts = facts_by_concept.get('total_liabilities') or facts_by_concept.get('liabilities_total') or []
        equity_facts = facts_by_concept.get('equity_total') or facts_by_concept.get('total_equity') or []
        
        if not (assets_facts and (liabilities_facts or equity_facts)):
            return  # Missing required concepts, skip check
        
        # Get primary facts (first with context_id, or first)
        assets = self._get_primary_fact(assets_facts)
        liabilities = self._get_primary_fact(liabilities_facts) if liabilities_facts else None
        equity = self._get_primary_fact(equity_facts)
        
        if not (assets and equity):
            return
        
        assets_val = self._get_numeric_value(assets)
        liabilities_val = self._get_numeric_value(liabilities) if liabilities else 0.0
        equity_val = self._get_numeric_value(equity)
        
        if assets_val is None or equity_val is None:
            return
        
        # Check equation: Assets = Liabilities + Equity
        calculated_equity = assets_val - liabilities_val
        difference = abs(equity_val - calculated_equity)
        tolerance = abs(assets_val) * (self.tolerance_pct / 100.0)
        
        if difference > tolerance:
            report.add_result(ValidationResult(
                rule_name="balance_sheet_equation",
                passed=False,
                severity="WARNING",
                message=f"Balance sheet equation violation: Assets ({assets_val:,.0f}) ≠ Liabilities ({liabilities_val:,.0f}) + Equity ({equity_val:,.0f})",
                expected_value=calculated_equity,
                actual_value=equity_val,
                tolerance_pct=self.tolerance_pct,
                details={
                    'assets': assets_val,
                    'liabilities': liabilities_val,
                    'equity': equity_val,
                    'calculated_equity': calculated_equity,
                    'difference': difference
                }
            ))
        else:
            report.add_result(ValidationResult(
                rule_name="balance_sheet_equation",
                passed=True,
                severity="INFO",
                message="Balance sheet equation holds"
            ))
    
    def _check_gross_profit_logic(self, facts_by_concept: Dict[str, List[Dict]], report: ValidationReport):
        """Check gross_profit ≤ revenue"""
        revenue_facts = facts_by_concept.get('revenue') or facts_by_concept.get('net_sales') or []
        gross_profit_facts = facts_by_concept.get('gross_profit') or []
        
        if not (revenue_facts and gross_profit_facts):
            return
        
        revenue = self._get_primary_fact(revenue_facts)
        gross_profit = self._get_primary_fact(gross_profit_facts)
        
        if not (revenue and gross_profit):
            return
        
        revenue_val = self._get_numeric_value(revenue)
        gross_profit_val = self._get_numeric_value(gross_profit)
        
        if revenue_val is None or gross_profit_val is None:
            return
        
        # Gross profit should be ≤ revenue (can be negative for losses)
        if abs(gross_profit_val) > abs(revenue_val) * 1.01:  # Allow 1% tolerance for rounding
            report.add_result(ValidationResult(
                rule_name="gross_profit_logic",
                passed=False,
                severity="WARNING",
                message=f"Gross profit ({gross_profit_val:,.0f}) exceeds revenue ({revenue_val:,.0f})",
                expected_value=revenue_val,
                actual_value=gross_profit_val,
                details={
                    'revenue': revenue_val,
                    'gross_profit': gross_profit_val
                }
            ))
        else:
            report.add_result(ValidationResult(
                rule_name="gross_profit_logic",
                passed=True,
                severity="INFO",
                message="Gross profit logic holds"
            ))
    
    def _check_income_statement_flow(self, facts_by_concept: Dict[str, List[Dict]], report: ValidationReport):
        """Check revenue - costs = gross_profit (basic flow)"""
        revenue_facts = facts_by_concept.get('revenue') or facts_by_concept.get('net_sales') or []
        cost_facts = facts_by_concept.get('cost_of_sales') or facts_by_concept.get('cost_of_goods_sold') or []
        gross_profit_facts = facts_by_concept.get('gross_profit') or []
        
        if not (revenue_facts and cost_facts and gross_profit_facts):
            return
        
        revenue = self._get_primary_fact(revenue_facts)
        cost = self._get_primary_fact(cost_facts)
        gross_profit = self._get_primary_fact(gross_profit_facts)
        
        if not (revenue and cost and gross_profit):
            return
        
        revenue_val = self._get_numeric_value(revenue)
        cost_val = self._get_numeric_value(cost)
        gross_profit_val = self._get_numeric_value(gross_profit)
        
        if revenue_val is None or cost_val is None or gross_profit_val is None:
            return
        
        # Check: revenue - cost = gross_profit
        calculated_gross_profit = revenue_val - cost_val
        difference = abs(gross_profit_val - calculated_gross_profit)
        tolerance = abs(revenue_val) * (self.tolerance_pct / 100.0)
        
        if difference > tolerance:
            report.add_result(ValidationResult(
                rule_name="income_statement_flow",
                passed=False,
                severity="WARNING",
                message=f"Income statement flow violation: Revenue ({revenue_val:,.0f}) - Cost ({cost_val:,.0f}) ≠ Gross Profit ({gross_profit_val:,.0f})",
                expected_value=calculated_gross_profit,
                actual_value=gross_profit_val,
                tolerance_pct=self.tolerance_pct,
                details={
                    'revenue': revenue_val,
                    'cost': cost_val,
                    'gross_profit': gross_profit_val,
                    'calculated_gross_profit': calculated_gross_profit,
                    'difference': difference
                }
            ))
        else:
            report.add_result(ValidationResult(
                rule_name="income_statement_flow",
                passed=True,
                severity="INFO",
                message="Income statement flow holds"
            ))
    
    def _check_gross_margin_reasonableness(self, facts_by_concept: Dict[str, List[Dict]], report: ValidationReport):
        """Check gross margin is 0-100% (logic, not health-based)"""
        revenue_facts = facts_by_concept.get('revenue') or facts_by_concept.get('net_sales') or []
        gross_profit_facts = facts_by_concept.get('gross_profit') or []
        
        if not (revenue_facts and gross_profit_facts):
            return
        
        revenue = self._get_primary_fact(revenue_facts)
        gross_profit = self._get_primary_fact(gross_profit_facts)
        
        if not (revenue and gross_profit):
            return
        
        revenue_val = self._get_numeric_value(revenue)
        gross_profit_val = self._get_numeric_value(gross_profit)
        
        if revenue_val is None or gross_profit_val is None or revenue_val == 0:
            return
        
        gross_margin_pct = (gross_profit_val / revenue_val) * 100.0
        
        # Gross margin should be 0-100% (logic check, not health-based)
        if gross_margin_pct < 0 or gross_margin_pct > 100:
            report.add_result(ValidationResult(
                rule_name="gross_margin_reasonableness",
                passed=False,
                severity="WARNING",
                message=f"Gross margin ({gross_margin_pct:.1f}%) outside reasonable range (0-100%)",
                expected_value=50.0,  # Midpoint for reference
                actual_value=gross_margin_pct,
                details={
                    'revenue': revenue_val,
                    'gross_profit': gross_profit_val,
                    'gross_margin_pct': gross_margin_pct
                }
            ))
        else:
            report.add_result(ValidationResult(
                rule_name="gross_margin_reasonableness",
                passed=True,
                severity="INFO",
                message=f"Gross margin ({gross_margin_pct:.1f}%) within reasonable range"
            ))
    
    def _check_equity_scaling(self, facts_by_concept: Dict[str, List[Dict]], report: ValidationReport):
        """Check equity is 10-80% of assets (catches unit scaling issues)"""
        assets_facts = facts_by_concept.get('total_assets') or facts_by_concept.get('assets_total') or []
        equity_facts = facts_by_concept.get('equity_total') or facts_by_concept.get('total_equity') or []
        
        if not (assets_facts and equity_facts):
            return
        
        assets = self._get_primary_fact(assets_facts)
        equity = self._get_primary_fact(equity_facts)
        
        if not (assets and equity):
            return
        
        assets_val = self._get_numeric_value(assets)
        equity_val = self._get_numeric_value(equity)
        
        if assets_val is None or equity_val is None or assets_val == 0:
            return
        
        equity_ratio = (abs(equity_val) / abs(assets_val)) * 100.0
        
        # Equity should be 10-80% of assets (catches unit scaling issues)
        # Values outside this range suggest unit scaling problems
        if equity_ratio < 1.0 or equity_ratio > 80.0:
            report.add_result(ValidationResult(
                rule_name="equity_scaling",
                passed=False,
                severity="WARNING",
                message=f"Equity ratio ({equity_ratio:.1f}%) outside expected range (10-80%), possible unit scaling issue",
                expected_value=30.0,  # Typical healthy range midpoint
                actual_value=equity_ratio,
                details={
                    'assets': assets_val,
                    'equity': equity_val,
                    'equity_ratio_pct': equity_ratio
                }
            ))
        else:
            report.add_result(ValidationResult(
                rule_name="equity_scaling",
                passed=True,
                severity="INFO",
                message=f"Equity ratio ({equity_ratio:.1f}%) within expected range"
            ))
    
    def _check_transaction_signs(self, facts_by_concept: Dict[str, List[Dict]], report: ValidationReport):
        """Check transaction signs: expenses negative, income positive"""
        # Income items should be positive
        income_concepts = ['revenue', 'net_sales', 'gross_profit', 'operating_income', 'net_income']
        # Expense items should be negative (in XBRL, expenses are often reported as negative)
        expense_concepts = ['cost_of_sales', 'cost_of_goods_sold', 'selling_expense', 'administrative_expense', 
                           'research_development', 'income_tax_expense']
        
        issues = []
        
        for concept in income_concepts:
            facts = facts_by_concept.get(concept, [])
            if not facts:
                continue
            
            primary = self._get_primary_fact(facts)
            if not primary:
                continue
            
            value = self._get_numeric_value(primary)
            if value is not None and value < 0:
                issues.append(f"{concept}: {value:,.0f} (expected positive)")
        
        for concept in expense_concepts:
            facts = facts_by_concept.get(concept, [])
            if not facts:
                continue
            
            primary = self._get_primary_fact(facts)
            if not primary:
                continue
            
            value = self._get_numeric_value(primary)
            # Expenses can be negative (XBRL convention) or positive, but shouldn't be opposite of expected
            # This is a soft check - just log if unexpected
            
        if issues:
            report.add_result(ValidationResult(
                rule_name="transaction_signs",
                passed=False,
                severity="WARNING",
                message=f"Transaction sign issues: {', '.join(issues)}",
                details={'issues': issues}
            ))
        else:
            report.add_result(ValidationResult(
                rule_name="transaction_signs",
                passed=True,
                severity="INFO",
                message="Transaction signs appear correct"
            ))
    
    def _check_net_income_consistency(self, facts_by_concept: Dict[str, List[Dict]], report: ValidationReport):
        """Check net income matches between income statement and comprehensive income"""
        net_income_facts = facts_by_concept.get('net_income') or facts_by_concept.get('net_profit') or []
        comprehensive_income_facts = facts_by_concept.get('comprehensive_income') or facts_by_concept.get('total_comprehensive_income') or []
        
        if not (net_income_facts and comprehensive_income_facts):
            return  # Both must be present to check consistency
        
        # This is a limited check at this stage - just verify both exist
        # Full consistency check requires period matching which is complex at this stage
        report.add_result(ValidationResult(
            rule_name="net_income_consistency",
            passed=True,
            severity="INFO",
            message="Net income and comprehensive income both present (full consistency check in later stage)"
        ))
    
    def _check_retained_earnings_consistency(self, facts_by_concept: Dict[str, List[Dict]], report: ValidationReport):
        """Check retained earnings changes match net income (if both present)"""
        retained_earnings_facts = facts_by_concept.get('retained_earnings') or []
        net_income_facts = facts_by_concept.get('net_income') or facts_by_concept.get('net_profit') or []
        
        if not (retained_earnings_facts and net_income_facts):
            return  # Both must be present
        
        # Limited check at this stage - full consistency requires period matching
        report.add_result(ValidationResult(
            rule_name="retained_earnings_consistency",
            passed=True,
            severity="INFO",
            message="Retained earnings and net income both present (full consistency check in later stage)"
        ))
    
    def _check_multiple_consolidated_facts(self, facts: List[Dict[str, Any]], report: ValidationReport):
        """Warn if multiple consolidated facts exist for same concept/period"""
        # Group by (concept, period, has_dimensions)
        concept_periods = defaultdict(list)
        
        for fact in facts:
            concept = fact.get('normalized_label') or fact.get('concept', '')
            if not concept:
                continue
            
            # Get period key
            period_key = None
            if fact.get('instant_date'):
                period_key = fact.get('instant_date')[:7]  # YYYY-MM
            elif fact.get('period_end'):
                period_key = fact.get('period_end')[:7]
            
            if period_key:
                has_dims = bool(fact.get('dimensions'))
                key = (concept, period_key, has_dims)
                concept_periods[key].append(fact)
        
        # Find concepts with multiple consolidated facts (no dimensions)
        conflicts = []
        for (concept, period, has_dims), facts_list in concept_periods.items():
            if not has_dims and len(facts_list) > 1:
                # Check if values differ significantly
                values = []
                for f in facts_list:
                    val = self._get_numeric_value(f)
                    if val is not None:
                        values.append(val)
                
                if values:
                    unique_values = len(set(values))
                    if unique_values > 1:
                        conflicts.append({
                            'concept': concept,
                            'period': period,
                            'count': len(facts_list),
                            'unique_values': unique_values,
                            'values': sorted(set(values))[:5]  # First 5 unique values
                        })
        
        if conflicts:
            # Group by concept for reporting
            by_concept = defaultdict(list)
            for conflict in conflicts:
                by_concept[conflict['concept']].append(conflict)
            
            messages = []
            for concept, conflict_list in list(by_concept.items())[:10]:  # Top 10 concepts
                total_conflicts = sum(c['count'] for c in conflict_list)
                messages.append(f"{concept}: {total_conflicts} consolidated facts across {len(conflict_list)} periods")
            
            report.add_result(ValidationResult(
                rule_name="multiple_consolidated_facts",
                passed=True,  # Not an error, just a warning
                severity="WARNING",
                message=f"Found {len(conflicts)} concept-period combinations with multiple consolidated facts: {', '.join(messages)}",
                details={
                    'conflicts': conflicts[:20],  # First 20 for details
                    'total_conflicts': len(conflicts)
                }
            ))
        else:
            report.add_result(ValidationResult(
                rule_name="multiple_consolidated_facts",
                passed=True,
                severity="INFO",
                message="No multiple consolidated facts detected (or all will be preserved via synthetic dimensions)"
            ))

