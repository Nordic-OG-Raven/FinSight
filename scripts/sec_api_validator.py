"""
SEC Company Facts API Validator

Uses SEC API to validate extracted XBRL data and identify missing concepts.
This is a validation/comparison tool, NOT a replacement for XBRL parsing.
"""

import requests
import json
from pathlib import Path
from typing import Dict, List, Optional
import time

SEC_API_BASE = "https://data.sec.gov/api/xbrl/companyfacts/CIK{}.json"
SEC_API_CONCEPT = "https://data.sec.gov/api/xbrl/companyconcept/CIK{}/{}/{}.json"

def get_cik_from_ticker(ticker: str) -> Optional[str]:
    """Get CIK from ticker symbol"""
    # SEC ticker to CIK mapping (simplified - in production, use SEC's ticker.json)
    # For now, hardcode known mappings or use a lookup service
    ticker_to_cik = {
        'NVO': '0000353278',  # Novo Nordisk (CORRECTED - was 0000353165)
        'AAPL': '0000320193',
        'MSFT': '0000789019',
        # Add more as needed
    }
    return ticker_to_cik.get(ticker.upper())

def fetch_sec_facts(cik: str, year: int = 2022, taxonomy: str = 'ifrs-full') -> Optional[Dict]:
    """
    Fetch facts from SEC Company Facts API for a specific year
    
    Args:
        cik: Company CIK (10 digits, zero-padded)
        year: Fiscal year to extract
        taxonomy: Taxonomy to use (default: 'ifrs-full' for IFRS companies like Novo Nordisk)
        
    Returns:
        Dictionary of facts for the year, or None if error
    """
    url = SEC_API_BASE.format(cik)
    
    try:
        headers = {
            'User-Agent': 'FinSight Data Validator (contact@example.com)',  # SEC requires user agent
            'Accept': 'application/json'
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        # Extract facts for the specified year
        facts_2022 = {}
        
        # Iterate through all facts in the API response
        if 'facts' in data:
            # Try specified taxonomy first, then fall back to any
            taxonomies_to_check = [taxonomy] if taxonomy in data['facts'] else list(data['facts'].keys())
            
            for tax in taxonomies_to_check:
                concepts = data['facts'][tax]
                for concept_name, concept_data in concepts.items():
                    if 'units' in concept_data:
                        for unit, periods in concept_data['units'].items():
                            for period in periods:
                                # Check if this period matches our year
                                period_year = None
                                if 'end' in period:
                                    period_year = period['end'][:4]  # Extract year from date
                                elif 'instant' in period:
                                    period_year = period['instant'][:4]
                                
                                if period_year and int(period_year) == year:
                                    # Store fact
                                    key = f"{concept_name}_{unit}"
                                    if key not in facts_2022:
                                        facts_2022[key] = []
                                    facts_2022[key].append({
                                        'concept': concept_name,
                                        'value': period.get('val'),
                                        'unit': unit,
                                        'period': period,
                                        'taxonomy': tax
                                    })
        
        return facts_2022
        
    except requests.exceptions.RequestException as e:
        print(f"Error fetching SEC API data: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status: {e.response.status_code}")
            print(f"Response text: {e.response.text[:500]}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error parsing SEC API response: {e}")
        return None

def compare_with_extracted(sec_facts: Dict, extracted_concepts: List[str]) -> Dict:
    """
    Compare SEC API facts with extracted concepts
    
    Args:
        sec_facts: Facts from SEC API
        extracted_concepts: List of concept names extracted from XBRL
        
    Returns:
        Comparison report with:
        - concepts_in_sec_api: Concepts found in SEC API
        - concepts_in_extracted: Concepts found in extracted data
        - missing_in_extracted: Concepts in SEC API but not in extracted
        - missing_in_sec_api: Concepts in extracted but not in SEC API
    """
    sec_concepts = set()
    for key, facts_list in sec_facts.items():
        for fact in facts_list:
            sec_concepts.add(fact['concept'])
    
    extracted_set = set(extracted_concepts)
    
    return {
        'concepts_in_sec_api': len(sec_concepts),
        'concepts_in_extracted': len(extracted_set),
        'missing_in_extracted': sorted(sec_concepts - extracted_set),
        'missing_in_sec_api': sorted(extracted_set - sec_concepts),
        'common_concepts': sorted(sec_concepts & extracted_set)
    }

def validate_2022_extraction(ticker: str, year: int = 2022, extracted_csv_path: Optional[Path] = None) -> Dict:
    """
    Validate extracted 2022 data against SEC API
    
    Args:
        ticker: Company ticker symbol
        year: Year to validate
        extracted_csv_path: Path to CSV file with extracted facts
        
    Returns:
        Validation report
    """
    print(f"\n{'='*60}")
    print(f"SEC API Validation for {ticker} {year}")
    print(f"{'='*60}\n")
    
    # Get CIK
    cik = get_cik_from_ticker(ticker)
    if not cik:
        return {'error': f'CIK not found for ticker {ticker}'}
    
    print(f"CIK: {cik}")
    
    # Fetch SEC API data
    print(f"Fetching data from SEC API...")
    # Novo Nordisk uses IFRS, not US-GAAP
    sec_facts = fetch_sec_facts(cik, year, taxonomy='ifrs-full')
    
    if not sec_facts:
        return {'error': 'Failed to fetch SEC API data'}
    
    print(f"Found {len(sec_facts)} fact groups in SEC API")
    
    # Load extracted concepts if CSV provided
    extracted_concepts = []
    if extracted_csv_path and extracted_csv_path.exists():
        import csv
        with open(extracted_csv_path) as f:
            reader = csv.DictReader(f)
            extracted_concepts = [row['concept'] for row in reader if row.get('concept')]
    
    # Compare
    if extracted_concepts:
        comparison = compare_with_extracted(sec_facts, extracted_concepts)
        
        print(f"\nComparison Results:")
        print(f"  Concepts in SEC API: {comparison['concepts_in_sec_api']}")
        print(f"  Concepts in extracted: {comparison['concepts_in_extracted']}")
        print(f"  Common concepts: {len(comparison['common_concepts'])}")
        print(f"  Missing in extracted: {len(comparison['missing_in_extracted'])}")
        print(f"  Missing in SEC API: {len(comparison['missing_in_sec_api'])}")
        
        if comparison['missing_in_extracted']:
            print(f"\n⚠️  Concepts in SEC API but missing in extracted (first 20):")
            for concept in comparison['missing_in_extracted'][:20]:
                print(f"    - {concept}")
        
        return {
            'sec_facts': sec_facts,
            'comparison': comparison
        }
    else:
        # Just return SEC API facts
        print(f"\nSEC API Facts (sample):")
        for i, (key, facts_list) in enumerate(list(sec_facts.items())[:10]):
            print(f"  {key}: {facts_list[0]['value']} {facts_list[0]['unit']}")
        
        return {
            'sec_facts': sec_facts,
            'total_facts': len(sec_facts)
        }

if __name__ == '__main__':
    import sys
    
    ticker = sys.argv[1] if len(sys.argv) > 1 else 'NVO'
    year = int(sys.argv[2]) if len(sys.argv) > 2 else 2022
    
    # Optional: path to extracted CSV for comparison
    csv_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    
    result = validate_2022_extraction(ticker, year, csv_path)
    
    if 'error' in result:
        print(f"\n❌ Error: {result['error']}")
    else:
        print(f"\n✅ Validation complete")

