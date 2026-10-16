"""
Canonical cross-taxonomy labels for the core financial-statement lines.

PRD §2.3 / ROADMAP top item: *one canonical label per economic line*, so the same line
reconciles across filers no matter which raw XBRL concept they tagged — a us-gaap concept vs
its ifrs-full equivalent, or synonymous us-gaap tags (e.g. `Revenues` vs
`RevenueFromContractWithCustomerExcludingAssessedTax`).

Deliberately SLIM and curated: it covers the "universal metrics" that matter for cross-company
comparison (the primary income-statement, balance-sheet, and cash-flow lines). Everything else
keeps its per-concept snake-case label — consolidating the long tail is not needed for
reconciliation and would be unmaintainable.

**Priority.** Each line lists its concepts most-preferred first. When one filing reports more
than one concept for a line (e.g. a bank tagging both `Revenues` and `RevenuesNetOfInterestExpense`,
or a filer tagging both parent-only and including-NCI equity), the loader gives the canonical
label to the highest-priority concept and lets the rest fall back to their own label — so the
canonical line is deterministic and nothing is silently dropped.
"""
from __future__ import annotations

from typing import Optional

# canonical_label -> concepts, highest priority first
CANONICAL: dict[str, list[str]] = {
    # ---- income statement ----
    "revenue": [
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax",
        "us-gaap:RevenuesNetOfInterestExpense",   # banks: total net revenue
        "us-gaap:Revenues",
        "ifrs-full:Revenue",
    ],
    "cost_of_revenue": [
        "us-gaap:CostOfRevenue",
        "us-gaap:CostOfGoodsAndServicesSold",
        "us-gaap:CostOfGoodsSold",
        "ifrs-full:CostOfSales",
    ],
    "gross_profit": ["us-gaap:GrossProfit", "ifrs-full:GrossProfit"],
    "research_and_development_expense": [
        "us-gaap:ResearchAndDevelopmentExpense",
        "ifrs-full:ResearchAndDevelopmentExpense",
    ],
    "selling_general_and_administrative_expense": [
        "us-gaap:SellingGeneralAndAdministrativeExpense",
        "us-gaap:SellingGeneralAndAdministrativeExpenses",
    ],
    "operating_income": [
        "us-gaap:OperatingIncomeLoss",
        "ifrs-full:ProfitLossFromOperatingActivities",
    ],
    "income_before_income_taxes": [
        "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "ifrs-full:ProfitLossBeforeTax",
    ],
    "income_tax_expense": [
        "us-gaap:IncomeTaxExpenseBenefit",
        "ifrs-full:IncomeTaxExpenseContinuingOperations",
    ],
    # NetIncomeLoss (attributable to parent) preferred over ProfitLoss (incl. NCI) when both
    # are tagged — the common headline. The loser keeps its own label, not dropped.
    "net_income": ["us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss", "ifrs-full:ProfitLoss"],
    "eps_basic": ["us-gaap:EarningsPerShareBasic", "ifrs-full:BasicEarningsLossPerShare"],
    "eps_diluted": ["us-gaap:EarningsPerShareDiluted", "ifrs-full:DilutedEarningsLossPerShare"],
    "weighted_average_shares_basic": ["us-gaap:WeightedAverageNumberOfSharesOutstandingBasic"],
    "weighted_average_shares_diluted": ["us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding"],

    # ---- balance sheet ----
    "total_assets": ["us-gaap:Assets", "ifrs-full:Assets"],
    "current_assets": ["us-gaap:AssetsCurrent", "ifrs-full:CurrentAssets"],
    "cash_and_cash_equivalents": [
        "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        "ifrs-full:CashAndCashEquivalents",
    ],
    "total_liabilities": ["us-gaap:Liabilities", "ifrs-full:Liabilities"],
    "current_liabilities": ["us-gaap:LiabilitiesCurrent", "ifrs-full:CurrentLiabilities"],
    # IncludingNCI is the true total equity; prefer it when both are present.
    "total_equity": [
        "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "us-gaap:StockholdersEquity",
        "ifrs-full:Equity",
        "ifrs-full:EquityAttributableToOwnersOfParent",
    ],
    "total_liabilities_and_equity": [
        "us-gaap:LiabilitiesAndStockholdersEquity",
        "us-gaap:LiabilitiesAndEquity",
        "ifrs-full:EquityAndLiabilities",
    ],

    # ---- cash flow ----
    "net_cash_from_operating_activities": [
        "us-gaap:NetCashProvidedByUsedInOperatingActivities",
        "us-gaap:NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        "ifrs-full:CashFlowsFromUsedInOperatingActivities",
    ],
    "net_cash_from_investing_activities": [
        "us-gaap:NetCashProvidedByUsedInInvestingActivities",
        "us-gaap:NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
        "ifrs-full:CashFlowsFromUsedInInvestingActivities",
    ],
    "net_cash_from_financing_activities": [
        "us-gaap:NetCashProvidedByUsedInFinancingActivities",
        "us-gaap:NetCashProvidedByUsedInFinancingActivitiesContinuingOperations",
        "ifrs-full:CashFlowsFromUsedInFinancingActivities",
    ],
    "capital_expenditures": [
        "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
        "us-gaap:PaymentsToAcquireProductiveAssets",
        "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    ],
    "depreciation_and_amortization": [
        "us-gaap:DepreciationDepletionAndAmortization",
        "us-gaap:DepreciationAmortizationAndAccretionNet",
        "us-gaap:DepreciationAndAmortization",
    ],
}

# reverse: concept -> (canonical_label, priority_index)  (lower index = higher priority)
_REVERSE: dict[str, tuple[str, int]] = {}
for _label, _concepts in CANONICAL.items():
    for _i, _c in enumerate(_concepts):
        if _c in _REVERSE:
            raise ValueError(f"concept {_c} mapped to two canonical labels — mapping must be 1:1")
        _REVERSE[_c] = (_label, _i)


def canonical(concept: str) -> Optional[tuple[str, int]]:
    """(canonical_label, priority) for a raw `taxonomy:Concept`, or None if not a core line."""
    return _REVERSE.get(concept)


def canonical_label(concept: str) -> Optional[str]:
    hit = _REVERSE.get(concept)
    return hit[0] if hit else None
