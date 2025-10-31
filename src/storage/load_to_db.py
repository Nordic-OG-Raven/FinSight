#!/usr/bin/env python3
"""
PostgreSQL Storage Module

Creates database schema and loads extracted financial facts into PostgreSQL.
Follows SupersetProjects pattern for database operations.
"""
import sys
import logging
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

import pandas as pd
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.dialects.postgresql import insert

# Add parent directory to path to import config
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import DATABASE_URI, POSTGRES_DB, POSTGRES_USER

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FinancialDataLoader:
    """Load financial facts into PostgreSQL database"""
    
    # SQL for creating the main facts table
    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS financial_facts (
        id SERIAL PRIMARY KEY,
        company VARCHAR(50) NOT NULL,
        filing_type VARCHAR(20),
        fiscal_year_end DATE,
        
        concept TEXT NOT NULL,
        concept_namespace VARCHAR(200),
        taxonomy VARCHAR(50),
        normalized_label VARCHAR(200),
        
        value_text TEXT,
        value_numeric DOUBLE PRECISION,
        
        context_id TEXT,
        period_type VARCHAR(20),
        period_start DATE,
        period_end DATE,
        instant_date DATE,
        
        entity_scheme VARCHAR(100),
        entity_identifier VARCHAR(100),
        dimensions JSONB,
        
        unit_id VARCHAR(50),
        unit_measure VARCHAR(50),
        unit_type VARCHAR(20),
        
        concept_type VARCHAR(50),
        concept_balance VARCHAR(20),
        concept_period_type VARCHAR(20),
        concept_data_type VARCHAR(50),
        concept_abstract BOOLEAN DEFAULT FALSE,
        
        source_line INTEGER,
        source_url TEXT,
        fact_id VARCHAR(100),
        decimals VARCHAR(20),
        precision VARCHAR(20),
        
        extraction_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        UNIQUE(company, filing_type, fiscal_year_end, concept, context_id)
    );
    """
    
    # SQL for creating indexes
    CREATE_INDEXES_SQL = [
        "CREATE INDEX IF NOT EXISTS idx_company ON financial_facts(company);",
        "CREATE INDEX IF NOT EXISTS idx_fiscal_year_end ON financial_facts(fiscal_year_end);",
        "CREATE INDEX IF NOT EXISTS idx_concept ON financial_facts(concept);",
        "CREATE INDEX IF NOT EXISTS idx_taxonomy ON financial_facts(taxonomy);",
        "CREATE INDEX IF NOT EXISTS idx_normalized_label ON financial_facts(normalized_label);",
        "CREATE INDEX IF NOT EXISTS idx_period_end ON financial_facts(period_end);",
        "CREATE INDEX IF NOT EXISTS idx_company_fiscal_year ON financial_facts(company, fiscal_year_end);",
        "CREATE INDEX IF NOT EXISTS idx_dimensions ON financial_facts USING GIN (dimensions);"
    ]
    
    def __init__(self, database_uri: str = DATABASE_URI):
        """
        Initialize database loader
        
        Args:
            database_uri: PostgreSQL connection string
        """
        self.database_uri = database_uri
        self.engine = None
    
    def connect(self):
        """Create database connection"""
        logger.info(f"Connecting to PostgreSQL database...")
        logger.info(f"  Database: {POSTGRES_DB}")
        
        try:
            self.engine = create_engine(self.database_uri)
            # Test connection
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("✅ Database connection successful")
            return True
        except Exception as e:
            logger.error(f"❌ Database connection failed: {e}")
            return False
    
    def create_schema(self):
        """Create database tables and indexes"""
        if not self.engine:
            logger.error("Not connected to database")
            return False
        
        logger.info("Creating database schema...")
        
        try:
            with self.engine.connect() as conn:
                # Create main table
                logger.info("  Creating financial_facts table...")
                conn.execute(text(self.CREATE_TABLE_SQL))
                conn.commit()
                
                # Create indexes
                logger.info("  Creating indexes...")
                for idx_sql in self.CREATE_INDEXES_SQL:
                    conn.execute(text(idx_sql))
                conn.commit()
            
            logger.info("✅ Schema created successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Schema creation failed: {e}")
            return False
    
    def load_facts(
        self, 
        facts: List[Dict[str, Any]], 
        company: str,
        filing_type: str,
        fiscal_year_end: str,
        source_url: str = None
    ) -> int:
        """
        Load facts into database
        
        Args:
            facts: List of fact dictionaries from XBRL parser
            company: Company ticker
            filing_type: Filing type (10-K, 20-F, etc.)
            fiscal_year_end: Fiscal year end date
            source_url: URL of source filing
            
        Returns:
            Number of facts loaded
        """
        if not self.engine:
            logger.error("Not connected to database")
            return 0
        
        if not facts:
            logger.warning("No facts to load")
            return 0
        
        logger.info(f"Loading {len(facts)} facts to database...")
        logger.info(f"  Company: {company}")
        logger.info(f"  Filing: {filing_type}")
        logger.info(f"  Fiscal Year End: {fiscal_year_end}")
        
        # Prepare facts for insertion
        df_facts = pd.DataFrame(facts)
        
        # Add required fields
        df_facts['company'] = company
        df_facts['filing_type'] = filing_type
        df_facts['fiscal_year_end'] = pd.to_datetime(fiscal_year_end).date()
        if source_url:
            df_facts['source_url'] = source_url
        
        # Convert date columns
        date_cols = ['period_start', 'period_end', 'instant_date']
        for col in date_cols:
            if col in df_facts.columns:
                df_facts[col] = pd.to_datetime(df_facts[col], errors='coerce')
        
        # Handle numeric values
        if 'value_numeric' in df_facts.columns:
            df_facts['value_numeric'] = pd.to_numeric(df_facts['value_numeric'], errors='coerce')
        
        # Handle dimensions - convert dict to JSON string for JSONB column
        if 'dimensions' in df_facts.columns:
            import json
            df_facts['dimensions'] = df_facts['dimensions'].apply(
                lambda x: json.dumps(x) if isinstance(x, dict) and x else None
            )
        
        try:
            # Use upsert (ON CONFLICT DO UPDATE) to handle duplicates
            # This allows re-running the pipeline without errors
            loaded_count = 0
            
            with self.engine.connect() as conn:
                for _, row in df_facts.iterrows():
                    # Prepare row data
                    row_data = row.to_dict()
                    
                    # Convert NaN to None
                    row_data = {k: (None if pd.isna(v) else v) for k, v in row_data.items()}
                    
                    # Insert with conflict handling
                    stmt = insert(text("financial_facts")).values(**row_data)
                    stmt = stmt.on_conflict_do_update(
                        constraint='financial_facts_company_filing_type_fiscal_year_end_concep_key',
                        set_={
                            'value_text': stmt.excluded.value_text,
                            'value_numeric': stmt.excluded.value_numeric,
                            'extraction_timestamp': stmt.excluded.extraction_timestamp
                        }
                    )
                    
                    try:
                        conn.execute(stmt)
                        loaded_count += 1
                    except Exception as e:
                        # If unique constraint fails, try basic insert
                        try:
                            conn.execute(text(f"""
                                INSERT INTO financial_facts ({', '.join(row_data.keys())})
                                VALUES ({', '.join([f':{k}' for k in row_data.keys()])})
                                ON CONFLICT DO NOTHING
                            """), row_data)
                            loaded_count += 1
                        except:
                            logger.warning(f"Failed to insert fact: {row_data.get('concept', 'unknown')}")
                            continue
                
                conn.commit()
            
            logger.info(f"✅ Loaded {loaded_count} facts to database")
            return loaded_count
            
        except Exception as e:
            logger.error(f"❌ Failed to load facts: {e}")
            return 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics"""
        if not self.engine:
            return {}
        
        try:
            with self.engine.connect() as conn:
                # Total facts
                result = conn.execute(text("SELECT COUNT(*) as total FROM financial_facts"))
                total = result.fetchone()[0]
                
                # Facts by company
                result = conn.execute(text("""
                    SELECT company, COUNT(*) as count
                    FROM financial_facts
                    GROUP BY company
                    ORDER BY count DESC
                """))
                by_company = {row[0]: row[1] for row in result}
                
                # Facts by taxonomy
                result = conn.execute(text("""
                    SELECT taxonomy, COUNT(*) as count
                    FROM financial_facts
                    GROUP BY taxonomy
                    ORDER BY count DESC
                """))
                by_taxonomy = {row[0]: row[1] for row in result}
                
                return {
                    'total_facts': total,
                    'by_company': by_company,
                    'by_taxonomy': by_taxonomy
                }
                
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {}


def main():
    """CLI interface for testing"""
    import argparse
    import json
    
    parser = argparse.ArgumentParser(description='Load XBRL facts to PostgreSQL')
    parser.add_argument('--input', required=True, help='Input JSON file with extracted facts')
    parser.add_argument('--company', required=True, help='Company ticker')
    parser.add_argument('--filing-type', required=True, help='Filing type')
    parser.add_argument('--fiscal-year-end', required=True, help='Fiscal year end (YYYY-MM-DD)')
    parser.add_argument('--source-url', help='Source filing URL')
    
    args = parser.parse_args()
    
    # Load facts from JSON
    logger.info(f"Loading facts from {args.input}")
    with open(args.input) as f:
        data = json.load(f)
        facts = data.get('facts', [])
    
    # Initialize loader
    loader = FinancialDataLoader()
    
    if not loader.connect():
        logger.error("Failed to connect to database")
        exit(1)
    
    # Create schema
    loader.create_schema()
    
    # Load facts
    count = loader.load_facts(
        facts=facts,
        company=args.company,
        filing_type=args.filing_type,
        fiscal_year_end=args.fiscal_year_end,
        source_url=args.source_url
    )
    
    if count > 0:
        # Show stats
        stats = loader.get_stats()
        print(f"\n📊 Database Statistics:")
        print(f"   Total facts: {stats['total_facts']}")
        print(f"\n   By company:")
        for company, cnt in stats['by_company'].items():
            print(f"     {company}: {cnt}")
        print(f"\n   By taxonomy:")
        for taxonomy, cnt in stats['by_taxonomy'].items():
            print(f"     {taxonomy}: {cnt}")
        
        print(f"\n✅ Successfully loaded {count} facts to database!")
    else:
        print("\n❌ Failed to load facts")
        exit(1)


if __name__ == '__main__':
    main()

