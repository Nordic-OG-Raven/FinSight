"""Tests for src/utils/edgar_url.py: dash handling, CIK form, and missing input."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.edgar_url import edgar_filing_url  # noqa: E402


def test_builds_expected_url():
    url = edgar_filing_url("320193", "0000320193-25-000079")
    assert url == (
        "https://www.sec.gov/Archives/edgar/data/"
        "320193/000032019325000079/0000320193-25-000079-index.htm"
    )


def test_tolerates_zero_padded_cik():
    # A defensively padded CIK should still yield the integer form in the path.
    assert "/data/320193/" in edgar_filing_url("0000320193", "0000320193-25-000079")


def test_accepts_integer_cik():
    assert "/data/320193/" in edgar_filing_url(320193, "0000320193-25-000079")


def test_missing_input_returns_none():
    assert edgar_filing_url(None, "0000320193-25-000079") is None
    assert edgar_filing_url("320193", None) is None
    assert edgar_filing_url("", "") is None
