#!/usr/bin/env python3
"""
Comprehensive XBRL Parser using Arelle

Extracts ALL facts from XBRL instance documents (target: 500-2000+ facts per filing).
Captures complete context, unit, and provenance information.
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from decimal import Decimal

from arelle import ModelManager, Cntlr, ModelXbrl, XbrlConst
from arelle.ModelDtsObject import ModelConcept
from arelle.ModelInstanceObject import ModelFact

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ComprehensiveXBRLParser:
    """Extract ALL facts from XBRL documents with full provenance"""
    
    def __init__(self):
        """Initialize Arelle controller"""
        # Initialize Arelle with minimal validation for faster processing
        self.controller = Cntlr.Cntlr(logFileName="logToBuffer")
        self.model_manager = ModelManager.initialize(self.controller)
        
        # Suppress schema validation errors for inline XBRL
        self.controller.logLevel = "WARNING"
    
    def load_filing(self, filepath: Path) -> Optional[ModelXbrl.ModelXbrl]:
        """
        Load XBRL filing using Arelle
        
        Args:
            filepath: Path to XBRL instance document
            
        Returns:
            Loaded XBRL model
        """
        logger.info(f"Loading XBRL file: {filepath}")
        
        try:
            # Load the XBRL instance
            model_xbrl = self.model_manager.load(str(filepath))
            
            if model_xbrl:
                logger.info(f"Successfully loaded XBRL document")
                logger.info(f"  Document type: {model_xbrl.modelDocument.type}")
                logger.info(f"  Namespaces: {len(model_xbrl.namespaceDocs)}")
                
                # Log errors but continue (inline XBRL often has schema loading issues)
                if model_xbrl.errors:
                    logger.warning(f"  Document loaded with {len(model_xbrl.errors)} errors (this is common for inline XBRL)")
                
                return model_xbrl
            else:
                logger.error("Failed to load XBRL")
                return None
                
        except Exception as e:
            logger.error(f"Error loading XBRL: {e}")
            return None
    
    def extract_all_facts(self, model_xbrl: ModelXbrl.ModelXbrl) -> List[Dict[str, Any]]:
        """
        Extract ALL facts from XBRL document with deduplication
        
        Args:
            model_xbrl: Loaded XBRL model
            
        Returns:
            List of fact dictionaries with complete metadata
        """
        logger.info("Extracting ALL facts from XBRL document...")
        
        facts = []
        fact_count = 0
        duplicates_removed = 0
        
        # Track facts by (concept, context, value) to detect duplicates
        fact_registry = {}  # key -> fact_dict
        
        # Iterate through ALL facts in the instance
        for fact in model_xbrl.facts:
            fact_count += 1
            
            try:
                fact_dict = self._extract_fact_details(fact, model_xbrl)
                if not fact_dict:
                    continue
                
                # Create deduplication key
                dedup_key = (
                    fact_dict.get('concept'),
                    fact_dict.get('context_id'),
                    fact_dict.get('value_numeric'),
                    fact_dict.get('value_text')
                )
                
                # Check if this is a duplicate
                if dedup_key in fact_registry:
                    duplicates_removed += 1
                    existing_fact = fact_registry[dedup_key]
                    
                    # Keep the one with LOWER order_index (primary statement location)
                    existing_order = existing_fact.get('order_index') or 999999
                    new_order = fact_dict.get('order_index') or 999999
                    
                    if new_order < existing_order:
                        # Replace with better ordered fact
                        fact_registry[dedup_key] = fact_dict
                        fact_dict['is_primary'] = True
                        logger.debug(f"Replaced duplicate with better ordered fact: {fact_dict.get('concept')}")
                    # else: keep existing (it has better order)
                else:
                    # New unique fact
                    fact_dict['is_primary'] = True
                    fact_registry[dedup_key] = fact_dict
                    
            except Exception as e:
                logger.warning(f"Error extracting fact {fact_count}: {e}")
                continue
        
        facts = list(fact_registry.values())
        
        logger.info(f"Extracted {len(facts)} unique facts from {fact_count} total facts")
        logger.info(f"Duplicates removed: {duplicates_removed}")
        return facts
    
    def _extract_fact_details(self, fact: ModelFact, model_xbrl: ModelXbrl.ModelXbrl) -> Dict[str, Any]:
        """
        Extract complete details for a single fact
        
        Args:
            fact: Arelle fact object
            model_xbrl: XBRL model
            
        Returns:
            Dictionary with fact details and metadata
        """
        # Basic fact information
        concept = fact.concept
        context = fact.context
        unit = fact.unit
        
        # Extract concept information
        concept_qname = fact.qname
        concept_name = concept_qname.localName if concept_qname else None
        concept_namespace = concept_qname.namespaceURI if concept_qname else None
        
        # Determine taxonomy (US-GAAP, IFRS, DEI, custom)
        taxonomy = self._identify_taxonomy(concept_namespace)
        
        # Extract value
        value_raw = fact.value
        value_text = fact.stringValue if hasattr(fact, 'stringValue') else str(value_raw)
        
        # Try to convert to numeric if possible
        value_numeric = None
        if value_raw:
            # Method 1: Check if concept is numeric type
            if concept and hasattr(concept, 'isNumeric') and concept.isNumeric:
                try:
                    value_numeric = float(value_raw)
                except (ValueError, TypeError):
                    pass
            # Method 2: Try parsing the value_text directly (fallback)
            if value_numeric is None and value_text:
                try:
                    # Remove common non-numeric characters but keep negative signs and decimals
                    cleaned = value_text.replace(',', '').replace(' ', '').strip()
                    if cleaned and (cleaned.replace('.', '').replace('-', '').replace('+', '').isdigit()):
                        value_numeric = float(cleaned)
                except (ValueError, TypeError, AttributeError):
                    pass
        
        # Extract context information
        context_info = self._extract_context_info(context) if context else {}
        
        # Extract unit information
        unit_info = self._extract_unit_info(unit) if unit else {}
        
        # Extract concept metadata
        concept_metadata = self._extract_concept_metadata(concept) if concept else {}
        
        # Extract NEW fields for completeness
        scale_int = fact.scaleInt if hasattr(fact, 'scaleInt') else None
        xbrl_format = str(fact.format) if hasattr(fact, 'format') else None
        order_index = fact.order if hasattr(fact, 'order') else None
        
        # Infer statement type from concept name
        statement_type = self._infer_statement_type(concept_name)
        
        # Build complete fact dictionary
        fact_dict = {
            # Core fact data
            'concept': concept_name,
            'concept_namespace': concept_namespace,
            'taxonomy': taxonomy,
            'value_text': value_text,
            'value_numeric': value_numeric,
            
            # Context information (dates, dimensions, segments)
            'context_id': context.id if context else None,
            'period_type': context_info.get('period_type'),
            'period_start': context_info.get('period_start'),
            'period_end': context_info.get('period_end'),
            'instant_date': context_info.get('instant_date'),
            'entity_scheme': context_info.get('entity_scheme'),
            'entity_identifier': context_info.get('entity_identifier'),
            'dimensions': context_info.get('dimensions', {}),
            
            # Unit information (currency, shares, etc.)
            'unit_id': unit.id if unit else None,
            'unit_measure': unit_info.get('measure'),
            'unit_type': unit_info.get('unit_type'),
            
            # Concept metadata
            'concept_type': concept_metadata.get('type'),
            'concept_balance': concept_metadata.get('balance'),
            'concept_period_type': concept_metadata.get('period_type'),
            'concept_data_type': concept_metadata.get('data_type'),
            'concept_abstract': concept_metadata.get('abstract', False),
            'statement_type': statement_type,
            
            # Provenance
            'source_line': fact.sourceline,
            'fact_id': fact.id if hasattr(fact, 'id') else None,
            'decimals': fact.decimals if hasattr(fact, 'decimals') else None,
            'precision': fact.precision if hasattr(fact, 'precision') else None,
            'scale_int': scale_int,
            'xbrl_format': xbrl_format,
            'order_index': order_index,
        }
        
        return fact_dict
    
    def _infer_statement_type(self, concept_name: Optional[str]) -> str:
        """Infer financial statement type from concept name"""
        if not concept_name:
            return 'other'
        
        concept_lower = concept_name.lower()
        
        # Balance Sheet indicators
        if any(term in concept_lower for term in [
            'asset', 'liability', 'equity', 'receivable', 'payable', 
            'inventory', 'property', 'goodwill', 'intangible', 'debt',
            'stockholder', 'sharehold', 'capital'
        ]):
            return 'balance_sheet'
        
        # Income Statement indicators
        elif any(term in concept_lower for term in [
            'revenue', 'sales', 'income', 'expense', 'cost', 'profit',
            'margin', 'earnings', 'ebit', 'tax', 'interest'
        ]):
            return 'income_statement'
        
        # Cash Flow indicators
        elif any(term in concept_lower for term in [
            'cashflow', 'operatingactivit', 'investingactivit', 
            'financingactivit', 'cashprovided', 'cashused'
        ]):
            return 'cash_flow'
        
        # Equity Statement indicators
        elif any(term in concept_lower for term in [
            'sharesissued', 'sharesoutstanding', 'dividend', 'stockissuance',
            'stockrepurchase', 'treasurystock'
        ]):
            return 'equity_statement'
        
        # Disclosure/Notes indicators  
        elif any(term in concept_lower for term in [
            'disclosure', 'policy', 'footnote', 'textblock'
        ]):
            return 'notes'
        
        else:
            return 'other'
    
    def _identify_taxonomy(self, namespace: Optional[str]) -> str:
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
    
    def _extract_context_info(self, context) -> Dict[str, Any]:
        """Extract complete context information"""
        context_info = {}
        
        # Entity information
        if context.entityIdentifier:
            context_info['entity_scheme'] = context.entityIdentifier[0]
            context_info['entity_identifier'] = context.entityIdentifier[1]
        
        # Period information
        if context.isInstantPeriod:
            context_info['period_type'] = 'instant'
            context_info['instant_date'] = context.instantDatetime.date() if context.instantDatetime else None
        elif context.isStartEndPeriod:
            context_info['period_type'] = 'duration'
            context_info['period_start'] = context.startDatetime.date() if context.startDatetime else None
            context_info['period_end'] = context.endDatetime.date() if context.endDatetime else None
        elif context.isForeverPeriod:
            context_info['period_type'] = 'forever'
        
        # Dimensional information (segments, scenarios, axes)
        dimensions = {}
        if context.qnameDims:
            for dim_qname, dim_value in context.qnameDims.items():
                if not dim_qname:
                    continue
                    
                dim_name = dim_qname.localName if dim_qname else None
                if not dim_name:
                    continue
                
                if hasattr(dim_value, 'memberQname') and dim_value.memberQname:
                    # Explicit dimension
                    member_name = dim_value.memberQname.localName if dim_value.memberQname else None
                    if member_name:
                        dimensions[dim_name] = {
                            'type': 'explicit',
                            'member': member_name
                        }
                elif hasattr(dim_value, 'typedMember'):
                    # Typed dimension
                    dimensions[dim_name] = {
                        'type': 'typed',
                        'value': str(dim_value.typedMember)
                    }
        
        context_info['dimensions'] = dimensions
        
        return context_info
    
    def _extract_unit_info(self, unit) -> Dict[str, Any]:
        """Extract unit information (currency, shares, etc.)"""
        unit_info = {}
        
        if not unit:
            return unit_info
        
        # Get measures
        measures = []
        if hasattr(unit, 'measures'):
            for measure_list in unit.measures:
                for measure in measure_list:
                    if measure and hasattr(measure, 'localName'):
                        measures.append(measure.localName)
        
        if measures:
            unit_info['measure'] = measures[0] if len(measures) == 1 else measures
            
            # Identify unit type
            measure_str = str(measures[0]).lower() if measures else ''
            if any(curr in measure_str for curr in ['usd', 'eur', 'gbp', 'dkk', 'jpy']):
                unit_info['unit_type'] = 'currency'
            elif 'shares' in measure_str:
                unit_info['unit_type'] = 'shares'
            elif 'pure' in measure_str:
                unit_info['unit_type'] = 'pure'
            else:
                unit_info['unit_type'] = 'other'
        
        return unit_info
    
    def _extract_concept_metadata(self, concept: ModelConcept) -> Dict[str, Any]:
        """Extract concept definition metadata"""
        metadata = {}
        
        if not concept:
            return metadata
        
        metadata['type'] = concept.type.localName if (concept.type and hasattr(concept.type, 'localName')) else None
        metadata['balance'] = concept.balance if hasattr(concept, 'balance') else None
        metadata['period_type'] = concept.periodType if hasattr(concept, 'periodType') else None
        metadata['data_type'] = concept.baseXbrliType if hasattr(concept, 'baseXbrliType') else None
        metadata['abstract'] = concept.isAbstract if hasattr(concept, 'isAbstract') else False
        
        return metadata
    
    def parse_filing(self, filepath: Path) -> Optional[Dict[str, Any]]:
        """
        Parse XBRL filing and extract all facts
        
        Args:
            filepath: Path to XBRL instance document
            
        Returns:
            Dictionary with facts and metadata
        """
        # Load filing
        model_xbrl = self.load_filing(filepath)
        
        if not model_xbrl:
            return None
        
        try:
            # Extract all facts
            facts = self.extract_all_facts(model_xbrl)
            
            # Get filing metadata
            metadata = self._extract_filing_metadata(model_xbrl)
            
            result = {
                'facts': facts,
                'metadata': metadata,
                'total_facts': len(facts),
                'extraction_timestamp': datetime.now().isoformat()
            }
            
            logger.info(f"Parsing complete: {len(facts)} facts extracted")
            
            return result
            
        finally:
            # Clean up
            model_xbrl.close()
    
    def _extract_filing_metadata(self, model_xbrl: ModelXbrl.ModelXbrl) -> Dict[str, Any]:
        """Extract filing-level metadata"""
        metadata = {
            'document_type': str(model_xbrl.modelDocument.type),
            'creation_software': model_xbrl.modelDocument.creationSoftwareComment if hasattr(model_xbrl.modelDocument, 'creationSoftwareComment') else None,
            'namespaces': list(model_xbrl.namespaceDocs.keys()),
            'schemas_loaded': len(model_xbrl.modelDocument.referencesDocument) if hasattr(model_xbrl.modelDocument, 'referencesDocument') else 0
        }
        
        return metadata


def main():
    """CLI interface for testing"""
    import argparse
    import json
    
    parser = argparse.ArgumentParser(description='Parse XBRL filing and extract all facts')
    parser.add_argument('--input', required=True, help='Path to XBRL instance document')
    parser.add_argument('--output', help='Output JSON file (optional)')
    
    args = parser.parse_args()
    
    xbrl_parser = ComprehensiveXBRLParser()
    result = xbrl_parser.parse_filing(Path(args.input))
    
    if result:
        print(f"\n✅ Parsing successful!")
        print(f"   Total facts extracted: {result['total_facts']}")
        print(f"   Document type: {result['metadata']['document_type']}")
        print(f"   Namespaces: {len(result['metadata']['namespaces'])}")
        
        # Show sample facts
        if result['facts']:
            print(f"\n📊 Sample facts:")
            for i, fact in enumerate(result['facts'][:5]):
                print(f"   {i+1}. {fact['concept']}: {fact['value_text']} ({fact['taxonomy']})")
        
        # Save to JSON if output specified
        if args.output:
            output_path = Path(args.output)
            output_path.write_text(json.dumps(result, indent=2, default=str))
            print(f"\n💾 Saved to: {output_path}")
    else:
        print("\n❌ Parsing failed")
        exit(1)


if __name__ == '__main__':
    main()

