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
        "Revenues",  # Total revenue (may include contract + collaborative arrangement revenue)
        "Revenue",   # Total revenue (IFRS)
        "RevenueFromContractWithCustomerIncludingAssessedTax",  # Total contract revenue INCLUDING assessed tax (alternative format)
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "SalesRevenueServicesNet",
    ],
    
    "revenue_from_contracts": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",  # Contract revenue only (component of total revenue, excludes collaborative arrangements)
    ],
    
    "revenue_from_collaborative_arrangements": [
        "RevenueFromCollaborativeArrangementExcludingRevenueFromContractWithCustomer",  # Collaborative arrangement revenue (component, excludes contract revenue)
    ],
    
    "revenue_from_sale_of_goods": [
        "RevenueFromSaleOfGoods",  # IFRS variant - product revenue component (SNY uses this as main component)
    ],
    
    "other_revenue": [
        "OtherRevenue",  # IFRS variant - other revenue component (SNY - sums with RevenueFromSaleOfGoods)
    ],
    
    "cost_of_revenue": [
        "CostOfRevenue",  # Generic cost of revenue
    ],
    
    "cost_of_goods_and_services_sold": [
        "CostOfGoodsAndServicesSold",  # More specific: goods AND services
    ],
    
    "cost_of_sales": [
        "CostOfSales",  # IFRS equivalent
        "CostOfGoodsSold",
    ],
    
    "gross_profit": [
        "GrossProfit",
        "GrossProfitLoss",
        # Note: Can be calculated as revenue - cost_of_revenue for companies that don't report it directly
    ],
    
    "operating_expenses": [
        "OperatingExpenses",
        "OperatingCostsAndExpenses",
    ],
    
    "costs_and_expenses": [
        "CostsAndExpenses",  # AMZN, WMT use this (total costs, not just operating)
        "TotalCostsAndExpenses",
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
        "ProfitLossFromOperatingActivities",  # IFRS variant (NVO, SNY)
        "ProfitLossFromOperatingActivitiesContinuingOperations",
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
        "ProfitLossAttributableToOwnersOfParent",  # IFRS variant (excludes NCI)
        "NetIncome",
    ],
    
    "net_income_to_common": [
        "NetIncomeLossAvailableToCommonStockholdersBasic",  # Use basic as canonical (diluted is same value, different share count)
        "NetIncomeLossAvailableToCommonStockholdersDiluted",  # Map to basic (same underlying net income value)
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
        "CashAndCashEquivalents",  # IFRS variant (NVO, SNY)
        "CashAndDueFromBanks",  # Bank-specific (BAC, JPM) - semantically equivalent to cash_and_equivalents
        "CashAndBankBalancesAtCentralBanks",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashAndRestrictedCashEquivalents",  # When it represents total cash
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
        "AccountsReceivableNet",  # Total accounts receivable (current + noncurrent)
        # Bank-specific: Financing receivables are banks' equivalent of accounts receivable
        # Use the main concept (before allowance), others are components/variants
        "FinancingReceivableExcludingAccruedInterestBeforeAllowanceForCreditLoss",  # BAC/JPM - main concept
        # Other variants are components/variants - will get component labels via taxonomy child detection
        "ReceivablesNet",  # IFRS equivalent - total
        "TradeReceivables",  # IFRS trade receivables
        "TradeAndOtherCurrentReceivables",  # IFRS variant
        "CurrentTradeReceivables",  # IFRS variant (NVO, SNY)
    ],
    
    "accounts_receivable_current": [
        "AccountsReceivableNetCurrent",  # Current-only accounts receivable
        "ReceivablesNetCurrent",  # IFRS current-only
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
        "PropertyPlantAndEquipment",  # IFRS variant (SNY)
        "PropertyPlantAndEquipmentIncludingRightofuseAssets",  # IFRS variant with right-of-use (NVO)
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
        "Assets",  # Assets side of balance sheet
        # Note: LiabilitiesAndStockholdersEquity maps to total_assets_equation (same value, different side)
    ],
    
    "total_assets_equation": [
        "LiabilitiesAndStockholdersEquity",  # Balance sheet equation (Assets = L + E) - same value as Assets
    ],
    
    # ============================================================================
    # BALANCE SHEET - LIABILITIES
    # ============================================================================
    
    "accounts_payable_and_accrued_liabilities": [
        "AccountsPayableAndAccruedLiabilitiesCurrent",  # Combined line item (accounts payable + accrued liabilities)
    ],
    
    "accounts_payable": [
        "AccountsPayableCurrent",
        "AccountsPayableTradeCurrent",  # Trade-only accounts payable (subset of combined)
        "TradeAndOtherCurrentPayables",
        "AccountsPayableAndOtherAccruedLiabilities",  # Bank-specific (JPM) - semantically equivalent to accounts_payable
        # AccruedLiabilitiesAndOtherLiabilities removed from explicit mapping
        # This is a parent concept - when both exist (ASML), causes duplicates
        # Universal solution: Let it auto-generate to accrued_liabilities_and_other_liabilities
        # Then calculate accounts_payable from it for companies missing accounts_payable (universal fix)
        "TradeAndOtherCurrentPayablesToTradeSuppliers",  # IFRS variant (NVO, SNY)
        "TradePayables",
        "AccountsPayableTrade",
        "AccountsPayableTradeCurrent",
    ],
    
    "accrued_liabilities_current": [
        "AccruedLiabilitiesCurrent",
    ],
    
    "employee_related_liabilities_current": [
        "EmployeeRelatedLiabilitiesCurrent",
    ],
    
    "other_accrued_liabilities_current": [
        "OtherAccruedLiabilitiesCurrent",
    ],
    
    "other_liabilities_current": [
        "OtherLiabilitiesCurrent",
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
        "LiabilitiesCurrent",  # US-GAAP - current liabilities only
        # CurrentLiabilities removed - handled by context_specific_patterns
        # (different values, different scope - keep separate)
        # Bank-specific: Deposit liabilities are COMPONENTS of current liabilities
        # They will be auto-detected as children and get component labels
        # (Do NOT map here - let component exclusion handle them)
    ],
    
    "total_liabilities": [
        "Liabilities",
        "LiabilitiesTotal",
        # NOTE: CurrentLiabilities removed - values don't match total or current
        # Let it auto-generate to 'current_liabilities' (different label) to prevent incorrect merging
        # Note: For IFRS companies, can be calculated as current_liabilities + noncurrent_liabilities
        # But we don't map components directly - they need to be calculated in views/queries
    ],
    
    "long_term_debt": [
        "LongTermDebt",
        "LongTermBorrowings",
        "LongtermBorrowings",  # IFRS variant (NVO)
    ],
    
    "long_term_debt_noncurrent": [
        "LongTermDebtNoncurrent",
    ],
    
    "noncurrent_liabilities": [
        "LiabilitiesNoncurrent",
        # NoncurrentLiabilities removed - handled by context_specific_patterns
        # (different values, different scope - keep separate)
        # Bank-specific: Long-term debt is noncurrent liability for banks
        # Note: LongTermDebt maps to long_term_debt, but for validation purposes,
        # banks with LongTermDebt have noncurrent liabilities (can calculate from total - current)
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
        "StockholdersEquity",  # US-GAAP (excludes NCI)
        "TotalEquity",  # Alternative IFRS name for total equity (excludes NCI)
        "EquityAttributableToOwnersOfParent",  # IFRS (excludes NCI, more specific)
        # NOTE: "Equity" (IFRS) may include or exclude NCI depending on company
        #       If Equity > EquityAttributableToOwnersOfParent → includes NCI → map to stockholders_equity_including_noncontrolling_interest
        #       If Equity ≈ EquityAttributableToOwnersOfParent → excludes NCI → map to stockholders_equity
        #       For SNY: Equity includes NCI, so it's handled separately
        #       For NVO: Equity excludes NCI, maps here via equity_total → stockholders_equity (via universal metrics variant)
    ],
    
    "equity_attributable_to_parent": [
        "EquityAttributableToOwnersOfParent",  # IFRS (excludes NCI, more specific)
    ],
    
    "equity_total": [
        "Equity",  # IFRS simple equity (may differ from EquityAttributableToOwnersOfParent when NCI exists)
        # Note: This is used as variant for stockholders_equity when company doesn't have US-GAAP structure
    ],
    
    "stockholders_equity_including_noncontrolling_interest": [
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",  # US-GAAP (includes NCI)
        "EquityIncludingPortionAttributableToNoncontrollingInterest",  # US-GAAP variant
        "Equity",  # IFRS simple equity when it includes NCI (SNY case: Equity > EquityAttributableToOwnersOfParent)
        # NOTE: This requires runtime check - we handle via normalization logic or calculated comparison
        # For now, map Equity to this when company reports both Equity and EquityAttributableToOwnersOfParent with different values
    ],
    
    "net_income_including_noncontrolling_interest": [
        "ProfitLoss",  # IFRS/US-GAAP - includes NCI (taxonomy label: "Net Income (Loss), Including Portion Attributable to Noncontrolling Interest")
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
        "NetCashProvidedByUsedInOperatingActivities",  # Total (includes discontinued operations)
        "CashFlowsFromUsedInOperatingActivities",  # IFRS variant
    ],
    
    "operating_cash_flow_continuing_operations": [
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",  # Continuing operations only
    ],
    
    "investing_cash_flow": [
        "NetCashProvidedByUsedInInvestingActivities",  # Total (includes discontinued operations)
        "CashFlowsFromUsedInInvestingActivities",  # IFRS variant
    ],
    
    "investing_cash_flow_continuing_operations": [
        "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",  # Continuing operations only
    ],
    
    "financing_cash_flow": [
        "NetCashProvidedByUsedInFinancingActivities",  # Total (includes discontinued operations)
        "CashFlowsFromUsedInFinancingActivities",  # IFRS variant
    ],
    
    "financing_cash_flow_continuing_operations": [
        "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations",  # Continuing operations only
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
        "PaymentsForRepurchaseOfCommonStock",  # Cash flow: payments for repurchases
        "PaymentsForRepurchaseOfEquity",  # Cash flow variant
    ],
    
    "treasury_stock_value_acquired": [
        "TreasuryStockValueAcquiredCostMethod",  # Balance sheet: treasury stock at cost (different from cash flow payments)
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
    
    "equity_securities_fvni_current": [
        "EquitySecuritiesFvNi",  # Current-only (taxonomy label: "Equity Securities, FV-NI, Current")
    ],
    
    "equity_securities_fvni": [
        "EquitySecuritiesFvNiCurrentAndNoncurrent",  # Total (current + noncurrent)
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
    
    # Pension discount rate removed - handled by context_specific_patterns
    # (different contexts: obligation vs periodic cost - keep separate)
    # "pension_discount_rate": [
    #     "DefinedBenefitPlanAssumptionsUsedCalculatingBenefitObligationDiscountRate",
    #     "DefinedBenefitPlanAssumptionsUsedCalculatingNetPeriodicBenefitCostDiscountRate",
    # ],
    
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
    
    # DEPRECATED: PropertyPlantAndEquipment and PropertyPlantAndEquipmentIncludingRightofuseAssets
    # now map to property_plant_equipment (see above)
    # "ppe_net_alternative": [
    #     "PropertyPlantAndEquipment",
    #     "PropertyPlantAndEquipmentIncludingRightofuseAssets",
    # ],
    
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
    
    "intangible_assets_other_than_goodwill": [
        "IntangibleAssetsOtherThanGoodwill",  # Explicit "other than goodwill"
    ],
    
    "other_intangible_assets": [
        "OtherIntangibleAssets",  # Generic "other" category
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
        "OtherComprehensiveIncomeLossNetOfTax",  # Total OCI
        "OtherComprehensiveIncome",
        # OtherComprehensiveIncomeLossNetOfTaxPortionAttributableToParent removed
        # (parent-only portion, different from total - keep separate)
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
    
    # DEPRECATED: CashAndCashEquivalents now maps to cash_and_equivalents
    # "cash_alternative_ifrs": [
    #     "CashAndCashEquivalents",
    # ],
    
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
    
    # NOTE: LeaseLiabilities removed from mapping to avoid ASML duplicate conflict
    # LeaseLiabilities (IFRS/custom) will auto-generate to 'lease_liabilities'
    # OperatingLeaseLiability (US-GAAP) maps to 'operating_lease_liability'
    # They're semantically equivalent but kept separate when both exist (ASML case)
    "operating_lease_liability": [
        "OperatingLeaseLiability",
        # "LeaseLiabilities",  # Removed: auto-generates to 'lease_liabilities' to avoid ASML duplicates
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


# Cache for taxonomy parent-child relationships (loaded once, reused)
_taxonomy_child_to_parent_cache = None

def _load_taxonomy_child_to_parent() -> dict:
    """Load parent-child relationships from taxonomy calculation linkbase (cached)."""
    global _taxonomy_child_to_parent_cache
    
    if _taxonomy_child_to_parent_cache is not None:
        return _taxonomy_child_to_parent_cache
    
    import json
    from pathlib import Path
    
    # Find taxonomy directory (relative to this file)
    taxonomy_dir = Path(__file__).parent.parent.parent / 'data' / 'taxonomies'
    
    calc_files = list(taxonomy_dir.glob("*/*-calc.json")) + list(taxonomy_dir.glob("*-calc.json"))
    
    child_to_parent = {}
    
    for calc_file in calc_files:
        try:
            with open(calc_file, 'r') as f:
                data = json.load(f)
            
            relationships = data.get('relationships', [])
            
            for rel in relationships:
                parent_name = rel.get('parent_concept', '')
                child_name = rel.get('child_concept', '')
                
                # Remove namespace prefixes if present
                parent_name = parent_name.split(':')[-1] if ':' in parent_name else parent_name
                child_name = child_name.split(':')[-1] if ':' in child_name else child_name
                
                if parent_name and child_name:
                    child_to_parent[child_name] = parent_name
        except Exception:
            continue  # Skip if file can't be read
    
    _taxonomy_child_to_parent_cache = child_to_parent
    return child_to_parent


# Reverse mapping: concept -> normalized_label
def get_normalized_label(concept: str) -> str | None:
    """
    Get the normalized label for a given concept name.
    
    Uses explicit mappings first, then auto-generates from concept name as fallback.
    IMPORTANT: If concept is a CHILD in taxonomy calculation linkbase and parent is mapped,
    gives component-specific label to prevent duplicates.
    
    Args:
        concept: XBRL concept name (e.g., 'RevenueFromContractWithCustomerExcludingAssessedTax')
    
    Returns:
        Normalized label (e.g., 'revenue') or auto-generated snake_case label
    """
    import re
    import hashlib
    
    # Check explicit mappings FIRST (before child check)
    # This ensures bank-specific concepts (e.g., CashAndDueFromBanks) map to universal metrics
    # even if they're children in taxonomy
    # EXCEPTION: If concept is a PARENT in taxonomy and company also has the child mapped to same label,
    # don't map the parent (to avoid duplicates)
    for normalized, concepts_list in CONCEPT_MAPPINGS.items():
        if concept in concepts_list:
            # Special case: AccruedLiabilitiesAndOtherLiabilities is a parent that includes AccountsPayableCurrent
            # If company has both, don't map AccruedLiabilitiesAndOtherLiabilities to accounts_payable
            # (AccountsPayableCurrent is the actual accounts_payable, AccruedLiabilitiesAndOtherLiabilities is the parent)
            if concept == 'AccruedLiabilitiesAndOtherLiabilities' and normalized == 'accounts_payable':
                # Check if this concept is a parent in taxonomy
                child_to_parent = _load_taxonomy_child_to_parent()
                # Check if AccountsPayableCurrent is a child of AccruedLiabilitiesAndOtherLiabilities
                if 'AccountsPayableCurrent' in child_to_parent:
                    parent_name = child_to_parent['AccountsPayableCurrent']
                    # If AccountsPayableCurrent is a child of AccruedLiabilitiesAndOtherLiabilities,
                    # then AccruedLiabilitiesAndOtherLiabilities is a parent - don't map it
                    # (let it auto-generate to its own label to avoid duplicates)
                    if parent_name == 'AccruedLiabilitiesAndOtherLiabilities':
                        # Skip mapping - let it auto-generate
                        break
            return normalized
    
    # Special handling for context-specific variants that should NOT share labels
    # These are concepts that appear similar but represent different contexts/uses
    context_specific_patterns = {
        # Pension discount rate: different contexts (obligation vs periodic cost)
        'DefinedBenefitPlanAssumptionsUsedCalculatingBenefitObligationDiscountRate': 'pension_discount_rate_obligation',
        'DefinedBenefitPlanAssumptionsUsedCalculatingNetPeriodicBenefitCostDiscountRate': 'pension_discount_rate_periodic_cost',
        # Operating lease: LeaseLiabilities (IFRS/custom) vs OperatingLeaseLiability (US-GAAP)
        # They're semantically the same, but when both exist for same company (ASML), keep separate
        # to avoid duplicates. LeaseLiabilities will auto-generate to 'lease_liabilities' which is
        # different from 'operating_lease_liability', but we can also handle explicitly if needed.
        # CurrentLiabilities vs LiabilitiesCurrent: Different values (47-85% difference) - NOT synonyms
        # CurrentLiabilities values are much larger, likely different scope or calculation
        'CurrentLiabilities': 'current_liabilities_ifrs_variant',  # Keep separate to prevent incorrect merging
        'NoncurrentLiabilities': 'noncurrent_liabilities_ifrs_variant',  # Similar issue - keep separate
        # OCI: Parent-only portion vs total OCI (different scopes)
        'OtherComprehensiveIncomeLossNetOfTaxPortionAttributableToParent': 'oci_total_parent_only',  # Keep separate from total OCI
        # AccruedLiabilitiesAndOtherLiabilities: Parent concept that includes AccountsPayableCurrent
        # When both exist (ASML), causes duplicates if both map to accounts_payable
        # Solution: Always map AccruedLiabilitiesAndOtherLiabilities to separate label
        # Then calculate accounts_payable from it for companies missing accounts_payable (universal fix)
        'AccruedLiabilitiesAndOtherLiabilities': 'accrued_liabilities_and_other_liabilities',  # Always separate to avoid duplicates
    }
    
    if concept in context_specific_patterns:
        return context_specific_patterns[concept]
    
    # Check if this concept is a CHILD in taxonomy calculation linkbase
    # If so, generate component-specific label to prevent duplicates with parent
    # NOTE: Explicit mappings checked FIRST above - this only applies if no explicit mapping exists
    child_to_parent = _load_taxonomy_child_to_parent()
    
    if concept in child_to_parent:
        parent_name = child_to_parent[concept]
        
        # Generate component-specific label for child concept
        # This ensures child doesn't get same label as parent (preventing duplicates)
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', concept)
        component_label = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
        
        # Also get what parent's label would be (to ensure uniqueness)
        parent_label = None
        
        # Check explicit mappings first
        for normalized, concepts_list in CONCEPT_MAPPINGS.items():
            if parent_name in concepts_list:
                parent_label = normalized
                break
        
        # If parent not in explicit mappings, generate parent label
        if parent_label is None:
            s1_parent = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', parent_name)
            parent_label = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1_parent).lower()
        
        # Ensure component label is different from parent label
        if component_label == parent_label:
            # Add component suffix to ensure uniqueness
            component_label = f"{component_label}_component"
        
        # Return component-specific label (prevents duplicate with parent)
        # This preserves data accessibility - component has its own queryable label
        return component_label
    
    # Special case: Bank deposit liabilities are components of current_liabilities
    # Even if not in taxonomy child-to-parent, they should get component labels
    bank_deposit_patterns = [
        'InterestBearingDepositLiabilitiesDomestic',
        'InterestBearingDepositLiabilitiesForeign',
        'NoninterestBearingDepositLiabilitiesDomestic',
        'NoninterestBearingDepositLiabilitiesForeign',
    ]
    
    if concept in bank_deposit_patterns:
        # Generate component-specific label (e.g., interest_bearing_deposit_liabilities_domestic)
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', concept)
        component_label = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
        # This will be different from 'current_liabilities' (e.g., interest_bearing_deposit_liabilities_domestic)
        return component_label
    
    # Special case: Financing receivable variants (components/variants)
    # Only the main concept maps to accounts_receivable, variants get component labels
    financing_variants = [
        'FinancingReceivableExcludingAccruedInterestBeforeAllowanceForCreditLossesNetOfDeferredIncome',
        'FinancingReceivableAccruedInterestBeforeAllowanceForCreditLoss',
    ]
    
    if concept in financing_variants:
        # Generate component-specific label
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', concept)
        component_label = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
        # Ensure it's different from accounts_receivable
        if component_label == 'accounts_receivable' or component_label.startswith('accounts_receivable'):
            component_label = 'financing_receivable_' + component_label.replace('accounts_receivable', '').strip('_')
        return component_label
    
    # Explicit mappings already checked above (before child check)
    # This section removed - check moved to top of function for bank concept support
    
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

