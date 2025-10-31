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
                            accession_match = re.search(r'/(\d{10}-\d{2}-\d{6})/', documents_url)
                            accession_number = accession_match.group(1) if accession_match else ''
                            
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
    
    def get_filing_files(self, documents_url: str) -> Optional[str]:
        """
        Get the XBRL instance document URL from a filing's documents page
        
        Args:
            documents_url: URL to the filing's documents page
            
        Returns:
            URL to the XBRL instance document (usually ends with .htm or .xml)
        """
        try:
            response = self.session.get(documents_url)
            response.raise_for_status()
            self._rate_limit()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find the documents table
            table = soup.find('table', {'class': 'tableFile'})
            if not table:
                logger.warning("Could not find documents table")
                return None
            
            # Look for XBRL instance document
            # Strategy: Find the primary document (usually the first .htm file that's not an exhibit)
            candidates = []
            
            for row in table.find_all('tr')[1:]:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    seq = cols[0].text.strip()  # Sequence number
                    doc_type = cols[3].text.strip()
                    filename = cols[2].text.strip()
                    
                    link = cols[2].find('a')
                    if not link:
                        continue
                    
                    file_url = self.BASE_URL + link['href']
                    
                    # Skip if it's clearly not an instance document
                    if any(x in filename.lower() for x in ['_cal', '_def', '_lab', '_pre', '_sch']):
                        continue
                    
                    # Skip exhibits (check doc_type first)
                    if 'EX-' in doc_type.upper():
                        continue
                    if 'exhibit' in filename.lower():
                        continue
                    
                    # Prioritize files that are clearly instance documents
                    priority = 0
                    if filename.endswith('.htm') or filename.endswith('.xml'):
                        priority += 10
                    if 'INSTANCE' in doc_type.upper() or '10-K' in doc_type or '20-F' in doc_type:
                        priority += 50  # Increased from 20
                    if seq == '1' or seq == '':  # Sequence 1 is usually the main document
                        priority += 30  # Increased from 5
                    # Strongly prefer _htm.xml (contains full inline XBRL data)
                    if filename.endswith('_htm.xml'):
                        priority += 100
                    
                    if priority > 0:
                        candidates.append((priority, filename, file_url))
            
            # Sort by priority and return the best match
            if candidates:
                candidates.sort(reverse=True)
                best_match = candidates[0]
                logger.info(f"Found XBRL instance document: {best_match[1]} (priority: {best_match[0]})")
                return best_match[2]
            
            logger.warning("Could not find XBRL instance document")
            return None
            
        except Exception as e:
            logger.error(f"Error getting filing files: {e}")
            return None
    
    def download_filing(
        self, 
        ticker: str, 
        year: int,
        filing_type: str = "10-K"
    ) -> Optional[Path]:
        """
        Download the most recent filing for a ticker and year
        
        Args:
            ticker: Stock ticker symbol
            year: Fiscal year
            filing_type: Type of filing (10-K, 20-F, etc.)
            
        Returns:
            Path to downloaded file, or None if download failed
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
        
        # Get XBRL instance document URL
        xbrl_url = self.get_filing_files(target_filing['documents_url'])
        
        if not xbrl_url:
            logger.error("Could not find XBRL instance document")
            return None
        
        # Download the file
        filename = f"{ticker}_{year}_{filing_type.replace('-', '')}_{target_filing['accession_number'].replace('-', '')}.htm"
        output_path = self.output_dir / filename
        
        # Check if already downloaded
        if output_path.exists():
            logger.info(f"File already exists: {output_path}")
            return output_path
        
        try:
            # Handle SEC inline XBRL viewer URLs (they start with /ix?doc=)
            if '/ix?doc=' in xbrl_url:
                # Extract the actual document URL from the viewer URL
                xbrl_url = xbrl_url.split('/ix?doc=')[1]
                if not xbrl_url.startswith('http'):
                    xbrl_url = self.BASE_URL + '/' + xbrl_url.lstrip('/')
            
            logger.info(f"Downloading from {xbrl_url}")
            response = self.session.get(xbrl_url)
            response.raise_for_status()
            
            output_path.write_bytes(response.content)
            logger.info(f"Successfully downloaded to {output_path}")
            
            self._rate_limit()
            return output_path
            
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            return None
    
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

