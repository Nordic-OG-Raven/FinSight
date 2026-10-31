"""Construct SEC EDGAR filing URLs from a stored CIK + accession.

The warehouse stores the CIK without leading zeros (e.g. "320193" for Apple) and the
accession *with* dashes (e.g. "0000320193-25-000079"). EDGAR's Archives path wants the
integer CIK, the accession with dashes removed for the folder, and the accession with
dashes kept for the -index.htm filename:

    https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/0000320193-25-000079-index.htm
"""
from __future__ import annotations


def edgar_filing_url(cik: str | int | None, accession: str | None) -> str | None:
    """Return the EDGAR filing-index URL, or None if cik/accession is missing.

    Tolerates a zero-padded CIK defensively (EDGAR accepts the integer form).
    """
    if not cik or not accession:
        return None
    folder = accession.replace("-", "")
    cik_int = str(cik).lstrip("0") or str(cik)  # tolerate a padded CIK; never produce ""
    return (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{cik_int}/{folder}/{accession}-index.htm"
    )
