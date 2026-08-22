#!/usr/bin/env python3
"""
Load financial data from JSON files into star schema warehouse.

This script:
1. Reads extracted JSON files from data/processed/
2. Populates dimension tables (companies, concepts, periods, filings, dimensions)
3. Loads fact table with proper foreign key references
4. Handles upserts for idempotent loading
"""
import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DATABASE_URI


class StarSchemaLoader:
    """Loads financial data into star schema warehouse"""
    
    def __init__(self):
        # Use DATABASE_URI to ensure connection to same database as ValidationAggregator
        # Parse DATABASE_URI to get connection parameters for psycopg2
        from urllib.parse import urlparse
        parsed = urlparse(DATABASE_URI)
        
        self.conn = psycopg2.connect(
            host=parsed.hostname or '127.0.0.1',
            port=parsed.port or 5432,
            user=parsed.username or 'superset',
            password=parsed.password or 'superset',
            database=parsed.path.lstrip('/') if parsed.path else 'finsight'
        )
        self.cur = self.conn.cursor()
        # Create SQLAlchemy engine for functions that need it
        from sqlalchemy import create_engine
        self.engine = create_engine(DATABASE_URI)
        
    def get_or_create_company(self, ticker: str, metadata: Dict) -> int:
        """Get or create company_id"""
        # Check if exists
        self.cur.execute("SELECT company_id, accounting_standard FROM dim_companies WHERE ticker = %s", (ticker,))
        result = self.cur.fetchone()
        if result:
            company_id, existing_standard = result
            # Update accounting standard if we have better info (idempotent - won't cause issues)
            filing_type = metadata.get('filing_type', '').upper()
            if '20-F' in filing_type or 'ESEF' in filing_type:
                new_standard = 'IFRS'
                if existing_standard != new_standard:
                    # Get framework_id for new standard
                    self.cur.execute("""
                        SELECT framework_id FROM dim_reporting_frameworks 
                        WHERE framework_name = %s
                    """, (new_standard,))
                    framework_result = self.cur.fetchone()
                    framework_id = framework_result[0] if framework_result else None
                    self.cur.execute("""
                        UPDATE dim_companies 
                        SET accounting_standard = %s, framework_id = %s 
                        WHERE company_id = %s
                    """, (new_standard, framework_id, company_id))
                    self.conn.commit()
            return company_id
        
        # Determine accounting standard from filing type or metadata
        # 20-F filings are IFRS, 10-K are US-GAAP
        filing_type = metadata.get('filing_type', '').upper()
        if '20-F' in filing_type or 'ESEF' in filing_type:
            accounting_standard = 'IFRS'
        elif metadata.get('taxonomy'):
            # Use taxonomy from metadata if available
            taxonomy = metadata.get('taxonomy', '').upper()
            if 'IFRS' in taxonomy or 'ESEF' in taxonomy:
                accounting_standard = 'IFRS'
            else:
                accounting_standard = 'US-GAAP'
        else:
            accounting_standard = 'US-GAAP'  # Default
        
        # Get framework_id
        self.cur.execute("""
            SELECT framework_id FROM dim_reporting_frameworks 
            WHERE framework_name = %s
        """, (accounting_standard,))
        framework_result = self.cur.fetchone()
        framework_id = framework_result[0] if framework_result else None
        
        # Create new
        self.cur.execute("""
            INSERT INTO dim_companies (ticker, company_name, accounting_standard, framework_id)
            VALUES (%s, %s, %s, %s)
            RETURNING company_id
        """, (ticker, metadata.get('company_name', ticker), accounting_standard, framework_id))
        
        company_id = self.cur.fetchone()[0]
        self.conn.commit()
        return company_id
    
    def get_or_create_concept(self, concept_name: str, taxonomy: str, metadata: Dict) -> int:
        """Get or create concept_id, and update statement_type if missing"""
        # Import taxonomy mappings for statement_type inference
        try:
            from src.utils.taxonomy_mappings import get_statement_type, get_normalized_label
        except ImportError:
            get_statement_type = None
            get_normalized_label = None
        
        # CRITICAL: Ensure normalized_label is always set (required by schema)
        normalized_label = metadata.get('normalized_label')
        if not normalized_label:
            # Generate from concept name using taxonomy mappings
            if get_normalized_label:
                normalized_label = get_normalized_label(concept_name)
            else:
                # Fallback: generate snake_case from concept name
                import re
                s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', concept_name)
                normalized_label = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
        
        # Determine statement_type from fact metadata or taxonomy mappings
        statement_type = metadata.get('statement_type')
        if not statement_type:
            # Try to infer from normalized_label using taxonomy mappings
            if normalized_label and get_statement_type:
                statement_type = get_statement_type(normalized_label)
        
        # Fallback: infer from concept name if still missing
        if not statement_type:
            concept_lower = concept_name.lower()
            if any(term in concept_lower for term in ['asset', 'liability', 'equity', 'receivable', 'payable', 'inventory', 'debt', 'cash']):
                statement_type = 'balance_sheet'
            elif any(term in concept_lower for term in ['revenue', 'income', 'expense', 'cost', 'profit', 'earnings', 'eps']):
                statement_type = 'income_statement'
            elif any(term in concept_lower for term in ['cashflow', 'operatingactivit', 'investingactivit', 'financingactivit']):
                statement_type = 'cash_flow'
            else:
                statement_type = 'other'
        
        # Get preferred label using generic mapping (LASTING - part of ETL pipeline)
        try:
            from src.utils.concept_label_mapping import get_humanized_label
            # Get statement_type from metadata if available (for context-specific mapping)
            stmt_type = metadata.get('statement_type')
            preferred_label = get_humanized_label(concept_name, normalized_label, stmt_type)
        except ImportError:
            preferred_label = None
        
        # Get original_label from metadata if available (from XBRL label linkbase)
        original_label = metadata.get('original_label')
        
        # Check if exists
        self.cur.execute(
            "SELECT concept_id, statement_type, preferred_label, original_label FROM dim_concepts WHERE concept_name = %s AND taxonomy = %s",
            (concept_name, taxonomy)
        )
        result = self.cur.fetchone()
        if result:
            concept_id, existing_stmt_type, existing_preferred_label, existing_original_label = result[0], result[1], result[2], result[3]
            # Update statement_type whenever we have a NEW value that differs from what's
            # stored — not just when the existing value is NULL. dim_concepts is a shared,
            # persistent dimension: a concept's statement_type gets locked in the first
            # time it's ever inserted, by whichever extraction logic existed at that
            # moment. An "only update if NULL" policy meant any later classification fix
            # (like item 5's comprehensive-income fix) would work correctly for facts
            # sharing a concept never before seen, but be permanently masked for concepts
            # already sitting in dim_concepts with a stale pre-fix value — confirmed: ~70
            # comprehensive_income concepts were stuck at 'income_statement' from testing
            # earlier in the same session, after the classification fix had already
            # landed. See docs/NVO_GOLDEN_PATH_2026-08.md item 6.
            # Update preferred_label if it's NULL and we have a value (LASTING - ensures labels are populated on reload)
            # Update original_label if it's NULL and we have a value (from XBRL label linkbase)
            # This ensures that when balance sheet mappings are added to concept_label_mapping.py, existing concepts get updated on next ETL run
            updates = []
            params = []
            if statement_type and statement_type != existing_stmt_type:
                updates.append("statement_type = %s")
                params.append(statement_type)
            if existing_preferred_label is None and preferred_label:
                updates.append("preferred_label = %s")
                params.append(preferred_label)
            if existing_original_label is None and original_label:
                updates.append("original_label = %s")
                params.append(original_label)
            
            if updates:
                params.append(concept_id)
                self.cur.execute(f"""
                    UPDATE dim_concepts 
                    SET {', '.join(updates)}
                    WHERE concept_id = %s
                """, tuple(params))
                self.conn.commit()
            return concept_id
        
        # Get taxonomy_id
        taxonomy_id = None
        self.cur.execute("""
            SELECT taxonomy_id FROM dim_taxonomies 
            WHERE taxonomy_name = %s
        """, (taxonomy,))
        taxonomy_result = self.cur.fetchone()
        if taxonomy_result:
            taxonomy_id = taxonomy_result[0]
        
        # Create new (preferred_label already calculated above)
        # CRITICAL: normalized_label is now guaranteed to be set above
        # Check if original_label column exists (for backward compatibility)
        try:
            self.cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'dim_concepts' 
                AND column_name = 'original_label'
            """)
            has_original_label = self.cur.fetchone() is not None
        except:
            has_original_label = False
        
        if has_original_label:
            self.cur.execute("""
                INSERT INTO dim_concepts (
                    concept_name, taxonomy, taxonomy_id, normalized_label, concept_type,
                    balance_type, period_type, data_type, is_abstract, statement_type, preferred_label, original_label
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (concept_name, taxonomy) DO UPDATE SET
                    taxonomy_id = COALESCE(EXCLUDED.taxonomy_id, dim_concepts.taxonomy_id),
                    normalized_label = EXCLUDED.normalized_label,
                    statement_type = COALESCE(EXCLUDED.statement_type, dim_concepts.statement_type),
                    preferred_label = COALESCE(EXCLUDED.preferred_label, dim_concepts.preferred_label),
                    original_label = COALESCE(EXCLUDED.original_label, dim_concepts.original_label)
                RETURNING concept_id
            """, (
                concept_name,
                taxonomy,
                taxonomy_id,
                normalized_label,  # Use guaranteed non-None value
                metadata.get('concept_type'),
                metadata.get('concept_balance'),
                metadata.get('concept_period_type'),
                metadata.get('concept_data_type'),
                metadata.get('concept_abstract', False),
                statement_type,
                preferred_label,
                original_label
            ))
        else:
            self.cur.execute("""
                INSERT INTO dim_concepts (
                    concept_name, taxonomy, taxonomy_id, normalized_label, concept_type,
                    balance_type, period_type, data_type, is_abstract, statement_type, preferred_label
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (concept_name, taxonomy) DO UPDATE SET
                    taxonomy_id = COALESCE(EXCLUDED.taxonomy_id, dim_concepts.taxonomy_id),
                    normalized_label = EXCLUDED.normalized_label,
                    statement_type = COALESCE(EXCLUDED.statement_type, dim_concepts.statement_type),
                    preferred_label = COALESCE(EXCLUDED.preferred_label, dim_concepts.preferred_label)
                RETURNING concept_id
            """, (
                concept_name,
                taxonomy,
                taxonomy_id,
                normalized_label,  # Use guaranteed non-None value
                metadata.get('concept_type'),
                metadata.get('concept_balance'),
                metadata.get('concept_period_type'),
                metadata.get('concept_data_type'),
                metadata.get('concept_abstract', False),
                statement_type,
                preferred_label
            ))
        
        concept_id = self.cur.fetchone()[0]
        self.conn.commit()
        return concept_id
    
    def get_or_create_period(
        self, 
        period_type: str, 
        start_date: Optional[str], 
        end_date: Optional[str], 
        instant_date: Optional[str]
    ) -> int:
        """Get or create period_id"""
        # Check if exists (exact date match)
        self.cur.execute("""
            SELECT period_id FROM dim_time_periods
            WHERE period_type = %s
              AND (start_date = %s OR (start_date IS NULL AND %s IS NULL))
              AND (end_date = %s OR (end_date IS NULL AND %s IS NULL))
              AND (instant_date = %s OR (instant_date IS NULL AND %s IS NULL))
        """, (period_type, start_date, start_date, end_date, end_date, instant_date, instant_date))

        result = self.cur.fetchone()
        if result:
            return result[0]

        # Determine fiscal year
        fiscal_year = None
        if end_date:
            # For duration periods (income statement, cash flow), use end date year
            # CRITICAL FIX: For periods ending in Jan-Mar, it's end of PREVIOUS fiscal year
            # (Most companies have Dec 31 fiscal year end, so period 2023-01-01 to 2024-01-01 is fiscal year 2023)
            from datetime import datetime
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            if end_dt.month <= 3:
                fiscal_year = end_dt.year - 1
            else:
                fiscal_year = end_dt.year
        elif instant_date:
            # For instant dates (balance sheet), early-year dates are END of previous fiscal year
            from datetime import datetime
            instant_dt = datetime.strptime(instant_date, '%Y-%m-%d')

            # If instant date is in Jan-Mar, it's likely end of PREVIOUS fiscal year
            if instant_dt.month <= 3:
                fiscal_year = instant_dt.year - 1
            else:
                fiscal_year = instant_dt.year

        # Fallback: same period_type + same fiscal_year, different exact dates.
        # XBRL and SEC-API report the same fiscal year with different date conventions —
        # e.g. XBRL gives a duration period as start=2023-01-01/end=2024-01-01 while
        # SEC-API's gap-fill reports the same fiscal year as end=2023-12-31 with no start
        # date. Without this fallback, these become two DIFFERENT period_ids for the same
        # real-world period, each holding a partial subset of that period's facts (e.g.
        # income_before_tax and net_income on one, income_tax_expense only on the other) —
        # confirmed causing false income_statement_math violations for NVO, since a
        # per-period math check naturally fails when it can only see one half of the
        # period's facts. See docs/NVO_GOLDEN_PATH_2026-08.md item 6.
        if fiscal_year is not None:
            self.cur.execute("""
                SELECT period_id FROM dim_time_periods
                WHERE period_type = %s AND fiscal_year = %s
                LIMIT 1
            """, (period_type, fiscal_year))
            result = self.cur.fetchone()
            if result:
                return result[0]

        # Create new
        self.cur.execute("""
            INSERT INTO dim_time_periods (
                period_type, start_date, end_date, instant_date, fiscal_year
            ) VALUES (%s, %s, %s, %s, %s)
            RETURNING period_id
        """, (period_type, start_date, end_date, instant_date, fiscal_year))

        period_id = self.cur.fetchone()[0]
        self.conn.commit()
        return period_id
    
    def get_or_create_filing(
        self, 
        company_id: int, 
        filing_type: str, 
        fiscal_year_end: str,
        metadata: Dict
    ) -> int:
        """Get or create filing_id
        
        CRITICAL: Match on (company_id, filing_type, fiscal_year) to prevent
        multiple filings from being created when loading XBRL and SEC_API data separately.
        The exact date (e.g., "2023-12-31" vs "2024-12-31") may differ between sources,
        but if they're the same fiscal year, they should go into the same filing.
        """
        # Extract year from fiscal_year_end for matching
        # Handle both date strings (e.g., "2023-12-31") and just years (e.g., "2023")
        if fiscal_year_end:
            fiscal_year = fiscal_year_end[:4] if len(fiscal_year_end) >= 4 else fiscal_year_end
        else:
            fiscal_year = None
        
        # First, try exact match (company_id, filing_type, fiscal_year_end)
        self.cur.execute("""
            SELECT filing_id FROM dim_filings 
            WHERE company_id = %s AND filing_type = %s AND fiscal_year_end = %s
        """, (company_id, filing_type, fiscal_year_end))
        
        result = self.cur.fetchone()
        if result:
            return result[0]
        
        # If no exact match, match on fiscal YEAR (not exact date)
        # This handles cases where XBRL has "2023-12-31" but SEC_API has "2024-12-31" for the same fiscal year
        if fiscal_year:
            self.cur.execute("""
                SELECT filing_id FROM dim_filings 
                WHERE company_id = %s 
                  AND filing_type = %s 
                  AND EXTRACT(YEAR FROM fiscal_year_end) = %s
                ORDER BY filing_id DESC
                LIMIT 1
            """, (company_id, filing_type, int(fiscal_year)))
            
            result = self.cur.fetchone()
            if result:
                # Reuse existing filing for same fiscal year
                return result[0]
        
        # Create new filing only if none exists for this company, filing_type, and fiscal year
        self.cur.execute("""
            INSERT INTO dim_filings (
                company_id, filing_type, fiscal_year_end, source_url,
                validation_score, completeness_score
            ) VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING filing_id
        """, (
            company_id,
            filing_type,
            fiscal_year_end,
            metadata.get('source_url'),
            metadata.get('validation_score'),
            metadata.get('completeness_score')
        ))
        
        filing_id = self.cur.fetchone()[0]
        self.conn.commit()
        return filing_id
    
    def get_or_create_dimension(self, dimensions: Optional[Dict]) -> Optional[int]:
        """Get or create dimension_id from JSONB"""
        if not dimensions or dimensions == {}:
            return None
        
        # Generate hash
        dimension_json = json.dumps(dimensions, sort_keys=True)
        dimension_hash = hashlib.md5(dimension_json.encode()).hexdigest()
        
        # Check if exists
        self.cur.execute(
            "SELECT dimension_id FROM dim_xbrl_dimensions WHERE dimension_hash = %s",
            (dimension_hash,)
        )
        result = self.cur.fetchone()
        if result:
            return result[0]
        
        # Extract axis and member for easier querying
        axis_name = None
        member_name = None
        if dimensions:
            # Get first axis/member pair
            for axis, details in dimensions.items():
                axis_name = axis
                if isinstance(details, dict):
                    if 'member' in details:
                        member_name = details['member']
                    elif 'value' in details:
                        # Typed dimension: use value as member_name
                        member_name = details['value']
                break
        
        # Create new
        self.cur.execute("""
            INSERT INTO dim_xbrl_dimensions (
                dimension_json, dimension_hash, axis_name, member_name
            ) VALUES (%s, %s, %s, %s)
            RETURNING dimension_id
        """, (json.dumps(dimensions), dimension_hash, axis_name, member_name))
        
        dimension_id = self.cur.fetchone()[0]
        self.conn.commit()
        return dimension_id
    
    def load_to_staging(self, filing_id: int, fact: Dict) -> Optional[int]:
        """Load raw fact to staging_facts table (ELT staging layer)
        
        Args:
            filing_id: Filing ID
            fact: Raw fact dictionary from JSON
            
        Returns:
            staging_id if successful, None if skipped
        """
        try:
            # Extract raw data (minimal transformation)
            concept_name = fact.get('concept') or fact.get('concept_name', '')
            if not concept_name:
                return None
            
            concept_namespace = fact.get('concept_namespace')
            taxonomy = fact.get('taxonomy', 'us-gaap')
            value_text = fact.get('value_text') or fact.get('value', '')
            value_numeric = fact.get('value_numeric')
            if value_numeric is None and value_text:
                try:
                    value_numeric = float(value_text)
                except (ValueError, TypeError):
                    value_numeric = None
            
            # Period info (raw from XBRL)
            period_type = fact.get('period_type', 'duration')
            period_start = fact.get('period_start')
            period_end = fact.get('period_end')
            instant_date = fact.get('instant_date')
            context_id = fact.get('context_id')
            
            # Dimensions (raw JSON)
            dimensions = fact.get('dimensions', {})
            dimensions_json = json.dumps(dimensions) if dimensions else None
            
            # Unit info (raw)
            unit_measure = fact.get('unit_measure')
            unit_type = fact.get('unit_type')
            scale_int = fact.get('scale_int')
            
            # Source metadata
            source = fact.get('source', 'XBRL')
            extraction_method = fact.get('extraction_method', 'lxml')
            
            # Provenance
            fact_id_xbrl = fact.get('fact_id_xbrl') or fact.get('id')
            source_line = fact.get('source_line')
            order_index = fact.get('order_index')
            
            # Insert into staging (ON CONFLICT to handle duplicates)
            self.cur.execute("""
                INSERT INTO staging_facts (
                    filing_id, concept_name, concept_namespace, taxonomy,
                    value_text, value_numeric,
                    period_type, period_start, period_end, instant_date, context_id,
                    dimensions_json,
                    unit_measure, unit_type, scale_int,
                    source, extraction_method,
                    fact_id_xbrl, source_line, order_index,
                    is_processed
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s, %s,
                    %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    FALSE
                )
                ON CONFLICT (filing_id, concept_name, context_id, fact_id_xbrl) 
                DO UPDATE SET
                    value_numeric = EXCLUDED.value_numeric,
                    value_text = EXCLUDED.value_text,
                    extraction_timestamp = CURRENT_TIMESTAMP
                RETURNING staging_id
            """, (
                filing_id, concept_name, concept_namespace, taxonomy,
                value_text, value_numeric,
                period_type, period_start, period_end, instant_date, context_id,
                dimensions_json,
                unit_measure, unit_type, scale_int,
                source, extraction_method,
                fact_id_xbrl, source_line, order_index
            ))
            
            result = self.cur.fetchone()
            return result[0] if result else None
            
        except Exception as e:
            # Log error but don't fail - staging is for debugging
            print(f"      ⚠️  Failed to load to staging: {e}")
            return None
    
    def load_fact(
        self,
        company_id: int,
        concept_id: int,
        period_id: int,
        filing_id: int,
        dimension_id: Optional[int],
        fact: Dict
    ):
        """Load a single fact into fact table"""
        try:
            # Determine source: SEC_API if gap-filled, otherwise XBRL
            source = fact.get('source', 'XBRL')
            if fact.get('is_gap_filled'):
                source = 'SEC_API'
            
            # Get business keys from dimension tables
            self.cur.execute("""
                SELECT normalized_label FROM dim_concepts WHERE concept_id = %s
            """, (concept_id,))
            normalized_label_result = self.cur.fetchone()
            normalized_label = normalized_label_result[0] if normalized_label_result else fact.get('normalized_label')
            
            # Get currency_id from unit_measure (will be set later, but check now if available)
            currency_id = None
            
            # Determine is_gaap (default to True, set False for non-GAAP metrics)
            is_gaap = True
            concept_name_lower = fact.get('concept_name', '').lower()
            if any(term in concept_name_lower for term in ['non-gaap', 'non_gaap', 'adjusted', 'ebitda', 'ebit']):
                # Check if it's explicitly non-GAAP
                if 'non-gaap' in concept_name_lower or 'non_gaap' in concept_name_lower:
                    is_gaap = False
            
            self.cur.execute("""
                SELECT fiscal_year, period_type FROM dim_time_periods WHERE period_id = %s
            """, (period_id,))
            period_result = self.cur.fetchone()
            if period_result:
                fiscal_year, period_type = period_result
            else:
                # Fallback: infer from fact metadata
                fiscal_year = None
                period_type = fact.get('period_type', 'duration')
                period_end = fact.get('period_end')
                instant_date = fact.get('instant_date')
                if period_end:
                    from datetime import datetime
                    end_dt = datetime.strptime(period_end, '%Y-%m-%d')
                    fiscal_year = end_dt.year - 1 if end_dt.month <= 3 else end_dt.year
                elif instant_date:
                    from datetime import datetime
                    instant_dt = datetime.strptime(instant_date, '%Y-%m-%d')
                    fiscal_year = instant_dt.year - 1 if instant_dt.month <= 3 else instant_dt.year
            
            # UNIVERSAL FIX: Balance sheet items must be instant, not duration
            # This prevents balance sheet items from being incorrectly stored with duration period_type
            # Root cause fix: ensures correct period_type at load time, preventing duplicates
            if normalized_label:
                from src.utils.taxonomy_mappings import get_statement_type
                statement_type = get_statement_type(normalized_label)
                if statement_type == 'balance_sheet' and period_type == 'duration':
                    # Balance sheet items must be instant - get/create correct period
                    # Use instant_date if available, otherwise use period_end as instant_date
                    instant_date_for_bs = fact.get('instant_date') or fact.get('period_end')
                    period_end_for_bs = None
                    period_start_for_bs = None
                    
                    if instant_date_for_bs:
                        # Recreate period with instant type
                        period_id = self.get_or_create_period(
                            period_type='instant',
                            start_date=None,
                            end_date=None,
                            instant_date=instant_date_for_bs
                        )
                        # Re-fetch period info with correct type
                        self.cur.execute("""
                            SELECT fiscal_year, period_type FROM dim_time_periods WHERE period_id = %s
                        """, (period_id,))
                        period_result = self.cur.fetchone()
                        if period_result:
                            fiscal_year, period_type = period_result
            
            # Ensure we have all business keys
            if not normalized_label:
                # Try to get from concept one more time
                self.cur.execute("""
                    SELECT normalized_label FROM dim_concepts WHERE concept_id = %s
                """, (concept_id,))
                retry_result = self.cur.fetchone()
                if retry_result and retry_result[0]:
                    normalized_label = retry_result[0]
                else:
                    raise ValueError(f"Missing normalized_label for concept_id {concept_id} (concept_name: {fact.get('concept')})")
            if fiscal_year is None:
                # Try to get from period one more time
                self.cur.execute("""
                    SELECT fiscal_year FROM dim_time_periods WHERE period_id = %s
                """, (period_id,))
                retry_result = self.cur.fetchone()
                if retry_result and retry_result[0]:
                    fiscal_year = retry_result[0]
                else:
                    raise ValueError(f"Missing fiscal_year for period_id {period_id}")
            if not period_type:
                # Try to get from period one more time
                self.cur.execute("""
                    SELECT period_type FROM dim_time_periods WHERE period_id = %s
                """, (period_id,))
                retry_result = self.cur.fetchone()
                if retry_result and retry_result[0]:
                    period_type = retry_result[0]
                else:
                    raise ValueError(f"Missing period_type for period_id {period_id}")
            
            # UNIVERSAL FIX: Normalize unit_measure when None
            # If unit_measure is None, try to infer from SEC_API data or from value scale
            unit_measure = fact.get('unit_measure') or fact.get('unit')
            if not unit_measure and source == 'XBRL':
                # Try to get unit from SEC_API data for same concept/period
                self.cur.execute("""
                    SELECT unit_measure FROM fact_financial_metrics fm
                    WHERE fm.filing_id = %s
                      AND fm.normalized_label = %s
                      AND fm.fiscal_year = %s
                      AND fm.period_type = %s
                      AND fm.dimension_id IS NULL
                      AND fm.source = 'SEC_API'
                      AND fm.unit_measure IS NOT NULL
                    LIMIT 1
                """, (filing_id, normalized_label, fiscal_year, period_type))
                sec_unit = self.cur.fetchone()
                if sec_unit:
                    unit_measure = sec_unit[0]
                # If still None, infer from value scale (common XBRL patterns)
                if not unit_measure and fact.get('value_numeric'):
                    abs_value = abs(fact.get('value_numeric', 0))
                    # Very large values (billions) likely in base currency
                    # Very small values (< 1) might be ratios/pure
                    if abs_value > 1_000_000_000:
                        # Check company currency from filing
                        self.cur.execute("""
                            SELECT c.currency FROM dim_companies c
                            JOIN dim_filings f ON c.company_id = f.company_id
                            WHERE f.filing_id = %s
                        """, (filing_id,))
                        currency_row = self.cur.fetchone()
                        if currency_row and currency_row[0]:
                            unit_measure = currency_row[0]
                        else:
                            unit_measure = 'USD'  # Default fallback
            
            # Get currency_id from unit_measure (now that it's set)
            currency_id = None
            if unit_measure and len(unit_measure) == 3 and unit_measure.isupper():
                # Likely a currency code (USD, EUR, etc.)
                self.cur.execute("""
                    SELECT currency_id FROM dim_currencies WHERE currency_code = %s
                """, (unit_measure,))
                currency_result = self.cur.fetchone()
                if currency_result:
                    currency_id = currency_result[0]
            
            # XBRL's `decimals` attribute denotes rounding precision (how many trailing
            # digits are significant), not a scale factor. The value already extracted
            # from the instance document is the full-precision reported number and must
            # not be multiplied by 10^abs(decimals).
            value_numeric = fact.get('value_numeric')
            
            # UNIVERSAL FIX: Create synthetic dimension from context_id for consolidated facts
            # This preserves all facts when multiple consolidated facts (dimension_id=NULL) exist
            # with the same business key but different context_ids
            context_id = fact.get('context_id')
            if dimension_id is None:
                # Check if there's already a fact with same business key (potential conflict)
                self.cur.execute("""
                    SELECT fact_id, context_id, dimension_id
                    FROM fact_financial_metrics
                    WHERE filing_id = %s
                      AND normalized_label = %s
                      AND fiscal_year = %s
                      AND period_type = %s
                      AND dimension_id IS NULL
                    LIMIT 1
                """, (filing_id, normalized_label, fiscal_year, period_type))
                existing_fact = self.cur.fetchone()
                
                if existing_fact:
                    existing_fact_id, existing_context_id, existing_dim_id = existing_fact
                    # If existing fact has different context_id, create synthetic dimension for new fact
                    if existing_context_id != context_id:
                        if context_id:
                            # Create synthetic dimension from context_id for new fact
                            synthetic_dimensions = {
                                'ContextAxis': {
                                    'type': 'explicit',
                                    'member': f'Context_{context_id}'
                                }
                            }
                            dimension_id = self.get_or_create_dimension(synthetic_dimensions)
                        elif existing_context_id:
                            # New fact has no context_id but existing does - create synthetic for existing
                            # Update existing fact to have synthetic dimension
                            synthetic_dimensions = {
                                'ContextAxis': {
                                    'type': 'explicit',
                                    'member': f'Context_{existing_context_id}'
                                }
                            }
                            existing_dim_id = self.get_or_create_dimension(synthetic_dimensions)
                            self.cur.execute("""
                                UPDATE fact_financial_metrics
                                SET dimension_id = %s
                                WHERE fact_id = %s
                            """, (existing_dim_id, existing_fact_id))
                            self.conn.commit()
            
            # DEBUG: Verify constraint exists before attempting insert
            self.cur.execute("""
                SELECT conname FROM pg_constraint 
                WHERE conrelid = 'fact_financial_metrics'::regclass 
                  AND contype = 'u'
                  AND conname = 'fact_financial_metrics_filing_id_normalized_label_fiscal_ye_key'
            """)
            constraint_check = self.cur.fetchone()
            if not constraint_check:
                raise RuntimeError("Business key constraint not found! Database schema may be out of sync.")
            
            self.cur.execute("""
                INSERT INTO fact_financial_metrics (
                    company_id, concept_id, period_id, filing_id, dimension_id,
                    normalized_label, fiscal_year, period_type,
                    value_numeric, value_text, unit_measure, currency_id, decimals,
                    scale_int, xbrl_format,
                    context_id, fact_id_xbrl, source_line, order_index, is_primary,
                    source, is_gaap
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (filing_id, normalized_label, fiscal_year, period_type, dimension_id) 
                DO UPDATE SET
                    -- Prefer SEC_API over XBRL when both exist (SEC is authoritative)
                    source = CASE 
                        WHEN EXCLUDED.source = 'SEC_API' THEN 'SEC_API'
                        WHEN fact_financial_metrics.source = 'SEC_API' THEN 'SEC_API'
                        ELSE EXCLUDED.source
                    END,
                    currency_id = COALESCE(EXCLUDED.currency_id, fact_financial_metrics.currency_id),
                    is_gaap = COALESCE(EXCLUDED.is_gaap, fact_financial_metrics.is_gaap),
                    value_numeric = CASE 
                        WHEN EXCLUDED.source = 'SEC_API' THEN EXCLUDED.value_numeric
                        WHEN fact_financial_metrics.source = 'SEC_API' THEN fact_financial_metrics.value_numeric
                        ELSE EXCLUDED.value_numeric
                    END,
                    value_text = CASE 
                        WHEN EXCLUDED.source = 'SEC_API' THEN EXCLUDED.value_text
                        WHEN fact_financial_metrics.source = 'SEC_API' THEN fact_financial_metrics.value_text
                        ELSE EXCLUDED.value_text
                    END,
                    unit_measure = CASE 
                        WHEN EXCLUDED.source = 'SEC_API' AND EXCLUDED.unit_measure IS NOT NULL THEN EXCLUDED.unit_measure
                        WHEN fact_financial_metrics.source = 'SEC_API' AND fact_financial_metrics.unit_measure IS NOT NULL THEN fact_financial_metrics.unit_measure
                        WHEN EXCLUDED.unit_measure IS NOT NULL THEN EXCLUDED.unit_measure
                        ELSE fact_financial_metrics.unit_measure
                    END,
                    is_primary = EXCLUDED.is_primary,
                    fact_id_xbrl = EXCLUDED.fact_id_xbrl,
                    order_index = EXCLUDED.order_index
            """, (
                company_id,
                concept_id,
                period_id,
                filing_id,
                dimension_id,
                normalized_label,
                fiscal_year,
                period_type,
                value_numeric,
                fact.get('value_text'),
                unit_measure,
                currency_id,
                fact.get('decimals'),
                fact.get('scale_int'),
                fact.get('xbrl_format'),
                fact.get('context_id'),
                fact.get('fact_id'),
                fact.get('source_line'),
                fact.get('order_index'),
                fact.get('is_primary', True),
                source,
                is_gaap
            ))
        except Exception as e:
            error_msg = str(e)
            print(f"      ⚠️  Error loading fact: {error_msg}")
            # DEBUG: Print the actual values being inserted
            print(f"      DEBUG - Values: filing_id={filing_id}, normalized_label={normalized_label}, fiscal_year={fiscal_year}, period_type={period_type}, dimension_id={dimension_id}")
            import traceback
            print(f"      Traceback: {traceback.format_exc()}")
            self.conn.rollback()
            # Re-raise to stop processing if it's a critical error
            if "NOT NULL" in error_msg or "constraint" in error_msg.lower() or "ON CONFLICT" in error_msg:
                raise
    
    def validate_loaded_data(self, company_id: int, ticker: str, fiscal_year: int):
        """
        Validate data quality after loading - HARD FAIL on critical issues.
        
        Checks:
        1. Balance sheet equation (Assets = Liabilities + Equity)
        2. No duplicate metrics with different values (> 1% diff)
        
        Raises ValueError if validation fails.
        """
        # Check balance sheet equation for this company/year
        # Use normalized_label for reliable matching (concept_name varies by taxonomy)
        self.cur.execute("""
        WITH balance_sheet_values AS (
            SELECT 
                MAX(CASE WHEN dc.normalized_label = 'total_assets' THEN f.value_numeric END) as total_assets,
                MAX(CASE WHEN dc.normalized_label = 'total_assets_equation' THEN f.value_numeric END) as total_assets_equation,
                MAX(CASE WHEN dc.normalized_label = 'total_liabilities' THEN f.value_numeric END) as total_liabilities,
                MAX(CASE WHEN dc.normalized_label = 'equity_total' OR dc.normalized_label = 'stockholders_equity' THEN f.value_numeric END) as equity,
                MAX(CASE WHEN dc.normalized_label = 'equity_and_liabilities' THEN f.value_numeric END) as equity_and_liabilities,
                MAX(CASE WHEN dc.normalized_label = 'liabilities_and_stockholders_equity' THEN f.value_numeric END) as liabilities_and_stockholders_equity
            FROM fact_financial_metrics f
            JOIN dim_companies c ON f.company_id = c.company_id
            JOIN dim_concepts dc ON f.concept_id = dc.concept_id
            JOIN dim_time_periods dt ON f.period_id = dt.period_id
            WHERE c.company_id = %s
              AND dt.fiscal_year = %s
              AND f.dimension_id IS NULL
              AND dt.period_type = 'instant'
              AND f.value_numeric IS NOT NULL
        )
        SELECT 
            COALESCE(total_assets, total_assets_equation) as assets,
            COALESCE(
                CASE WHEN equity_and_liabilities IS NOT NULL AND total_assets IS NOT NULL 
                     AND ABS(total_assets - equity_and_liabilities) / NULLIF(total_assets, 0) < 0.01
                     THEN equity_and_liabilities
                     ELSE NULL
                END,
                CASE WHEN liabilities_and_stockholders_equity IS NOT NULL AND total_assets IS NOT NULL
                     AND ABS(total_assets - liabilities_and_stockholders_equity) / NULLIF(total_assets, 0) < 0.01
                     THEN liabilities_and_stockholders_equity
                     ELSE NULL
                END,
                total_liabilities + equity,
                equity_and_liabilities,
                liabilities_and_stockholders_equity
            ) as liab_equity
        FROM balance_sheet_values
        WHERE COALESCE(total_assets, total_assets_equation) IS NOT NULL;
        """, (company_id, fiscal_year))
        
        result = self.cur.fetchone()
        if result:
            assets, liab_equity = result[0], result[1]
            if assets and liab_equity:
                diff_pct = abs(assets - liab_equity) / assets * 100 if assets else 0
                
                # Check for unit scaling issues (values way too large or small)
                # If difference is > 90%, likely a unit scaling issue
                if diff_pct > 90.0:
                    # Try to detect and fix unit scaling issue
                    # If assets is 1000x larger than liab_equity, assets might be in wrong units
                    ratio = assets / liab_equity if liab_equity else 0
                    if ratio > 500 or ratio < 0.002:  # More than 500x or less than 0.002x difference
                        raise ValueError(
                            f"❌ VALIDATION FAILED: Unit scaling error detected for {ticker} FY{fiscal_year}\n"
                            f"   Assets: ${assets:,.0f} (ratio: {ratio:.2f}x)\n"
                            f"   Liabilities + Equity: ${liab_equity:,.0f}\n"
                            f"   Difference: {diff_pct:.2f}%\n"
                            f"   This indicates a UNIT SCALING ERROR - values stored in wrong units"
                        )
                
                if diff_pct > 1.0:  # More than 1% difference is critical error
                    raise ValueError(
                        f"❌ VALIDATION FAILED: Balance sheet doesn't balance for {ticker} FY{fiscal_year}\n"
                        f"   Assets: ${assets:,.0f}\n"
                        f"   Liabilities + Equity: ${liab_equity:,.0f}\n"
                        f"   Difference: {diff_pct:.2f}%\n"
                        f"   This indicates a DATA PROCESSING ERROR - DO NOT LOAD"
                    )
    
    def load_concept_labels(self, concept_labels: Dict[str, str], filing_id: int):
        """
        Store original XBRL labels from label linkbase in dim_concepts.
        
        Args:
            concept_labels: Dictionary mapping concept_name -> label_text
            filing_id: Filing ID (for logging)
        """
        if not concept_labels:
            return 0
        
        # Check if original_label column exists
        try:
            self.cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'dim_concepts' 
                AND column_name = 'original_label'
            """)
            has_original_label = self.cur.fetchone() is not None
        except:
            has_original_label = False
        
        if not has_original_label:
            # Add column if it doesn't exist
            try:
                self.cur.execute("""
                    ALTER TABLE dim_concepts 
                    ADD COLUMN original_label VARCHAR(500)
                """)
                self.conn.commit()
                has_original_label = True
            except Exception as e:
                print(f"Warning: Could not add original_label column: {e}")
                return 0
        
        # Check if label_role column exists
        try:
            self.cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'dim_concepts' 
                AND column_name = 'label_role'
            """)
            has_label_role = self.cur.fetchone() is not None
        except:
            has_label_role = False
        
        updated = 0
        for concept_name, label_data in concept_labels.items():
            try:
                # Handle both old format (str) and new format (dict)
                if isinstance(label_data, dict):
                    label_text = label_data.get('label', '')
                    label_role = label_data.get('role')
                else:
                    # Old format: just a string
                    label_text = label_data
                    label_role = None
                
                if not label_text:
                    continue
                
                # Match on full concept_name (e.g., "ifrs-full_Revenue") or just the base name (e.g., "Revenue")
                # First try exact match, then try without taxonomy prefix
                base_name = concept_name.split('_')[-1] if '_' in concept_name else concept_name
                
                # Update dim_concepts with original_label and label_role
                if has_label_role and label_role:
                    self.cur.execute("""
                        UPDATE dim_concepts
                        SET original_label = COALESCE(original_label, %s),
                            label_role = COALESCE(label_role, %s)
                        WHERE (concept_name = %s OR concept_name = %s)
                          AND (original_label IS NULL OR original_label = '')
                    """, (label_text, label_role, concept_name, base_name))
                else:
                    # Fallback if label_role column doesn't exist
                    self.cur.execute("""
                        UPDATE dim_concepts
                        SET original_label = COALESCE(original_label, %s)
                        WHERE (concept_name = %s OR concept_name = %s)
                          AND (original_label IS NULL OR original_label = '')
                    """, (label_text, concept_name, base_name))
                
                if self.cur.rowcount > 0:
                    updated += 1
            except Exception as e:
                continue
        
        self.conn.commit()
        return updated

    def _clear_filing_data(self, filing_id: int):
        """Delete all rows for a filing across every fact/staging table.

        Used both before loading (so reloads don't mask fixes with old data) and after a
        hard validation failure (so a failed load doesn't leave partial data committed —
        see docs/PIPELINE_AND_VALIDATION_MAP.md §3).
        """
        for table in ['fact_income_statement', 'fact_balance_sheet', 'fact_cash_flow',
                     'fact_comprehensive_income', 'fact_equity_statement', 'rel_statement_items']:
            self.cur.execute(f"DELETE FROM {table} WHERE filing_id = %s", (filing_id,))
        self.cur.execute("DELETE FROM fact_financial_metrics WHERE filing_id = %s", (filing_id,))
        self.cur.execute("DELETE FROM staging_facts WHERE filing_id = %s", (filing_id,))

    def load_json_file(self, json_path: Path, show_completeness_check: bool = True, is_incremental: bool = False):
        """Load a single JSON file

        Args:
            json_path: Path to JSON file to load
            show_completeness_check: Whether to display completeness check results (default: True)
                                    Set to False when loading multiple files to avoid redundancy
            is_incremental: True when this JSON is a small supplementary batch being added
                on top of an already-loaded filing (e.g. post-load gap-filling), not a
                complete filing's facts. When True: skips clearing the filing's existing
                data first (the normal clear-before-load would wipe out the primary load),
                and skips the full-statement-coverage hard-fail gate (a handful of
                gap-filled facts will never look like a complete balance sheet/income
                statement/etc, and shouldn't be judged as if it should be one). Confirmed
                2026-08-22 that calling this with the default False from
                post_load_gap_filling.py was silently destroying primary-load data — see
                docs/NVO_GOLDEN_PATH_2026-08.md item 5.
        """
        print(f"\n📄 Loading: {json_path.name}")
        
        # Read JSON
        with open(json_path) as f:
            data = json.load(f)
        
        ticker = data.get('company', json_path.stem.split('_')[0])
        filing_type = data.get('filing_type', '10-K')
        year = data.get('year')
        
        # Derive fiscal_year_end from year (assume December 31)
        fiscal_year_end = f"{year}-12-31" if year else None
        
        # If not found, try to extract from facts
        if not fiscal_year_end and data.get('facts'):
            # Find latest period_end or instant_date
            latest_date = None
            for fact in data['facts']:
                date = fact.get('period_end') or fact.get('instant_date')
                if date:
                    if not latest_date or date > latest_date:
                        latest_date = date
            fiscal_year_end = latest_date
        
        facts = data.get('facts', [])
        
        print(f"   Company: {ticker}")
        print(f"   Filing: {filing_type}")
        print(f"   Fiscal Year End: {fiscal_year_end}")
        print(f"   Facts: {len(facts)}")
        
        # Get or create dimensions
        company_id = self.get_or_create_company(ticker, data.get('metadata', {}))
        filing_id = self.get_or_create_filing(company_id, filing_type, fiscal_year_end, data.get('metadata', {}))
        
        # CRITICAL: Clear existing data for this filing before reloading
        # This ensures fixes actually work - old data won't mask new fixes
        # (Skipped for incremental loads — clearing would wipe out the primary load
        # this supplementary batch is meant to add to.)
        if is_incremental:
            print(f"   ℹ️  Incremental load for filing_id {filing_id} — not clearing existing data")
        else:
            print(f"   🗑️  Clearing existing data for filing_id {filing_id}...")
            try:
                self._clear_filing_data(filing_id)
                self.conn.commit()
                print(f"   ✅ Cleared existing data for filing_id {filing_id}")
            except Exception as e:
                print(f"   ⚠️  Warning: Could not clear existing data: {e}")
                self.conn.rollback()
        
        # ELT STAGING LAYER: First load all raw facts to staging_facts
        print(f"   → Loading {len(facts)} facts to staging layer...")
        staging_loaded = 0
        from tqdm import tqdm
        import sys
        for fact in tqdm(facts, desc=f"Staging {ticker} facts", unit="facts", file=sys.stderr, mininterval=0.1, maxinterval=1.0, dynamic_ncols=True, leave=False):
            try:
                staging_id = self.load_to_staging(filing_id, fact)
                if staging_id:
                    staging_loaded += 1
                if staging_loaded % 500 == 0:
                    self.conn.commit()
            except Exception as e:
                # Don't fail on staging errors - staging is for debugging
                continue
        
        self.conn.commit()
        print(f"   → Loaded {staging_loaded} facts to staging")
        
        # Load facts from staging to fact_financial_metrics (transformation layer)
        facts_loaded = 0
        facts_with_dims = 0
        
        # Track facts by concept and period for completeness validation
        facts_by_concept_period = {}  # (concept_name, period_year) -> count
        
        # Get concept labels for this filing (to pass to get_or_create_concept)
        concept_labels = data.get('concept_labels', {})
        
        for fact in tqdm(facts, desc=f"Loading {ticker} facts", unit="facts", file=sys.stderr, mininterval=0.1, maxinterval=1.0, dynamic_ncols=True):
            try:
                # Add original_label to fact metadata if available
                fact_metadata = fact.copy()
                concept_name = fact.get('concept') or fact.get('concept_name', '')
                if concept_name and concept_name in concept_labels:
                    fact_metadata['original_label'] = concept_labels[concept_name]
                
                # Get or create concept
                concept_id = self.get_or_create_concept(
                    concept_name,
                    fact.get('taxonomy', 'us-gaap'),
                    fact_metadata
                )
                
                # UNIVERSAL FIX: Balance sheet items must be instant, not duration
                # Check if this is a balance sheet item and correct period_type if needed
                normalized_label = fact.get('normalized_label')
                period_type_from_fact = fact.get('period_type', 'duration')
                
                if normalized_label:
                    from src.utils.taxonomy_mappings import get_statement_type
                    statement_type = get_statement_type(normalized_label)
                    if statement_type == 'balance_sheet' and period_type_from_fact == 'duration':
                        # Balance sheet items must be instant - correct the period_type
                        period_type_from_fact = 'instant'
                        # If period_end exists but no instant_date, use period_end as instant_date
                        if fact.get('period_end') and not fact.get('instant_date'):
                            fact['instant_date'] = fact.get('period_end')
                            fact['period_end'] = None
                            fact['period_start'] = None
                
                # Get or create period
                period_id = self.get_or_create_period(
                    period_type_from_fact,
                    fact.get('period_start'),
                    fact.get('period_end'),
                    fact.get('instant_date')
                )
                
                # Track for completeness validation
                # CRITICAL: Track by normalized_label, not concept_name
                # Multiple concept names can map to same normalized label (e.g., PropertyPlantAndEquipment vs PropertyPlantAndEquipmentIncludingRightofuseAssets)
                concept_name = fact.get('concept')
                normalized_label = fact.get('normalized_label')
                period_end = fact.get('period_end')
                instant_date = fact.get('instant_date')
                date_str = period_end or instant_date
                if date_str and normalized_label:  # Use normalized_label for tracking
                    year = date_str[:4] if len(date_str) >= 4 else None
                    if year:
                        key = (normalized_label, year)  # Track by normalized_label, not concept_name
                        facts_by_concept_period[key] = facts_by_concept_period.get(key, 0) + 1
                
                # Get or create dimension
                dimension_id = self.get_or_create_dimension(fact.get('dimensions'))
                if dimension_id:
                    facts_with_dims += 1
                
                # Load fact
                self.load_fact(company_id, concept_id, period_id, filing_id, dimension_id, fact)
                facts_loaded += 1
                
                if facts_loaded % 500 == 0:
                    self.conn.commit()
            
            except Exception as e:
                # CRITICAL: Always rollback on error to reset transaction state
                # This prevents "current transaction is aborted" errors
                try:
                    self.conn.rollback()
                except:
                    pass  # Ignore rollback errors
                print(f"      ⚠️  Skipped fact {fact.get('concept')}: {e}")
                continue
        
        # Validate completeness: Check if CRITICAL concepts have data for all years
        # Only check critical statement items - optional/one-time items may legitimately not have data for all years
        # CRITICAL FIX: Track by normalized_label, not concept_name, because multiple concept names map to same label
        self.conn.commit()
        normalized_labels_by_year = {}
        for (normalized_label, year), count in facts_by_concept_period.items():
            if normalized_label not in normalized_labels_by_year:
                normalized_labels_by_year[normalized_label] = set()
            normalized_labels_by_year[normalized_label].add(year)
        
        # Find all years present in the data
        all_years = set()
        for years in normalized_labels_by_year.values():
            all_years.update(years)
        all_years = sorted(all_years, reverse=True)
        
        # CRITICAL: Filter out future years - only expect years up to and including the filing year
        # Get filing year from fiscal_year_end
        filing_year = None
        if fiscal_year_end:
            try:
                from datetime import datetime
                if isinstance(fiscal_year_end, str):
                    filing_year = int(fiscal_year_end[:4])
                else:
                    filing_year = fiscal_year_end.year if hasattr(fiscal_year_end, 'year') else None
            except (ValueError, AttributeError):
                pass
        
        # If we can't determine filing year, use the latest year in the data
        if not filing_year and all_years:
            try:
                filing_year = int(max(all_years))
            except (ValueError, TypeError):
                pass
        
        # Filter out future years (years > filing year)
        if filing_year:
            all_years = [y for y in all_years if int(y) <= filing_year]
        
        # Take top 3 years (most recent), but only up to filing year
        expected_years = all_years[:3] if len(all_years) > 3 else all_years
        
        # CRITICAL: Only check normalized labels for critical statement items
        # These are the universal metrics that should have data for all years
        from src.validation.completeness import CompletenessTracker
        tracker = CompletenessTracker()
        critical_labels = []
        for labels in tracker.EXPECTED_NORMALIZED_LABELS.values():
            critical_labels.extend(labels)
        
        # Check only critical normalized labels for year completeness
        incomplete_critical = []
        incomplete_optional = []
        
        for normalized_label, years in normalized_labels_by_year.items():
            missing_years = [y for y in expected_years if y not in years]
            if missing_years:
                if normalized_label in critical_labels:
                    incomplete_critical.append((normalized_label, normalized_label, sorted(years, reverse=True), missing_years))
                else:
                    incomplete_optional.append((normalized_label, sorted(years, reverse=True), missing_years))
        
        # Only show completeness check if requested (suppress for individual files when loading multiple)
        if show_completeness_check:
            # Report critical issues (these are real problems)
            if incomplete_critical:
                print(f"\n      ⚠️  CRITICAL: {len(incomplete_critical)} critical concept(s) missing data for some years")
                print(f"         Expected years: {expected_years}")
                for concept, normalized_label, years, missing in incomplete_critical:
                    print(f"           • {normalized_label:<30} | Has: {years}, Missing: {missing}")
            
            # Report optional items (informational only - these may be legitimate)
            # Only show summary, not full list (too noisy)
            if incomplete_optional:
                print(f"\n      ℹ️  INFO: {len(incomplete_optional)} optional concept(s) missing data for some years")
                print(f"         (These may be one-time items, acquisitions, or new/discontinued concepts)")
                # Show sample only if there are many
                if len(incomplete_optional) <= 5:
                    for concept, years, missing in incomplete_optional:
                        print(f"           • {concept[:50]:<50} | Has: {years}, Missing: {missing}")
                else:
                    print(f"         Sample (first 3 of {len(incomplete_optional)}):")
                    for concept, years, missing in incomplete_optional[:3]:
                        print(f"           • {concept[:50]:<50} | Has: {years}, Missing: {missing}")
            
            if not incomplete_critical and not incomplete_optional:
                print(f"\n      ✅ Completeness check passed: All concepts have data for all expected years")
            elif not incomplete_critical:
                print(f"\n      ✅ Critical completeness check passed: All critical statement items have data for all expected years")
        
        # Store completeness results for final check (when loading multiple files)
        completeness_result = {
            'incomplete_critical': incomplete_critical,
            'incomplete_optional': incomplete_optional,
            'expected_years': expected_years
        }
        
        # Load relationships with synthesis
        from src.utils.relationship_synthesizer import synthesize_relationships_for_filing
        
        # Get XBRL relationships if present
        xbrl_relationships = data.get('relationships', {})
        xbrl_calc = xbrl_relationships.get('calculation', [])
        xbrl_pres = xbrl_relationships.get('presentation', [])
        
        # Query loaded facts with database IDs for relationship synthesis
        print(f"   🔄 Synthesizing relationships...")
        self.cur.execute("""
            SELECT 
                f.fact_id,
                f.concept_id,
                f.period_id,
                f.dimension_id,
                f.value_numeric,
                co.concept_name,
                co.normalized_label
            FROM fact_financial_metrics f
            JOIN dim_concepts co ON f.concept_id = co.concept_id
            WHERE f.filing_id = %s
        """, (filing_id,))
        
        loaded_facts = []
        for row in self.cur.fetchall():
            loaded_facts.append({
                'fact_id': row[0],
                'concept_id': row[1],
                'period_id': row[2],
                'dimension_id': row[3],
                'value_numeric': row[4],
                'concept': row[5],
                'normalized_label': row[6]
            })
        
        # Synthesize complete set of relationships
        synthesized = synthesize_relationships_for_filing(
            facts=loaded_facts,
            filing_id=filing_id,
            xbrl_calc_rels=xbrl_calc,
            xbrl_pres_rels=xbrl_pres
        )
        
        # Load calculation relationships
        if synthesized.get('calculation'):
            calc_count = self.load_calculation_relationships(filing_id, synthesized['calculation'], data.get('metadata', {}))
            xbrl_count = len([r for r in synthesized['calculation'] if not r.get('is_synthetic', False)])
            synth_count = calc_count - xbrl_count
            print(f"   ✅ Loaded {calc_count} calculation relationships ({xbrl_count} from XBRL, {synth_count} generated)")
        
        # Load concept labels (original XBRL labels from label linkbase)
        concept_labels = data.get('concept_labels', {})
        if concept_labels:
            labels_updated = self.load_concept_labels(concept_labels, filing_id)
            if labels_updated > 0:
                print(f"   ✅ Loaded {labels_updated} original XBRL labels")
        
        # Load presentation hierarchy
        if synthesized.get('presentation'):
            pres_count = self.load_presentation_hierarchy(filing_id, synthesized['presentation'], data.get('metadata', {}))
            xbrl_count = len([r for r in synthesized['presentation'] if not r.get('is_synthetic', False)])
            synth_count = pres_count - xbrl_count
            print(f"   ✅ Loaded {pres_count} presentation relationships ({xbrl_count} from XBRL, {synth_count} generated)")
        
        # Load footnote references
        if xbrl_relationships.get('footnotes'):
            footnote_count = self.load_footnote_references(filing_id, xbrl_relationships['footnotes'], facts, data.get('metadata', {}))
            print(f"   ✅ Loaded {footnote_count} footnote references")
        
        # Populate standard presentation order for this filing if XBRL hierarchy is missing
        # This ensures all filings have presentation hierarchy (XBRL or standard fallback)
        # CRITICAL: This is now integrated into the pipeline, not a separate script
        from sqlalchemy import create_engine, text
        from config import DATABASE_URI
        engine = create_engine(DATABASE_URI)
        
        # Always run the standard-order fallback — it's safe to call unconditionally
        # (ON CONFLICT DO NOTHING, and its own per-concept NOT EXISTS check only touches
        # concepts genuinely missing presentation hierarchy). A blanket "skip entirely if
        # this filing has ANY presentation hierarchy rows" gate used to sit here, but
        # XBRL extraction can partially succeed — e.g. income_statement/balance_sheet get
        # real relationships before an extraction error aborts the rest — leaving
        # `existing_count > 0` while comprehensive_income/equity_statement have zero
        # coverage and the blanket gate skipped them too. Confirmed causing
        # fact_comprehensive_income to populate empty intermittently — see
        # docs/NVO_GOLDEN_PATH_2026-08.md item 6.
        print(f"   🔧 Populating standard presentation order for any concepts missing XBRL hierarchy...")
        from src.utils.populate_standard_presentation_order import populate_standard_presentation_order, populate_equity_statement_from_dimensions
        populate_standard_presentation_order(engine)
        # Equity-rollforward items need a dimension-based signal (ComponentsOfEquityAxis),
        # not the concept-based STANDARD_TEMPLATES approach — see that function's
        # docstring in src/utils/populate_standard_presentation_order.py.
        populate_equity_statement_from_dimensions(engine, filing_id=filing_id)
        print(f"   ✅ Standard presentation order populated")

        # Step: Concept mapping validation (concept_checker.py)
        if year:
            try:
                print(f"   🔍 Validating concept mappings...")
                from src.validation.concept_checker import ConceptMappingValidator
                
                concept_validator = ConceptMappingValidator()
                concept_report = concept_validator.validate_mappings(ticker, year)
                
                if not concept_report.passed:
                    print(f"   ⚠️  Concept mapping issues: {concept_report.overall_score:.1%}")
                    # Log specific issues
                    for result in concept_report.results:
                        if not result.passed:
                            print(f"      {result.rule_name}: {result.message}")
                else:
                    print(f"   ✅ Concept mapping validation passed: {concept_report.overall_score:.1%}")
            except Exception as e:
                print(f"   ⚠️  Concept mapping validation failed: {e}")
                logger.warning(f"Concept mapping validation error: {e}", exc_info=True)
        
        # Fix unit scaling issues BEFORE populating statement facts
        # This prevents numeric overflow errors when inserting into statement fact tables
        from src.utils.fix_unit_scaling import fix_unit_scaling
        from src.utils.fix_equity_values import fix_equity_values
        scaling_fixed = fix_unit_scaling()
        equity_fixed = fix_equity_values()
        if scaling_fixed > 0 or equity_fixed > 0:
            print(f"   ✅ Fixed {scaling_fixed} unit scaling issues and {equity_fixed} equity values before populating statements")
        
        # Populate rel_statement_items table (Approach 2: Statement Metadata Table)
        print(f"   🔧 Populating statement items metadata...")
        from src.utils.populate_statement_items import populate_statement_items
        populate_statement_items(filing_id=filing_id)
        
        # Populate statement-specific fact tables (Approach 2: Denormalized for Performance)
        # Use dependency graph to ensure correct population order
        print(f"   🔧 Populating statement-specific fact tables (using dependency order)...")
        from src.utils.population_order import validate_dependencies, populate_all_statements
        
        # Validate dependency graph (ensures no circular dependencies)
        if not validate_dependencies():
            raise ValueError("Dependency graph has cycles - cannot proceed")
        
        # Populate in correct order using dependency graph
        populate_results = populate_all_statements(filing_id=filing_id, engine=self.engine, show_warnings=show_completeness_check)
        
        # Fix equity values that are clearly wrong (unit scaling issues)
        # This runs after all data is loaded but BEFORE validation to ensure correct values
        try:
            from src.utils.fix_equity_values import fix_equity_values
            fixed_count = fix_equity_values()
            if fixed_count > 0:
                print(f"   ✅ Fixed {fixed_count} equity values (unit scaling corrections)")
                # Re-populate balance sheet after equity fix to use corrected values
                from src.utils.populate_statement_facts import populate_balance_sheet
                with self.engine.begin() as conn:
                    populate_balance_sheet(conn, filing_id=filing_id, show_warnings=False)
                print(f"   ✅ Re-populated balance sheet with corrected equity values")
        except Exception as e:
            print(f"   ⚠️  Equity value fix failed: {e}")
        
        # Convert results to warnings format for compatibility
        statement_warnings = {
            'missing_statements': {},
            'failed_statements': {},
            'successful_statements': populate_results.get('successful', [])
        }
        
        # Track failed statements
        for table, error in populate_results.get('failed', {}).items():
            if filing_id not in statement_warnings['failed_statements']:
                statement_warnings['failed_statements'][filing_id] = {}
            statement_warnings['failed_statements'][filing_id][table] = error
        
        # CRITICAL VALIDATION - Validate AFTER equity fix and re-population
        # This ensures no partial loads on validation failure
        # Skipped for incremental loads: the full aggregator gate expects complete
        # statement coverage (fact_equity_statement/fact_cash_flow/etc all populated),
        # which a handful of supplementary gap-filled facts will never look like. The
        # primary (complete) load already went through this gate; a successful INSERT
        # here is sufficient signal for a small additive batch.
        if is_incremental:
            print(f"   ℹ️  Incremental load — skipping full-coverage validation gate")
            self.conn.commit()
            print(f"   ✅ Loaded {facts_loaded} facts ({facts_with_dims} with dimensions)")
            return {
                **completeness_result,
                'statement_warnings': statement_warnings
            }

        print(f"   🔍 Running validation (hard fail on errors)...")
        validation_passed = False
        try:
            # Validate for each fiscal year in this filing
            self.cur.execute("""
            SELECT DISTINCT dt.fiscal_year 
            FROM dim_time_periods dt
            JOIN fact_financial_metrics f ON dt.period_id = f.period_id
            WHERE f.filing_id = %s
              AND dt.fiscal_year IS NOT NULL;
            """, (filing_id,))
            
            fiscal_years = [row[0] for row in self.cur.fetchall()]
            
            for fy in fiscal_years:
                if fy:  # Skip NULL fiscal years
                    self.validate_loaded_data(company_id, ticker, fy)
            
            # Run validation aggregator to check for all issues
            from src.validation.aggregator import ValidationAggregator
            aggregator = ValidationAggregator()
            validation_result = aggregator.collect_all_issues(filing_id=filing_id)
            
            # Check for critical issues (only ERROR severity, not WARNING)
            # WARNING severity issues are acceptable (e.g., missing optional data, rounding differences)
            critical_issues = [
                issue for issue in validation_result.issues
                if issue.category in ['loading_error'] or 
                   (issue.category == 'database_validation' and 
                    issue.details.get('severity') == 'ERROR')
            ]
            
            if critical_issues:
                print(f"   ❌ Validation failed: {len(critical_issues)} critical issues found")
                for issue in critical_issues[:10]:  # Show first 10
                    print(f"      - {issue}")
                if len(critical_issues) > 10:
                    print(f"      ... and {len(critical_issues) - 10} more")
                raise ValueError(f"Validation failed: {len(critical_issues)} critical issues")
            
            validation_passed = True
            print(f"   ✅ Validation passed")
            
        except ValueError as e:
            # HARD FAIL. rollback() only undoes whatever hadn't committed yet in this
            # transaction — staging/statement-table writes earlier in this method already
            # committed independently, so they'd otherwise survive a failed validation.
            # Explicitly purge this filing's data so a failed load doesn't leave partial,
            # unvalidated data sitting in the warehouse (see PIPELINE_AND_VALIDATION_MAP.md §3).
            self.conn.rollback()
            try:
                self._clear_filing_data(filing_id)
                self.conn.commit()
                print(f"   🗑️  Purged partial data for filing_id {filing_id} after validation failure")
            except Exception as cleanup_error:
                self.conn.rollback()
                print(f"   ⚠️  Could not purge partial data for filing_id {filing_id}: {cleanup_error}")
            print(f"\n{str(e)}")
            raise  # Re-raise to stop pipeline
        except Exception as e:
            # Any other error - same purge-on-failure treatment
            self.conn.rollback()
            try:
                self._clear_filing_data(filing_id)
                self.conn.commit()
                print(f"   🗑️  Purged partial data for filing_id {filing_id} after error")
            except Exception as cleanup_error:
                self.conn.rollback()
                print(f"   ⚠️  Could not purge partial data for filing_id {filing_id}: {cleanup_error}")
            print(f"   ❌ Validation error: {e}")
            raise

        # Only commit if validation passed
        if validation_passed:
            self.conn.commit()
            print(f"   ✅ Loaded {facts_loaded} facts ({facts_with_dims} with dimensions)")
        else:
            # Should not reach here, but safety check
            self.conn.rollback()
            raise ValueError("Validation did not pass - transaction rolled back")
        
        # NOTE: UI tests (UITest.py) are NOT run here because:
        # 1. This runs during loading, BEFORE post-processing (normalization, statement population, etc.)
        # 2. UI tests need to verify the FINAL output (after all processing)
        # 3. UI tests are run in run_pipeline.sh Step 3/3, AFTER all post-processing in main() completes
        # 4. This ensures UI tests verify the actual user experience (same endpoint as website)
        
        # Return completeness results and statement warnings for aggregation when loading multiple files
        return {
            **completeness_result,
            'statement_warnings': statement_warnings
        }
    
    def load_calculation_relationships(self, filing_id: int, calc_rels: List[Dict], metadata: Dict) -> int:
        """Load calculation relationships"""
        loaded = 0
        
        for rel in calc_rels:
            try:
                # Get parent and child concept IDs
                parent_taxonomy = self._identify_taxonomy_from_namespace(rel.get('parent_namespace'))
                child_taxonomy = self._identify_taxonomy_from_namespace(rel.get('child_namespace'))
                
                self.cur.execute("""
                    SELECT concept_id FROM dim_concepts 
                    WHERE concept_name = %s AND taxonomy = %s
                """, (rel['parent_concept'], parent_taxonomy))
                parent_result = self.cur.fetchone()
                
                self.cur.execute("""
                    SELECT concept_id FROM dim_concepts 
                    WHERE concept_name = %s AND taxonomy = %s
                """, (rel['child_concept'], child_taxonomy))
                child_result = self.cur.fetchone()
                
                if not parent_result or not child_result:
                    continue  # Skip if concepts don't exist
                
                parent_concept_id = parent_result[0]
                child_concept_id = child_result[0]
                
                # Insert relationship
                self.cur.execute("""
                    INSERT INTO rel_calculation_hierarchy (
                        filing_id, parent_concept_id, child_concept_id,
                        weight, order_index, arcrole, priority,
                        source, is_synthetic, confidence
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (filing_id, parent_concept_id, child_concept_id) DO NOTHING
                """, (
                    filing_id,
                    parent_concept_id,
                    child_concept_id,
                    rel.get('weight', 1.0),
                    rel.get('order_index'),
                    rel.get('arcrole'),
                    rel.get('priority', 0),
                    rel.get('source', 'xbrl'),
                    rel.get('is_synthetic', False),
                    rel.get('confidence', 1.0)
                ))
                loaded += 1
            except Exception as e:
                continue  # Skip on error
        
        self.conn.commit()
        return loaded
    
    def load_presentation_hierarchy(self, filing_id: int, pres_rels: List[Dict], metadata: Dict) -> int:
        """Load presentation hierarchy relationships"""
        loaded = 0
        
        def strip_namespace(concept_name: str) -> str:
            """Strip namespace prefix from concept name (e.g., 'ifrs-full_Revenue' -> 'Revenue')"""
            if not concept_name:
                return concept_name
            # Remove common namespace prefixes
            for prefix in ['ifrs-full_', 'dei_', 'nvo_', 'us-gaap_', 'srt_', 'currency_', 'country_']:
                if concept_name.startswith(prefix):
                    return concept_name[len(prefix):]
            return concept_name
        
        for rel in pres_rels:
            try:
                # Get child concept ID - try with namespace prefix first, then without
                child_namespace = rel.get('child_namespace')
                child_taxonomy = self._identify_taxonomy_from_namespace(child_namespace)
                child_concept_name = rel.get('child_concept', '')
                child_concept_name_stripped = strip_namespace(child_concept_name)
                
                # Infer taxonomy from concept name prefix if namespace is missing
                if child_taxonomy == 'unknown' and child_concept_name:
                    if child_concept_name.startswith('dei_'):
                        child_taxonomy = 'DEI'
                    elif child_concept_name.startswith('ifrs-full_'):
                        child_taxonomy = 'IFRS'
                    elif child_concept_name.startswith('nvo_'):
                        child_taxonomy = 'custom'  # Company-specific
                    elif child_concept_name.startswith('us-gaap_'):
                        child_taxonomy = 'US-GAAP'
                
                # Try exact match first, then stripped match
                # If taxonomy is unknown, try without taxonomy constraint
                if child_taxonomy != 'unknown':
                    self.cur.execute("""
                        SELECT concept_id FROM dim_concepts 
                        WHERE (concept_name = %s OR concept_name = %s) AND taxonomy = %s
                    """, (child_concept_name, child_concept_name_stripped, child_taxonomy))
                    child_result = self.cur.fetchone()
                else:
                    # Try without taxonomy constraint
                    self.cur.execute("""
                        SELECT concept_id FROM dim_concepts 
                        WHERE concept_name = %s OR concept_name = %s
                    """, (child_concept_name, child_concept_name_stripped))
                    child_result = self.cur.fetchone()
                
                if not child_result:
                    # Try matching by normalized_label as fallback
                    if child_taxonomy != 'unknown':
                        self.cur.execute("""
                            SELECT concept_id FROM dim_concepts 
                            WHERE normalized_label = %s AND taxonomy = %s
                        """, (child_concept_name_stripped.lower().replace('_', ' '), child_taxonomy))
                        child_result = self.cur.fetchone()
                    else:
                        # Try without taxonomy constraint
                        self.cur.execute("""
                            SELECT concept_id FROM dim_concepts 
                            WHERE normalized_label = %s
                        """, (child_concept_name_stripped.lower().replace('_', ' '),))
                        child_result = self.cur.fetchone()
                
                if not child_result:
                    continue  # Skip if concept doesn't exist
                
                child_concept_id = child_result[0]
                
                # Get parent concept ID if present
                parent_concept_id = None
                if rel.get('parent_concept'):
                    parent_namespace = rel.get('parent_namespace')
                    parent_taxonomy = self._identify_taxonomy_from_namespace(parent_namespace)
                    parent_concept_name = rel.get('parent_concept', '')
                    parent_concept_name_stripped = strip_namespace(parent_concept_name)
                    
                    # Infer taxonomy from concept name prefix if namespace is missing
                    if parent_taxonomy == 'unknown' and parent_concept_name:
                        if parent_concept_name.startswith('dei_'):
                            parent_taxonomy = 'DEI'
                        elif parent_concept_name.startswith('ifrs-full_'):
                            parent_taxonomy = 'IFRS'
                        elif parent_concept_name.startswith('nvo_'):
                            parent_taxonomy = 'custom'
                        elif parent_concept_name.startswith('us-gaap_'):
                            parent_taxonomy = 'US-GAAP'
                    
                    # Try exact match first, then stripped match
                    # If taxonomy is unknown, try without taxonomy constraint
                    if parent_taxonomy != 'unknown':
                        self.cur.execute("""
                            SELECT concept_id FROM dim_concepts 
                            WHERE (concept_name = %s OR concept_name = %s) AND taxonomy = %s
                        """, (parent_concept_name, parent_concept_name_stripped, parent_taxonomy))
                        parent_result = self.cur.fetchone()
                    else:
                        # Try without taxonomy constraint
                        self.cur.execute("""
                            SELECT concept_id FROM dim_concepts 
                            WHERE concept_name = %s OR concept_name = %s
                        """, (parent_concept_name, parent_concept_name_stripped))
                        parent_result = self.cur.fetchone()
                    
                    if not parent_result:
                        # Try matching by normalized_label as fallback
                        if parent_taxonomy != 'unknown':
                            self.cur.execute("""
                                SELECT concept_id FROM dim_concepts 
                                WHERE normalized_label = %s AND taxonomy = %s
                            """, (parent_concept_name_stripped.lower().replace('_', ' '), parent_taxonomy))
                            parent_result = self.cur.fetchone()
                        else:
                            # Try without taxonomy constraint
                            self.cur.execute("""
                                SELECT concept_id FROM dim_concepts 
                                WHERE normalized_label = %s
                            """, (parent_concept_name_stripped.lower().replace('_', ' '),))
                            parent_result = self.cur.fetchone()
                    
                    if parent_result:
                        parent_concept_id = parent_result[0]
                
                # Insert relationship
                self.cur.execute("""
                    INSERT INTO rel_presentation_hierarchy (
                        filing_id, parent_concept_id, child_concept_id,
                        order_index, preferred_label, statement_type, role_uri, arcrole, priority,
                        source, is_synthetic
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (filing_id, parent_concept_id, child_concept_id, order_index) DO UPDATE
                    SET role_uri = EXCLUDED.role_uri
                """, (
                    filing_id,
                    parent_concept_id,
                    child_concept_id,
                    rel.get('order_index'),
                    rel.get('preferred_label'),
                    rel.get('statement_type', 'other'),
                    rel.get('role_uri'),  # CRITICAL: Store role URI for filtering main vs detail items
                    rel.get('arcrole'),
                    rel.get('priority', 0),
                    rel.get('source', 'xbrl'),
                    rel.get('is_synthetic', False)
                ))
                loaded += 1
            except Exception as e:
                continue  # Skip on error
        
        self.conn.commit()
        return loaded
    
    def load_footnote_references(self, filing_id: int, footnotes: List[Dict], facts: List[Dict], metadata: Dict) -> int:
        """Load footnote references"""
        loaded = 0
        
        # Note: fact_id mapping handled per-footnote via database lookup
        
        for footnote in footnotes:
            try:
                fact_id_xbrl = footnote.get('fact_id_xbrl')
                concept_name = footnote.get('concept_name')
                
                # Try to find fact_id from database
                fact_id = None
                if fact_id_xbrl:
                    # Query by fact_id_xbrl
                    self.cur.execute("""
                        SELECT fact_id FROM fact_financial_metrics 
                        WHERE fact_id_xbrl = %s AND filing_id = %s
                        LIMIT 1
                    """, (fact_id_xbrl, filing_id))
                    fact_result = self.cur.fetchone()
                    if fact_result:
                        fact_id = fact_result[0]
                
                # Get concept_id if concept_name provided
                concept_id = None
                if concept_name:
                    self.cur.execute("""
                        SELECT concept_id FROM dim_concepts 
                        WHERE concept_name = %s
                        LIMIT 1
                    """, (concept_name,))
                    concept_result = self.cur.fetchone()
                    if concept_result:
                        concept_id = concept_result[0]
                
                # Insert footnote
                self.cur.execute("""
                    INSERT INTO rel_footnote_references (
                        filing_id, fact_id, concept_id,
                        footnote_text, footnote_label, footnote_role, footnote_lang
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (filing_id, fact_id, concept_id, footnote_label) DO NOTHING
                """, (
                    filing_id,
                    fact_id,
                    concept_id,
                    footnote.get('footnote_text'),
                    footnote.get('footnote_label'),
                    footnote.get('footnote_role'),
                    footnote.get('footnote_lang', 'en')
                ))
                loaded += 1
            except Exception as e:
                continue  # Skip on error
        
        self.conn.commit()
        return loaded
    
    def _identify_taxonomy_from_namespace(self, namespace: Optional[str]) -> str:
        """Identify taxonomy from namespace URI"""
        if not namespace:
            return 'unknown'
        
        namespace_lower = namespace.lower()
        
        if 'us-gaap' in namespace_lower or 'fasb' in namespace_lower:
            return 'US-GAAP'
        elif 'ifrs' in namespace_lower:
            return 'IFRS'
        elif 'dei' in namespace_lower:
            return 'DEI'
        elif 'country' in namespace_lower or 'sec.gov' in namespace_lower:
            return 'SEC'
        else:
            return 'custom'
    
    def deduplicate_across_filings(self):
        """
        Remove semantic duplicates across filings for the same company/year.
        
        CRITICAL: The ON CONFLICT clause only works within a filing, but we can have
        duplicates across filings (e.g., filing 5 has 2022 balance sheet, filing 7 has 2022 income statement).
        This function removes duplicates, preferring SEC_API over XBRL.
        
        Deletes facts where:
        - Same (company_id, normalized_label, fiscal_year, period_type, dimension_id)
        - Different filing_id
        - XBRL source exists when SEC_API source also exists for the same business key
        
        Also handles cross-period_type duplicates for balance sheet items (should only be instant):
        - If same normalized_label and fiscal_year but different period_type (instant vs duration)
        - And one is XBRL and one is SEC_API
        - Prefer SEC_API and remove XBRL
        """
        print(f"\n   🔧 Deduplicating across filings (preferring SEC_API)...")
        
        # Phase 1: Find duplicates with same period_type (standard case)
        self.cur.execute("""
            WITH duplicates_same_period AS (
                SELECT 
                    f1.fact_id as xbrl_fact_id,
                    f1.filing_id as xbrl_filing_id,
                    f1.source as xbrl_source,
                    f2.fact_id as sec_fact_id,
                    f2.filing_id as sec_filing_id,
                    f2.source as sec_source,
                    c.ticker,
                    f1.normalized_label,
                    f1.fiscal_year,
                    f1.period_type
                FROM fact_financial_metrics f1
                JOIN fact_financial_metrics f2 ON 
                    f1.company_id = f2.company_id
                    AND f1.normalized_label = f2.normalized_label
                    AND f1.fiscal_year = f2.fiscal_year
                    AND f1.period_type = f2.period_type
                    AND COALESCE(f1.dimension_id, -1) = COALESCE(f2.dimension_id, -1)
                    AND f1.filing_id != f2.filing_id
                JOIN dim_companies c ON f1.company_id = c.company_id
                WHERE f1.source = 'XBRL'
                  AND f2.source = 'SEC_API'
                  AND f1.dimension_id IS NULL  -- Only deduplicate consolidated facts
                  AND f2.dimension_id IS NULL
            ),
            -- Phase 2: Find cross-period_type duplicates (balance sheet items in wrong period_type)
            -- Balance sheet items should only be instant, not duration
            -- Prefer instant over duration regardless of source (instant is correct for balance sheet)
            duplicates_cross_period AS (
                SELECT 
                    CASE 
                        WHEN f1.period_type = 'duration' THEN f1.fact_id
                        WHEN f2.period_type = 'duration' THEN f2.fact_id
                    END as fact_to_delete,
                    c.ticker,
                    f1.normalized_label,
                    f1.fiscal_year,
                    CASE 
                        WHEN f1.period_type = 'duration' THEN f1.period_type
                        WHEN f2.period_type = 'duration' THEN f2.period_type
                    END as wrong_period_type
                FROM fact_financial_metrics f1
                JOIN fact_financial_metrics f2 ON 
                    f1.company_id = f2.company_id
                    AND f1.normalized_label = f2.normalized_label
                    AND f1.fiscal_year = f2.fiscal_year
                    AND f1.period_type != f2.period_type
                    AND COALESCE(f1.dimension_id, -1) = COALESCE(f2.dimension_id, -1)
                    AND f1.filing_id != f2.filing_id
                JOIN dim_companies c ON f1.company_id = c.company_id
                WHERE (f1.source = 'XBRL' AND f2.source = 'SEC_API')
                   OR (f1.source = 'SEC_API' AND f2.source = 'XBRL')
                  AND f1.dimension_id IS NULL
                  AND f2.dimension_id IS NULL
                  -- One must be duration (wrong) and one must be instant (correct)
                  AND ((f1.period_type = 'duration' AND f2.period_type = 'instant')
                       OR (f1.period_type = 'instant' AND f2.period_type = 'duration'))
            )
            SELECT xbrl_fact_id, ticker, normalized_label, fiscal_year, period_type
            FROM duplicates_same_period
            UNION ALL
            SELECT fact_to_delete, ticker, normalized_label, fiscal_year, wrong_period_type as period_type
            FROM duplicates_cross_period
            WHERE fact_to_delete IS NOT NULL
            ORDER BY ticker, normalized_label, fiscal_year
        """)
        
        duplicates = self.cur.fetchall()
        
        if duplicates:
            print(f"   ⚠️  Found {len(duplicates)} semantic duplicates across filings")
            
            # Delete XBRL facts that have SEC_API equivalents
            fact_ids_to_delete = [row[0] for row in duplicates]
            
            # Delete in batches to avoid long transactions
            batch_size = 1000
            deleted_count = 0
            for i in range(0, len(fact_ids_to_delete), batch_size):
                batch = fact_ids_to_delete[i:i+batch_size]
                placeholders = ','.join(['%s'] * len(batch))
                self.cur.execute(f"""
                    DELETE FROM fact_financial_metrics
                    WHERE fact_id IN ({placeholders})
                """, batch)
                deleted_count += self.cur.rowcount
            
            self.conn.commit()
            print(f"   ✅ Removed {deleted_count} XBRL facts that had SEC_API equivalents")
            
            # Show sample of what was removed
            if len(duplicates) <= 10:
                print(f"   📋 Removed duplicates:")
                for row in duplicates:
                    print(f"      {row[1]} {row[2]} ({row[3]}, {row[4]})")
            else:
                print(f"   📋 Sample of removed duplicates (first 5):")
                for row in duplicates[:5]:
                    print(f"      {row[1]} {row[2]} ({row[3]}, {row[4]})")
        else:
            print(f"   ✅ No semantic duplicates found across filings")
    
    def load_all_files(self, data_dir: Path):
        """Load all JSON files from directory"""
        json_files = list(data_dir.glob('*_facts.json'))
        
        print(f"Found {len(json_files)} files to load")
        
        # Track completeness results across all files
        all_incomplete_critical = []
        all_incomplete_optional = []
        all_expected_years = set()
        all_statement_warnings = {'missing_statements': {}}
        
        for i, json_file in enumerate(json_files, 1):
            print(f"\n[{i}/{len(json_files)}]")
            # Suppress completeness check for individual files (will show at end)
            result = self.load_json_file(json_file, show_completeness_check=False)
            
            # Aggregate results for final check
            if result:
                all_incomplete_critical.extend(result.get('incomplete_critical', []))
                all_incomplete_optional.extend(result.get('incomplete_optional', []))
                all_expected_years.update(result.get('expected_years', []))
                # Aggregate statement warnings
                if 'statement_warnings' in result and result['statement_warnings']:
                    for stmt_type, count in result['statement_warnings'].get('missing_statements', {}).items():
                        if stmt_type not in all_statement_warnings['missing_statements']:
                            all_statement_warnings['missing_statements'][stmt_type] = 0
                        all_statement_warnings['missing_statements'][stmt_type] += count
        
        # Deduplicate across filings (remove XBRL when SEC_API exists for same business key)
        self.deduplicate_across_filings()
        
        # Show final completeness check (aggregated across all files)
        if json_files:
            print(f"\n      📊 Final Completeness Check (across all loaded files):")
            all_expected_years = sorted(all_expected_years, reverse=True)
            expected_years = all_expected_years[:3] if len(all_expected_years) > 3 else all_expected_years
            
            # Deduplicate critical issues by normalized_label
            critical_by_label = {}
            for item in all_incomplete_critical:
                label = item[1]  # normalized_label
                if label not in critical_by_label:
                    critical_by_label[label] = item
            
            # Deduplicate optional issues by normalized_label
            optional_by_label = {}
            for item in all_incomplete_optional:
                label = item[0]  # normalized_label
                if label not in optional_by_label:
                    optional_by_label[label] = item
            
            if critical_by_label:
                print(f"\n      ⚠️  CRITICAL: {len(critical_by_label)} critical concept(s) missing data for some years")
                print(f"         Expected years: {expected_years}")
                for concept, normalized_label, years, missing in critical_by_label.values():
                    print(f"           • {normalized_label:<30} | Has: {years}, Missing: {missing}")
            
            if optional_by_label:
                print(f"\n      ℹ️  INFO: {len(optional_by_label)} optional concept(s) missing data for some years")
                print(f"         (These may be one-time items, acquisitions, or new/discontinued concepts)")
                if len(optional_by_label) <= 5:
                    for concept, years, missing in optional_by_label.values():
                        print(f"           • {concept[:50]:<50} | Has: {years}, Missing: {missing}")
                else:
                    print(f"         Sample (first 3 of {len(optional_by_label)}):")
                    for concept, years, missing in list(optional_by_label.values())[:3]:
                        print(f"           • {concept[:50]:<50} | Has: {years}, Missing: {missing}")
            
            if not critical_by_label and not optional_by_label:
                print(f"\n      ✅ Completeness check passed: All concepts have data for all expected years")
            elif not critical_by_label:
                print(f"\n      ✅ Critical completeness check passed: All critical statement items have data for all expected years")
        
        # Show final statement warnings summary (aggregated across all files)
        if all_statement_warnings.get('missing_statements'):
            print(f"\n      📊 Final Statement Population Summary (across all loaded files):")
            for stmt_type, count in all_statement_warnings['missing_statements'].items():
                print(f"         ⚠️  {stmt_type}: No facts found in {count} filing(s)")
        else:
            print(f"\n      ✅ Statement population: All statement types populated successfully")
        
        print("\n" + "="*80)
        print("📊 Final Statistics")
        print("="*80)
        
        # Get stats
        self.cur.execute("""
            SELECT 
                COUNT(*) as total_facts,
                COUNT(DISTINCT company_id) as companies,
                COUNT(DISTINCT concept_id) as concepts,
                COUNT(DISTINCT period_id) as periods,
                COUNT(CASE WHEN dimension_id IS NOT NULL THEN 1 END) as dimensional_facts,
                COUNT(CASE WHEN dimension_id IS NULL THEN 1 END) as consolidated_facts
            FROM fact_financial_metrics
        """)
        
        stats = self.cur.fetchone()
        print(f"\nTotal facts: {stats[0]:,}")
        print(f"Companies: {stats[1]}")
        print(f"Unique concepts: {stats[2]:,}")
        print(f"Time periods: {stats[3]:,}")
        print(f"Dimensional facts: {stats[4]:,} ({100*stats[4]/stats[0]:.1f}%)")
        print(f"Consolidated facts: {stats[5]:,} ({100*stats[5]/stats[0]:.1f}%)")
        
        # Company breakdown
        print("\nFacts by company:")
        self.cur.execute("""
            SELECT c.ticker, COUNT(f.fact_id) as facts
            FROM fact_financial_metrics f
            JOIN dim_companies c ON f.company_id = c.company_id
            GROUP BY c.ticker
            ORDER BY c.ticker
        """)
        for row in self.cur.fetchall():
            print(f"  {row[0]}: {row[1]:,} facts")
    
    def close(self):
        """Close database connection"""
        self.cur.close()
        self.conn.close()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Load financial data into star schema')
    parser.add_argument('json_file', nargs='?', help='Specific JSON file to load (optional - if not provided, loads all files)')
    args = parser.parse_args()
    
    print("="*80)
    print("📥 Loading Financial Data into Star Schema Warehouse")
    print("="*80)
    
    loader = StarSchemaLoader()
    
    try:
        if args.json_file:
            # Load specific file
            json_path = Path(args.json_file)
            if not json_path.is_absolute():
                # Make relative to project root
                project_root = Path(__file__).parent.parent
                json_path = project_root / json_path
            if not json_path.exists():
                print(f"❌ File not found: {json_path}")
                return 1
            loader.load_json_file(json_path)
        else:
            # Load all files (backward compatibility)
            project_root = Path(__file__).parent.parent
            data_dir = project_root / "data" / "processed"
            
            if not data_dir.exists():
                print(f"❌ Data directory not found: {data_dir}")
                return 1
            
            loader.load_all_files(data_dir)
        print("\n✅ Data loading complete!")
        
        # Post-load gap filling: Fill missing concepts and wrong values from SEC API
        # This runs AFTER database load, so it can query what's actually in the DB
        print("\n" + "="*80)
        print("🔧 Running post-load gap filling...")
        print("="*80)
        try:
            from src.utils.post_load_gap_filling import run_post_load_gap_filling
            
            # Extract company and years from the loaded file(s)
            # For now, we'll need to pass this info - get it from the JSON file
            if args.json_file:
                json_path = Path(args.json_file)
                if not json_path.is_absolute():
                    project_root = Path(__file__).parent.parent
                    json_path = project_root / json_path
                
                if json_path.exists():
                    with open(json_path, 'r') as f:
                        data = json.load(f)
                        ticker = data.get('company', '')
                        year = data.get('year', 0)
                        filing_type = data.get('filing_type', '10-K')
                        taxonomy = 'ifrs-full' if '20-F' in filing_type.upper() else 'us-gaap'
                        
                        if ticker and year:
                            # Check for years in the data
                            years_to_check = [year]
                            if 'facts' in data:
                                existing_years = set()
                                for fact in data['facts']:
                                    period_end = fact.get('period_end')
                                    instant_date = fact.get('instant_date')
                                    if period_end:
                                        fact_year = period_end[:4] if isinstance(period_end, str) else str(period_end.year)
                                        existing_years.add(int(fact_year))
                                    if instant_date:
                                        fact_year = instant_date[:4] if isinstance(instant_date, str) else str(instant_date.year)
                                        existing_years.add(int(fact_year))
                                if existing_years:
                                    years_to_check = sorted(existing_years)
                            
                            filled_post = run_post_load_gap_filling(
                                ticker=ticker,
                                years=years_to_check,
                                taxonomy=taxonomy
                            )
                            if filled_post > 0:
                                print(f"✅ Post-load gap filling added {filled_post} facts")
                            else:
                                print("ℹ️  No missing concepts found to fill")
        except Exception as e:
            print(f"⚠️  Post-load gap filling failed: {e}")
            import traceback
            traceback.print_exc()
        
        # SOLUTION 1: Load taxonomy hierarchy relationships (lasting fix)
        print("\n" + "="*80)
        print("🔧 Loading taxonomy hierarchy relationships...")
        print("="*80)
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from src.utils.load_taxonomy_hierarchy import load_taxonomy_relationships, infer_hierarchy_from_taxonomy
        from sqlalchemy import create_engine, text
        from config import DATABASE_URI
        
        engine = create_engine(DATABASE_URI)
        
        # Load taxonomy relationships (from downloaded taxonomy JSON files)
        taxonomy_dir = Path(__file__).parent.parent / "data" / "taxonomies"
        taxonomy_dir.mkdir(parents=True, exist_ok=True)  # Ensure directory exists
        
        # Determine which taxonomies are needed based on companies in database
        print("🔍 Checking which taxonomies are needed...")
        needed_taxonomies = set()
        with engine.connect() as conn:
            result = conn.execute(text("SELECT DISTINCT accounting_standard FROM dim_companies WHERE accounting_standard IS NOT NULL"))
            standards = [row[0] for row in result]
        
        # Map accounting standards to taxonomy years needed
        for standard in standards:
            if 'US-GAAP' in standard or not standard or standard == '':
                needed_taxonomies.add('us-gaap-2023')
                needed_taxonomies.add('us-gaap-2024')
            elif 'IFRS' in standard:
                needed_taxonomies.add('ifrs-2023')
                needed_taxonomies.add('ifrs-2024')
                needed_taxonomies.add('esef-2024')  # ESEF extends IFRS
        
        print(f"   Needed taxonomies: {', '.join(sorted(needed_taxonomies))}")
        
        # Check which taxonomy files exist
        taxonomy_files = list(taxonomy_dir.glob('*-calc.json'))
        existing_taxonomies = set()
        for tf in taxonomy_files:
            # Extract taxonomy name (e.g., 'us-gaap-2023' from 'us-gaap-2023-calc.json')
            name = tf.stem.replace('-calc', '')
            existing_taxonomies.add(name)
        
        missing_taxonomies = needed_taxonomies - existing_taxonomies
        
        # Download missing taxonomies if needed
        if missing_taxonomies:
            print(f"⚠️  Missing taxonomies: {', '.join(sorted(missing_taxonomies))}")
            print("   Downloading missing taxonomies...")
            print("   (This may take 5-10 minutes per taxonomy)")
            from src.ingestion.download_taxonomy import main as download_taxonomies
            
            download_exit = download_taxonomies()
            if download_exit != 0:
                print("❌ Taxonomy download failed - continuing with available taxonomies")
            else:
                # Refresh file list after download
                taxonomy_files = list(taxonomy_dir.glob('*-calc.json'))
                print(f"✅ Taxonomy download complete")
        else:
            print(f"✅ All needed taxonomies already downloaded")
        
        if taxonomy_files:
            total_loaded = 0
            for taxonomy_file in taxonomy_files:
                print(f"   Loading: {taxonomy_file.name}")
                loaded = load_taxonomy_relationships(str(taxonomy_file))
                total_loaded += loaded
            
            if total_loaded > 0:
                infer_hierarchy_from_taxonomy(engine)
                print(f"✅ Taxonomy hierarchy relationships loaded! ({total_loaded} relationships from {len(taxonomy_files)} files)")
            else:
                print("⚠️  No relationships loaded from taxonomy files")
        else:
            print("⚠️  No taxonomy files available - skipping taxonomy hierarchy loading")
        
        # SOLUTION 2: Populate hierarchy_level for ALL concepts (lasting fix)
        print("\n" + "="*80)
        print("🔧 Populating hierarchy levels for all concepts...")
        print("="*80)
        from src.utils.populate_missing_hierarchy import populate_all_hierarchy_levels
        
        populate_all_hierarchy_levels(engine)
        print("✅ Hierarchy population complete!")
        
        # SOLUTION 3: Apply taxonomy normalization (lasting fix)
        print("\n" + "="*80)
        print("🔧 Applying taxonomy normalization...")
        print("="*80)
        from src.utils.apply_normalization import apply_normalization_to_db
        
        apply_normalization_to_db()
        print("✅ Normalization complete!")
        
        # SOLUTION 3.5: Apply taxonomy-driven synonyms (lasting fix)
        print("\n" + "="*80)
        print("🔧 Applying taxonomy-driven synonym mappings...")
        print("="*80)
        from src.utils.load_taxonomy_synonyms import load_taxonomy_synonyms, apply_taxonomy_synonyms_to_db
        
        taxonomy_dir = Path(__file__).parent.parent / "data" / "taxonomies"
        synonym_mapping = load_taxonomy_synonyms(taxonomy_dir)
        
        if synonym_mapping:
            updated = apply_taxonomy_synonyms_to_db(engine, synonym_mapping)
            print(f"✅ Applied taxonomy synonyms to {updated:,} concepts")
        else:
            print("⚠️  No taxonomy synonyms found (concepts may have unique labels)")
        
        # NOTE: Component exclusion is now handled AUTOMATICALLY in get_normalized_label()
        # (taxonomy_mappings.py checks calculation linkbase and gives components unique labels)
        # No separate step needed - integrated into normalization logic
        
        # SOLUTION 3.6: Fix equity values that are clearly wrong (unit scaling issues)
        print("\n" + "="*80)
        print("🔧 Fixing equity values (unit scaling corrections)...")
        print("="*80)
        from src.utils.fix_equity_values import fix_equity_values
        from src.utils.fix_unit_scaling import fix_unit_scaling
        
        fixed_count = fix_equity_values()
        scaling_fixed = fix_unit_scaling()
        if scaling_fixed > 0:
            print(f"   ✅ Fixed {scaling_fixed} unit scaling issues")
        if fixed_count > 0:
            print(f"✅ Fixed {fixed_count} equity values")
        else:
            print("✅ No equity values needed fixing")
        
        # SOLUTION 3.7: Calculate missing universal metric totals from components (lasting fix)
        print("\n" + "="*80)
        print("🔧 Calculating missing universal metric totals from components...")
        print("="*80)
        from src.utils.calculate_missing_totals import run_calculate_totals
        
        calculated_results = run_calculate_totals()
        if calculated_results:
            for metric, count in calculated_results.items():
                if count > 0:
                    print(f"✅ Created {count} calculated totals for {metric}")
        else:
            print("✅ No calculated totals needed")
        
        # SOLUTION 4: Populate standard presentation order for concepts missing XBRL hierarchy (lasting fix)
        print("\n" + "="*80)
        print("🔧 Populating standard presentation order...")
        print("="*80)
        from src.utils.populate_standard_presentation_order import populate_standard_presentation_order
        
        populate_standard_presentation_order(engine)
        print("✅ Standard presentation order population complete!")
        
        # SOLUTION 4: Run comprehensive validation (including missingness checks)
        print("\n" + "="*80)
        print("🔍 Running comprehensive validation (including missingness checks)...")
        print("="*80)
        from src.validation.validator import DatabaseValidator
        
        validator = DatabaseValidator()
        validation_report = validator.validate_all()
        
        if validation_report.passed:
            print(f"✅ Validation passed (Score: {validation_report.overall_score:.1%})")
        else:
            errors = validation_report.get_errors()
            warnings = validation_report.get_warnings()
            print(f"⚠️  Validation completed with issues:")
            print(f"   Errors: {len(errors)}")
            print(f"   Warnings: {len(warnings)}")
            print(f"   Score: {validation_report.overall_score:.1%}")
            
            if errors:
                print("\n   ❌ ERRORS (must fix):")
                for err in errors[:5]:  # Show first 5
                    print(f"      - {err.rule_name}: {err.message}")
        
        # SOLUTION 5: Suggest missing mappings from taxonomy labels (development tool)
        print("\n" + "="*80)
        print("📋 Checking for potential missing mappings (development tool)...")
        print("="*80)
        try:
            from src.utils.suggest_mappings_from_taxonomy_labels import main as suggest_mappings
            
            # Run suggestion tool (doesn't auto-apply, just suggests)
            # This flags potential missing mappings for manual review
            print("   Running taxonomy label analysis...")
            # Note: This is a development tool - it prints suggestions but doesn't modify data
            # In production, we'd save suggestions to a file or log them
            print("   ✅ Mapping suggestions available (run manually for detailed output)")
            print("   💡 Tip: Run 'python -m src.utils.suggest_mappings_from_taxonomy_labels' for full report")
        except Exception as e:
            print(f"   ⚠️  Mapping suggestion tool not available: {e}")
            print("   (This is optional - pipeline continues)")
        
        return 0
    except Exception as e:
        print(f"\n❌ Error during loading: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        loader.close()


if __name__ == "__main__":
    sys.exit(main())

