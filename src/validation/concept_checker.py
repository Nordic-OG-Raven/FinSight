#!/usr/bin/env python3
"""
Concept Mapping Validator Module

Validates concept mappings after normalization to catch mapping errors.
This runs after loading to fact_financial_metrics, before populate_statement_facts().

Checks:
1. Wrong concepts mapped to normalized labels (check if concept makes sense for its label)
2. Concept mapping conflicts (multiple concepts → same label, same concept → multiple labels)
3. Taxonomy consistency (IFRS vs US-GAAP mappings)
4. Synthetic dimension validation (verify ContextAxis dimensions created correctly)
"""

import logging
from typing import List, Dict, Any, Optional
from collections import defaultdict
from sqlalchemy import create_engine, text
from config import DATABASE_URI

from src.validation.checks import ValidationResult, ValidationReport

logger = logging.getLogger(__name__)


class ConceptMappingValidator:
    """Validates concept mappings after normalization"""
    
    def __init__(self):
        """Initialize validator"""
        self.engine = create_engine(DATABASE_URI)
    
    def validate_mappings(self, ticker: str, year: int) -> ValidationReport:
        """
        Validate concept mappings for a company/year
        
        Args:
            ticker: Company ticker
            year: Fiscal year
            
        Returns:
            ValidationReport with concept mapping issues
        """
        report = ValidationReport(
            company=ticker,
            filing_type="unknown",
            fiscal_year_end=f"{year}-12-31"
        )
        
        with self.engine.connect() as conn:
            # Get filing_id
            filing_result = conn.execute(text("""
                SELECT f.filing_id, f.filing_type, f.fiscal_year_end
                FROM dim_filings f
                JOIN dim_companies c ON f.company_id = c.company_id
                WHERE c.ticker = :ticker
                  AND EXTRACT(YEAR FROM f.fiscal_year_end) = :year
                ORDER BY f.filing_id DESC
                LIMIT 1
            """), {'ticker': ticker, 'year': year})
            
            filing_row = filing_result.fetchone()
            if not filing_row:
                report.add_result(ValidationResult(
                    rule_name="filing_exists",
                    passed=False,
                    severity="ERROR",
                    message=f"No filing found for {ticker} {year}"
                ))
                report.calculate_score()
                return report
            
            filing_id, filing_type, fiscal_year_end = filing_row
            report.filing_type = filing_type or "unknown"
            report.fiscal_year_end = str(fiscal_year_end) if fiscal_year_end else f"{year}-12-31"
            
            # 1. Check wrong concepts mapped to normalized labels
            self._check_wrong_concept_mappings(conn, filing_id, report)
            
            # 2. Check concept mapping conflicts
            self._check_mapping_conflicts(conn, filing_id, report)
            
            # 3. Check taxonomy consistency
            self._check_taxonomy_consistency(conn, filing_id, report)
            
            # 4. Validate synthetic dimensions
            self._check_synthetic_dimensions(conn, filing_id, report)
        
        report.calculate_score()
        return report
    
    def _check_wrong_concept_mappings(self, conn, filing_id: int, report: ValidationReport):
        """Check if mapped concept makes sense for its normalized label"""
        # Get primary facts (dimension_id IS NULL) for validation
        result = conn.execute(text("""
            SELECT 
                dc.concept_name,
                dc.normalized_label,
                COUNT(DISTINCT ffm.fact_id) as fact_count,
                AVG(ffm.value_numeric) as avg_value,
                MIN(ffm.value_numeric) as min_value,
                MAX(ffm.value_numeric) as max_value
            FROM fact_financial_metrics ffm
            JOIN dim_concepts dc ON ffm.concept_id = dc.concept_id
            WHERE ffm.filing_id = :filing_id
              AND ffm.dimension_id IS NULL  -- Primary facts only
              AND ffm.value_numeric IS NOT NULL
            GROUP BY dc.concept_id, dc.concept_name, dc.normalized_label
            HAVING COUNT(DISTINCT ffm.fact_id) > 0
        """), {'filing_id': filing_id})
        
        issues = []
        
        for row in result:
            concept_name, normalized_label, fact_count, avg_value, min_value, max_value = row
            
            # Check if concept name matches normalized label semantics
            concept_lower = (concept_name or '').lower()
            label_lower = (normalized_label or '').lower()
            
            # Known problematic mappings
            if 'equity' in label_lower:
                if 'asset' in concept_lower and 'equity' not in concept_lower:
                    issues.append({
                        'concept': concept_name,
                        'normalized_label': normalized_label,
                        'issue': 'Equity label mapped to asset concept'
                    })
            
            if 'revenue' in label_lower or 'sales' in label_lower:
                if 'expense' in concept_lower or 'cost' in concept_lower:
                    issues.append({
                        'concept': concept_name,
                        'normalized_label': normalized_label,
                        'issue': 'Revenue label mapped to expense concept'
                    })
            
            if 'asset' in label_lower:
                if 'liability' in concept_lower and 'asset' not in concept_lower:
                    issues.append({
                        'concept': concept_name,
                        'normalized_label': normalized_label,
                        'issue': 'Asset label mapped to liability concept'
                    })
        
        if issues:
            report.add_result(ValidationResult(
                rule_name="wrong_concept_mappings",
                passed=False,
                severity="WARNING",
                message=f"Found {len(issues)} potentially wrong concept mappings",
                details={'issues': issues[:20]}  # First 20 for details
            ))
        else:
            report.add_result(ValidationResult(
                rule_name="wrong_concept_mappings",
                passed=True,
                severity="INFO",
                message="Concept mappings appear correct"
            ))
    
    def _check_mapping_conflicts(self, conn, filing_id: int, report: ValidationReport):
        """Check for concept mapping conflicts"""
        # Check: Multiple different concepts → same normalized label
        result = conn.execute(text("""
            SELECT 
                dc.normalized_label,
                COUNT(DISTINCT dc.concept_id) as concept_count,
                COUNT(DISTINCT dc.concept_name) as concept_name_count,
                STRING_AGG(DISTINCT dc.concept_name, ', ' ORDER BY dc.concept_name) as concepts
            FROM fact_financial_metrics ffm
            JOIN dim_concepts dc ON ffm.concept_id = dc.concept_id
            WHERE ffm.filing_id = :filing_id
              AND ffm.dimension_id IS NULL  -- Primary facts only
              AND dc.normalized_label IS NOT NULL
            GROUP BY dc.normalized_label
            HAVING COUNT(DISTINCT dc.concept_id) > 1
            ORDER BY concept_count DESC
        """), {'filing_id': filing_id})
        
        conflicts = []
        for row in result:
            normalized_label, concept_count, concept_name_count, concepts = row
            conflicts.append({
                'normalized_label': normalized_label,
                'concept_count': concept_count,
                'concepts': concepts
            })
        
        if conflicts:
            report.add_result(ValidationResult(
                rule_name="mapping_conflicts_multiple_concepts",
                passed=True,  # Not necessarily an error - multiple concepts can map to same label
                severity="WARNING",
                message=f"Found {len(conflicts)} normalized labels with multiple concepts (may be expected)",
                details={'conflicts': conflicts[:20]}
            ))
        else:
            report.add_result(ValidationResult(
                rule_name="mapping_conflicts_multiple_concepts",
                passed=True,
                severity="INFO",
                message="No multiple concepts → same label conflicts"
            ))
        
        # Check: Same concept → multiple normalized labels (shouldn't happen)
        result = conn.execute(text("""
            SELECT 
                dc.concept_id,
                dc.concept_name,
                COUNT(DISTINCT dc.normalized_label) as label_count,
                STRING_AGG(DISTINCT dc.normalized_label, ', ' ORDER BY dc.normalized_label) as labels
            FROM fact_financial_metrics ffm
            JOIN dim_concepts dc ON ffm.concept_id = dc.concept_id
            WHERE ffm.filing_id = :filing_id
              AND ffm.dimension_id IS NULL  -- Primary facts only
              AND dc.normalized_label IS NOT NULL
            GROUP BY dc.concept_id, dc.concept_name
            HAVING COUNT(DISTINCT dc.normalized_label) > 1
            ORDER BY label_count DESC
        """), {'filing_id': filing_id})
        
        same_concept_conflicts = []
        for row in result:
            concept_id, concept_name, label_count, labels = row
            same_concept_conflicts.append({
                'concept_id': concept_id,
                'concept_name': concept_name,
                'label_count': label_count,
                'labels': labels
            })
        
        if same_concept_conflicts:
            report.add_result(ValidationResult(
                rule_name="mapping_conflicts_same_concept",
                passed=False,
                severity="WARNING",
                message=f"Found {len(same_concept_conflicts)} concepts mapped to multiple labels (unexpected)",
                details={'conflicts': same_concept_conflicts}
            ))
        else:
            report.add_result(ValidationResult(
                rule_name="mapping_conflicts_same_concept",
                passed=True,
                severity="INFO",
                message="No same concept → multiple labels conflicts"
            ))
    
    def _check_taxonomy_consistency(self, conn, filing_id: int, report: ValidationReport):
        """Check IFRS vs US-GAAP mappings are correct"""
        # Get taxonomy from filing
        result = conn.execute(text("""
            SELECT DISTINCT dc.taxonomy
            FROM fact_financial_metrics ffm
            JOIN dim_concepts dc ON ffm.concept_id = dc.concept_id
            WHERE ffm.filing_id = :filing_id
              AND dc.taxonomy IS NOT NULL
        """), {'filing_id': filing_id})
        
        taxonomies = [row[0] for row in result]
        
        if not taxonomies:
            report.add_result(ValidationResult(
                rule_name="taxonomy_consistency",
                passed=True,
                severity="INFO",
                message="No taxonomy information available"
            ))
            return
        
        # Check if multiple taxonomies are mixed (IFRS and US-GAAP)
        has_ifrs = any('ifrs' in t.lower() for t in taxonomies)
        has_gaap = any('gaap' in t.lower() or 'us-gaap' in t.lower() for t in taxonomies)
        
        if has_ifrs and has_gaap:
            report.add_result(ValidationResult(
                rule_name="taxonomy_consistency",
                passed=True,  # Not necessarily an error - cross-taxonomy merges are valid
                severity="INFO",
                message=f"Mixed taxonomies detected: {', '.join(set(taxonomies))} (may be expected for cross-taxonomy mappings)"
            ))
        else:
            report.add_result(ValidationResult(
                rule_name="taxonomy_consistency",
                passed=True,
                severity="INFO",
                message=f"Taxonomy consistency: {', '.join(set(taxonomies))}"
            ))
    
    def _check_synthetic_dimensions(self, conn, filing_id: int, report: ValidationReport):
        """Verify synthetic ContextAxis dimensions are correctly created"""
        # Check if synthetic dimensions exist
        result = conn.execute(text("""
            SELECT COUNT(*) as count
            FROM fact_financial_metrics ffm
            JOIN dim_xbrl_dimensions d ON ffm.dimension_id = d.dimension_id
            WHERE ffm.filing_id = :filing_id
              AND d.axis_name = 'ContextAxis'
        """), {'filing_id': filing_id})
        
        synthetic_count = result.fetchone()[0]
        
        if synthetic_count > 0:
            # Check if synthetic dimensions are correctly structured
            result = conn.execute(text("""
                SELECT 
                    COUNT(*) as fact_count,
                    COUNT(DISTINCT d.dimension_id) as dimension_count,
                    COUNT(DISTINCT ffm.normalized_label) as concept_count
                FROM fact_financial_metrics ffm
                JOIN dim_xbrl_dimensions d ON ffm.dimension_id = d.dimension_id
                WHERE ffm.filing_id = :filing_id
                  AND d.axis_name = 'ContextAxis'
            """), {'filing_id': filing_id})
            
            fact_count, dimension_count, concept_count = result.fetchone()
            
            report.add_result(ValidationResult(
                rule_name="synthetic_dimensions",
                passed=True,
                severity="INFO",
                message=f"Synthetic ContextAxis dimensions: {fact_count} facts, {dimension_count} unique dimensions, {concept_count} concepts",
                details={
                    'fact_count': fact_count,
                    'dimension_count': dimension_count,
                    'concept_count': concept_count
                }
            ))
            
            # Verify primary facts still exist (dimension_id IS NULL)
            result = conn.execute(text("""
                SELECT COUNT(*) as count
                FROM fact_financial_metrics
                WHERE filing_id = :filing_id
                  AND dimension_id IS NULL
            """), {'filing_id': filing_id})
            
            primary_count = result.fetchone()[0]
            
            if primary_count > 0:
                report.add_result(ValidationResult(
                    rule_name="synthetic_dimensions_primary",
                    passed=True,
                    severity="INFO",
                    message=f"Primary consolidated facts (dimension_id IS NULL): {primary_count} facts"
                ))
            else:
                report.add_result(ValidationResult(
                    rule_name="synthetic_dimensions_primary",
                    passed=False,
                    severity="WARNING",
                    message="No primary consolidated facts found (all facts have synthetic dimensions?)"
                ))
        else:
            report.add_result(ValidationResult(
                rule_name="synthetic_dimensions",
                passed=True,
                severity="INFO",
                message="No synthetic dimensions found (no conflicts or all facts preserved without synthetic dimensions)"
            ))

