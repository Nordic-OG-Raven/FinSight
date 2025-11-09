#!/usr/bin/env python3
"""
SEC Filing Ingestion Module

Downloads XBRL filings (10-K, 20-F) from SEC EDGAR.
Supports both automated search by ticker/year and direct URL downloads.
"""
import re
import time
import logging
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime
import requests
from bs4 import BeautifulSoup

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SECFilingDownloader:
    """Download XBRL filings from SEC EDGAR"""
    
    # SEC requires User-Agent header
    HEADERS = {
        'User-Agent': 'FinSight Financial Analysis Pipeline contact@example.com',
        'Accept-Encoding': 'gzip, deflate',
        'Host': 'www.sec.gov'
    }
    
    BASE_URL = "https://www.sec.gov"
    EDGAR_SEARCH_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
    
    def __init__(self, output_dir: Path, rate_limit_delay: float = 0.1):
        """
        Initialize SEC downloader
        
        Args:
            output_dir: Directory to save downloaded files
            rate_limit_delay: Seconds to wait between requests (SEC requires rate limiting)
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.rate_limit_delay = rate_limit_delay
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
    
    def _rate_limit(self):
        """Enforce rate limiting between requests"""
        time.sleep(self.rate_limit_delay)
    
    def search_filings(
        self, 
        ticker: str, 
        filing_type: str = "10-K",
        count: int = 10
    ) -> List[Dict[str, str]]:
        """
        Search for company filings by ticker
        
        Args:
            ticker: Stock ticker symbol
            filing_type: Type of filing (10-K, 20-F, etc.)
            count: Number of recent filings to retrieve
            
        Returns:
            List of filing metadata dicts with keys: date, accession_number, url
        """
        logger.info(f"Searching for {filing_type} filings for {ticker}...")
        
        params = {
            'action': 'getcompany',
            'CIK': ticker,
            'type': filing_type,
            'dateb': '',
            'owner': 'exclude',
            'count': count,
            'search_text': ''
        }
        
        try:
            response = self.session.get(self.EDGAR_SEARCH_URL, params=params)
            response.raise_for_status()
            self._rate_limit()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find the filings table
            filings_table = soup.find('table', {'class': 'tableFile2'})
            if not filings_table:
                logger.warning(f"No filings found for {ticker}")
                return []
            
            filings = []
            rows = filings_table.find_all('tr')[1:]  # Skip header row
            
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    filing_type_col = cols[0].text.strip()
                    if filing_type in filing_type_col:
                        filing_date = cols[3].text.strip()
                        
                        # Get documents link
                        documents_link = cols[1].find('a', {'id': 'documentsbutton'})
                        if documents_link:
                            documents_url = self.BASE_URL + documents_link['href']
                            
                            # Extract accession number from URL
                            # Format: /Archives/edgar/data/CIK/ACCESSION-NUMBER/index.htm
                            accession_match = re.search(r'/(\d{10}-\d{2}-\d{6})/', documents_url)
                            if not accession_match:
                                # Try alternative format without dashes
                                accession_match = re.search(r'/(\d{10}\d{2}\d{6})/', documents_url)
                                if accession_match:
                                    # Add dashes to match standard format
                                    acc_str = accession_match.group(1)
                                    accession_number = f"{acc_str[:10]}-{acc_str[10:12]}-{acc_str[12:]}"
                                else:
                                    accession_number = ''
                            else:
                                accession_number = accession_match.group(1)
                            
                            filings.append({
                                'date': filing_date,
                                'accession_number': accession_number,
                                'documents_url': documents_url,
                                'filing_type': filing_type_col
                            })
            
            logger.info(f"Found {len(filings)} {filing_type} filings for {ticker}")
            return filings
            
        except Exception as e:
            logger.error(f"Error searching filings: {e}")
            return []
    
    def get_filing_files(self, documents_url: str) -> Dict[str, List[Dict[str, str]]]:
        """
        Get ALL XBRL-related files from a filing's documents page
        
        Args:
            documents_url: URL to the filing's documents page
            
        Returns:
            Dictionary with 'instance', 'calculation', 'presentation', 'definition', 
            'label', 'schema' keys, each containing list of file info dicts
        """
        try:
            response = self.session.get(documents_url)
            response.raise_for_status()
            self._rate_limit()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find ALL documents tables (there can be multiple - main filing and XBRL files are often separate)
            tables = soup.find_all('table', {'class': 'tableFile'})
            if not tables:
                logger.warning("Could not find documents table")
                return {}
            
            # Categorize XBRL files
            xbrl_files = {
                'instance': [],
                'calculation': [],
                'presentation': [],
                'definition': [],
                'label': [],
                'schema': []
            }
            
            # Process all tables
            for table in tables:
                for row in table.find_all('tr')[1:]:
                    cols = row.find_all('td')
                    if len(cols) >= 4:
                        seq = cols[0].text.strip()
                        doc_type = cols[3].text.strip()
                        filename = cols[2].text.strip()
                        
                        link = cols[2].find('a')
                        if not link:
                            continue
                        
                        file_url = self.BASE_URL + link['href']
                        
                        # Skip exhibits
                        if 'EX-' in doc_type.upper() or 'exhibit' in filename.lower():
                            continue
                        
                        file_info = {
                            'filename': filename,
                            'url': file_url,
                            'doc_type': doc_type,
                            'sequence': seq
                        }
                        
                        # Categorize by filename pattern
                        filename_lower = filename.lower()
                        
                        if '_cal.xml' in filename_lower or 'calculation' in filename_lower:
                            xbrl_files['calculation'].append(file_info)
                            logger.debug(f"Found calculation linkbase: {filename}")
                        elif '_pre.xml' in filename_lower or 'presentation' in filename_lower:
                            xbrl_files['presentation'].append(file_info)
                            logger.debug(f"Found presentation linkbase: {filename}")
                        elif '_def.xml' in filename_lower or 'definition' in filename_lower:
                            xbrl_files['definition'].append(file_info)
                            logger.debug(f"Found definition linkbase: {filename}")
                        elif '_lab.xml' in filename_lower or 'label' in filename_lower:
                            xbrl_files['label'].append(file_info)
                            logger.debug(f"Found label linkbase: {filename}")
                        elif filename_lower.endswith('.xsd') or 'schema' in filename_lower:
                            xbrl_files['schema'].append(file_info)
                            logger.debug(f"Found schema: {filename}")
                        elif (filename_lower.endswith('.htm') or filename_lower.endswith('.xml')) and \
                             not any(x in filename_lower for x in ['_cal', '_def', '_lab', '_pre', '_sch']):
                            # Instance document
                            priority = 0
                            if 'INSTANCE' in doc_type.upper() or '10-K' in doc_type or '20-F' in doc_type:
                                priority += 50
                            if seq == '1' or seq == '':
                                priority += 30
                            if filename_lower.endswith('_htm.xml'):
                                priority += 100
                            
                            file_info['priority'] = priority
                            xbrl_files['instance'].append(file_info)
                            logger.debug(f"Found instance document: {filename} (priority: {priority})")
            if xbrl_files['instance']:
                xbrl_files['instance'].sort(key=lambda x: x.get('priority', 0), reverse=True)
            
            # Log summary
            logger.info(f"Found XBRL package:")
            logger.info(f"  Instance documents: {len(xbrl_files['instance'])}")
            logger.info(f"  Calculation linkbases: {len(xbrl_files['calculation'])}")
            logger.info(f"  Presentation linkbases: {len(xbrl_files['presentation'])}")
            logger.info(f"  Definition linkbases: {len(xbrl_files['definition'])}")
            logger.info(f"  Label linkbases: {len(xbrl_files['label'])}")
            logger.info(f"  Schema files: {len(xbrl_files['schema'])}")
            
            return xbrl_files
            
        except Exception as e:
            logger.error(f"Error getting filing files: {e}")
            return {}
    
    def download_filing(
        self, 
        ticker: str, 
        year: int,
        filing_type: str = "10-K",
        download_complete_package: bool = True
    ) -> Optional[Path]:
        """
        Download XBRL filing package for a ticker and year
        
        Args:
            ticker: Stock ticker symbol
            year: Fiscal year
            filing_type: Type of filing (10-K, 20-F, etc.)
            download_complete_package: If True, downloads all linkbase files; if False, only instance
            
        Returns:
            Path to downloaded instance file (main entry point), or None if download failed
        """
        logger.info(f"Downloading {filing_type} for {ticker} - year {year}")
        
        # Search for filings
        filings = self.search_filings(ticker, filing_type, count=20)
        
        if not filings:
            logger.error(f"No {filing_type} filings found for {ticker}")
            return None
        
        # Find filing for the specified year
        target_filing = None
        for filing in filings:
            filing_date = datetime.strptime(filing['date'], '%Y-%m-%d')
            if filing_date.year == year or filing_date.year == year + 1:  # Allow year+1 for fiscal year differences
                target_filing = filing
                break
        
        if not target_filing:
            logger.warning(f"No {filing_type} found for {ticker} in year {year}, using most recent")
            target_filing = filings[0]
        
        logger.info(f"Found filing dated {target_filing['date']}")
        
        # Get all XBRL files
        xbrl_files = self.get_filing_files(target_filing['documents_url'])
        
        if not xbrl_files.get('instance'):
            logger.error("Could not find XBRL instance document")
            return None
        
        # Create a subdirectory for this filing
        accession = target_filing['accession_number'].replace('-', '')
        filing_dir = self.output_dir / f"{ticker}_{year}_{filing_type.replace('-', '')}_{accession}"
        filing_dir.mkdir(parents=True, exist_ok=True)
        
        # Download instance document (required)
        instance_file = xbrl_files['instance'][0]
        instance_filename = instance_file['filename']
        instance_path = filing_dir / instance_filename
        
        # Check if already downloaded
        if instance_path.exists() and not download_complete_package:
            logger.info(f"Instance file already exists: {instance_path}")
            return instance_path
        
        try:
            # Download instance document
            instance_url = instance_file['url']
            
            # Handle SEC inline XBRL viewer URLs
            if '/ix?doc=' in instance_url:
                instance_url = instance_url.split('/ix?doc=')[1]
                if not instance_url.startswith('http'):
                    instance_url = self.BASE_URL + '/' + instance_url.lstrip('/')
            
            if not instance_path.exists():
                logger.info(f"Downloading instance: {instance_filename}")
                response = self.session.get(instance_url)
                response.raise_for_status()
                instance_path.write_bytes(response.content)
                self._rate_limit()
            
            # SOLUTION: Extract and download schema files referenced in instance document
            # Schema files are often not in documents table but are required for parsing
            if instance_path.exists():
                self._download_referenced_schemas(instance_path, filing_dir, target_filing)
            
            # Download complete package if requested
            if download_complete_package:
                # Download linkbase files
                linkbase_downloaded = 0
                for category in ['calculation', 'presentation', 'definition', 'label', 'schema']:
                    for file_info in xbrl_files.get(category, []):
                        file_path = filing_dir / file_info['filename']
                        
                        if file_path.exists():
                            logger.debug(f"Already exists: {file_info['filename']}")
                            linkbase_downloaded += 1
                            continue
                        
                        try:
                            logger.info(f"Downloading {category}: {file_info['filename']}")
                            response = self.session.get(file_info['url'])
                            response.raise_for_status()
                            file_path.write_bytes(response.content)
                            linkbase_downloaded += 1
                            self._rate_limit()
                        except Exception as e:
                            logger.warning(f"Failed to download {file_info['filename']}: {e}")
                            continue
                
                # CRITICAL: Also check for linkbase files referenced in the HTML/instance document
                # For inline XBRL, linkbases may be referenced but not in the documents table
                if instance_path.exists():
                    # Try to extract linkbase references from the instance document
                    try:
                        with open(instance_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read(50000)  # Read first 50KB
                            import re
                            # Find linkbase references (e.g., nvo-20241231_pre.xml)
                            linkbase_refs = re.findall(r'xlink:href="([^"]*_(?:pre|cal|def|lab)\.xml)"', content, re.IGNORECASE)
                            for linkbase_ref in set(linkbase_refs):
                                linkbase_path = filing_dir / linkbase_ref
                                if not linkbase_path.exists():
                                    # Try to construct URL and download
                                    # Linkbase files are typically in the same directory as the instance
                                    base_url = target_filing.get('url', '').rsplit('/', 1)[0] if target_filing.get('url') else ''
                                    if base_url:
                                        linkbase_url = f"{base_url}/{linkbase_ref}"
                                        try:
                                            logger.info(f"Downloading referenced linkbase: {linkbase_ref}")
                                            response = self.session.get(linkbase_url)
                                            response.raise_for_status()
                                            linkbase_path.write_bytes(response.content)
                                            linkbase_downloaded += 1
                                            self._rate_limit()
                                        except Exception as e:
                                            # If that fails, try alternative URL pattern (accession without dashes)
                                            # EDGAR sometimes uses accession number without dashes for linkbases
                                            if 'Archives/edgar/data' in base_url:
                                                # Extract CIK and accession from base_url
                                                parts = base_url.split('/')
                                                if len(parts) >= 6:
                                                    cik = parts[5]
                                                    accession_with_dashes = parts[6]
                                                    accession_no_dashes = accession_with_dashes.replace('-', '')
                                                    alt_base_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}"
                                                    alt_linkbase_url = f"{alt_base_url}/{linkbase_ref}"
                                                    try:
                                                        logger.info(f"Trying alternative URL: {alt_linkbase_url}")
                                                        response = self.session.get(alt_linkbase_url)
                                                        response.raise_for_status()
                                                        linkbase_path.write_bytes(response.content)
                                                        linkbase_downloaded += 1
                                                        self._rate_limit()
                                                    except Exception as e2:
                                                        logger.debug(f"Could not download {linkbase_ref} from {alt_linkbase_url}: {e2}")
                                            else:
                                                logger.debug(f"Could not download {linkbase_ref} from {linkbase_url}: {e}")
                    except Exception as e:
                        logger.debug(f"Could not extract linkbase references from instance: {e}")
                
                logger.info(f"Downloaded {linkbase_downloaded} linkbase file(s)")
            
            logger.info(f"✅ Successfully downloaded XBRL package to {filing_dir}")
            logger.info(f"   Instance: {instance_path}")
            
            return instance_path
            
        except Exception as e:
            logger.error(f"Error downloading files: {e}")
            return None
    
    def _download_referenced_schemas(self, instance_path: Path, filing_dir: Path, filing_info: Dict):
        """
        Extract schema references from instance document and download them.
        Schemas are often referenced but not listed in documents table.
        """
        try:
            from bs4 import BeautifulSoup
            import re
            
            # Read instance document
            content = instance_path.read_bytes()
            
            # Parse to find schema references
            soup = BeautifulSoup(content, 'xml')
            schema_refs = soup.find_all('link:schemaRef') + soup.find_all('schemaRef', {'xlink:type': 'simple'})
            
            if not schema_refs:
                # Try regex as fallback
                schema_ref_match = re.search(r'xlink:href=["\']([^"\']+\.xsd)["\']', content.decode('utf-8', errors='ignore'))
                if schema_ref_match:
                    schema_refs = [{'href': schema_ref_match.group(1)}]
                else:
                    return
            
            # Extract base URL from instance file path or filing info
            # Schema files are in the same directory as the instance
            instance_dir = instance_path.parent
            instance_filename = instance_path.name
            
            # Try to extract from documents_url first
            docs_url = filing_info.get('documents_url', '')
            if docs_url:
                # Extract CIK and accession from documents URL
                # Format: /Archives/edgar/data/CIK/ACCESSION-NUMBER/index.htm
                url_match = re.search(r'/Archives/edgar/data/(\d+)/(\d{10}-\d{2}-\d{6})/', docs_url)
                if url_match:
                    cik = url_match.group(1)
                    accession = url_match.group(2).replace('-', '')
                    base_url = f"{self.BASE_URL}/Archives/edgar/data/{cik}/{accession}/"
                else:
                    # Fallback: try to extract from instance file's directory name
                    # Directory format: TICKER_YEAR_FILINGTYPE_ACCESSION
                    dir_name = instance_dir.name
                    acc_match = re.search(r'_(\d{10}\d{2}\d{6})', dir_name)
                    if acc_match:
                        accession = acc_match.group(1)
                        # Try to get CIK from search or use a placeholder (will fail if needed)
                        cik_match = re.search(r'/data/(\d+)/', docs_url)
                        if cik_match:
                            cik = cik_match.group(1)
                            base_url = f"{self.BASE_URL}/Archives/edgar/data/{cik}/{accession}/"
                        else:
                            logger.warning("Could not determine CIK for schema download")
                            return
                    else:
                        logger.warning("Could not determine accession number for schema download")
                        return
            else:
                logger.warning("No documents URL available for schema download")
                return
            
            # Download each referenced schema
            for schema_ref in schema_refs:
                if isinstance(schema_ref, dict):
                    schema_filename = schema_ref.get('href', '')
                else:
                    schema_filename = schema_ref.get('xlink:href', '') or schema_ref.get('href', '')
                
                if not schema_filename or not schema_filename.endswith('.xsd'):
                    continue
                
                # Handle relative paths
                if not schema_filename.startswith('http'):
                    schema_url = base_url + schema_filename
                else:
                    schema_url = schema_filename
                
                schema_path = filing_dir / schema_filename
                
                if schema_path.exists():
                    logger.debug(f"Schema already exists: {schema_filename}")
                    continue
                
                try:
                    logger.info(f"Downloading referenced schema: {schema_filename}")
                    response = self.session.get(schema_url)
                    if response.status_code == 200:
                        schema_path.write_bytes(response.content)
                        self._rate_limit()
                        logger.debug(f"✅ Downloaded schema: {schema_filename}")
                    else:
                        logger.warning(f"Schema not found at {schema_url} (HTTP {response.status_code})")
                except Exception as e:
                    logger.warning(f"Failed to download schema {schema_filename}: {e}")
                    
        except Exception as e:
            logger.warning(f"Error extracting/downloading schemas: {e}")
            # Don't fail the whole download if schema extraction fails
    
    def download_from_url(self, url: str, ticker: str, year: int) -> Optional[Path]:
        """
        Download a filing from a direct URL
        
        Args:
            url: Direct URL to XBRL filing
            ticker: Stock ticker (for filename)
            year: Year (for filename)
            
        Returns:
            Path to downloaded file
        """
        logger.info(f"Downloading from direct URL: {url}")
        
        try:
            response = self.session.get(url)
            response.raise_for_status()
            
            # Generate filename
            filename = f"{ticker}_{year}_direct.htm"
            output_path = self.output_dir / filename
            
            output_path.write_bytes(response.content)
            logger.info(f"Successfully downloaded to {output_path}")
            
            return output_path
            
        except Exception as e:
            logger.error(f"Error downloading from URL: {e}")
            return None


def main():
    """CLI interface for testing"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Download SEC XBRL filings')
    parser.add_argument('--ticker', required=True, help='Stock ticker symbol')
    parser.add_argument('--year', type=int, required=True, help='Fiscal year')
    parser.add_argument('--filing-type', default='10-K', help='Filing type (10-K, 20-F, etc.)')
    parser.add_argument('--output', default='data/raw', help='Output directory')
    
    args = parser.parse_args()
    
    downloader = SECFilingDownloader(output_dir=args.output)
    result = downloader.download_filing(args.ticker, args.year, args.filing_type)
    
    if result:
        print(f"\n✅ Successfully downloaded: {result}")
        print(f"   File size: {result.stat().st_size / 1024:.1f} KB")
    else:
        print("\n❌ Download failed")
        exit(1)


if __name__ == '__main__':
    main()

