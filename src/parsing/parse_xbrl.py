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
    
    def __init__(self, enable_network=True):
        """
        Initialize Arelle controller
        
        Args:
            enable_network: If True, allows Arelle to fetch linkbases from network.
                          Required for inline XBRL to get calculation/presentation relationships.
        """
        # Initialize Arelle with network access for linkbase fetching
        self.controller = Cntlr.Cntlr(logFileName="logToBuffer")
        self.model_manager = ModelManager.initialize(self.controller)
        
        # Configure network access for fetching linkbases
        if enable_network:
            self.controller.webCache.workOffline = False  # Allow network access
            logger.info("Network access enabled - Arelle will fetch linkbases automatically")
        else:
            logger.warning("Network access disabled - relationships may not be available")
        
        # Suppress schema validation errors for inline XBRL
        self.controller.logLevel = "WARNING"
    
    def load_filing(self, filepath: Path) -> Optional[ModelXbrl.ModelXbrl]:
        """
        Load XBRL filing using Arelle
        
        CRITICAL: For inline XBRL, we must ensure ALL facts are loaded, including
        facts for ALL periods (years). Financial statements include comparative
        data for multiple years, and every concept should have data for all years.
        
        Args:
            filepath: Path to XBRL instance document
            
        Returns:
            Loaded XBRL model
        """
        logger.info(f"Loading XBRL file: {filepath}")
        
        try:
            # Configure Arelle to load ALL facts, including inline XBRL
            # For inline XBRL, we need to ensure all contexts are processed
            self.controller.logLevel = "WARNING"  # Suppress schema errors but keep warnings
            
            # Load the XBRL instance
            # For inline XBRL, Arelle should automatically extract all facts
            # CRITICAL: Ensure linkbases are loaded for presentation relationships
            
            # For inline XBRL files, linkbases may be referenced as relative paths
            # Arelle needs to either find them locally or fetch from network
            # First, try to load local linkbase files if they exist
            linkbase_files = list(filepath.parent.glob(f"{filepath.stem.split('_')[0]}-*pre.xml")) + \
                           list(filepath.parent.glob(f"{filepath.stem.split('_')[0]}-*cal.xml"))
            
            if linkbase_files:
                logger.info(f"Found {len(linkbase_files)} linkbase files locally - Arelle should load them automatically")
            
            # Load the main file - Arelle should automatically load referenced linkbases
            # If network is enabled, Arelle will try to fetch missing linkbases
            # CRITICAL: For inline XBRL, we need to use file:// URL for proper relative path resolution
            file_url = filepath.absolute().as_uri()
            model_xbrl = self.model_manager.load(file_url)
            
            # CRITICAL FIX: For inline XBRL, Arelle may not automatically process linkbaseRef elements
            # We need to explicitly load linkbases referenced in the HTML
            if model_xbrl and model_xbrl.modelDocument:
                # Check if linkbaseRef elements exist but weren't processed
                pres_arcrole = XbrlConst.parentChild if hasattr(XbrlConst, 'parentChild') else 'http://www.xbrl.org/2003/arcrole/parent-child'
                pres_rels = model_xbrl.relationshipSet(pres_arcrole)
                
                if not pres_rels or len(list(pres_rels.modelConcepts)) == 0:
                    # Linkbases weren't automatically loaded - manually process linkbaseRef elements
                    logger.info("LinkbaseRef elements not automatically processed - manually loading linkbases...")
                    
                    # Read HTML to find linkbaseRef elements
                    try:
                        import re
                        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read(100000)  # Read first 100KB
                        
                        # Find all linkbaseRef href attributes
                        linkbase_refs = re.findall(r'xlink:href="([^"]*_(?:pre|cal|def|lab)\.xml)"', content, re.IGNORECASE)
                        linkbase_refs = list(set(linkbase_refs))  # Remove duplicates
                        
                        if linkbase_refs:
                            logger.info(f"Found {len(linkbase_refs)} linkbaseRef elements in HTML")
                            
                            # Load each linkbase file and ensure it's linked to the model
                            for lb_ref in linkbase_refs:
                                lb_path = filepath.parent / lb_ref
                                if lb_path.exists():
                                    lb_url = lb_path.absolute().as_uri()
                                    try:
                                        # Load linkbase - Arelle should automatically link it if loaded after main document
                                        lb_model = self.model_manager.load(lb_url)
                                        if lb_model:
                                            logger.debug(f"Loaded linkbase: {lb_ref}")
                                    except Exception as e:
                                        logger.warning(f"Could not load linkbase {lb_ref}: {e}")
                            
                            # CRITICAL: Arelle has a documented limitation with inline XBRL - its inlineXbrlDiscover()
                            # method does NOT automatically process linkbaseRef elements to link linkbases to the main
                            # document's relationship sets. This is confirmed by:
                            # 1. Arelle source code: inlineXbrlDiscover() doesn't call linkbasesDiscover()
                            # 2. XBRL 2.1 spec: linkbaseRef elements are standard and should be processed
                            # 3. Arelle community: Users have reported challenges with inline XBRL linkbase loading
                            # 
                            # BEST PRACTICE: Manual XML parsing of linkbaseRef elements (as implemented below)
                            # This is the recommended approach per XBRL community discussions, as it:
                            # - Ensures all linkbases are loaded reliably
                            # - Works immediately without modifying Arelle source code
                            # - Maintains compatibility with Arelle updates
                            logger.info("Arelle limitation detected: linkbaseRef elements not processed - using manual XML parsing (best practice)")
                            
                            # Note: Manual parsing will be handled in extract_presentation_hierarchy method
                            # We just need to ensure the model_xbrl is returned so extraction can proceed
                    except Exception as e:
                        logger.warning(f"Error manually processing linkbaseRef elements: {e}")
            
            # After loading, check if linkbases were loaded
            # For inline XBRL, Arelle should load linkbases automatically if they're referenced
            if model_xbrl and model_xbrl.modelDocument:
                # Check if we have any linkbase documents loaded
                linkbase_count = 0
                if hasattr(model_xbrl, 'modelDocument'):
                    # Count linkbase documents
                    def count_linkbases(doc, visited=None):
                        if visited is None:
                            visited = set()
                        if doc and id(doc) not in visited:
                            visited.add(id(doc))
                            count = 1 if doc.type == 4 else 0  # Type 4 = linkbase
                            if hasattr(doc, 'references'):
                                for ref in doc.references:
                                    if hasattr(ref, 'referredDocument') and ref.referredDocument:
                                        count += count_linkbases(ref.referredDocument, visited)
                            return count
                    
                    linkbase_count = count_linkbases(model_xbrl.modelDocument)
                    if linkbase_count > 0:
                        logger.info(f"Loaded {linkbase_count} linkbase document(s)")
                    else:
                        logger.warning("No linkbase documents loaded - presentation relationships may be unavailable")
            
            if model_xbrl:
                logger.info(f"Successfully loaded XBRL document")
                logger.info(f"  Document type: {model_xbrl.modelDocument.type}")
                logger.info(f"  Namespaces: {len(model_xbrl.namespaceDocs)}")
                
                # Count contexts to verify we have multiple periods
                contexts = list(model_xbrl.contexts) if hasattr(model_xbrl, 'contexts') else []
                if contexts:
                    periods = set()
                    for ctx in contexts:
                        if hasattr(ctx, 'isInstantPeriod') and ctx.isInstantPeriod:
                            if ctx.instantDatetime:
                                periods.add(ctx.instantDatetime.date())
                        elif hasattr(ctx, 'isStartEndPeriod') and ctx.isStartEndPeriod:
                            if ctx.endDatetime:
                                periods.add(ctx.endDatetime.date())
                    if periods:
                        years = sorted(set(p.year for p in periods if p))
                        logger.info(f"  Contexts found: {len(contexts)}")
                        logger.info(f"  Periods found: {len(periods)}")
                        logger.info(f"  Years in filing: {years}")
                        if len(years) < 2:
                            logger.warning(f"  ⚠️  Only {len(years)} year(s) found. Financial statements typically include 2-3 years of comparative data.")
                
                # Log errors but continue (inline XBRL often has schema loading issues)
                if model_xbrl.errors:
                    logger.warning(f"  Document loaded with {len(model_xbrl.errors)} errors (this is common for inline XBRL)")
                
                # Verify we have facts
                fact_count = len(list(model_xbrl.facts)) if hasattr(model_xbrl, 'facts') else 0
                logger.info(f"  Facts available in model: {fact_count}")
                if fact_count == 0:
                    logger.error("  ❌ No facts found in XBRL model. This may indicate a parsing issue.")
                
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
        
        CRITICAL: This method must extract ALL facts for ALL periods (years) in the filing.
        Financial statements always include comparative data for multiple years, and every
        concept should have data for all years presented in the filing.
        
        Args:
            model_xbrl: Loaded XBRL model
            
        Returns:
            List of fact dictionaries with complete metadata
        """
        logger.info("Extracting ALL facts from XBRL document...")
        
        facts = []
        fact_count = 0
        duplicates_removed = 0
        skipped_no_details = 0
        
        # Track facts by (concept, context, value) to detect duplicates
        # IMPORTANT: context_id must be included to preserve facts for different periods
        fact_registry = {}  # key -> fact_dict
        
        # Track contexts to verify we're getting all periods
        contexts_seen = set()
        periods_seen = set()
        
        # Iterate through ALL facts in the instance
        # For inline XBRL, model_xbrl.facts should contain all facts from all contexts
        all_facts = list(model_xbrl.facts)
        
        logger.info(f"Total facts available from Arelle: {len(all_facts)}")
        
        for fact in all_facts:
            fact_count += 1
            
            try:
                fact_dict = self._extract_fact_details(fact, model_xbrl)
                if not fact_dict:
                    skipped_no_details += 1
                    continue
                
                # Track context and period for validation
                context_id = fact_dict.get('context_id')
                if context_id:
                    contexts_seen.add(context_id)
                
                # Track periods
                period_end = fact_dict.get('period_end')
                instant_date = fact_dict.get('instant_date')
                if period_end:
                    periods_seen.add(period_end)
                if instant_date:
                    periods_seen.add(instant_date)
                
                # Create deduplication key
                # CRITICAL: Include context_id to ensure facts for different periods are NOT deduplicated
                dedup_key = (
                    fact_dict.get('concept'),
                    fact_dict.get('context_id'),  # Different contexts = different periods = keep both
                    fact_dict.get('value_numeric'),
                    fact_dict.get('value_text')
                )
                
                # Check if this is a duplicate (same concept, same context, same value)
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
                    # New unique fact (different context = different period = keep it)
                    fact_dict['is_primary'] = True
                    fact_registry[dedup_key] = fact_dict
                    
            except Exception as e:
                logger.warning(f"Error extracting fact {fact_count}: {e}")
                continue
        
        facts = list(fact_registry.values())
        
        # Validation: Check if we have facts for multiple periods
        periods_by_year = {}
        for fact in facts:
            period_end = fact.get('period_end')
            instant_date = fact.get('instant_date')
            date_obj = period_end or instant_date
            if date_obj:
                # Handle both string and date objects
                if isinstance(date_obj, str):
                    year = date_obj[:4] if len(date_obj) >= 4 else None
                elif hasattr(date_obj, 'year'):
                    year = str(date_obj.year)
                else:
                    year = None
                if year:
                    periods_by_year[year] = periods_by_year.get(year, 0) + 1
        
        logger.info(f"Extracted {len(facts)} unique facts from {fact_count} total facts")
        logger.info(f"Duplicates removed: {duplicates_removed}")
        logger.info(f"Skipped (no details): {skipped_no_details}")
        logger.info(f"Contexts seen: {len(contexts_seen)}")
        logger.info(f"Periods by year: {dict(sorted(periods_by_year.items()))}")
        
        # Warn if we don't have multiple years (financial statements should have comparative data)
        if len(periods_by_year) < 2:
            logger.warning(f"⚠️  Only found data for {len(periods_by_year)} year(s). Financial statements typically include 2-3 years of comparative data.")
        
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
    
    def _extract_statement_type_from_role_uri(self, role_uri: Optional[str]) -> str:
        """
        Extract statement_type from XBRL role_uri (AUTHORITATIVE SOURCE).
        
        This is the correct way - role_uri contains the statement type information.
        Examples:
        - http://www.xbrl.org/role/statement/IncomeStatement -> income_statement
        - http://www.novonordisk.com/role/Balancesheet -> balance_sheet
        - http://www.xbrl.org/role/statement/StatementOfCashFlows -> cash_flow
        - http://www.xbrl.org/role/statement/StatementOfComprehensiveIncome -> comprehensive_income
        
        Args:
            role_uri: XBRL role URI from presentationLink
        
        Returns:
            statement_type: 'income_statement', 'balance_sheet', 'cash_flow', 'comprehensive_income', or 'other'
        """
        if not role_uri:
            return 'other'
        
        role_lower = role_uri.lower()
        
        # Extract from role_uri patterns (AUTHORITATIVE - this is what XBRL tells us)
        # CRITICAL: Combined role URIs like "IncomestatementandStatementofcomprehensiveincome" 
        # contain BOTH income statement and comprehensive income sections.
        # We default to 'income_statement' for combined roles, and let populate_statement_items.py
        # route OCI items to comprehensive_income based on concept patterns.
        if 'statementofcomprehensiveincome' in role_lower or 'comprehensiveincome' in role_lower:
            # If it's explicitly comprehensive income ONLY (not combined), return comprehensive_income
            if 'incomestatementandstatement' not in role_lower and 'incomestatement' not in role_lower:
                return 'comprehensive_income'
            # If combined, default to income_statement (OCI items will be routed later)
            # This is correct because the combined role contains both sections
            return 'income_statement'
        
        # Balance Sheet
        if 'balancesheet' in role_lower or 'balance' in role_lower and 'sheet' in role_lower:
            return 'balance_sheet'
        if 'statementoffinancialposition' in role_lower:
            return 'balance_sheet'
        
        # Cash Flow
        if 'cashflow' in role_lower or 'statementofcashflows' in role_lower:
            return 'cash_flow'
        
        # Income Statement
        if 'incomestatement' in role_lower:
            return 'income_statement'
        
        # Equity Statement
        if 'equitystatement' in role_lower or 'statementofchangesinequity' in role_lower:
            return 'equity_statement'
        
        # Default: other (notes, disclosures, etc.)
        return 'other'
    
    def _infer_statement_type(self, concept_name: Optional[str]) -> str:
        """
        FALLBACK: Infer financial statement type from concept name.
        
        This should ONLY be used when role_uri is not available.
        The authoritative source is role_uri (see _extract_statement_type_from_role_uri).
        """
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
            
            # Extract XBRL relationships
            calculation_relationships = self.extract_calculation_relationships(model_xbrl)
            presentation_hierarchy = self.extract_presentation_hierarchy(model_xbrl)
            footnote_references = self.extract_footnote_references(model_xbrl, facts)
            
            # Get filing metadata
            metadata = self._extract_filing_metadata(model_xbrl)
            
            result = {
                'facts': facts,
                'relationships': {
                    'calculation': calculation_relationships,
                    'presentation': presentation_hierarchy,
                    'footnotes': footnote_references
                },
                'metadata': metadata,
                'total_facts': len(facts),
                'extraction_timestamp': datetime.now().isoformat()
            }
            
            logger.info(f"Parsing complete: {len(facts)} facts extracted")
            logger.info(f"  Calculation relationships: {len(calculation_relationships)}")
            logger.info(f"  Presentation relationships: {len(presentation_hierarchy)}")
            logger.info(f"  Footnote references: {len(footnote_references)}")
            
            return result
            
        finally:
            # Clean up
            model_xbrl.close()
    
    def extract_calculation_relationships(self, model_xbrl: ModelXbrl.ModelXbrl) -> List[Dict[str, Any]]:
        """
        Extract calculation relationships (parent-child summation relationships)
        
        Args:
            model_xbrl: Loaded XBRL model
            
        Returns:
            List of calculation relationship dictionaries
        """
        relationships = []
        
        try:
            # Get calculation relationship set
            # XBRL uses 'http://www.xbrl.org/2003/arcrole/summation-item' for calculations
            calc_arcrole = XbrlConst.summationItem if hasattr(XbrlConst, 'summationItem') else 'http://www.xbrl.org/2003/arcrole/summation-item'
            calc_rels = model_xbrl.relationshipSet(calc_arcrole)
            
            if not calc_rels:
                logger.debug("No calculation relationships found")
                return relationships
            
            # Iterate through all calculation relationships
            for from_concept in calc_rels.modelConcepts:
                for to_concept, rel in calc_rels.fromModelObject(from_concept):
                    parent_qname = from_concept.qname if from_concept else None
                    child_qname = to_concept.qname if to_concept else None
                    
                    if not parent_qname or not child_qname:
                        continue
                    
                    # Extract weight (usually 1.0 for addition, -1.0 for subtraction)
                    weight = float(rel.weight) if hasattr(rel, 'weight') and rel.weight else 1.0
                    
                    # Extract order and priority
                    order_index = rel.order if hasattr(rel, 'order') else None
                    priority = rel.priority if hasattr(rel, 'priority') else 0
                    arcrole = rel.arcrole if hasattr(rel, 'arcrole') else calc_arcrole
                    
                    relationships.append({
                        'parent_concept': parent_qname.localName,
                        'parent_namespace': parent_qname.namespaceURI,
                        'child_concept': child_qname.localName,
                        'child_namespace': child_qname.namespaceURI,
                        'weight': weight,
                        'order_index': order_index,
                        'priority': priority,
                        'arcrole': arcrole
                    })
            
            logger.info(f"Extracted {len(relationships)} calculation relationships")
            
        except Exception as e:
            logger.warning(f"Error extracting calculation relationships: {e}")
        
        return relationships
    
    def extract_presentation_hierarchy(self, model_xbrl: ModelXbrl.ModelXbrl) -> List[Dict[str, Any]]:
        """
        Extract presentation hierarchy (how concepts are organized in statements)
        
        Args:
            model_xbrl: Loaded XBRL model
            
        Returns:
            List of presentation relationship dictionaries
        """
        relationships = []
        
        try:
            # Get presentation relationship set (parent-child in presentation linkbase)
            pres_arcrole = XbrlConst.parentChild if hasattr(XbrlConst, 'parentChild') else 'http://www.xbrl.org/2003/arcrole/parent-child'
            pres_rels = model_xbrl.relationshipSet(pres_arcrole)
            
            if not pres_rels:
                logger.warning("No presentation relationship set found - Arelle's inlineXbrlDiscover() doesn't process linkbaseRef elements")
                # PRIMARY METHOD: Manually parse linkbase XML files (best practice for Arelle's inline XBRL limitation)
                if hasattr(model_xbrl, 'modelDocument') and model_xbrl.modelDocument:
                    filepath = Path(model_xbrl.modelDocument.uri.replace('file://', ''))
                    if filepath.exists():
                        # Look for presentation linkbase file in the same directory
                        linkbase_files = list(filepath.parent.glob("*_pre.xml"))
                        if linkbase_files:
                            logger.info(f"Manually parsing {len(linkbase_files)} presentation linkbase file(s) (Arelle limitation)...")
                            manual_rels = self._parse_linkbase_xml(linkbase_files[0])
                            if manual_rels:
                                logger.info(f"✅ Manually extracted {len(manual_rels)} presentation relationships from linkbase XML")
                                return manual_rels
                        else:
                            logger.warning("No presentation linkbase files found for manual parsing")
                
                return relationships
            
            # Track statement type and role URI for each relationship
            statement_types = {}
            
            # CRITICAL: Arelle organizes relationship sets by role URI
            # Each relationship set corresponds to one role (e.g., IncomeStatement, IncomeStatementDetail)
            # We need to get the role URI from the relationship set itself
            role_uri = None
            if hasattr(pres_rels, 'modelRole'):
                role_uri = str(pres_rels.modelRole) if pres_rels.modelRole else None
            elif hasattr(pres_rels, 'role'):
                role_uri = str(pres_rels.role) if pres_rels.role else None
            elif hasattr(pres_rels, 'roleURI'):
                role_uri = str(pres_rels.roleURI) if pres_rels.roleURI else None
            
            # If we still don't have role_uri, try to get it from the model's role definitions
            if not role_uri and hasattr(model_xbrl, 'roleTypes'):
                # Try to find role from relationship set's internal structure
                try:
                    # Relationship sets in Arelle are keyed by role URI
                    # We can get it from the relationship set's key if available
                    if hasattr(pres_rels, '__dict__'):
                        for key, value in pres_rels.__dict__.items():
                            if 'role' in key.lower() and value:
                                role_uri = str(value)
                                break
                except:
                    pass
            
            # Iterate through all presentation relationships
            for from_concept in pres_rels.modelConcepts:
                for to_concept, rel in pres_rels.fromModelObject(from_concept):
                    parent_qname = from_concept.qname if from_concept else None
                    child_qname = to_concept.qname if to_concept else None
                    
                    if not child_qname:
                        continue
                    
                    # Extract order and metadata
                    order_index = rel.order if hasattr(rel, 'order') else None
                    priority = rel.priority if hasattr(rel, 'priority') else 0
                    arcrole = rel.arcrole if hasattr(rel, 'arcrole') else pres_arcrole
                    
                    # Extract preferred label role
                    preferred_label = None
                    if hasattr(rel, 'preferredLabel'):
                        preferred_label = str(rel.preferredLabel)
                    
                    # Use the role URI from the relationship set (all relationships in a set share the same role)
                    # This is the key to distinguishing main statement items from detailed breakdowns
                    rel_role_uri = role_uri
                    
                    # CRITICAL FIX: Extract statement_type from role_uri (AUTHORITATIVE SOURCE)
                    # This is what the ERD intended - use XBRL role_uri as the source of truth
                    # Not fragile concept name pattern matching
                    statement_type = self._extract_statement_type_from_role_uri(rel_role_uri)
                    
                    # FALLBACK: Only if role_uri doesn't provide statement_type, infer from concept name
                    # This should rarely happen if XBRL is properly structured
                    if statement_type == 'other' and rel_role_uri:
                        # Try to infer from concept name as last resort
                        if parent_qname:
                            statement_type = self._infer_statement_type(parent_qname.localName)
                        else:
                            statement_type = self._infer_statement_type(child_qname.localName)
                    
                    relationships.append({
                        'parent_concept': parent_qname.localName if parent_qname else None,
                        'parent_namespace': parent_qname.namespaceURI if parent_qname else None,
                        'child_concept': child_qname.localName,
                        'child_namespace': child_qname.namespaceURI,
                        'order_index': order_index,
                        'priority': priority,
                        'arcrole': arcrole,
                        'preferred_label': preferred_label,
                        'role_uri': rel_role_uri,  # CRITICAL: Store role URI for filtering main vs detail items
                        'statement_type': statement_type
                    })
            
            logger.info(f"Extracted {len(relationships)} presentation relationships")
            
        except Exception as e:
            logger.warning(f"Error extracting presentation relationships: {e}")
        
        return relationships
    
    def _parse_linkbase_xml(self, linkbase_path: Path) -> List[Dict[str, Any]]:
        """
        Manually parse presentation linkbase XML file when Arelle doesn't load it automatically
        
        Args:
            linkbase_path: Path to presentation linkbase XML file
            
        Returns:
            List of presentation relationship dictionaries
        """
        relationships = []
        
        try:
            import xml.etree.ElementTree as ET
            
            tree = ET.parse(linkbase_path)
            root = tree.getroot()
            
            # XBRL namespaces
            ns = {
                'link': 'http://www.xbrl.org/2003/linkbase',
                'xlink': 'http://www.w3.org/1999/xlink'
            }
            
            # Find all presentationLink elements
            presentation_links = root.findall('.//link:presentationLink', ns)
            
            for pres_link in presentation_links:
                role = pres_link.get(f'{{{ns["xlink"]}}}role', '')
                
                # Find all locators (concepts) in this presentationLink
                locators = {}
                for loc in pres_link.findall('.//link:loc', ns):
                    label = loc.get(f'{{{ns["xlink"]}}}label', '')
                    href = loc.get(f'{{{ns["xlink"]}}}href', '')
                    # Extract concept name from href (e.g., "nvo-20241231.xsd#nvo_Revenue" -> "nvo_Revenue")
                    if '#' in href:
                        concept = href.split('#')[-1]
                        locators[label] = concept
                
                # Find all presentation arcs (relationships)
                arcs = pres_link.findall('.//link:presentationArc', ns)
                
                for arc in arcs:
                    from_label = arc.get(f'{{{ns["xlink"]}}}from', '')
                    to_label = arc.get(f'{{{ns["xlink"]}}}to', '')
                    order = arc.get('order', '')
                    
                    parent_concept = locators.get(from_label, '')
                    child_concept = locators.get(to_label, '')
                    
                    if parent_concept and child_concept:
                        # CRITICAL: Extract role URI from presentationLink element
                        # This is the key to distinguishing main statement items from detailed breakdowns
                        # Main statement items: http://www.xbrl.org/role/statement/IncomeStatement
                        # Detailed breakdowns: http://www.xbrl.org/role/statement/IncomeStatementDetail
                        role_uri = role  # Role from presentationLink element
                        
                        # CRITICAL FIX: Extract statement_type from role_uri (AUTHORITATIVE SOURCE)
                        # This is what the ERD intended - use XBRL role_uri as the source of truth
                        statement_type = self._extract_statement_type_from_role_uri(role_uri)
                        
                        # FALLBACK: Only if role_uri doesn't provide statement_type, infer from concept name
                        if statement_type == 'other':
                            statement_type = self._infer_statement_type(child_concept)
                        
                        relationships.append({
                            'parent_concept': parent_concept,
                            'parent_namespace': None,  # Not available from XML parsing
                            'child_concept': child_concept,
                            'child_namespace': None,  # Not available from XML parsing
                            'order_index': int(order) if order.isdigit() else None,
                            'priority': 0,  # Not available from XML parsing
                            'arcrole': 'http://www.xbrl.org/2003/arcrole/parent-child',
                            'preferred_label': None,  # Could extract from arc if needed
                            'role_uri': role_uri,  # CRITICAL: Store role URI for filtering
                            'statement_type': statement_type
                        })
            
            logger.info(f"Manually parsed {len(relationships)} relationships from {linkbase_path.name}")
            
        except Exception as e:
            logger.warning(f"Error manually parsing linkbase XML {linkbase_path}: {e}")
        
        return relationships
    
    def extract_footnote_references(self, model_xbrl: ModelXbrl.ModelXbrl, facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract footnote references linking facts to footnote disclosures
        
        Args:
            model_xbrl: Loaded XBRL model
            facts: List of extracted fact dictionaries
            
        Returns:
            List of footnote reference dictionaries
        """
        footnotes = []
        
        try:
            # Create fact lookup by fact ID
            fact_lookup = {f.get('fact_id'): f for f in facts if f.get('fact_id')}
            
            # Iterate through all facts to find footnote references
            for fact_obj in model_xbrl.facts:
                # Check if fact has footnote references
                if hasattr(fact_obj, 'footnoteRefs') and fact_obj.footnoteRefs:
                    fact_qname = fact_obj.qname
                    concept_name = fact_qname.localName if fact_qname else None
                    fact_id_xbrl = fact_obj.id if hasattr(fact_obj, 'id') else None
                    
                    for footnote_ref in fact_obj.footnoteRefs:
                        if not footnote_ref:
                            continue
                        
                        # Get footnote object
                        footnote_obj = model_xbrl.modelObject(footnote_ref)
                        if not footnote_obj:
                            continue
                        
                        # Extract footnote text
                        footnote_text = None
                        if hasattr(footnote_obj, 'textValue'):
                            footnote_text = footnote_obj.textValue
                        elif hasattr(footnote_obj, 'stringValue'):
                            footnote_text = footnote_obj.stringValue
                        
                        # Extract footnote label/ID
                        footnote_label = None
                        if hasattr(footnote_obj, 'label'):
                            footnote_label = footnote_obj.label
                        elif hasattr(footnote_obj, 'id'):
                            footnote_label = footnote_obj.id
                        
                        # Extract footnote role
                        footnote_role = None
                        if hasattr(footnote_obj, 'role'):
                            footnote_role = footnote_obj.role
                        
                        # Extract language
                        footnote_lang = 'en'
                        if hasattr(footnote_obj, 'xmlLang'):
                            footnote_lang = footnote_obj.xmlLang or 'en'
                        
                        footnotes.append({
                            'fact_id_xbrl': fact_id_xbrl,
                            'concept_name': concept_name,
                            'footnote_text': footnote_text,
                            'footnote_label': footnote_label,
                            'footnote_role': footnote_role,
                            'footnote_lang': footnote_lang
                        })
            
            logger.info(f"Extracted {len(footnotes)} footnote references")
            
        except Exception as e:
            logger.warning(f"Error extracting footnote references: {e}")
        
        return footnotes
    
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

