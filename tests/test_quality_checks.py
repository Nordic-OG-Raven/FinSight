"""
Tests for the duplicate/conflict + anomaly detectors in src/validation/quality.py.

The clean 8-filer reference set produces zero findings (verified on load); these tests prove
the detectors actually FIRE on constructed bad data, so "no findings" means clean rather than
broken.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.extraction.edgartools_adapter import Fact  # noqa: E402
from src.validation.quality import _detect_anomalies, _detect_conflicts  # noqa: E402


def _dur(concept, value, year):
    return Fact(concept=concept, label=None, value_numeric=value, value_text=None, unit="USD",
                period_start=date(year, 1, 1), period_end=date(year, 12, 31), instant_date=None,
                period_type="duration", fiscal_year=year, fiscal_period="FY",
                statement_type="income_statement", dimensions=None, is_dimensioned=False)


def _inst(concept, value, year):
    return Fact(concept=concept, label=None, value_numeric=value, value_text=None, unit="USD",
                period_start=None, period_end=None, instant_date=date(year, 12, 31),
                period_type="instant", fiscal_year=year, fiscal_period="FY",
                statement_type="balance_sheet", dimensions=None, is_dimensioned=False)


def test_conflict_fires_on_disagreeing_synonyms():
    facts = [_dur("us-gaap:Revenues", 100, 2025),
             _dur("us-gaap:RevenuesNetOfInterestExpense", 90, 2025)]
    found = _detect_conflicts(facts)
    assert any("revenue" in f for f in found), found


def test_no_conflict_when_synonyms_agree():
    # JPM's real case: both tags carry the identical value
    facts = [_dur("us-gaap:Revenues", 182447, 2025),
             _dur("us-gaap:RevenuesNetOfInterestExpense", 182447, 2025)]
    assert _detect_conflicts(facts) == []


def test_anomaly_net_margin_over_100pct():
    facts = [_dur("us-gaap:Revenues", 100, 2025), _dur("us-gaap:NetIncomeLoss", 250, 2025)]
    assert any("net margin" in a for a in _detect_anomalies(facts))


def test_anomaly_negative_revenue():
    assert any("revenue is negative" in a for a in _detect_anomalies([_dur("us-gaap:Revenues", -5, 2025)]))


def test_anomaly_gross_profit_exceeds_revenue():
    facts = [_dur("us-gaap:Revenues", 100, 2025), _dur("us-gaap:GrossProfit", 150, 2025)]
    assert any("gross profit" in a for a in _detect_anomalies(facts))


def test_anomaly_yoy_scale_jump():
    facts = [_dur("us-gaap:Revenues", 100, 2024), _dur("us-gaap:Revenues", 100_000, 2025)]
    assert any("scale error" in a for a in _detect_anomalies(facts))


def test_clean_facts_produce_no_findings():
    facts = [_dur("us-gaap:Revenues", 1000, 2024), _dur("us-gaap:Revenues", 1100, 2025),
             _dur("us-gaap:NetIncomeLoss", 200, 2025), _dur("us-gaap:GrossProfit", 600, 2025),
             _inst("us-gaap:Assets", 5000, 2025),
             _inst("us-gaap:StockholdersEquity", 2000, 2025)]
    assert _detect_conflicts(facts) == []
    assert _detect_anomalies(facts) == []


if __name__ == "__main__":
    import traceback
    fails = 0
    for n, fn in sorted(globals().items()):
        if n.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS {n}")
            except Exception:
                fails += 1; print(f"FAIL {n}"); traceback.print_exc()
    sys.exit(1 if fails else 0)
