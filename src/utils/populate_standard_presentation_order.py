#!/usr/bin/env python3
"""
Populate standard presentation hierarchy for concepts missing XBRL presentation order.

This ensures ALL concepts have proper ordering for financial statement presentation,
using standard accounting templates when XBRL presentation hierarchy is missing.

SOLUTION: Two-Tier Presentation Hierarchy
- Tier 1: XBRL Presentation Hierarchy (from rel_presentation_hierarchy, source='xbrl')
- Tier 2: Standard Accounting Templates (synthetic, source='standard')
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from config import DATABASE_URI
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Comprehensive standard templates with sections and order
# Based on IFRS/US-GAAP standard practices
STANDARD_TEMPLATES = {
    'balance_sheet': {
        'sections': {
            'noncurrent_assets': {
                'order': 1,
                'items': {
                    'intangible_assets': 1,
                    'property_plant_equipment': 2,
                    'investments_in_associated_companies': 3,
                    'investments_associated': 3,
                    'deferred_tax_assets': 4,
                    'deferred_income_tax_assets': 4,
                    'other_receivables_and_prepayments': 5,
                    'other_financial_assets': 6,
                    'other_noncurrent_assets': 7,
                    'noncurrent_assets': 8,  # Section total
                    'total_noncurrent_assets': 8,
                }
            },
            'current_assets': {
                'order': 2,
                'items': {
                    'inventory': 1,
                    'inventories': 1,
                    'trade_receivables': 2,
                    'accounts_receivable': 2,
                    'tax_receivables': 3,
                    'other_receivables_and_prepayments': 4,
                    'marketable_securities': 5,
                    'derivative_financial_instruments': 6,
                    'cash_and_equivalents': 7,
                    'cash_at_bank': 7,
                    'cash': 7,
                    'current_assets': 8,  # Section total
                    'total_current_assets': 8,
                }
            },
            'equity': {
                'order': 3,
                'items': {
                    'share_capital': 1,
                    'common_stock': 1,
                    'treasury_shares': 2,
                    'retained_earnings': 3,
                    'other_reserves': 4,
                    'accumulated_other_comprehensive_income': 4,
                    'total_equity': 5,  # Section total
                    'stockholders_equity': 5,
                }
            },
            'noncurrent_liabilities': {
                'order': 4,
                'items': {
                    'borrowings': 1,
                    'long_term_debt': 1,
                    'deferred_tax_liabilities': 2,
                    'deferred_income_tax_liabilities': 2,
                    'retirement_benefit_obligations': 3,
                    'other_liabilities': 4,
                    'provisions_noncurrent': 5,
                    'provisions': 5,
                    'noncurrent_liabilities': 6,  # Section total
                    'total_noncurrent_liabilities': 6,
                }
            },
            'current_liabilities': {
                'order': 5,
                'items': {
                    'borrowings': 1,
                    'short_term_debt': 1,
                    'trade_payables': 2,
                    'accounts_payable': 2,
                    'tax_payables': 3,
                    'other_liabilities': 4,
                    'derivative_financial_instruments': 5,
                    'provisions': 6,
                    'current_liabilities': 7,  # Section total
                    'total_current_liabilities': 7,
                }
            },
            'totals': {
                'order': 6,
                'items': {
                    'total_assets': 1,
                    'total_liabilities': 2,
                    'total_liabilities_and_equity': 3,
                }
            }
        }
    },
    'income_statement': {
        'sections': {
            'revenue': {
                'order': 1,
                'items': {
                    'revenue': 1,
                    'revenues': 1,
                    'net_sales': 1,
                    'sales_revenue': 1,
                    'sales_revenue_goods_gross': 1,
                    'revenue_from_contracts': 1,
                    'revenue_from_sale_of_goods': 1,
                    'other_revenue': 2,
                }
            },
            'costs': {
                'order': 2,
                'items': {
                    'cost_of_sales': 1,
                    'cost_of_revenue': 1,
                    'cost_of_goods_and_services_sold': 1,
                    'cost_of_goods_sold': 1,
                }
            },
            'gross_profit': {
                'order': 3,
                'items': {
                    'gross_profit': 1,
                }
            },
            'operating_expenses': {
                'order': 4,
                'items': {
                    'selling_expense_and_distribution_costs': 1,
                    'sales_and_distribution_costs': 1,
                    'selling_general_admin': 1,
                    'sales_marketing': 1,
                    'research_development': 2,
                    'research_and_development': 2,
                    'administrative_expense': 3,
                    'administrative_costs': 3,
                    'general_administrative': 3,
                    'other_operating_income_expense': 4,
                    'other_operating_income': 4,
                    'other_operating_expenses': 4,
                }
            },
            'operating_income': {
                'order': 5,
                'items': {
                    'operating_income': 1,
                    'operating_profit': 1,
                }
            },
            'financial_items': {
                'order': 6,
                'items': {
                    'finance_income': 1,
                    'financial_income': 1,
                    'interest_income': 1,
                    'finance_costs': 2,
                    'financial_expenses': 2,
                    'interest_expense': 2,
                }
            },
            'income_before_tax': {
                'order': 7,
                'items': {
                    'income_before_tax': 1,
                    'profit_before_tax': 1,
                    'profit_before_income_taxes': 1,
                }
            },
            'tax': {
                'order': 8,
                'items': {
                    'income_tax_expense_continuing_operations': 1,
                    'income_tax_expense': 1,
                    'income_tax': 1,
                    'income_taxes': 1,
                    'tax_expense': 1,
                }
            },
            'net_income': {
                'order': 9,
                'items': {
                    'net_income_including_noncontrolling_interest': 1,
                    'net_income': 1,
                    'net_profit': 1,
                    'net_income_to_common': 2,
                }
            },
            'eps': {
                'order': 10,
                'items': {
                    'basic_earnings_loss_per_share': 1,
                    'basic_earnings_per_share': 1,
                    'eps_basic': 1,
                    'diluted_earnings_loss_per_share': 2,
                    'diluted_earnings_per_share': 2,
                    'eps_diluted': 2,
                    'shares_basic': 3,
                    'shares_diluted': 4,
                }
            }
        }
    },
    'comprehensive_income': {
        'sections': {
            'net_profit': {
                'order': 1,
                'items': {
                    'net_profit': 1,
                    'net_income': 1,
                }
            },
            'oci_not_reclassified': {
                'order': 2,
                'items': {
                    'remeasurements_of_retirement_benefit_obligations': 1,
                    'other_comprehensive_income_that_will_not_be_reclassified_to_profit_or_loss_before_tax': 2,
                    'items_that_will_not_be_reclassified_subsequently_to_the_income_statement': 2,
                }
            },
            'oci_reclassified': {
                'order': 3,
                'items': {
                    'exchange_rate_adjustments_of_investments_in_subsidiaries': 1,
                    'cash_flow_hedges': 2,
                    'realisation_of_previously_deferred_gains_losses': 3,
                    'deferred_gains_losses_related_to_acquisition_of_businesses': 4,
                    'deferred_gains_losses_on_hedges_open_at_year_end': 5,
                    'tax_and_other_items': 6,
                    'other_comprehensive_income_that_will_be_reclassified_to_profit_or_loss_net_of_tax': 7,
                    'items_that_will_be_reclassified_subsequently_to_the_income_statement': 7,
                }
            },
            'oci_total': {
                'order': 4,
                'items': {
                    'other_comprehensive_income': 1,
                    'oci_total': 1,
                }
            },
            'total_comprehensive_income': {
                'order': 5,
                'items': {
                    'total_comprehensive_income': 1,
                }
            }
        }
    },
    'cash_flow': {
        'sections': {
            'operating_activities': {
                'order': 1,
                'items': {
                    'net_income': 1,
                    'depreciation_amortization': 2,
                    'depreciation_and_amortization': 2,
                    'stock_based_compensation': 3,
                    'change_in_working_capital': 4,
                    'change_in_receivables': 5,
                    'change_in_inventory': 6,
                    'change_in_payables': 7,
                    'interest_received': 8,
                    'interest_paid': 9,
                    'income_taxes_paid': 10,
                    'operating_cash_flow': 11,  # Section total
                }
            },
            'investing_activities': {
                'order': 2,
                'items': {
                    'capex': 1,
                    'capital_expenditures': 1,
                    'purchase_of_property_plant_equipment': 1,
                    'purchase_of_intangible_assets': 2,
                    'acquisition_of_businesses': 3,
                    'purchase_of_investments': 4,
                    'sale_of_investments': 5,
                    'investing_cash_flow': 6,  # Section total
                }
            },
            'financing_activities': {
                'order': 3,
                'items': {
                    'dividends_paid': 1,
                    'stock_repurchased': 2,
                    'proceeds_from_borrowings': 3,
                    'repayment_of_borrowings': 4,
                    'proceeds_from_equity': 5,
                    'financing_cash_flow': 6,  # Section total
                }
            },
            'net_change': {
                'order': 4,
                'items': {
                    'net_change_in_cash': 1,
                    'cash_at_beginning': 2,
                    'cash_at_end': 3,
                }
            }
        }
    }
}


def get_template_order(normalized_label: str, statement_type: str) -> tuple[str, int] | None:
    """
    Get section and order_index from standard template.
    
    Uses exact matching first, then fuzzy matching for variations.
    
    Returns:
        (section_name, order_index) or None if not found in templates
    """
    if statement_type not in STANDARD_TEMPLATES:
        return None
    
    template = STANDARD_TEMPLATES[statement_type]
    label_lower = normalized_label.lower()
    
    # Search through all sections
    for section_name, section_data in template['sections'].items():
        # First try exact match
        if normalized_label in section_data['items']:
            item_order = section_data['items'][normalized_label]
            section_order = section_data['order']
            combined_order = section_order * 1000 + item_order
            return (section_name, combined_order)
        
        # Then try fuzzy matching - but only for main statement items
        # Exclude disclosure items, policy notes, descriptions, etc.
        if any(exclude_term in label_lower for exclude_term in [
            'description_of_accounting_policy', 'policy', 'disclosure', 'note',
            'explanatory', 'reconciliation', 'adjustment', 'reconcile',
            'tax_rate_effect', 'effective_tax_rate', 'statutory_tax_rate',
            'percentage', 'percent', 'ratio', 'growth_percent',
            'classified_as', '_paid', '_received', '_current_period',
            '_prior_period', '_gross', '_net', '_detail', '_breakdown',
            '_component', '_other', 'auditors_remuneration', 'professional_fees',
            'provisions_for', 'discount_rate', 'deferred_tax_expense_income_recognised'
        ]):
            return None
        
        for template_key, item_order in section_data['items'].items():
            template_key_lower = template_key.lower()
            # Only match if template key is the PRIMARY part of the label (starts with or is the main term)
            # Not just contained anywhere (which would match "description_of_accounting_policy_for_revenue" to "revenue")
            if (template_key_lower == label_lower or 
                label_lower.startswith(template_key_lower + '_') or
                label_lower.endswith('_' + template_key_lower) or
                ('_' + template_key_lower + '_' in label_lower)):
                section_order = section_data['order']
                combined_order = section_order * 1000 + item_order
                return (section_name, combined_order)
    
    return None


def populate_standard_presentation_order(engine):
    """
    Populate standard presentation hierarchy for concepts missing XBRL order.
    
    Strategy:
    1. For each filing, find concepts that have facts but no presentation hierarchy
    2. Apply standard templates based on normalized_label and statement_type
    3. Insert synthetic presentation hierarchy relationships with source='standard'
    """
    logger.info("Populating standard presentation order for concepts missing XBRL hierarchy...")
    
    with engine.connect() as conn:
        # Get all filings
        filings_result = conn.execute(text("""
            SELECT DISTINCT f.filing_id, f.company_id, c.ticker
            FROM dim_filings f
            JOIN dim_companies c ON f.company_id = c.company_id
            ORDER BY f.filing_id
        """))
        filings = filings_result.fetchall()
        
        logger.info(f"Processing {len(filings)} filings...")
        
        total_inserted = 0
        
        for filing_id, company_id, ticker in filings:
            # Find concepts in this filing that don't have presentation hierarchy
            concepts_result = conn.execute(text("""
                SELECT DISTINCT
                    co.concept_id,
                    co.normalized_label,
                    co.statement_type,
                    co.parent_concept_id
                FROM fact_financial_metrics fm
                JOIN dim_concepts co ON fm.concept_id = co.concept_id
                WHERE fm.filing_id = :filing_id
                  AND fm.dimension_id IS NULL  -- Only consolidated facts
                  AND co.normalized_label IS NOT NULL
                  AND co.statement_type IN ('income_statement', 'balance_sheet', 'cash_flow')
                  AND NOT EXISTS (
                      SELECT 1 
                      FROM rel_presentation_hierarchy ph
                      WHERE ph.filing_id = :filing_id
                        AND ph.child_concept_id = co.concept_id
                  )
                ORDER BY co.statement_type, co.normalized_label
            """), {'filing_id': filing_id})
            
            concepts = concepts_result.fetchall()
            
            if not concepts:
                continue
            
            inserted_count = 0
            
            for concept_id, normalized_label, statement_type, parent_concept_id in concepts:
                # Get template order
                template_result = get_template_order(normalized_label, statement_type)
                
                if template_result is None:
                    # Not in template - skip (will be handled by fallback in UI)
                    continue
                
                section_name, order_index = template_result
                
                # Insert synthetic presentation hierarchy relationship
                try:
                    conn.execute(text("""
                        INSERT INTO rel_presentation_hierarchy (
                            filing_id,
                            parent_concept_id,
                            child_concept_id,
                            order_index,
                            statement_type,
                            source,
                            is_synthetic,
                            priority
                        ) VALUES (
                            :filing_id,
                            :parent_concept_id,
                            :child_concept_id,
                            :order_index,
                            :statement_type,
                            'standard',
                            TRUE,
                            0
                        )
                        ON CONFLICT (filing_id, parent_concept_id, child_concept_id, order_index) DO NOTHING
                    """), {
                        'filing_id': filing_id,
                        'parent_concept_id': parent_concept_id,
                        'child_concept_id': concept_id,
                        'order_index': order_index,
                        'statement_type': statement_type
                    })
                    inserted_count += 1
                except Exception as e:
                    logger.warning(f"Failed to insert presentation hierarchy for {normalized_label}: {e}")
                    continue
            
            if inserted_count > 0:
                conn.commit()
                total_inserted += inserted_count
                logger.info(f"  {ticker}: Inserted {inserted_count} standard presentation relationships")
        
        logger.info(f"✅ Total: Inserted {total_inserted:,} standard presentation relationships")
        
        # Show statistics
        stats_result = conn.execute(text("""
            SELECT 
                source,
                COUNT(*) as count
            FROM rel_presentation_hierarchy
            GROUP BY source
            ORDER BY source
        """))
        
        logger.info("\nPresentation hierarchy sources:")
        for source, count in stats_result:
            logger.info(f"  {source}: {count:,} relationships")


def main():
    engine = create_engine(DATABASE_URI)
    populate_standard_presentation_order(engine)
    return 0


if __name__ == '__main__':
    sys.exit(main())

