"""
Tests for the canonical cross-taxonomy label map (PRD §2.3: a *tested* mapping per taxonomy).

Pure unit tests — no database. They lock in the two properties that make the mapping correct:
1. synonymous concepts across taxonomies resolve to the SAME canonical label (reconciliation);
2. priority ordering is right, so when a filing reports co-occurring synonyms the intended
   concept wins the canonical label (determinism).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.extraction.canonical_labels import CANONICAL, canonical, canonical_label  # noqa: E402


def test_reverse_map_is_one_to_one():
    """No raw concept may belong to two canonical lines (import-time guard; assert here too)."""
    seen = {}
    for label, concepts in CANONICAL.items():
        for c in concepts:
            assert c not in seen, f"{c} in both {seen.get(c)} and {label}"
            seen[c] = label


def test_revenue_synonyms_share_one_label():
    for c in ("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
              "us-gaap:Revenues", "us-gaap:RevenuesNetOfInterestExpense", "ifrs-full:Revenue"):
        assert canonical_label(c) == "revenue", c


def test_usgaap_and_ifrs_equivalents_align():
    pairs = {
        "net_income": ("us-gaap:NetIncomeLoss", "ifrs-full:ProfitLoss"),
        "total_assets": ("us-gaap:Assets", "ifrs-full:Assets"),
        "total_equity": ("us-gaap:StockholdersEquity", "ifrs-full:Equity"),
        "total_liabilities_and_equity": ("us-gaap:LiabilitiesAndStockholdersEquity",
                                         "ifrs-full:EquityAndLiabilities"),
        "net_cash_from_operating_activities": ("us-gaap:NetCashProvidedByUsedInOperatingActivities",
                                               "ifrs-full:CashFlowsFromUsedInOperatingActivities"),
        "eps_diluted": ("us-gaap:EarningsPerShareDiluted", "ifrs-full:DilutedEarningsLossPerShare"),
    }
    for label, (us, ifrs) in pairs.items():
        assert canonical_label(us) == label
        assert canonical_label(ifrs) == label


def test_priority_resolves_cooccurring_synonyms():
    # bank: total-net-revenue must outrank the gross Revenues tag
    assert canonical("us-gaap:RevenuesNetOfInterestExpense")[1] < canonical("us-gaap:Revenues")[1]
    # equity: the including-NCI total must outrank parent-only stockholders' equity
    assert (canonical("us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")[1]
            < canonical("us-gaap:StockholdersEquity")[1])
    # net income: parent NetIncomeLoss preferred over ProfitLoss (incl. NCI)
    assert canonical("us-gaap:NetIncomeLoss")[1] < canonical("us-gaap:ProfitLoss")[1]


def test_noncore_concepts_return_none():
    for c in ("us-gaap:GoodwillImpairmentLoss", "us-gaap:LeaseCost", "dei:EntityCommonStockSharesOutstanding"):
        assert canonical(c) is None
        assert canonical_label(c) is None


if __name__ == "__main__":
    import traceback
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception:
                failures += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    sys.exit(1 if failures else 0)
