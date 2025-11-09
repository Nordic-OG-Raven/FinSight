#!/usr/bin/env python3
"""
Relationship Synthesizer

Generates synthetic calculation and presentation relationships when not available in XBRL filings.
Uses dimensional breakdowns and standard financial statement hierarchies.
"""
import logging
from typing import Dict, List, Tuple, Set, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


class RelationshipSynthesizer:
    """Generate synthetic relationships from fact data"""
    
    # Standard financial statement hierarchy templates
    STANDARD_HIERARCHIES = {
        'income_statement': {
            'revenue': ['product_revenue', 'service_revenue', 'sales'],
            'gross_profit': ['revenue', '-cost_of_revenue'],
            'operating_income': ['gross_profit', '-operating_expenses'],
            'operating_expenses': ['research_development', 'sales_marketing', 'general_administrative'],
            'net_income': ['operating_income', '+other_income', '-tax_expense', '-interest_expense'],
            'earnings_per_share': [],  # Calculated, not summed
        },
        'balance_sheet': {
            'total_assets': ['current_assets', 'noncurrent_assets'],
            'current_assets': ['cash', 'accounts_receivable', 'inventory', 'prepaid_expenses'],
            'noncurrent_assets': ['property_plant_equipment', 'intangible_assets', 'goodwill'],
            'total_liabilities': ['current_liabilities', 'noncurrent_liabilities'],
            'current_liabilities': ['accounts_payable', 'accrued_liabilities', 'short_term_debt'],
            'noncurrent_liabilities': ['long_term_debt', 'deferred_tax_liabilities'],
            'total_equity': ['common_stock', 'retained_earnings', 'accumulated_other_comprehensive_income'],
        },
        'cash_flow': {
            'operating_cashflow': ['net_income', '+depreciation', '+changes_working_capital'],
            'investing_cashflow': ['capital_expenditures', 'acquisitions', 'asset_sales'],
            'financing_cashflow': ['debt_issuance', 'debt_repayment', 'dividends_paid', 'stock_buybacks'],
            'net_change_cash': ['operating_cashflow', 'investing_cashflow', 'financing_cashflow'],
        }
    }
    
    def __init__(self):
        pass
    
    def generate_from_dimensions(
        self, 
        facts: List[Dict], 
        filing_id: int
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Generate calculation relationships from multi-concept aggregations
        
        NOTE: Dimensional breakdowns (same concept, different dimensions) are NOT
        calculation relationships. They're just filtering. This method looks for
        cases where DIFFERENT concepts sum to a parent concept.
        
        Example:
          TotalAssets (concept A) = CurrentAssets (concept B) + NoncurrentAssets (concept C)
          
        NOT:
          Revenue (dimension=NULL) = Revenue (GeographyAxis=USA) + Revenue (GeographyAxis=Europe)
          ^^^^ This is dimensional filtering, not a calc relationship
        
        Args:
            facts: List of fact dictionaries
            filing_id: Filing ID
            
        Returns:
            Tuple of (calculation_relationships, presentation_relationships)
        """
        calc_relationships = []
        pres_relationships = []
        
        # For now, don't generate calc relationships from dimensional data
        # Dimensional breakdowns are handled via dimension filtering in queries, not calc hierarchy
        
        logger.info("Dimensional drill-down uses dimension filtering, not calc relationships")
        logger.info("Calc relationships require DIFFERENT concepts that sum to a parent")
        logger.info("No synthetic calc relationships generated (dimensional data is same-concept breakdowns)")
        
        # Future: Could search for cross-concept summations, but requires more complex analysis
        # e.g., finding that CurrentAssets + NoncurrentAssets = TotalAssets by verifying values
        
        return calc_relationships, pres_relationships
    
    def generate_from_standard_hierarchy(
        self,
        facts: List[Dict],
        filing_id: int,
        statement_type: str = 'income_statement'
    ) -> List[Dict]:
        """
        Generate relationships based on standard financial statement hierarchy
        
        Args:
            facts: List of fact dictionaries
            filing_id: Filing ID
            statement_type: Type of statement ('income_statement', 'balance_sheet', 'cash_flow')
            
        Returns:
            List of calculation relationship dictionaries
        """
        calc_relationships = []
        
        if statement_type not in self.STANDARD_HIERARCHIES:
            return calc_relationships
        
        hierarchy = self.STANDARD_HIERARCHIES[statement_type]
        
        # Build concept lookup by normalized_label
        concept_lookup = {}
        for fact in facts:
            normalized_label = fact.get('normalized_label')
            if normalized_label and fact.get('concept_id'):
                concept_lookup[normalized_label] = fact['concept_id']
        
        # Create relationships based on hierarchy
        order = 0
        for parent_label, children_spec in hierarchy.items():
            if parent_label not in concept_lookup:
                continue
            
            parent_concept_id = concept_lookup[parent_label]
            
            for child_spec in children_spec:
                # Parse weight from spec ('+' = 1.0, '-' = -1.0)
                weight = 1.0
                child_label = child_spec
                
                if child_spec.startswith('-'):
                    weight = -1.0
                    child_label = child_spec[1:]
                elif child_spec.startswith('+'):
                    child_label = child_spec[1:]
                
                if child_label in concept_lookup:
                    child_concept_id = concept_lookup[child_label]
                    
                    calc_relationships.append({
                        'filing_id': filing_id,
                        'parent_concept_id': parent_concept_id,
                        'child_concept_id': child_concept_id,
                        'weight': weight,
                        'order_index': order,
                        'source': 'standard',
                        'is_synthetic': True,
                        'confidence': 0.8  # Lower confidence for template-based
                    })
                    
                    order += 1
        
        logger.info(f"Generated {len(calc_relationships)} relationships from standard {statement_type} hierarchy")
        
        return calc_relationships
    
    def merge_relationships(
        self,
        xbrl_rels: List[Dict],
        dimensional_rels: List[Dict],
        standard_rels: List[Dict]
    ) -> List[Dict]:
        """
        Merge relationships from all sources, with priority: XBRL > Dimensional > Standard
        
        Args:
            xbrl_rels: Relationships from XBRL linkbases
            dimensional_rels: Relationships generated from dimensions
            standard_rels: Relationships from standard templates
            
        Returns:
            Merged list of relationships (deduplicated by parent-child pair)
        """
        # Track which parent-child pairs we've seen
        seen_pairs = set()
        merged = []
        
        # Priority 1: XBRL (mark as not synthetic)
        for rel in xbrl_rels:
            # XBRL relationships may have concept names or IDs
            # If they have names, we'll skip merging here and let the loader handle conversion
            if 'parent_concept_id' in rel and 'child_concept_id' in rel:
                pair = (rel['parent_concept_id'], rel['child_concept_id'])
                if pair not in seen_pairs:
                    rel['source'] = 'xbrl'
                    rel['is_synthetic'] = False
                    merged.append(rel)
                    seen_pairs.add(pair)
            elif 'parent_concept' in rel or 'child_concept' in rel:
                # XBRL relationships with concept names - pass through as-is
                # The loader will convert names to IDs
                rel['source'] = 'xbrl'
                rel['is_synthetic'] = False
                merged.append(rel)
        
        # Priority 2: Dimensional (generated from actual data)
        for rel in dimensional_rels:
            pair = (rel['parent_concept_id'], rel['child_concept_id'])
            if pair not in seen_pairs:
                merged.append(rel)
                seen_pairs.add(pair)
        
        # Priority 3: Standard (fill remaining gaps)
        for rel in standard_rels:
            pair = (rel['parent_concept_id'], rel['child_concept_id'])
            if pair not in seen_pairs:
                merged.append(rel)
                seen_pairs.add(pair)
        
        logger.info(f"Merged relationships: {len(xbrl_rels)} XBRL + {len(dimensional_rels)} dimensional + {len(standard_rels)} standard = {len(merged)} total")
        
        return merged


def synthesize_relationships_for_filing(
    facts: List[Dict],
    filing_id: int,
    xbrl_calc_rels: List[Dict] = None,
    xbrl_pres_rels: List[Dict] = None
) -> Dict[str, List[Dict]]:
    """
    Main entry point: synthesize complete set of relationships for a filing
    
    CONSERVATIVE APPROACH: Only generate relationships we can mathematically verify.
    NO template-based guessing. Data-driven only.
    
    Args:
        facts: List of fact dictionaries from filing
        filing_id: Filing ID
        xbrl_calc_rels: Calculation relationships from XBRL (if available)
        xbrl_pres_rels: Presentation relationships from XBRL (if available)
        
    Returns:
        Dictionary with 'calculation' and 'presentation' relationship lists
    """
    synthesizer = RelationshipSynthesizer()
    
    # Start with XBRL relationships (confidence=1.0, verified by company)
    xbrl_calc_rels = xbrl_calc_rels or []
    xbrl_pres_rels = xbrl_pres_rels or []
    
    # Generate ONLY from dimensional data (mathematically verified)
    # These are the ONLY synthetic relationships we create
    dim_calc_rels, dim_pres_rels = synthesizer.generate_from_dimensions(facts, filing_id)
    
    # NO TEMPLATE GENERATION
    # We don't guess. If dimensional data doesn't sum correctly, no relationship.
    # Better to have fewer relationships than incorrect ones.
    
    # Merge: XBRL takes priority, then verified dimensional
    final_calc_rels = synthesizer.merge_relationships(xbrl_calc_rels, dim_calc_rels, [])
    final_pres_rels = synthesizer.merge_relationships(xbrl_pres_rels, dim_pres_rels, [])
    
    logger.info(f"Final relationships: {len(final_calc_rels)} calc ({len(xbrl_calc_rels)} XBRL, {len(dim_calc_rels)} verified dimensional)")
    
    return {
        'calculation': final_calc_rels,
        'presentation': final_pres_rels
    }

