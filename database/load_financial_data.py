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
        self.cur.execute("SELECT company_id FROM dim_companies WHERE ticker = %s", (ticker,))
        result = self.cur.fetchone()
        if result:
            return result[0]
        
        # Create new
        self.cur.execute("""
            INSERT INTO dim_companies (ticker, company_name, accounting_standard)
            VALUES (%s, %s, %s)
            RETURNING company_id
        """, (ticker, metadata.get('company_name', ticker), metadata.get('taxonomy', 'US-GAAP')))
        
        company_id = self.cur.fetchone()[0]
        self.conn.commit()
        return company_id
    
    def get_or_create_concept(self, concept_name: str, taxonomy: str, metadata: Dict) -> int:
        """Get or create concept_id"""
        # Check if exists
        self.cur.execute(
            "SELECT concept_id FROM dim_concepts WHERE concept_name = %s AND taxonomy = %s",
            (concept_name, taxonomy)
        )
        result = self.cur.fetchone()
        if result:
            return result[0]
        
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
            metadata.get('statement_type', 'other')
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
            fiscal_year = int(end_date[:4])
        elif instant_date:
            fiscal_year = int(instant_date[:4])
        
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
                ON CONFLICT (filing_id, concept_id, period_id, dimension_id, fact_id_xbrl) 
                DO UPDATE SET
                    value_numeric = EXCLUDED.value_numeric,
                    value_text = EXCLUDED.value_text,
                    is_primary = EXCLUDED.is_primary
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
    
    data_dir = Path("/Users/jonas/FinSight/data/processed")
    
    if not data_dir.exists():
        print(f"❌ Data directory not found: {data_dir}")
        return 1
    
    loader = StarSchemaLoader()
    
    try:
        loader.load_all_files(data_dir)
        print("\n✅ Data loading complete!")
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

