"""
Taxonomy concept mappings between US-GAAP, IFRS, and normalized labels.

This module provides standardized labels for financial concepts across different
taxonomies, enabling cross-company comparisons.
"""

# Core mapping: normalized_label -> list of possible concept names
# Ordered by priority (most specific first)

CONCEPT_MAPPINGS = {
    # ============================================================================
    # INCOME STATEMENT
    # ============================================================================
    
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "Revenue",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "SalesRevenueServicesNet",
    ],
    
    "cost_of_revenue": [
        "CostOfGoodsAndServicesSold",
        "CostOfRevenue",
        "CostOfSales",
        "CostOfGoodsSold",
    ],
    
    "gross_profit": [
        "GrossProfit",
        "GrossProfitLoss",
    ],
    
    "operating_expenses": [
        "OperatingExpenses",
        "OperatingCostsAndExpenses",
    ],
    
    "research_development": [
        "ResearchAndDevelopmentExpense",
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    ],
    
    "selling_general_admin": [
        "SellingGeneralAndAdministrativeExpense",
        "SellingAndMarketingExpense",
        "GeneralAndAdministrativeExpense",
    ],
    
    "operating_income": [
        "OperatingIncomeLoss",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ],
    
    "interest_expense": [
        "InterestExpense",
        "InterestExpenseDebt",
        "FinanceCosts",
        "FinanceExpense",
    ],
    
    "interest_income": [
        "InterestIncomeExpenseNonoperatingNet",
        "InterestIncomeExpenseNet",
        "InvestmentIncomeInterest",
        "FinanceIncome",
    ],
    
    "income_before_tax": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "ProfitLossBeforeTax",
    ],
    
    "income_tax_expense": [
        "IncomeTaxExpenseBenefit",
        "IncomeTaxesPaid",
        "CurrentIncomeTaxExpenseBenefit",
    ],
    
    "net_income": [
        "NetIncomeLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "ProfitLossAttributableToOwnersOfParent",
        "ProfitLoss",
        "NetIncome",
    ],
    
    "net_income_to_common": [
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "NetIncomeLossAvailableToCommonStockholdersDiluted",
    ],
    
    "eps_basic": [
        "EarningsPerShareBasic",
        "IncomeLossFromContinuingOperationsPerBasicShare",
    ],
    
    "eps_diluted": [
        "EarningsPerShareDiluted",
        "IncomeLossFromContinuingOperationsPerDilutedShare",
    ],
    
    "shares_basic": [
        "WeightedAverageNumberOfSharesOutstandingBasic",
        "WeightedAverageNumberOfSharesIssuedBasic",
    ],
    
    "shares_diluted": [
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesIssuedDiluted",
    ],
    
    # ============================================================================
    # BALANCE SHEET - ASSETS
    # ============================================================================
    
    "cash_and_equivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "Cash",
        "CashAndBankBalancesAtCentralBanks",
    ],
    
    "short_term_investments": [
        "ShortTermInvestments",
        "AvailableForSaleSecuritiesCurrent",
        "MarketableSecuritiesCurrent",
    ],
    
    "accounts_receivable": [
        "AccountsReceivableNetCurrent",
        "AccountsReceivableNet",
        "TradeAndOtherCurrentReceivables",
    ],
    
    "inventory": [
        "InventoryNet",
        "Inventories",
    ],
    
    "current_assets": [
        "AssetsCurrent",
        "CurrentAssets",
    ],
    
    "property_plant_equipment": [
        "PropertyPlantAndEquipmentNet",
        "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
    ],
    
    "goodwill": [
        "Goodwill",
    ],
    
    "intangible_assets": [
        "IntangibleAssetsNetExcludingGoodwill",
        "FiniteLivedIntangibleAssetsNet",
    ],
    
    "long_term_investments": [
        "LongTermInvestments",
        "AvailableForSaleSecuritiesNoncurrent",
        "MarketableSecuritiesNoncurrent",
    ],
    
    "noncurrent_assets": [
        "AssetsNoncurrent",
        "NoncurrentAssets",
    ],
    
    "total_assets": [
        "Assets",
        "AssetsCurrent",  # Fallback if only current reported
    ],
    
    # ============================================================================
    # BALANCE SHEET - LIABILITIES
    # ============================================================================
    
    "accounts_payable": [
        "AccountsPayableCurrent",
        "AccountsPayableAndAccruedLiabilitiesCurrent",
        "TradeAndOtherCurrentPayables",
    ],
    
    "short_term_debt": [
        "DebtCurrent",
        "ShortTermBorrowings",
        "CommercialPaper",
    ],
    
    "current_liabilities": [
        "LiabilitiesCurrent",
        "CurrentLiabilities",
    ],
    
    "long_term_debt": [
        "LongTermDebt",
        "LongTermDebtNoncurrent",
        "LongTermBorrowings",
    ],
    
    "noncurrent_liabilities": [
        "LiabilitiesNoncurrent",
        "NoncurrentLiabilities",
    ],
    
    "total_liabilities": [
        "Liabilities",
        "LiabilitiesAndStockholdersEquity",  # Will need special handling
    ],
    
    # ============================================================================
    # BALANCE SHEET - EQUITY
    # ============================================================================
    
    "common_stock": [
        "CommonStockValue",
        "CommonStockSharesOutstanding",
        "ShareCapital",
    ],
    
    "retained_earnings": [
        "RetainedEarningsAccumulatedDeficit",
        "RetainedEarnings",
    ],
    
    "accumulated_other_comprehensive_income": [
        "AccumulatedOtherComprehensiveIncomeLossNetOfTax",
        "AccumulatedOtherComprehensiveIncomeLoss",
    ],
    
    "stockholders_equity": [
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "StockholdersEquity",
        "Equity",
        "EquityAttributableToOwnersOfParent",
    ],
    
    "noncontrolling_interest": [
        "MinorityInterest",
        "NoncontrollingInterestInSubsidiaries",
    ],
    
    "total_equity": [
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "StockholdersEquity",
        "Equity",
    ],
    
    # ============================================================================
    # CASH FLOW STATEMENT
    # ============================================================================
    
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        "CashFlowsFromUsedInOperatingActivities",
    ],
    
    "investing_cash_flow": [
        "NetCashProvidedByUsedInInvestingActivities",
        "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
        "CashFlowsFromUsedInInvestingActivities",
    ],
    
    "financing_cash_flow": [
        "NetCashProvidedByUsedInFinancingActivities",
        "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations",
        "CashFlowsFromUsedInFinancingActivities",
    ],
    
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForCapitalImprovements",
        "PurchaseOfPropertyPlantAndEquipment",
    ],
    
    "dividends_paid": [
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
        "DividendsPaid",
    ],
    
    "stock_repurchased": [
        "PaymentsForRepurchaseOfCommonStock",
        "TreasuryStockValueAcquiredCostMethod",
        "PaymentsForRepurchaseOfEquity",
    ],
    
    "free_cash_flow": [
        "FreeCashFlow",  # Sometimes directly reported
    ],
    
    # ============================================================================
    # OTHER FINANCIAL METRICS
    # ============================================================================
    
    "depreciation_amortization": [
        "DepreciationDepletionAndAmortization",
        "Depreciation",
        "DepreciationAndAmortization",
    ],
    
    "stock_based_compensation": [
        "ShareBasedCompensation",
        "AllocatedShareBasedCompensationExpense",
    ],
    
    "deferred_revenue": [
        "DeferredRevenue",
        "ContractWithCustomerLiability",
        "DeferredIncome",
    ],
    
    # ============================================================================
    # INVESTMENTS & SECURITIES
    # ============================================================================
    
    "available_for_sale_securities": [
        "AvailableForSaleSecuritiesDebtSecurities",
        "AvailableForSaleSecurities",
    ],
    
    "available_for_sale_securities_current": [
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
    ],
    
    "available_for_sale_securities_noncurrent": [
        "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent",
    ],
    
    "afs_unrealized_gain": [
        "AvailableForSaleDebtSecuritiesAccumulatedGrossUnrealizedGainBeforeTax",
    ],
    
    "afs_unrealized_loss": [
        "AvailableForSaleDebtSecuritiesAccumulatedGrossUnrealizedLossBeforeTax",
    ],
    
    "afs_amortized_cost": [
        "AvailableForSaleDebtSecuritiesAmortizedCostBasis",
    ],
    
    "equity_securities_fvni": [
        "EquitySecuritiesFVNINoncurrent",
        "EquitySecuritiesFvNiCurrentAndNoncurrent",
        "EquitySecuritiesFvNi",
    ],
    
    "equity_securities_fvni_gain_loss": [
        "EquitySecuritiesFvNiGainLoss",
    ],
    
    "equity_securities_no_fair_value": [
        "EquitySecuritiesWithoutReadilyDeterminableFairValueAmount",
    ],
    
    "equity_method_investments": [
        "EquityMethodInvestments",
    ],
    
    "equity_method_investment_income": [
        "ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod",
    ],
    
    # ============================================================================
    # DEBT & BORROWINGS (DETAILED)
    # ============================================================================
    
    "debt_carrying_amount": [
        "DebtInstrumentCarryingAmount",
    ],
    
    "debt_face_amount": [
        "DebtInstrumentFaceAmount",
    ],
    
    "debt_fair_value": [
        "LongTermDebtFairValue",
    ],
    
    "debt_interest_rate_stated": [
        "DebtInstrumentInterestRateStatedPercentage",
    ],
    
    "debt_interest_rate_effective": [
        "DebtInstrumentInterestRateEffectivePercentage",
    ],
    
    "debt_weighted_avg_interest_rate": [
        "DebtWeightedAverageInterestRate",
    ],
    
    "borrowings": [
        "Borrowings",
        "OtherBankBorrowings",
        "OtherBorrowings",
    ],
    
    "borrowings_interest_rate": [
        "BorrowingsInterestRate",
    ],
    
    "bonds_issued": [
        "BondsIssued",
    ],
    
    "long_term_borrowings": [
        "LongtermBorrowings",
        "LongTermBorrowings",
    ],
    
    "short_term_borrowings": [
        "ShortTermBorrowings",
    ],
    
    "bank_overdrafts": [
        "BankOverdraftsClassifiedAsCashEquivalents",
    ],
    
    "debt_net_of_cash": [
        "DebtNetOfCashAndCashEquivalents",
    ],
    
    # ============================================================================
    # DERIVATIVES & HEDGING
    # ============================================================================
    
    "derivative_assets": [
        "DerivativeAssets",
    ],
    
    "derivative_assets_current": [
        "DerivativeAssetsCurrent",
    ],
    
    "derivative_assets_noncurrent": [
        "DerivativeAssetsNoncurrent",
    ],
    
    "derivative_liabilities": [
        "DerivativeLiabilities",
    ],
    
    "derivative_liabilities_current": [
        "DerivativeLiabilitiesCurrent",
    ],
    
    "derivative_liabilities_noncurrent": [
        "DerivativeLiabilitiesNoncurrent",
    ],
    
    "derivative_fair_value_asset": [
        "DerivativeFairValueOfDerivativeAsset",
    ],
    
    "derivative_fair_value_liability": [
        "DerivativeFairValueOfDerivativeLiability",
    ],
    
    "derivative_notional_amount": [
        "DerivativeNotionalAmount",
        "NotionalAmount",
    ],
    
    "derivative_gain_loss": [
        "DerivativeGainLossOnDerivativeNet",
        "DerivativeInstrumentsNotDesignatedAsHedgingInstrumentsGainLossNet",
    ],
    
    "derivative_financial_instruments": [
        "DerivativeFinancialInstruments",
        "DerivativeFinancialInstrumentsToManageFinancialExposure",
    ],
    
    # ============================================================================
    # PENSION & POSTRETIREMENT BENEFITS
    # ============================================================================
    
    "pension_plan_assets": [
        "DefinedBenefitPlanFairValueOfPlanAssets",
    ],
    
    "pension_benefit_obligation": [
        "DefinedBenefitPlanBenefitObligation",
        "DefinedBenefitObligationAtPresentValue",
    ],
    
    "pension_funded_status": [
        "DefinedBenefitPlanFundedStatusOfPlan",
        "LiabilityAssetOfDefinedBenefitPlans",
    ],
    
    "pension_service_cost": [
        "DefinedBenefitPlanServiceCost",
        "CurrentServiceCostNetDefinedBenefitLiabilityAsset",
    ],
    
    "pension_interest_cost": [
        "DefinedBenefitPlanInterestCost",
    ],
    
    "pension_expected_return": [
        "DefinedBenefitPlanExpectedReturnOnPlanAssets",
    ],
    
    "pension_amortization_gains_losses": [
        "DefinedBenefitPlanAmortizationOfGainsLosses",
    ],
    
    "pension_amortization_prior_service": [
        "DefinedBenefitPlanAmortizationOfPriorServiceCostCredit",
    ],
    
    "pension_net_periodic_cost": [
        "DefinedBenefitPlanNetPeriodicBenefitCost",
    ],
    
    "pension_discount_rate": [
        "DefinedBenefitPlanAssumptionsUsedCalculatingBenefitObligationDiscountRate",
        "DefinedBenefitPlanAssumptionsUsedCalculatingNetPeriodicBenefitCostDiscountRate",
    ],
    
    "pension_expected_return_rate": [
        "DefinedBenefitPlanAssumptionsUsedCalculatingNetPeriodicBenefitCostExpectedLongTermReturnOnAssets",
    ],
    
    "pension_liability_noncurrent": [
        "PensionAndOtherPostretirementDefinedBenefitPlansLiabilitiesNoncurrent",
    ],
    
    # ============================================================================
    # PROPERTY, PLANT & EQUIPMENT (DETAILED)
    # ============================================================================
    
    "ppe_gross": [
        "PropertyPlantAndEquipmentGross",
    ],
    
    "ppe_net_alternative": [
        "PropertyPlantAndEquipment",
        "PropertyPlantAndEquipmentIncludingRightofuseAssets",
    ],
    
    "ppe_useful_life": [
        "PropertyPlantAndEquipmentUsefulLife",
    ],
    
    "ppe_additions": [
        "AdditionsOtherThanThroughBusinessCombinationsPropertyPlantAndEquipment",
    ],
    
    "ppe_disposals": [
        "DisposalsAndRetirementsPropertyPlantAndEquipment",
    ],
    
    "ppe_impairment": [
        "ImpairmentLossRecognisedInProfitOrLossPropertyPlantAndEquipmentIncludingRightofuseAssets",
    ],
    
    "ppe_fx_changes": [
        "IncreaseDecreaseThroughNetExchangeDifferencesPropertyPlantAndEquipment",
    ],
    
    "ppe_depreciation": [
        "DepreciationPropertyPlantAndEquipmentIncludingRightofuseAssets",
    ],
    
    # ============================================================================
    # INTANGIBLE ASSETS (DETAILED)
    # ============================================================================
    
    "intangible_assets_alternative": [
        "IntangibleAssetsOtherThanGoodwill",
        "OtherIntangibleAssets",
    ],
    
    "intangible_assets_gross": [
        "FiniteLivedIntangibleAssetsGross",
    ],
    
    "intangible_assets_accumulated_amortization": [
        "FiniteLivedIntangibleAssetsAccumulatedAmortization",
    ],
    
    "intangible_assets_indefinite_lived": [
        "IndefiniteLivedIntangibleAssetsExcludingGoodwill",
    ],
    
    "intangible_assets_useful_life": [
        "UsefulLifeMeasuredAsPeriodOfTimeIntangibleAssetsOtherThanGoodwill",
    ],
    
    "intangible_assets_amortization": [
        "AmortisationIntangibleAssetsOtherThanGoodwill",
    ],
    
    "intangible_assets_additions": [
        "AdditionsOtherThanThroughBusinessCombinationsIntangibleAssetsOtherThanGoodwill",
    ],
    
    "intangible_assets_disposals": [
        "DisposalsAndRetirementsIntangibleAssetsOtherThanGoodwill",
    ],
    
    "intangible_assets_impairment": [
        "ImpairmentOfIntangibleAssetsExcludingGoodwill",
        "ImpairmentLossOnIntangibleAssetsOtherThanGoodwill",
        "ImpairmentLossRecognisedInProfitOrLossIntangibleAssetsOtherThanGoodwill",
    ],
    
    "intangible_assets_fx_changes": [
        "IncreaseDecreaseThroughNetExchangeDifferencesIntangibleAssetsOtherThanGoodwill",
    ],
    
    # ============================================================================
    # GOODWILL (DETAILED)
    # ============================================================================
    
    "goodwill_acquired": [
        "GoodwillAcquiredDuringPeriod",
    ],
    
    "goodwill_other_changes": [
        "GoodwillOtherIncreaseDecrease",
    ],
    
    # ============================================================================
    # TAX (DETAILED)
    # ============================================================================
    
    "current_tax_expense": [
        "CurrentIncomeTaxExpenseBenefit",
    ],
    
    "deferred_tax_expense": [
        "DeferredIncomeTaxExpenseBenefit",
    ],
    
    "current_federal_tax": [
        "CurrentFederalTaxExpenseBenefit",
    ],
    
    "current_foreign_tax": [
        "CurrentForeignTaxExpenseBenefit",
    ],
    
    "current_state_local_tax": [
        "CurrentStateAndLocalTaxExpenseBenefit",
    ],
    
    "deferred_federal_tax": [
        "DeferredFederalIncomeTaxExpenseBenefit",
    ],
    
    "deferred_foreign_tax": [
        "DeferredForeignIncomeTaxExpenseBenefit",
    ],
    
    "unrecognized_tax_benefits": [
        "UnrecognizedTaxBenefits",
    ],
    
    "unrecognized_tax_benefits_increase_current": [
        "UnrecognizedTaxBenefitsIncreasesResultingFromCurrentPeriodTaxPositions",
    ],
    
    "unrecognized_tax_benefits_increase_prior": [
        "UnrecognizedTaxBenefitsIncreasesResultingFromPriorPeriodTaxPositions",
    ],
    
    "unrecognized_tax_benefits_decrease_prior": [
        "UnrecognizedTaxBenefitsDecreasesResultingFromPriorPeriodTaxPositions",
    ],
    
    "unrecognized_tax_benefits_decrease_settlements": [
        "UnrecognizedTaxBenefitsDecreasesResultingFromSettlementsWithTaxingAuthorities",
    ],
    
    "deferred_tax_assets": [
        "DeferredTaxAssets",
    ],
    
    "deferred_tax_liabilities": [
        "DeferredTaxLiabilities",
    ],
    
    "deferred_tax_asset_liability_net": [
        "DeferredTaxLiabilityAsset",
    ],
    
    "deferred_tax_valuation_allowance": [
        "DeferredTaxAssetsValuationAllowance",
        "ValuationAllowancesAndReservesBalance",
    ],
    
    "effective_tax_rate": [
        "EffectiveIncomeTaxRateContinuingOperations",
    ],
    
    "statutory_tax_rate": [
        "EffectiveIncomeTaxRateReconciliationAtFederalStatutoryIncomeTaxRate",
    ],
    
    "tax_rate_reconciliation_state_local": [
        "EffectiveIncomeTaxRateReconciliationStateAndLocalIncomeTaxes",
    ],
    
    "foreign_pretax_income": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesForeign",
    ],
    
    # ============================================================================
    # STOCK-BASED COMPENSATION (DETAILED)
    # ============================================================================
    
    "stock_options_granted": [
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsGrantsInPeriod",
        "NumberOfShareOptionsGrantedInSharebasedPaymentArrangement",
    ],
    
    "stock_options_grant_date_fair_value": [
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsGrantsInPeriodWeightedAverageGrantDateFairValue",
    ],
    
    "stock_options_vested_fair_value": [
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsVestedInPeriodTotalFairValue",
    ],
    
    "stock_options_nonvested": [
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsNonvestedNumber",
    ],
    
    "stock_options_vesting_period": [
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardAwardVestingPeriod1",
    ],
    
    "stock_options_unrecognized_compensation": [
        "EmployeeServiceShareBasedCompensationNonvestedAwardsTotalCompensationCostNotYetRecognizedPeriodForRecognition1",
    ],
    
    "stock_options_dividend_rate_assumption": [
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardFairValueAssumptionsExpectedDividendRate",
    ],
    
    "stock_issued_value_sbc": [
        "StockIssuedDuringPeriodValueShareBasedCompensation",
        "AdjustmentsToAdditionalPaidInCapitalSharebasedCompensationRequisiteServicePeriodRecognitionValue",
    ],
    
    # ============================================================================
    # OTHER INCOME & EXPENSES
    # ============================================================================
    
    "nonoperating_income_expense": [
        "NonoperatingIncomeExpense",
        "OtherNonoperatingIncomeExpense",
    ],
    
    "restructuring_charges": [
        "RestructuringCharges",
    ],
    
    "restructuring_reserve": [
        "RestructuringReserve",
    ],
    
    # ============================================================================
    # OTHER COMPREHENSIVE INCOME (DETAILED)
    # ============================================================================
    
    "oci_before_reclassifications": [
        "OciBeforeReclassificationsNetOfTaxAttributableToParent",
    ],
    
    "oci_reclassifications": [
        "ReclassificationFromAociCurrentPeriodNetOfTaxAttributableToParent",
    ],
    
    "oci_total": [
        "OtherComprehensiveIncomeLossNetOfTaxPortionAttributableToParent",
        "OtherComprehensiveIncomeLossNetOfTax",
        "OtherComprehensiveIncome",
    ],
    
    "oci_tax": [
        "OtherComprehensiveIncomeLossTax",
    ],
    
    "oci_cash_flow_hedge_pretax": [
        "OtherComprehensiveIncomeLossCashFlowHedgeGainLossBeforeReclassificationAndTax",
    ],
    
    "oci_cash_flow_hedge_after_tax": [
        "OtherComprehensiveIncomeLossCashFlowHedgeGainLossBeforeReclassificationAfterTax",
    ],
    
    "oci_cash_flow_hedge_reclassification_pretax": [
        "OtherComprehensiveIncomeLossCashFlowHedgeGainLossReclassificationBeforeTax",
    ],
    
    "oci_cash_flow_hedge_reclassification_after_tax": [
        "OtherComprehensiveIncomeLossCashFlowHedgeGainLossReclassificationAfterTax",
    ],
    
    "oci_net_investment_hedge": [
        "OtherComprehensiveIncomeLossNetInvestmentHedgeGainLossBeforeReclassificationAndTax",
    ],
    
    "oci_pension_adjustments": [
        "OtherComprehensiveIncomeLossPensionAndOtherPostretirementBenefitPlansAdjustmentBeforeTax",
        "GainLossOnRemeasurementOfNetDefinedBenefitLiabilityAsset",
    ],
    
    "comprehensive_income": [
        "ComprehensiveIncome",
        "ComprehensiveIncomeNetOfTax",
    ],
    
    # ============================================================================
    # CASH & CASH FLOW (DETAILED)
    # ============================================================================
    
    "cash_restricted": [
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    
    "cash_change_in_period": [
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
    ],
    
    "cash_and_marketable_securities": [
        "CashCashEquivalentsAndMarketableSecurities",
    ],
    
    "cash_fair_value_disclosure": [
        "CashAndCashEquivalentsFairValueDisclosure",
    ],
    
    "cash_alternative_ifrs": [
        "CashAndCashEquivalents",
    ],
    
    # ============================================================================
    # WORKING CAPITAL CHANGES
    # ============================================================================
    
    "change_in_receivables": [
        "IncreaseDecreaseInAccountsReceivable",
    ],
    
    "change_in_inventory": [
        "IncreaseDecreaseInInventories",
    ],
    
    # ============================================================================
    # BUSINESS COMBINATIONS
    # ============================================================================
    
    "business_combination_purchase_price": [
        "PaymentsToAcquireBusinessesNetOfCashAcquired",
    ],
    
    "business_combination_contingent_consideration": [
        "BusinessCombinationContingentConsiderationLiability",
    ],
    
    # ============================================================================
    # LEASES
    # ============================================================================
    
    "operating_lease_cost": [
        "OperatingLeaseCost",
    ],
    
    "operating_lease_payments": [
        "OperatingLeasePayments",
    ],
    
    "operating_lease_right_of_use_asset": [
        "OperatingLeaseRightOfUseAsset",
        "RightofuseAssets",
    ],
    
    "operating_lease_liability": [
        "OperatingLeaseLiability",
        "LeaseLiabilities",
    ],
    
    # ============================================================================
    # EQUITY & SHARES (DETAILED)
    # ============================================================================
    
    "common_stock_shares_authorized": [
        "CommonStockSharesAuthorized",
    ],
    
    "common_stock_shares_issued": [
        "CommonStockSharesIssued",
    ],
    
    "stock_repurchased_value": [
        "StockRepurchasedAndRetiredDuringPeriodValue",
    ],
    
    "dividends_per_share": [
        "CommonStockDividendsPerShareDeclared",
    ],
    
    "dividends_paid_cash": [
        "DividendsCommonStockCash",
    ],
    
    "stockholders_equity_other": [
        "StockholdersEquityOther",
    ],
    
    "profit_attributable_to_nci": [
        "ProfitLossAttributableToNoncontrollingInterests",
    ],
    
    # ============================================================================
    # OTHER ASSETS & LIABILITIES
    # ============================================================================
    
    "other_assets_noncurrent": [
        "OtherAssetsNoncurrent",
    ],
    
    "other_liabilities_noncurrent": [
        "OtherLiabilitiesNoncurrent",
    ],
    
    "provisions_noncurrent": [
        "NoncurrentProvisions",
    ],
    
    "provisions_used": [
        "ProvisionUsedOtherProvisions",
    ],
    
    "provisions_fx_changes": [
        "IncreaseDecreaseThroughNetExchangeDifferencesOtherProvisions",
    ],
    
    "financial_assets": [
        "FinancialAssets",
    ],
    
    "financial_liabilities": [
        "FinancialLiabilities",
    ],
    
    # ============================================================================
    # CONCENTRATIONS & RISKS
    # ============================================================================
    
    "concentration_risk_percentage": [
        "ConcentrationRiskPercentage1",
    ],
    
    # ============================================================================
    # SEGMENT DATA
    # ============================================================================
    
    "intersegment_revenue": [
        "IntersegmentRevenue",
    ],
    
    "segment_revenue": [
        "RevenueForReportableSegments",
    ],
    
    "segment_capex": [
        "SegmentExpenditureAdditionToLongLivedAssets",
    ],
    
    "revenue_growth_percent": [
        "RevenueGrowthPercent",
        "PercentageChangeInSalesBySegmentOfBusiness",
    ],
    
    # ============================================================================
    # ANTIDILUTIVE SECURITIES
    # ============================================================================
    
    "antidilutive_securities_excluded": [
        "AntidilutiveSecuritiesExcludedFromComputationOfEarningsPerShareAmount",
    ],
    
    # ============================================================================
    # REVENUE COMPONENTS (ADDITIONAL)
    # ============================================================================
    
    "revenue_from_sale_of_goods": [
        "RevenueFromSaleOfGoods",
    ],
    
    # ============================================================================
    # EMPLOYEE BENEFITS
    # ============================================================================
    
    "employee_benefits_expense": [
        "EmployeeBenefitsExpense",
    ],
}


# Reverse mapping: concept -> normalized_label
def get_normalized_label(concept: str) -> str | None:
    """
    Get the normalized label for a given concept name.
    
    Args:
        concept: XBRL concept name (e.g., 'RevenueFromContractWithCustomerExcludingAssessedTax')
    
    Returns:
        Normalized label (e.g., 'revenue') or None if not found
    """
    for normalized, concepts in CONCEPT_MAPPINGS.items():
        if concept in concepts:
            return normalized
    return None


def get_concepts_for_label(normalized_label: str) -> list[str]:
    """
    Get all possible concept names for a normalized label.
    
    Args:
        normalized_label: Normalized label (e.g., 'revenue')
    
    Returns:
        List of concept names, ordered by priority
    """
    return CONCEPT_MAPPINGS.get(normalized_label, [])


# Statement type classification
STATEMENT_TYPES = {
    "income_statement": [
        "revenue", "cost_of_revenue", "gross_profit", "operating_expenses",
        "research_development", "selling_general_admin", "operating_income",
        "interest_expense", "interest_income", "income_before_tax",
        "income_tax_expense", "net_income", "net_income_to_common",
        "eps_basic", "eps_diluted", "shares_basic", "shares_diluted"
    ],
    "balance_sheet": [
        "cash_and_equivalents", "short_term_investments", "accounts_receivable",
        "inventory", "current_assets", "property_plant_equipment", "goodwill",
        "intangible_assets", "long_term_investments", "noncurrent_assets",
        "total_assets", "accounts_payable", "short_term_debt", "current_liabilities",
        "long_term_debt", "noncurrent_liabilities", "total_liabilities",
        "common_stock", "retained_earnings", "accumulated_other_comprehensive_income",
        "stockholders_equity", "noncontrolling_interest", "total_equity"
    ],
    "cash_flow": [
        "operating_cash_flow", "investing_cash_flow", "financing_cash_flow",
        "capex", "dividends_paid", "stock_repurchased", "free_cash_flow"
    ],
    "other": [
        "depreciation_amortization", "stock_based_compensation", "deferred_revenue"
    ]
}


def get_statement_type(normalized_label: str) -> str | None:
    """
    Get the statement type for a normalized label.
    
    Args:
        normalized_label: Normalized label (e.g., 'revenue')
    
    Returns:
        Statement type ('income_statement', 'balance_sheet', 'cash_flow', 'other') or None
    """
    for stmt_type, labels in STATEMENT_TYPES.items():
        if normalized_label in labels:
            return stmt_type
    return None


# Taxonomy identification
def identify_taxonomy(concept: str) -> str:
    """
    Identify the taxonomy from the concept name.
    
    Args:
        concept: XBRL concept name
    
    Returns:
        Taxonomy identifier ('us-gaap', 'ifrs', 'dei', 'custom', 'unknown')
    """
    concept_lower = concept.lower()
    
    # Common US-GAAP patterns
    if any(pattern in concept_lower for pattern in [
        'stockholders', 'commonstock', 'treasury', 'epsdiluted', 'epsbasic'
    ]):
        return 'us-gaap'
    
    # Common IFRS patterns
    if any(pattern in concept_lower for pattern in [
        'profitloss', 'equity', 'shareholders', 'financecosts', 'noncurrent'
    ]):
        return 'ifrs'
    
    # DEI (Document Entity Information)
    if any(pattern in concept_lower for pattern in [
        'entityregistrant', 'documenttype', 'documentperiod', 'tradingsymbol'
    ]):
        return 'dei'
    
    # Default
    return 'unknown'

