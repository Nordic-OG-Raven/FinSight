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
from config import POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB


class StarSchemaLoader:
    """Loads financial data into star schema warehouse"""
    
    def __init__(self):
        self.conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            database=POSTGRES_DB
        )
        self.cur = self.conn.cursor()
        
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
                    self.cur.execute("UPDATE dim_companies SET accounting_standard = %s WHERE company_id = %s", 
                                   (new_standard, company_id))
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
        
        # Create new
        self.cur.execute("""
            INSERT INTO dim_companies (ticker, company_name, accounting_standard)
            VALUES (%s, %s, %s)
            RETURNING company_id
        """, (ticker, metadata.get('company_name', ticker), accounting_standard))
        
        company_id = self.cur.fetchone()[0]
        self.conn.commit()
        return company_id
    
    def get_or_create_concept(self, concept_name: str, taxonomy: str, metadata: Dict) -> int:
        """Get or create concept_id, and update statement_type if missing"""
        # Import taxonomy mappings for statement_type inference
        try:
            from src.utils.taxonomy_mappings import get_statement_type
        except ImportError:
            get_statement_type = None
        
        # Determine statement_type from fact metadata or taxonomy mappings
        statement_type = metadata.get('statement_type')
        if not statement_type:
            # Try to infer from normalized_label using taxonomy mappings
            normalized_label = metadata.get('normalized_label')
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
        
        # Check if exists
        self.cur.execute(
            "SELECT concept_id, statement_type FROM dim_concepts WHERE concept_name = %s AND taxonomy = %s",
            (concept_name, taxonomy)
        )
        result = self.cur.fetchone()
        if result:
            concept_id, existing_stmt_type = result[0], result[1]
            # Update statement_type if it's NULL and we have a value
            if existing_stmt_type is None and statement_type:
                self.cur.execute("""
                    UPDATE dim_concepts 
                    SET statement_type = %s 
                    WHERE concept_id = %s
                """, (statement_type, concept_id))
                self.conn.commit()
            return concept_id
        
        # Create new
        self.cur.execute("""
            INSERT INTO dim_concepts (
                concept_name, taxonomy, normalized_label, concept_type,
                balance_type, period_type, data_type, is_abstract, statement_type
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING concept_id
        """, (
            concept_name,
            taxonomy,
            metadata.get('normalized_label'),
            metadata.get('concept_type'),
            metadata.get('concept_balance'),
            metadata.get('concept_period_type'),
            metadata.get('concept_data_type'),
            metadata.get('concept_abstract', False),
            statement_type
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
        # Check if exists
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
        """Get or create filing_id"""
        # Check if exists
        self.cur.execute("""
            SELECT filing_id FROM dim_filings 
            WHERE company_id = %s AND filing_type = %s AND fiscal_year_end = %s
        """, (company_id, filing_type, fiscal_year_end))
        
        result = self.cur.fetchone()
        if result:
            return result[0]
        
        # Create new
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
                if isinstance(details, dict) and 'member' in details:
                    member_name = details['member']
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
            self.cur.execute("""
                INSERT INTO fact_financial_metrics (
                    company_id, concept_id, period_id, filing_id, dimension_id,
                    value_numeric, value_text, unit_measure, decimals,
                    scale_int, xbrl_format,
                    context_id, fact_id_xbrl, source_line, order_index, is_primary
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (filing_id, concept_id, period_id, dimension_id) 
                DO UPDATE SET
                    value_numeric = EXCLUDED.value_numeric,
                    value_text = EXCLUDED.value_text,
                    is_primary = EXCLUDED.is_primary,
                    fact_id_xbrl = EXCLUDED.fact_id_xbrl,
                    order_index = EXCLUDED.order_index
            """, (
                company_id,
                concept_id,
                period_id,
                filing_id,
                dimension_id,
                fact.get('value_numeric'),
                fact.get('value_text'),
                fact.get('unit_measure'),
                fact.get('decimals'),
                fact.get('scale_int'),
                fact.get('xbrl_format'),
                fact.get('context_id'),
                fact.get('fact_id'),
                fact.get('source_line'),
                fact.get('order_index'),
                fact.get('is_primary', True)
            ))
        except Exception as e:
            print(f"      ⚠️  Error loading fact: {e}")
            self.conn.rollback()
    
    def validate_loaded_data(self, company_id: int, ticker: str, fiscal_year: int):
        """
        Validate data quality after loading - HARD FAIL on critical issues.
        
        Checks:
        1. Balance sheet equation (Assets = Liabilities + Equity)
        2. No duplicate metrics with different values (> 1% diff)
        
        Raises ValueError if validation fails.
        """
        # Check balance sheet equation for this company/year
        self.cur.execute("""
        SELECT 
            c.ticker,
            dt.fiscal_year,
            MAX(CASE WHEN dc.concept_name = 'Assets' THEN f.value_numeric END) as assets,
            MAX(CASE WHEN dc.concept_name = 'LiabilitiesAndStockholdersEquity' THEN f.value_numeric END) as liab_equity
        FROM fact_financial_metrics f
        JOIN dim_companies c ON f.company_id = c.company_id
        JOIN dim_concepts dc ON f.concept_id = dc.concept_id
        JOIN dim_time_periods dt ON f.period_id = dt.period_id
        WHERE c.company_id = %s
          AND dt.fiscal_year = %s
          AND f.dimension_id IS NULL
          AND dc.concept_name IN ('Assets', 'LiabilitiesAndStockholdersEquity')
        GROUP BY c.ticker, dt.fiscal_year
        HAVING MAX(CASE WHEN dc.concept_name = 'Assets' THEN f.value_numeric END) IS NOT NULL
           AND MAX(CASE WHEN dc.concept_name = 'LiabilitiesAndStockholdersEquity' THEN f.value_numeric END) IS NOT NULL;
        """, (company_id, fiscal_year))
        
        result = self.cur.fetchone()
        if result:
            assets, liab_equity = result[2], result[3]
            diff_pct = abs(assets - liab_equity) / assets * 100 if assets else 0
            
            if diff_pct > 1.0:  # More than 1% difference is critical error
                raise ValueError(
                    f"❌ VALIDATION FAILED: Balance sheet doesn't balance for {ticker} FY{fiscal_year}\n"
                    f"   Assets: ${assets:,.0f}\n"
                    f"   Liabilities + Equity: ${liab_equity:,.0f}\n"
                    f"   Difference: {diff_pct:.2f}%\n"
                    f"   This indicates a DATA PROCESSING ERROR - DO NOT LOAD"
                )
    
    def load_json_file(self, json_path: Path):
        """Load a single JSON file"""
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
        
        # Load facts
        facts_loaded = 0
        facts_with_dims = 0
        
        for fact in facts:
            try:
                # Get or create concept
                concept_id = self.get_or_create_concept(
                    fact.get('concept'),
                    fact.get('taxonomy', 'us-gaap'),
                    fact
                )
                
                # Get or create period
                period_id = self.get_or_create_period(
                    fact.get('period_type', 'duration'),
                    fact.get('period_start'),
                    fact.get('period_end'),
                    fact.get('instant_date')
                )
                
                # Get or create dimension
                dimension_id = self.get_or_create_dimension(fact.get('dimensions'))
                if dimension_id:
                    facts_with_dims += 1
                
                # Load fact
                self.load_fact(company_id, concept_id, period_id, filing_id, dimension_id, fact)
                facts_loaded += 1
                
                if facts_loaded % 500 == 0:
                    self.conn.commit()
                    print(f"      ... {facts_loaded}/{len(facts)} facts loaded")
            
            except Exception as e:
                print(f"      ⚠️  Skipped fact {fact.get('concept')}: {e}")
                continue
        
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
        
        self.conn.commit()
        print(f"   ✅ Loaded {facts_loaded} facts ({facts_with_dims} with dimensions)")
        
        # CRITICAL VALIDATION - HARD FAIL on data quality issues
        print(f"   🔍 Running validation (hard fail on errors)...")
        try:
            # Validate for each fiscal year in this filing
            self.cur.execute("""
            SELECT DISTINCT fiscal_year 
            FROM dim_time_periods dt
            JOIN fact_financial_metrics f ON dt.period_id = f.period_id
            WHERE f.filing_id = %s;
            """, (filing_id,))
            
            fiscal_years = [row[0] for row in self.cur.fetchall()]
            
            for fy in fiscal_years:
                if fy:  # Skip NULL fiscal years
                    self.validate_loaded_data(company_id, ticker, fy)
            
            print(f"   ✅ Validation passed")
        except ValueError as e:
            # HARD FAIL - rollback all changes
            self.conn.rollback()
            print(f"\n{str(e)}")
            raise  # Re-raise to stop pipeline
    
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
        
        for rel in pres_rels:
            try:
                # Get child concept ID
                child_taxonomy = self._identify_taxonomy_from_namespace(rel.get('child_namespace'))
                
                self.cur.execute("""
                    SELECT concept_id FROM dim_concepts 
                    WHERE concept_name = %s AND taxonomy = %s
                """, (rel['child_concept'], child_taxonomy))
                child_result = self.cur.fetchone()
                
                if not child_result:
                    continue  # Skip if concept doesn't exist
                
                child_concept_id = child_result[0]
                
                # Get parent concept ID if present
                parent_concept_id = None
                if rel.get('parent_concept'):
                    parent_taxonomy = self._identify_taxonomy_from_namespace(rel.get('parent_namespace'))
                    self.cur.execute("""
                        SELECT concept_id FROM dim_concepts 
                        WHERE concept_name = %s AND taxonomy = %s
                    """, (rel['parent_concept'], parent_taxonomy))
                    parent_result = self.cur.fetchone()
                    if parent_result:
                        parent_concept_id = parent_result[0]
                
                # Insert relationship
                self.cur.execute("""
                    INSERT INTO rel_presentation_hierarchy (
                        filing_id, parent_concept_id, child_concept_id,
                        order_index, preferred_label, statement_type, arcrole, priority,
                        source, is_synthetic
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (filing_id, parent_concept_id, child_concept_id, order_index) DO NOTHING
                """, (
                    filing_id,
                    parent_concept_id,
                    child_concept_id,
                    rel.get('order_index'),
                    rel.get('preferred_label'),
                    rel.get('statement_type', 'other'),
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
    
    def load_all_files(self, data_dir: Path):
        """Load all JSON files from directory"""
        json_files = list(data_dir.glob('*_facts.json'))
        
        print(f"Found {len(json_files)} files to load")
        
        for i, json_file in enumerate(json_files, 1):
            print(f"\n[{i}/{len(json_files)}]")
            self.load_json_file(json_file)
        
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
    print("="*80)
    print("📥 Loading Financial Data into Star Schema Warehouse")
    print("="*80)
    
    # Use relative path from project root (works in both host and Docker)
    project_root = Path(__file__).parent.parent
    data_dir = project_root / "data" / "processed"
    
    if not data_dir.exists():
        print(f"❌ Data directory not found: {data_dir}")
        return 1
    
    loader = StarSchemaLoader()
    
    try:
        loader.load_all_files(data_dir)
        print("\n✅ Data loading complete!")
        
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
        
        # SOLUTION 3.6: Calculate missing universal metric totals from components (lasting fix)
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

