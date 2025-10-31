#!/usr/bin/env python3
"""
Populate Hierarchical Structure in dim_concepts

Uses XBRL calculation relationships to build parent-child hierarchy.
Calculates aggregated facts when parents are missing but children exist.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from config import DATABASE_URI
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def populate_parent_child_links(engine):
    """
    Populate parent_concept_id and calculation_weight from rel_calculation_hierarchy.
    """
    logger.info("Populating parent-child links from calculation relationships...")
    
    with engine.connect() as conn:
        # For each child in calculation hierarchy, set its parent
        result = conn.execute(text("""
        UPDATE dim_concepts dc
        SET 
            parent_concept_id = rch.parent_concept_id,
            calculation_weight = rch.weight
        FROM rel_calculation_hierarchy rch
        WHERE dc.concept_id = rch.child_concept_id
          AND dc.parent_concept_id IS NULL;  -- Only update if not already set
        """))
        conn.commit()
        
        updated_count = result.rowcount
        logger.info(f"  ✅ Updated {updated_count} concepts with parent links")
        
        return updated_count


def infer_hierarchy_levels(engine):
    """
    Infer hierarchy_level based on position in tree.
    
    Rules:
    - Level 1 (Detail): Has parent, not a parent itself
    - Level 2 (Subtotal): Has parent AND is parent to others
    - Level 3 (Section): Is parent, parent is also parent (2 levels deep)
    - Level 4 (Statement): No parent (top of tree)
    """
    logger.info("Inferring hierarchy levels...")
    
    with engine.connect() as conn:
        # Level 4: Statement totals (no parent)
        conn.execute(text("""
        UPDATE dim_concepts
        SET hierarchy_level = 4
        WHERE parent_concept_id IS NULL
          AND concept_id IN (SELECT DISTINCT parent_concept_id FROM dim_concepts WHERE parent_concept_id IS NOT NULL);
        """))
        conn.commit()
        
        # Level 1: Detail/leaf nodes (has parent, not a parent)
        conn.execute(text("""
        UPDATE dim_concepts
        SET hierarchy_level = 1
        WHERE parent_concept_id IS NOT NULL
          AND concept_id NOT IN (SELECT DISTINCT parent_concept_id FROM dim_concepts WHERE parent_concept_id IS NOT NULL);
        """))
        conn.commit()
        
        # Level 2: Subtotals (has parent AND is a parent)
        conn.execute(text("""
        UPDATE dim_concepts dc
        SET hierarchy_level = 2
        WHERE parent_concept_id IS NOT NULL
          AND concept_id IN (SELECT DISTINCT parent_concept_id FROM dim_concepts WHERE parent_concept_id IS NOT NULL)
          AND (SELECT hierarchy_level FROM dim_concepts WHERE concept_id = dc.parent_concept_id) = 4;
        """))
        conn.commit()
        
        # Level 3: Section totals (parent's parent is statement total)
        conn.execute(text("""
        UPDATE dim_concepts dc
        SET hierarchy_level = 3
        WHERE parent_concept_id IS NOT NULL
          AND concept_id IN (SELECT DISTINCT parent_concept_id FROM dim_concepts WHERE parent_concept_id IS NOT NULL)
          AND (SELECT hierarchy_level FROM dim_concepts WHERE concept_id = dc.parent_concept_id) IN (2, 3);
        """))
        conn.commit()
        
        # Get counts
        result = conn.execute(text("""
        SELECT 
            hierarchy_level,
            COUNT(*) as count
        FROM dim_concepts
        WHERE hierarchy_level IS NOT NULL
        GROUP BY hierarchy_level
        ORDER BY hierarchy_level;
        """))
        
        for row in result:
            level_name = {1: 'Detail', 2: 'Subtotal', 3: 'Section', 4: 'Statement'}.get(row[0], 'Unknown')
            logger.info(f"  Level {row[0]} ({level_name}): {row[1]} concepts")


def calculate_missing_parent_facts(engine):
    """
    Calculate and insert parent facts when company reports children but not parent.
    
    Only calculates when:
    1. Parent concept exists in dim_concepts
    2. Children exist with values for this company/period
    3. Parent fact doesn't already exist (is_calculated=FALSE)
    
    Validates: If parent IS reported, verify calculated = reported (within 1%)
    """
    logger.info("Calculating missing parent facts from children...")
    
    with engine.connect() as conn:
        # Find all (company, period, parent_concept) combinations where:
        # - Children have values
        # - Parent fact is missing
        query = text("""
        WITH parent_children AS (
            SELECT DISTINCT
                dc_parent.concept_id as parent_concept_id,
                dc_parent.concept_name as parent_name,
                dc_child.concept_id as child_concept_id,
                dc_child.calculation_weight as child_weight
            FROM dim_concepts dc_parent
            JOIN dim_concepts dc_child ON dc_child.parent_concept_id = dc_parent.concept_id
            WHERE dc_parent.parent_concept_id IS NOT NULL  -- Not statement totals
        ),
        missing_parents AS (
            SELECT DISTINCT
                f.company_id,
                f.period_id,
                f.filing_id,
                pc.parent_concept_id,
                pc.parent_name
            FROM fact_financial_metrics f
            JOIN parent_children pc ON f.concept_id = pc.child_concept_id
            WHERE f.dimension_id IS NULL
              AND f.value_numeric IS NOT NULL
              -- Parent fact doesn't exist for this company/period
              AND NOT EXISTS (
                  SELECT 1
                  FROM fact_financial_metrics fp
                  WHERE fp.company_id = f.company_id
                    AND fp.period_id = f.period_id
                    AND fp.concept_id = pc.parent_concept_id
                    AND fp.dimension_id IS NULL
              )
            GROUP BY f.company_id, f.period_id, f.filing_id, pc.parent_concept_id, pc.parent_name
        )
        SELECT * FROM missing_parents
        LIMIT 100;  -- Process in batches
        """)
        
        missing = conn.execute(query).fetchall()
        
        logger.info(f"  Found {len(missing)} missing parent facts to calculate")
        
        calculated_count = 0
        validation_errors = []
        
        for company_id, period_id, filing_id, parent_concept_id, parent_name in missing:
            # Get children for this parent
            children_query = text("""
            SELECT 
                dc.concept_id,
                dc.calculation_weight,
                f.value_numeric
            FROM dim_concepts dc
            JOIN fact_financial_metrics f ON f.concept_id = dc.concept_id
            WHERE dc.parent_concept_id = :parent_concept_id
              AND f.company_id = :company_id
              AND f.period_id = :period_id
              AND f.dimension_id IS NULL
              AND f.value_numeric IS NOT NULL;
            """)
            
            children = conn.execute(children_query, {
                'parent_concept_id': parent_concept_id,
                'company_id': company_id,
                'period_id': period_id
            }).fetchall()
            
            if not children:
                continue
            
            # Calculate parent value
            calculated_value = sum([child[2] * child[1] for child in children])
            
            # Insert calculated fact
            insert_query = text("""
            INSERT INTO fact_financial_metrics (
                company_id, concept_id, period_id, filing_id, dimension_id,
                value_numeric, is_calculated, extraction_method
            ) VALUES (
                :company_id, :concept_id, :period_id, :filing_id, NULL,
                :value_numeric, TRUE, 'calculated_from_children'
            )
            ON CONFLICT (filing_id, concept_id, period_id, dimension_id) DO UPDATE
            SET value_numeric = EXCLUDED.value_numeric,
                is_calculated = TRUE;
            """)
            
            conn.execute(insert_query, {
                'company_id': company_id,
                'concept_id': parent_concept_id,
                'period_id': period_id,
                'filing_id': filing_id,
                'value_numeric': calculated_value
            })
            conn.commit()
            
            calculated_count += 1
        
        logger.info(f"  ✅ Calculated {calculated_count} parent facts")
        
        if validation_errors:
            logger.error(f"  ❌ {len(validation_errors)} validation errors:")
            for err in validation_errors[:10]:
                logger.error(f"     {err}")


def validate_parent_child_sums(engine):
    """
    Validate that reported parents match calculated parents (within 1%).
    
    Checks cases where:
    - Parent fact exists (reported in filing)
    - Children also exist
    - Calculate sum of children and compare to reported parent
    
    Returns: List of validation errors (parent ≠ sum of children)
    """
    logger.info("Validating parent-child summations...")
    
    with engine.connect() as conn:
        query = text("""
        WITH parent_reported AS (
            SELECT 
                f.company_id,
                f.period_id,
                f.concept_id as parent_concept_id,
                f.value_numeric as reported_value,
                dc.concept_name as parent_name
            FROM fact_financial_metrics f
            JOIN dim_concepts dc ON f.concept_id = dc.concept_id
            WHERE f.dimension_id IS NULL
              AND f.is_calculated = FALSE  -- Reported, not calculated
              AND f.value_numeric IS NOT NULL
              AND dc.concept_id IN (SELECT DISTINCT parent_concept_id FROM dim_concepts WHERE parent_concept_id IS NOT NULL)
        ),
        children_sum AS (
            SELECT 
                f.company_id,
                f.period_id,
                dc.parent_concept_id,
                SUM(f.value_numeric * dc.calculation_weight) as calculated_value
            FROM fact_financial_metrics f
            JOIN dim_concepts dc ON f.concept_id = dc.concept_id
            WHERE f.dimension_id IS NULL
              AND f.value_numeric IS NOT NULL
              AND dc.parent_concept_id IS NOT NULL
            GROUP BY f.company_id, f.period_id, dc.parent_concept_id
        )
        SELECT 
            c.ticker,
            pr.parent_name,
            t.fiscal_year,
            pr.reported_value,
            cs.calculated_value,
            ABS(pr.reported_value - cs.calculated_value) / NULLIF(pr.reported_value, 0) * 100 as diff_pct
        FROM parent_reported pr
        JOIN children_sum cs ON 
            pr.company_id = cs.company_id AND
            pr.period_id = cs.period_id AND
            pr.parent_concept_id = cs.parent_concept_id
        JOIN dim_companies c ON pr.company_id = c.company_id
        JOIN dim_time_periods t ON pr.period_id = t.period_id
        WHERE ABS(pr.reported_value - cs.calculated_value) / NULLIF(pr.reported_value, 0) * 100 > 1.0  -- More than 1% off
        ORDER BY diff_pct DESC
        LIMIT 20;
        """)
        
        errors = conn.execute(query).fetchall()
        
        if errors:
            logger.error(f"  ❌ Found {len(errors)} validation errors:")
            for err in errors[:10]:
                logger.error(
                    f"     {err[0]} {err[1]} FY{err[2]}: "
                    f"Reported=${err[3]:,.0f}, Calculated=${err[4]:,.0f} ({err[5]:.2f}% diff)"
                )
            return errors
        else:
            logger.info("  ✅ All parent-child summations validated (< 1% difference)")
            return []


def main():
    engine = create_engine(DATABASE_URI)
    
    # Step 1: Populate parent-child links
    updated = populate_parent_child_links(engine)
    
    if updated == 0:
        logger.warning("No calculation relationships found. Hierarchy cannot be built.")
        logger.warning("Ensure XBRL files include calculation linkbases or download complete packages.")
        return
    
    # Step 2: Infer hierarchy levels
    infer_hierarchy_levels(engine)
    
    # Step 3: Calculate missing parent facts
    calculate_missing_parent_facts(engine)
    
    # Step 4: Validate
    errors = validate_parent_child_sums(engine)
    
    if errors:
        logger.error(f"\n❌ Hierarchy population FAILED: {len(errors)} validation errors")
        logger.error("   Parent values don't match sum of children")
        logger.error("   This indicates incorrect calculation relationships or data quality issues")
        return 1
    
    logger.info("\n✅ Hierarchy population complete - all validations passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())

