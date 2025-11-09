"""
Generic Concept-to-Label Mapping
Maps XBRL concept names to human-readable labels based on accounting terminology patterns.
This is universal and works for all companies, not company-specific.

Best Practice: Use accounting standard terminology patterns, not company-specific labels.
"""

# Generic mapping: concept_name pattern -> human-readable label
# These are based on IFRS/US-GAAP standard terminology, not company-specific
CONCEPT_LABEL_MAP = {
    # Comprehensive Income - Standard IFRS/US-GAAP terminology
    'ReclassificationAdjustmentsOnCashFlowHedgesBeforeTax': 'Realisation of previously deferred (gains)/losses',
    'ReclassificationAdjustmentsOnCashFlowHedges': 'Realisation of previously deferred (gains)/losses',
    'GainsLossesOnCashFlowHedgesBeforeTax': 'Deferred gains/(losses) on hedges open at year-end',
    'GainsLossesOnCashFlowHedgesRelatedToAcquisitionOfBusinesses': 'Deferred gains/(losses) related to acquisition of businesses',
    'OtherComprehensiveIncome': 'Other comprehensive income',
    'OtherComprehensiveIncomeLossNetOfTax': 'Other comprehensive income',
    'OtherComprehensiveIncomeNetOfTaxExchangeDifferencesOnTranslation': 'Exchange rate adjustments of investments in subsidiaries',
    'OtherComprehensiveIncomeNetOfTaxExchangeDifferences': 'Exchange rate adjustments of investments in subsidiaries',
    'GainsLossesOnRemeasurementsOfDefinedBenefitPlans': 'Remeasurements of retirement benefit obligations',
    'RemeasurementsOfDefinedBenefitPlans': 'Remeasurements of retirement benefit obligations',
    'GainsLossesOnRemeasurementsOfDefinedBenefitPlans': 'Remeasurements of retirement benefit obligations',  # Alternative spelling
    'IncomeTaxAndOtherRelatingToComponentsOfOtherComprehensiveIncome': 'Tax and other items',
    'IncomeTaxRelatingToComponentsOfOtherComprehensiveIncome': 'Tax and other items',
    'OtherComprehensiveIncomeThatWillBeReclassifiedToProfitOrLossNetOfTax': 'Items that will be reclassified subsequently to the income statement',
    'OtherComprehensiveIncomeThatWillNotBeReclassifiedToProfitOrLossBeforeTax': 'Items that will not be reclassified subsequently to the income statement',
    'ComprehensiveIncome': 'Total comprehensive income',
    'ComprehensiveIncomeNetOfTax': 'Total comprehensive income',
    
    # Income Statement - Standard terminology
    'Revenue': 'Revenue',
    'RevenueFromContractWithCustomerExcludingAssessedTax': 'Revenue',
    'NetSales': 'Net sales',
    'CostOfSales': 'Cost of goods sold',
    'CostOfGoodsSold': 'Cost of goods sold',
    'GrossProfit': 'Gross profit',
    'OperatingIncome': 'Operating profit',
    'OperatingProfit': 'Operating profit',
    'FinanceIncome': 'Financial income',
    'FinanceCosts': 'Financial expenses',
    'FinancialExpenses': 'Financial expenses',
    'IncomeBeforeTax': 'Profit before income taxes',
    'ProfitBeforeTax': 'Profit before income taxes',
    'IncomeTaxExpenseContinuingOperations': 'Income taxes',
    'IncomeTaxes': 'Income taxes',
    'NetIncomeIncludingNoncontrollingInterest': 'Net profit',
    'NetIncome': 'Net profit',
    'ProfitLossAttributableToOwnersOfParent': 'Net profit',
    
    # Balance Sheet - Standard IFRS/US-GAAP terminology
    'Assets': 'Assets',
    'TotalAssets': 'Total assets',
    # Note: 'Assets' concept_name can be used for both header and total - check normalized_label
    'IntangibleAssetsOtherThanGoodwill': 'Intangible assets',
    'PropertyPlantAndEquipment': 'Property, plant and equipment',
    'PropertyPlantAndEquipmentIncludingRightofuseAssets': 'Property, plant and equipment',
    'InvestmentsInAssociatesAccountedForUsingEquityMethod': 'Investments in associated companies',
    'DeferredTaxAssets': 'Deferred income tax assets',
    'OtherReceivablesAndPrepaymentsNoncurrent': 'Other receivables and prepayments',
    'OtherNoncurrentFinancialAssets': 'Other financial assets',
    'NoncurrentAssets': 'Total non-current assets',
    'Inventories': 'Inventories',
    'CurrentTradeReceivables': 'Trade receivables',
    'TradeReceivables': 'Trade receivables',
    'CurrentTaxAssetsCurrent': 'Tax receivables',
    'CurrentPrepaymentsAndOtherCurrentAssets': 'Other receivables and prepayments',
    'CurrentFinancialAssetsAtFairValueThroughProfitOrLoss': 'Marketable securities',
    'CurrentDerivativeFinancialAssets': 'Derivative financial instruments',
    'CashAndCashEquivalents': 'Cash at bank',  # For balance sheet
    'CashAndEquivalents': 'Cash at bank',  # For balance sheet
    'BalancesWithBanks': 'Cash at bank',  # For balance sheet
    'BalancesWithBanksAndCash': 'Cash at bank',  # For balance sheet
    # Note: For cash flow statement, "cash_and_equivalents" at end of period = "Cash and cash equivalents at the end of the year"
    # This is handled in get_humanized_label() using normalized_label context
    'CurrentAssets': 'Total current assets',
    'EquityAndLiabilities': 'Equity and liabilities',
    'ShareCapital': 'Share capital',
    'IssuedCapital': 'Share capital',
    'TreasuryShares': 'Treasury shares',
    'RetainedEarnings': 'Retained earnings',
    'OtherReserves': 'Other reserves',
    'Equity': 'Total equity',
    'EquityTotal': 'Total equity',
    'StockholdersEquity': 'Total equity',
    'Borrowings': 'Borrowings',
    'LongtermBorrowings': 'Borrowings',
    'DeferredTaxLiabilities': 'Deferred income tax liabilities',
    'NoncurrentRecognisedLiabilitiesDefinedBenefitPlan': 'Retirement benefit obligations',
    'OtherNoncurrentLiabilities': 'Other liabilities',
    'NoncurrentProvisions': 'Provisions',
    'ProvisionsNoncurrent': 'Provisions',
    'NoncurrentLiabilities': 'Total non-current liabilities',
    'CurrentPortionOfLongtermBorrowings': 'Borrowings',
    'TradeAndOtherCurrentPayablesToTradeSuppliers': 'Trade payables',
    'AccountsPayable': 'Trade payables',
    'CurrentTaxLiabilities': 'Tax payables',
    'OtherCurrentLiabilities': 'Other liabilities',
    'CurrentDerivativeFinancialLiabilities': 'Derivative financial instruments',
    'CurrentProvisions': 'Provisions',
    'CurrentLiabilities': 'Total current liabilities',
    'Liabilities': 'Total liabilities',
    'TotalLiabilities': 'Total liabilities',
    
    # Equity Statement - Standard IFRS/US-GAAP terminology
    'BalanceAtBeginningOfYear': 'Balance at the beginning of the year',
    'EquityAtBeginningOfPeriod': 'Balance at the beginning of the year',
    'BalanceAtEndOfYear': 'Balance at the end of the year',
    'EquityAtEndOfPeriod': 'Balance at the end of the year',
    'TransactionsWithOwnersHeader': 'Transactions with owners',  # Remove "Header" suffix
    'TransactionsWithOwners': 'Transactions with owners',
    'DividendsPaid': 'Dividends',
    'DividendsPaidClassifiedAsFinancingActivities': 'Dividends',
    'PaymentsOfDividends': 'Dividends',
    'IncreaseDecreaseThroughSharebasedPaymentTransactions': 'Share-based payments',
    'SharebasedPaymentTransactions': 'Share-based payments',
    'PaymentsToAcquireOrRedeemEntitysShares': 'Purchase of treasury shares',
    'PurchaseOfTreasuryShares': 'Purchase of treasury shares',
    'ReductionOfIssuedCapital': 'Reduction of the B share capital',
    'ReductionOfShareCapital': 'Reduction of the B share capital',
    'DecreaseIncreaseThroughTaxOnSharebasedPaymentTransactions': 'Tax related to transactions with owners',
    'TaxOnSharebasedPaymentTransactions': 'Tax related to transactions with owners',
    'AmountRemovedFromReserveOfCashFlowHedgesAndIncludedInInitialCostOrOtherCarryingAmountOfNonfinancialAssetLiabilityOrFirmCommitmentForWhichFairValueHedgeAccountingIsApplied': 'Transfer of cash flow hedge reserve to intangible assets',
    
    # Cash Flow Statement - Standard IFRS/US-GAAP terminology
    'ProfitLoss': 'Net profit',
    'AdjustmentsForIncomeTaxExpense': 'Income taxes in the income statement',
    'AdjustmentsForDepreciationAndAmortisationExpenseAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss': 'Depreciation, amortisation and impairment losses',
    'AdjustmentsForDepreciationAndAmortisationExpense': 'Depreciation, amortisation and impairment losses',
    'DepreciationAmortisationAndImpairment': 'Depreciation, amortisation and impairment losses',
    'OtherAdjustmentsForNoncashItems': 'Other non-cash items',
    'IncreaseDecreaseInWorkingCapital': 'Changes in working capital',
    'InterestReceivedClassifiedAsOperatingActivities': 'Interest received',
    'InterestPaidClassifiedAsOperatingActivities': 'Interest paid',
    'IncomeTaxesPaidRefundClassifiedAsOperatingActivities': 'Income taxes paid',
    'CashFlowsFromUsedInOperatingActivities': 'Net cash flows from operating activities',
    'OperatingCashFlow': 'Net cash flows from operating activities',
    'PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities': 'Purchase of intangible assets',
    'PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities': 'Purchase of property, plant and equipment',
    'CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinessesClassifiedAsInvestingActivities': 'Cash used for acquisition of businesses',
    'ProceedsFromSaleOfOtherFinancialAssetsClassifiedAsInvestingActivities': 'Proceeds from other financial assets',
    'PurchaseOfOtherFinancialAssetsClassifiedAsInvestingActivities': 'Purchase of other financial assets',
    'PurchaseOfFinancialAssetsMeasuredAtFairValueThroughProfitOrLossClassifiedAsInvestingActivities': 'Purchase of marketable securities',
    'ProceedsFromDisposalOfMarketableSecuritiesClassifiedAsInvestingActivities': 'Sale of marketable securities',
    'CashFlowsFromUsedInInvestingActivities': 'Net cash flows from investing activities',
    'InvestingCashFlow': 'Net cash flows from investing activities',
    'PaymentsToAcquireOrRedeemEntitysShares': 'Purchase of treasury shares',
    'DividendsPaidClassifiedAsFinancingActivities': 'Dividends paid',
    'ProceedsFromBorrowingsClassifiedAsFinancingActivities': 'Proceeds from borrowings',
    'RepaymentsOfBorrowingsClassifiedAsFinancingActivities': 'Repayment of borrowings',
    'CashFlowsFromUsedInFinancingActivities': 'Net cash flows from financing activities',
    'FinancingCashFlow': 'Net cash flows from financing activities',
    'IncreaseDecreaseInCashAndCashEquivalentsBeforeEffectOfExchangeRateChanges': 'Net cash generated from activities',
    'CashAndCashEquivalentsAtTheBeginningOfTheYear': 'Cash and cash equivalents at the beginning of the year',
    'EffectOfExchangeRateChangesOnCashAndCashEquivalents': 'Exchange gains/(losses) on cash and cash equivalents',
    'CashAndCashEquivalentsAtTheEndOfTheYear': 'Cash and cash equivalents at the end of the year',
}

# Pattern-based mapping for concepts that match patterns
CONCEPT_PATTERN_MAP = [
    # Comprehensive Income patterns
    (r'ReclassificationAdjustments.*CashFlowHedges', 'Realisation of previously deferred (gains)/losses'),
    (r'GainsLossesOnCashFlowHedgesBeforeTax$', 'Deferred gains/(losses) on hedges open at year-end'),
    (r'GainsLossesOnCashFlowHedgesRelatedToAcquisition', 'Deferred gains/(losses) related to acquisition of businesses'),
    
    # Cash Flow Statement patterns
    (r'AdjustmentsFor.*IncomeTax', 'Income taxes in the income statement'),
    (r'AdjustmentsFor.*Depreciation.*Amortisation', 'Depreciation, amortisation and impairment losses'),
    (r'OtherAdjustmentsForNoncash', 'Other non-cash items'),
    (r'IncreaseDecreaseInWorkingCapital', 'Changes in working capital'),
    (r'InterestReceived.*Operating', 'Interest received'),
    (r'InterestPaid.*Operating', 'Interest paid'),
    (r'IncomeTaxesPaid.*Operating', 'Income taxes paid'),
    (r'CashFlowsFrom.*Operating', 'Net cash flows from operating activities'),
    (r'PurchaseOfIntangibleAssets.*Investing', 'Purchase of intangible assets'),
    (r'PurchaseOfPropertyPlantAndEquipment.*Investing', 'Purchase of property, plant and equipment'),
    (r'CashFlowsUsedInObtainingControl', 'Cash used for acquisition of businesses'),
    (r'ProceedsFromSaleOfOtherFinancialAssets.*Investing', 'Proceeds from other financial assets'),
    (r'PurchaseOfOtherFinancialAssets.*Investing', 'Purchase of other financial assets'),
    (r'PurchaseOfFinancialAssetsMeasuredAtFairValue.*Investing', 'Purchase of marketable securities'),
    (r'ProceedsFromDisposalOfMarketableSecurities.*Investing', 'Sale of marketable securities'),
    (r'CashFlowsFrom.*Investing', 'Net cash flows from investing activities'),
    (r'PaymentsToAcquireOrRedeemEntitysShares', 'Purchase of treasury shares'),
    (r'DividendsPaid.*Financing', 'Dividends paid'),
    (r'ProceedsFromBorrowings.*Financing', 'Proceeds from borrowings'),
    (r'RepaymentsOfBorrowings.*Financing', 'Repayment of borrowings'),
    (r'CashFlowsFrom.*Financing', 'Net cash flows from financing activities'),
    (r'IncreaseDecreaseInCashAndCashEquivalentsBeforeEffect', 'Net cash generated from activities'),
    (r'CashAndCashEquivalentsAtTheBeginning', 'Cash and cash equivalents at the beginning of the year'),
    (r'EffectOfExchangeRateChangesOnCashAndCashEquivalents', 'Exchange gains/(losses) on cash and cash equivalents'),
    (r'CashAndCashEquivalentsAtTheEnd', 'Cash and cash equivalents at the end of the year'),
    
    # Equity Statement patterns
    (r'DividendsPaid.*', 'Dividends'),
    (r'PaymentsOfDividends.*', 'Dividends'),
    (r'SharebasedPayment.*', 'Share-based payments'),
    (r'IncreaseDecreaseThroughSharebasedPayment.*', 'Share-based payments'),
    (r'PurchaseOfTreasuryShares.*', 'Purchase of treasury shares'),
    (r'PaymentsToAcquireOrRedeemEntitysShares.*', 'Purchase of treasury shares'),
    (r'ReductionOf.*Capital', 'Reduction of the B share capital'),
    (r'ReductionOfIssuedCapital.*', 'Reduction of the B share capital'),
    (r'TaxOnSharebasedPayment.*', 'Tax related to transactions with owners'),
    (r'DecreaseIncreaseThroughTaxOnSharebasedPayment.*', 'Tax related to transactions with owners'),
    (r'BalanceAtBeginningOfYear.*', 'Balance at the beginning of the year'),
    (r'EquityAtBeginningOfPeriod.*', 'Balance at the beginning of the year'),
    (r'BalanceAtEndOfYear.*', 'Balance at the end of the year'),
    (r'EquityAtEndOfPeriod.*', 'Balance at the end of the year'),
    (r'AmountRemovedFromReserveOfCashFlowHedges.*', 'Transfer of cash flow hedge reserve to intangible assets'),
    
    (r'OtherComprehensiveIncomeNetOfTaxExchangeDifferences', 'Exchange rate adjustments of investments in subsidiaries'),
    (r'GainsLossesOnRemeasurementsOfDefinedBenefit', 'Remeasurements of retirement benefit obligations'),
    (r'.*RemeasurementsOfDefinedBenefit.*', 'Remeasurements of retirement benefit obligations'),
    (r'IncomeTax.*RelatingToComponentsOfOtherComprehensiveIncome', 'Tax and other items'),
    (r'OtherComprehensiveIncomeThatWillBeReclassified', 'Items that will be reclassified subsequently to the income statement'),
    (r'OtherComprehensiveIncomeThatWillNotBeReclassified', 'Items that will not be reclassified subsequently to the income statement'),
    (r'^ComprehensiveIncome$', 'Total comprehensive income'),
    (r'^OtherComprehensiveIncome$', 'Other comprehensive income'),
    (r'^OtherComprehensiveIncomeLossNetOfTax$', 'Other comprehensive income'),
    
    # Balance Sheet patterns
    (r'^Assets$', 'Assets'),
    (r'^TotalAssets$', 'Total assets'),
    (r'IntangibleAssetsOtherThanGoodwill', 'Intangible assets'),
    (r'PropertyPlantAndEquipment.*', 'Property, plant and equipment'),
    (r'InvestmentsInAssociates.*', 'Investments in associated companies'),
    (r'DeferredTaxAssets', 'Deferred income tax assets'),
    (r'OtherReceivablesAndPrepayments.*', 'Other receivables and prepayments'),
    (r'OtherNoncurrentFinancialAssets', 'Other financial assets'),
    (r'NoncurrentAssets', 'Total non-current assets'),
    (r'^Inventories$', 'Inventories'),
    (r'CurrentTradeReceivables|TradeReceivables', 'Trade receivables'),
    (r'CurrentTaxAssets.*', 'Tax receivables'),
    (r'CurrentFinancialAssetsAtFairValue.*', 'Marketable securities'),
    (r'CurrentDerivativeFinancialAssets', 'Derivative financial instruments'),
    (r'CashAnd.*', 'Cash at bank'),
    (r'BalancesWithBanks.*', 'Cash at bank'),
    (r'CurrentAssets', 'Total current assets'),
    (r'EquityAndLiabilities', 'Equity and liabilities'),
    (r'ShareCapital|IssuedCapital', 'Share capital'),
    (r'TreasuryShares', 'Treasury shares'),
    (r'RetainedEarnings', 'Retained earnings'),
    (r'OtherReserves', 'Other reserves'),
    (r'^Equity$|EquityTotal|StockholdersEquity', 'Total equity'),
    (r'Borrowings|LongtermBorrowings', 'Borrowings'),
    (r'DeferredTaxLiabilities', 'Deferred income tax liabilities'),
    (r'NoncurrentRecognisedLiabilitiesDefinedBenefitPlan', 'Retirement benefit obligations'),
    (r'OtherNoncurrentLiabilities', 'Other liabilities'),
    (r'NoncurrentProvisions|ProvisionsNoncurrent', 'Provisions'),
    (r'NoncurrentLiabilities', 'Total non-current liabilities'),
    (r'CurrentPortionOfLongtermBorrowings', 'Borrowings'),
    (r'TradeAndOtherCurrentPayables.*|AccountsPayable', 'Trade payables'),
    (r'CurrentTaxLiabilities', 'Tax payables'),
    (r'OtherCurrentLiabilities', 'Other liabilities'),
    (r'CurrentDerivativeFinancialLiabilities', 'Derivative financial instruments'),
    (r'CurrentProvisions', 'Provisions'),
    (r'CurrentLiabilities', 'Total current liabilities'),
    (r'^Liabilities$|TotalLiabilities', 'Total liabilities'),
]


def get_humanized_label(concept_name: str, normalized_label: str = None, statement_type: str = None) -> str:
    """
    Get humanized label for a concept.
    
    Priority:
    1. Exact match in CONCEPT_LABEL_MAP
    2. Pattern match in CONCEPT_PATTERN_MAP
    3. Smart CamelCase conversion with prefix removal
    4. Fallback to normalized_label conversion
    
    Args:
        concept_name: XBRL concept name (CamelCase)
        normalized_label: Normalized label (snake_case) as fallback
        statement_type: Statement type (for context-specific mapping)
    
    Returns:
        Human-readable label
    """
    import re
    
    if not concept_name:
        # Fallback to normalized_label
        if normalized_label:
            return normalized_label.replace('_', ' ').title()
        return 'Unknown'
    
    # 1. Check exact match, but handle ambiguous cases using normalized_label
    if concept_name in CONCEPT_LABEL_MAP:
        # Special case: 'Assets' concept_name can be used for both header and total
        # Use normalized_label to distinguish
        if concept_name == 'Assets' and normalized_label:
            if normalized_label == 'total_assets':
                return 'Total assets'
            elif normalized_label == 'assets_header':
                return 'Assets'
        
        # Special case: 'CashAndCashEquivalents' in cash flow statement
        # If it's in cash flow and appears at end of period, it's "Cash and cash equivalents at the end of the year"
        if concept_name in ['CashAndCashEquivalents', 'CashAndEquivalents'] and statement_type == 'cash_flow':
            if normalized_label and 'end' in normalized_label.lower():
                return 'Cash and cash equivalents at the end of the year'
            elif normalized_label and 'beginning' in normalized_label.lower():
                return 'Cash and cash equivalents at the beginning of the year'
            # Default for cash flow: assume end of year if no context
            return 'Cash and cash equivalents at the end of the year'
        
        return CONCEPT_LABEL_MAP[concept_name]
    
    # 2. Check pattern matches
    for pattern, label in CONCEPT_PATTERN_MAP:
        if re.match(pattern, concept_name):
            return label
    
    # 3. Smart CamelCase conversion with prefix removal
    # Convert CamelCase to readable format
    humanized = re.sub(r'([a-z])([A-Z])', r'\1 \2', concept_name)
    humanized = re.sub(r'([A-Z])([A-Z][a-z])', r'\1 \2', humanized)
    humanized = humanized.strip()
    
    # Remove redundant prefixes for comprehensive income
    redundant_prefixes = [
        'Other Comprehensive Income Net Of Tax ',
        'Other Comprehensive Income Net Of Tax',
    ]
    
    for prefix in redundant_prefixes:
        if humanized.startswith(prefix) and len(humanized) > len(prefix):
            humanized = humanized[len(prefix):].strip()
            break
    
    # Title Case
    words = humanized.split()
    humanized = ' '.join(word.capitalize() for word in words)
    
    return humanized

