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
        "Revenues",  # Total revenue (US-GAAP)
        "Revenue",   # Total revenue (IFRS)
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "SalesRevenueServicesNet",
    ],
    
    "revenue_from_contracts": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",  # Contract revenue only (component)
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    ],
    
    "cost_of_revenue": [
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfSales",  # IFRS
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
    ],
    
    "research_development_excluding_acquired_in_process": [
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    ],
    
    "selling_general_admin": [
        "SellingGeneralAndAdministrativeExpense",
    ],
    
    "selling_and_marketing_expense": [
        "SellingAndMarketingExpense",
    ],
    
    "general_and_administrative_expense": [
        "GeneralAndAdministrativeExpense",
    ],
    
    "operating_income": [
        "OperatingIncomeLoss",
    ],
    
    "interest_expense": [
        "InterestExpense",
        "InterestExpenseDebt",
    ],
    
    "finance_costs": [
        "FinanceCosts",
        "FinanceExpense",
    ],
    
    "interest_income": [
        "InterestIncome",
    ],
    
    "finance_income": [
        "FinanceIncome",  # IFRS - can include other financial income beyond interest
    ],
    
    "interest_income_investment": [
        "InvestmentIncomeInterest",  # Specific source
    ],
    
    "interest_income_expense_net": [
        "InterestIncomeExpenseNet",
        "InterestIncomeExpenseNonoperatingNet",
    ],
    
    "income_before_tax": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "ProfitLossBeforeTax",
    ],
    
    "income_tax_expense": [
        "IncomeTaxExpenseBenefit",
    ],
    
    "income_tax_paid": [
        "IncomeTaxesPaid",
    ],
    
    "current_income_tax_expense": [
        "CurrentIncomeTaxExpenseBenefit",
    ],
    
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",  # IFRS equivalent
        "ProfitLossAttributableToOwnersOfParent",  # IFRS variant
        "NetIncome",
    ],
    
    "net_income_to_common": [
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "NetIncomeLossAvailableToCommonStockholdersDiluted",
    ],
    
    "eps_basic": [
        "EarningsPerShareBasic",
    ],
    
    "eps_basic_continuing_ops": [
        "IncomeLossFromContinuingOperationsPerBasicShare",
    ],
    
    "eps_diluted": [
        "EarningsPerShareDiluted",
    ],
    
    "eps_diluted_continuing_ops": [
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
        "CashAndBankBalancesAtCentralBanks",
    ],
    
    "cash": [
        "Cash",
    ],
    
    "short_term_investments": [
        "ShortTermInvestments",
        "MarketableSecuritiesCurrent",
        "AvailableForSaleSecuritiesCurrent",
    ],
    
    "accounts_receivable": [
        "AccountsReceivableNet",
        "AccountsReceivableNetCurrent",
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
    ],
    
    "finite_lived_intangible_assets": [
        "FiniteLivedIntangibleAssetsNet",
    ],
    
    "long_term_investments": [
        "LongTermInvestments",
        "MarketableSecuritiesNoncurrent",
        "AvailableForSaleSecuritiesNoncurrent",
    ],
    
    "noncurrent_assets": [
        "AssetsNoncurrent",  # US-GAAP: Always the total
    ],
    
    "noncurrent_assets_ifrs": [
        "NoncurrentAssets",  # IFRS: Total noncurrent (context-dependent in US-GAAP)
    ],
    
    "total_assets": [
        "Assets",
        "LiabilitiesAndStockholdersEquity",  # Balance sheet total (Assets = L + E)
    ],
    
    # ============================================================================
    # BALANCE SHEET - LIABILITIES
    # ============================================================================
    
    "accounts_payable": [
        "AccountsPayableCurrent",
        "TradeAndOtherCurrentPayables",
    ],
    
    "accrued_liabilities_current": [
        "AccruedLiabilitiesCurrent",
        "OtherAccruedLiabilitiesCurrent",  # AAPL variant
        "AccountsPayableAndAccruedLiabilitiesCurrent",  # KO combined line item
        "AccruedExpensesCurrent",
        "OtherLiabilitiesCurrent",  # LLY uses this
        "EmployeeRelatedLiabilitiesCurrent",  # LLY employee accruals
    ],
    
    "short_term_debt": [
        "DebtCurrent",
    ],
    
    "short_term_borrowings": [
        "ShortTermBorrowings",
    ],
    
    "commercial_paper": [
        "CommercialPaper",
    ],
    
    "current_liabilities": [
        "LiabilitiesCurrent",
        "CurrentLiabilities",
    ],
    
    "long_term_debt": [
        "LongTermDebt",
        "LongTermBorrowings",
    ],
    
    "long_term_debt_noncurrent": [
        "LongTermDebtNoncurrent",
    ],
    
    "noncurrent_liabilities": [
        "LiabilitiesNoncurrent",
        "NoncurrentLiabilities",
    ],
    
    "total_liabilities": [
        "Liabilities",
        "LiabilitiesTotal",
    ],
    
    # ============================================================================
    # BALANCE SHEET - EQUITY
    # ============================================================================
    
    "common_stock_value": [
        "CommonStockValue",
        "ShareCapital",  # IFRS
    ],
    
    "common_stock_shares_outstanding": [
        "CommonStockSharesOutstanding",
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
        "StockholdersEquity",
        "EquityAttributableToOwnersOfParent",  # IFRS equivalent
        "Equity",  # IFRS simple equity
    ],
    
    "stockholders_equity_including_noncontrolling_interest": [
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
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
        "DividendsPaid",
        "PaymentsOfDividendsCommonStock",  # Common stock is the main dividend for most companies
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
    
    "depreciation": [
        "Depreciation",
    ],
    
    "depreciation_and_amortization": [
        "DepreciationAndAmortization",
    ],
    
    "depreciation_depletion_and_amortization": [
        "DepreciationDepletionAndAmortization",
    ],
    
    "stock_based_compensation": [
        "ShareBasedCompensation",
    ],
    
    "allocated_stock_based_compensation": [
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
        "EquitySecuritiesFvNi",
        "EquitySecuritiesFvNiCurrentAndNoncurrent",  # Total
    ],
    
    "equity_securities_fvni_noncurrent": [
        "EquitySecuritiesFVNINoncurrent",  # Noncurrent portion only
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
    ],
    
    "other_bank_borrowings": [
        "OtherBankBorrowings",
    ],
    
    "other_borrowings": [
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
    ],
    
    "other_nonoperating_income_expense": [
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
    
    Uses explicit mappings first, then auto-generates from concept name as fallback.
    Ensures uniqueness by preserving semantic distinctions, not blindly truncating.
    
    Args:
        concept: XBRL concept name (e.g., 'RevenueFromContractWithCustomerExcludingAssessedTax')
    
    Returns:
        Normalized label (e.g., 'revenue') or auto-generated snake_case label
    """
    import re
    import hashlib
    
    # Try explicit mappings first (curated, high-quality)
    for normalized, concepts in CONCEPT_MAPPINGS.items():
        if concept in concepts:
            return normalized
    
    # Fallback: Auto-generate normalized label from concept name
    # This ensures 100% coverage while prioritizing curated mappings for key metrics
    
    # Convert CamelCase to snake_case
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', concept)
    s2 = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
    
    # Mark text/disclosure fields clearly to avoid confusion with numeric data
    is_text_field = False
    if any(suffix in s2 for suffix in ['_disclosure_text_block', '_text_block', '_policy_text_block', '_table_text_block']):
        is_text_field = True
    
    # Remove common XBRL suffixes but mark type
    s2 = s2.replace('_disclosure_text_block', '_disclosure_note')  # MARK as note
    s2 = s2.replace('_text_block', '_note')  # MARK as note
    s2 = s2.replace('_abstract', '_section_header')  # MARK as abstract
    s2 = s2.replace('_policy_text_block', '_policy_note')  # Already marked
    s2 = s2.replace('_table_text_block', '_table_note')  # MARK as table
    
    # Smart length management: preserve uniqueness instead of blind truncation
    # If the label is too long, keep the start and append a unique hash of the full string
    MAX_BASE_LENGTH = 100  # Increased from 80 to preserve more semantics
    
    if len(s2) > MAX_BASE_LENGTH:
        # Take first 92 chars and append 8-char hash to ensure uniqueness
        # This prevents different concepts from being conflated
        hash_suffix = hashlib.sha256(s2.encode()).hexdigest()[:8]
        s2 = s2[:92] + '_' + hash_suffix
    
    return s2


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
        "depreciation", "depreciation_and_amortization", "depreciation_depletion_and_amortization", 
        "stock_based_compensation", "deferred_revenue"
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

