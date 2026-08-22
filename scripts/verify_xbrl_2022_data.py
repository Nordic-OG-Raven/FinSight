"""
2022 XBRL Data Extraction and SEC API Validation

This script extracts 2022 financial facts from XBRL filings using Arelle's ModelXbrl
with progress bars. This extracts ALL facts including values and contexts.

Usage:
    # Download and extract (uses sec-edgar-downloader):
    python verify_xbrl_2022_data.py [ticker] [year] [filing_type]
    
    # Extract from existing file:
    python verify_xbrl_2022_data.py --file [file_path] [ticker] [year]
    
    # Extraction + SEC API validation:
    python verify_xbrl_2022_data.py --validate [ticker] [year] [filing_type]
    python verify_xbrl_2022_data.py -v [ticker] [year] [filing_type]
"""

from pathlib import Path
from datetime import datetime
import csv
import json
import sys
import tempfile
from tqdm import tqdm
from arelle import ModelManager, Cntlr, ModelXbrl

# Import SEC API validator (kept separate for Grok assistance)
try:
    from sec_api_validator import validate_2022_extraction, get_cik_from_ticker
    SEC_API_AVAILABLE = True
except ImportError:
    SEC_API_AVAILABLE = False
    print("Warning: SEC API validator not available. Run without --validate flag.")

# Complete missing_concepts list (Grok confirmed all 168 are explicit facts in XBRL)
missing_concepts_list = [
    'AcquisitiondateFairValueOfTotalConsiderationTransferred',
    'AcquisitionRelatedCosts',
    'AcquisitionsThroughBusinessCombinationsIntangibleAssetsOtherThanGoodwill',
    'AcquisitionsThroughBusinessCombinationsOtherProvisions',
    'AcquisitionsThroughBusinessCombinationsPropertyPlantAndEquipmentIncludingRightofuseAssets',
    'AdditionalRecognitionGoodwill',
    'AdditionsOtherThanThroughBusinessCombinationsIntangibleAssetsOtherThanGoodwill',
    'AdditionsOtherThanThroughBusinessCombinationsPropertyPlantAndEquipmentIncludingRightofuseAssets',
    'AdjustmentsForAmortisationExpense',
    'AdjustmentsIncludingUnusedAmountsReversedDuringTheYear',
    'AmortisationIntangibleAssetsOtherThanGoodwill',
    'AmountRemovedFromReserveOfCashFlowHedgesAndIncludedInInitialCostOrOtherCarryingAmountOfNonfinancialAssetLiabilityOrFirmCommitmentForWhichFairValueHedgeAccountingIsApplied',
    'Assets',
    'AveragePriceOfHedgingInstrument',
    'BalancesWithBanks',
    'BankBorrowingsUndiscountedCashFlows',
    'BankOverdraftsClassifiedAsFinancialResourcesLeasing',
    'BankOverdraftsClassifiedAsFinancialResourcesWithLeasing',
    'BondsIssued',
    'BondsIssuedUndiscountedCashFlows',
    'Borrowings',
    'BorrowingsInterestRate',
    'CashAndCashEquivalentsRecognisedAsOfAcquisitionDate',
    'CashTransferred',
    'CommercialProductLaunchPotentialMilestonePayments',
    'CurrentAssets',
    'CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued',
    'CurrentDerivativeFinancialAssets',
    'CurrentDerivativeFinancialLiabilities',
    'CurrentInventoriesIndirectProductionCostsPercentOfInventoryValue',
    'CurrentInventoriesIndirectProductionCostsWorkInProgressAndFinishedGoods',
    'CurrentLeaseLiabilities',
    'CurrentLiabilities',
    'CurrentPortionOfLongtermBorrowings',
    'CurrentPrepaymentsAndOtherCurrentAssets',
    'CurrentProvisions',
    'CurrentTaxAssetsCurrent',
    'CurrentTaxLiabilitiesCurrent',
    'CurrentTradeReceivables',
    'DecreaseThroughClassifiedAsHeldForSaleGoodwill',
    'DeferredTaxAssets',
    'DeferredTaxAssetsLiabilitiesRecognisedAsOfAcquisitionDate',
    'DeferredTaxExpenseIncomeRecognisedInProfitOrLoss',
    'DeferredTaxLiabilities',
    'DeferredTaxRelatingToAcquisitionOfSubsidiaries',
    'DeferredTaxRelatingToIncomeChargeToOthercomprehensiveIncome',
    'DeferredTaxRelatingToItemsChargedOrCreditedDirectlyToEquity',
    'DescriptionOfDiscountRatesAppliedToCashFlowProjections',
    'DiscountRateAppliedToCashFlowProjectionsPreTax',
    'DisposalsIntangibleAssetsOtherThanGoodwill',
    'DisposalsPropertyPlantAndEquipmentIncludingRightofuseAssets',
    'DistributableReserves',
    'EntityCommonStockSharesOutstanding',
    'EquityAndLiabilities',
    'EquityAsAPercentageOfShareCapital',
    'FinancialAssetsAtFairValue',
    'FinancialAssetsAvailableForSaleTransferredCarryingAmount',
    'FinancialLiabilities',
    'FinancialLiabilitiesAtFairValue',
    'FinishedGoods',
    'GainsLossesRecognisedInOtherComprehensiveIncomeFairValueMeasurementAssets',
    'GainsLossesRecognisedInOtherComprehensiveIncomeFairValueMeasurementLiabilities',
    'GainsLossesRecognisedInOtherComprehensiveIncomeIncludingExchangeDifferencesFairValueMeasurementRelatedToAcquisitionOfBusinesses',
    'GainsLossesRecognisedInProfitOrLossFairValueMeasurementAssets',
    'GainsLossesRecognisedInProfitOrLossFairValueMeasurementLiabilities',
    'GrossLeaseLiabilities',
    'HedgingInstrumentAssets',
    'HedgingInstrumentLiabilities',
    'IdentifiableAssetsAcquiredLiabilitiesAssumed',
    'ImpairmentLossRecognisedInProfitOrLossGoodwill',
    'ImpairmentLossRecognizedInProfitOrLossGoodwillReversed',
    'IncomeTaxConsequencesOfDividendsNotPracticablyDeterminableNotRecognisedAsLiability',
    'IncreaseDecreaseThroughAdditionsLiabilitiesArisingFromFinancingActivities',
    'IncreaseDecreaseThroughBusinessCombinationsDeferredTaxLiabilityAsset',
    'IncreaseDecreaseThroughCashFlowsBorrowings',
    'IncreaseDecreaseThroughEffectOfChangesInForeignExchangeRatesLiabilitiesArisingFromFinancingActivities',
    'IncreaseDecreaseThroughFinancingCashFlowsLiabilitiesArisingFromFinancingActivities',
    'IncreaseDecreaseThroughForeignExchangeFinancialAssets',
    'IncreaseDecreaseThroughNetExchangeDifferencesDeferredTaxLiabilityAsset',
    'IncreaseDecreaseThroughNetExchangeDifferencesGoodwill',
    'IncreaseDecreaseThroughNetExchangeDifferencesIntangibleAssetsOtherThanGoodwill',
    'IncreaseDecreaseThroughNetExchangeDifferencesPropertyPlantAndEquipmentIncludingRightofuseAssets',
    'IncreaseDecreaseThroughObtainingOrLosingControlOfSubsidiariesOrOtherBusinessesLiabilitiesArisingFromFinancingActivities',
    'IncreaseDecreaseThroughOtherChangesLiabilitiesArisingFromFinancingActivities',
    'IncreaseDecreaseThroughOtherMovementsFinancialAssets',
    'IncreaseDecreaseThroughTransfersPropertyPlantAndEquipmentIncludingRightofuseAssets',
    'IncreaseThroughProceedsObtainedLiabilitiesArisingFromFinancingActivities',
    'IntangibleAssetsMaterialToEntity',
    'IntangibleAssetsUnderDevelopment',
    'IntellectualPropertyRightsAndOtherIntangibleAssetsRecognizedAsOfAcquisitionDate',
    'InventoryWritedown2011',
    'InvestmentsInAssociatesAccountedForUsingEquityMethod',
    'IssuedCapital',
    'KeyManagementPersonnelCompensationRecruitmentArrangementsAndConditionalAmountsPayable',
    'LeaseAndBorrowingUndiscountedCashFlow',
    'LeaseLiabilities',
    'LeaseObligationsNotRecognisedInTheBalanceSheet',
    'Liabilities',
    'LineOfCreditFacilityMaximumBorrowingCapacity1',
    'LongtermBorrowings',
    'MaximumExposureToCreditRisk',
    'MaximumShareAllocationAmountOfMonthsBaseSalary',
    'NetConsiderationBusinessCombination',
    'NoncurrentAssets',
    'NoncurrentLeaseLiabilities',
    'NoncurrentLiabilities',
    'NoncurrentPortionOfNoncurrentBondsIssued',
    'NoncurrentProvisions',
    'NoncurrentRecognisedLiabilitiesDefinedBenefitPlan',
    'NotionalAmount',
    'NumberOfBusinessSegments',
    'NumberOfEmployeesThatFiledPutativeClassActions',
    'NumberOfMainCommercialUnits',
    'NumberOfMajorWholesalers',
    'NumberOfSharesCancelled',
    'NumberOfSharesPurchased',
    'NumberOfSharesPurchasedRelatedPartyTransactions',
    'NumberOfSharesReleasedToEmployees',
    'NumberOfSitesAcquired',
    'NumberOfTranchesIssuedBonds',
    'NumberOfVotes',
    'ObligationsNotRecognisedOnTheBalanceSheet',
    'OtherCurrentLiabilities',
    'OtherGuarantees',
    'OtherNetAssetsRecognisedAsOfAcquisitionDate',
    'OtherNoncurrentFinancialAssets',
    'OtherNoncurrentLiabilities',
    'OtherPurchaseObligations',
    'OtherReceivablesAndPrepaymentsNoncurrent',
    'OtherReserves',
    'PercentOfPoolAllocationOtherEquityInstrumentsInSharebasedPaymentArrangement',
    'PropertyPlantAndEquipmentAndIntangibleAssets',
    'PropertyPlantAndEquipmentRecognisedAsOfAcquisitionDate',
    'ProportionOfOwnershipInterestInAssociate',
    'ProportionOfOwnershipInterestInSubsidiary',
    'ProportionOfVotingPowerHeldInSubsidiary',
    'ProvisionsForSalesRebates',
    'ProvisionsRecognisedAsOfAcquisitionDate',
    'PurchaseObligationsRelatingToContractManufacturers',
    'PurchaseObligationsRelatingToInvestmentsInPropertyPlantAndEquipment',
    'RawMaterials',
    'ResearchAndDevelopmentObligations',
    'ResearchAndDevelopmentPotentialMilestonePayments',
    'RestrictedCashAndCashEquivalents',
    'RetainedEarnings',
    'RevenueExpectedThatWasToBeIncludedInContractLiabilityBalanceAtBeginningOfPeriodNextFiscalYear',
    'RevenueExpectedThatWasToBeIncludedInContractLiabilityBalanceAtBeginningOfPeriodThereafter',
    'ReversalOfImpairmentLossRecognisedInOtherComprehensiveIncomeIntangibleAssetsOtherThanGoodwill',
    'ReversalOfImpairmentLossRecognisedInProfitOrLoss',
    'ReversalOfImpairmentLossRecognisedInProfitOrLossIntangibleAssetsOtherThanGoodwill',
    'ReversalOfImpairmentLossRecognisedInProfitOrLossPropertyPlantAndEquipmentIncludingRightofuseAssets',
    'ReversalOfInventoryWritedown',
    'RightofuseAssets',
    'SensitivityAnalysisForTypesOfMarketRiskReasonablyPossibleChangeInRiskVariableImpactOnOtherComprehensiveIncome',
    'SensitivityAnalysisForTypesOfMarketRiskReasonablyPossibleChangeInRiskVariableImpactOnOtherComprehensiveIncomeAndProfitLoss',
    'SensitivityAnalysisForTypesOfMarketRiskReasonablyPossibleChangeInRiskVariableImpactOnProfitLoss',
    'SensitivityAnalysisForTypesOfMarketRiskReasonablyPossibleChangeInRiskVariablePercent',
    'SettlementOfPreExistingRelationshipsBusinessCombination',
    'ShorttermBorrowings',
    'StatutoryDiscountsOfNet',
    'StockRepurchaseProgramAuthorizedAmount11',
    'StockRepurchaseProgramRemainingAuthorizedRepurchaseAmount2',
    'TechnologyBasedIntangibleAssetsKnowHowRecognisedAsOfAcquisitionDate',
    'TradeAndOtherCurrentPayablesToTradeSuppliers',
    'TreasuryShares',
    'UnusedTaxLossesForWhichNoDeferredTaxAssetRecognised',
    'UtilisationofInventoryWriteDown',
    'WorkInProgress'
]

def download_filing_with_sec_edgar_downloader(ticker: str, year: int, filing_type: str = '20-F', output_dir: Path = None) -> Path:
    """
    Download filing using sec-edgar-downloader (better maintained, more reliable).
    
    Returns:
        Path to downloaded instance file
    """
    try:
        from sec_edgar_downloader import Downloader
    except ImportError:
        raise ImportError("sec-edgar-downloader not installed. Run: pip install sec-edgar-downloader")
    
    if output_dir is None:
        output_dir = Path('data/raw')
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\n[DOWNLOAD] Using sec-edgar-downloader to get {ticker} {year} {filing_type}...")
    
    # Initialize downloader
    dl = Downloader(output_dir)
    
    # Download filing
    try:
        dl.get(filing_type, ticker, limit=1)
        print(f"  ✅ Download complete")
        
        # Find the downloaded file
        # sec-edgar-downloader saves to: output_dir/ticker/filing_type/accession_number/filename
        ticker_dir = output_dir / ticker.upper() / filing_type
        if not ticker_dir.exists():
            raise FileNotFoundError(f"Downloaded file not found in {ticker_dir}")
        
        # Find the most recent filing (should be the one we just downloaded)
        accession_dirs = sorted(ticker_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)
        if not accession_dirs:
            raise FileNotFoundError(f"No filing found in {ticker_dir}")
        
        # Find .htm or .xml file in the accession directory
        filing_dir = accession_dirs[0]
        instance_files = list(filing_dir.glob('*.htm')) + list(filing_dir.glob('*.xml'))
        if not instance_files:
            raise FileNotFoundError(f"No instance file found in {filing_dir}")
        
        # Prefer .htm for inline XBRL
        instance_file = None
        for f in instance_files:
            if f.suffix == '.htm':
                instance_file = f
                break
        if instance_file is None:
            instance_file = instance_files[0]
        
        print(f"  ✅ Found: {instance_file.name}")
        return instance_file
        
    except Exception as e:
        raise RuntimeError(f"sec-edgar-downloader failed: {e}")

def extract_2022_facts_via_modelxbrl(xbrl_path: Path, target_year: int = 2022):
    """
    Extract facts for target_year using Arelle's ModelXbrl (which has ALL data including values/contexts).
    Uses progress bars to show it's working, not hanging.
    """
    print("="*70)
    print(f"EXTRACTING {target_year} FACTS VIA ARELLE MODELXBRL")
    print("="*70)
    
    # Step 1: Load XBRL with Arelle
    print("\n[STEP 1] Loading XBRL file with Arelle...")
    print("  This may take a moment (progress will be shown)...")
    
    controller = Cntlr.Cntlr(logFileName="logToBuffer")
    model_manager = ModelManager.initialize(controller)
    controller.webCache.workOffline = False  # Allow network for linkbases
    
    file_url = xbrl_path.absolute().as_uri()
    
    print(f"  Loading: {xbrl_path.name}")
    print("  [Processing...]")
    
    try:
        # CRITICAL FIX (Grok): Load IFRS taxonomy explicitly for NS-aware QName resolution
        # This ensures "ifrs-full:Assets" is properly resolved
        print("  Loading IFRS taxonomy for namespace resolution...")
        try:
            # Load IFRS taxonomy XSD (Grok's recommendation)
            # Arelle will auto-resolve from instance document, but explicit load ensures proper resolution
            taxonomy_url = 'https://xbrl.ifrs.org/taxonomy/2024-03-27/full_ifrs/full_ifrs-cor_2024-03-27.xsd'
            try:
                model_manager.loadTaxonomy(taxonomy_url)
                print("  ✅ IFRS taxonomy loaded")
            except Exception as e:
                print(f"  ⚠️  Taxonomy load warning (will use auto-resolved): {e}")
        except Exception as e:
            print(f"  ⚠️  Taxonomy load error: {e}")
        
        # Load the instance document
        model_xbrl = model_manager.load(file_url)
        
        if not model_xbrl:
            raise RuntimeError("Failed to load XBRL file")
        
        # CRITICAL: Force inline XBRL discovery (Grok's recommendation)
        # This is required to extract all facts from Inline XBRL files
        if model_xbrl.modelDocument and hasattr(model_xbrl.modelDocument, 'inlineXbrlDiscover'):
            try:
                html_element = None
                if hasattr(model_xbrl.modelDocument, 'htmlElement'):
                    html_element = model_xbrl.modelDocument.htmlElement
                elif hasattr(model_xbrl.modelDocument, 'xmlRootElement'):
                    html_element = model_xbrl.modelDocument.xmlRootElement
                
                if html_element is not None:
                    print("  Triggering inline XBRL discovery...")
                    model_xbrl.modelDocument.inlineXbrlDiscover(html_element)
                    print("  ✅ Inline XBRL discovery complete")
            except Exception as e:
                print(f"  ⚠️  Inline XBRL discovery error: {e}")
        
        # Get all facts
        all_facts = list(model_xbrl.facts)
        print(f"  ✅ Loaded {len(all_facts)} total facts")
        
    except Exception as e:
        raise RuntimeError(f"Arelle loading failed: {e}")
    
    # Step 2: Extract target_year contexts
    print(f"\n[STEP 2] Identifying {target_year} contexts...")
    contexts_target_instant = set()
    contexts_target_duration = set()
    
    for ctx_id, ctx in tqdm(model_xbrl.contexts.items(), desc="  Checking contexts", unit="contexts", file=sys.stderr, total=len(model_xbrl.contexts)):
        # Access period via ctx.period
        if not hasattr(ctx, 'period') or ctx.period is None:
            continue
        
        period = ctx.period
        
        # CRITICAL FIX (Grok): Use period.stringValue for period filtering
        # This is the recommended way to check periods
        period_str = period.stringValue if hasattr(period, 'stringValue') else str(period)
        
        # Check instant period (balance sheet) - 2022-12-31
        if f'{target_year}-12-31' in period_str:
            # Check if it's an instant period (not a duration)
            if 'to' not in period_str.lower() and 'start' not in period_str.lower():
                contexts_target_instant.add(ctx_id)
        
        # Check duration period (income statement, cash flow) - 2022-01-01 to 2022-12-31
        if (f'{target_year}-01-01' in period_str and 
            f'{target_year}-12-31' in period_str):
            contexts_target_duration.add(ctx_id)
    
    all_target_contexts = contexts_target_instant | contexts_target_duration
    print(f"  ✅ Found {len(contexts_target_instant)} instant + {len(contexts_target_duration)} duration contexts for {target_year}")
    
    # Step 3: Extract target_year facts
    print(f"\n[STEP 3] Extracting {target_year} facts...")
    facts_target = []
    
    for fact in tqdm(all_facts, desc="  Extracting facts", unit="facts", file=sys.stderr):
        if not fact.context or not fact.context.id:
            continue
        
        ctx_id = fact.context.id
        
        # CRITICAL FIX (Grok): Use fact.context.period.stringValue for period filtering
        # This is the recommended way to check periods
        is_target_year = False
        period = fact.context.period if fact.context.period else None
        
        if period:
            # Use stringValue (Grok's recommendation)
            period_str = period.stringValue if hasattr(period, 'stringValue') else str(period)
            
            # Check if period string contains target_year date
            if f'{target_year}-12-31' in period_str:
                is_target_year = True
            elif f'{target_year}-01-01' in period_str and f'{target_year}-12-31' in period_str:
                is_target_year = True
        
        # Fallback: Check our parsed contexts
        if not is_target_year and ctx_id in all_target_contexts:
            is_target_year = True
        
        if not is_target_year:
            continue
        
        # CRITICAL FIX (Grok): Use NS-aware QName extraction
        # For ModelInlineFact, fact.concept is None, so use fact.qname.localName
        # This properly handles "ifrs-full:Assets" -> "Assets"
        concept_name = ''
        if hasattr(fact, 'concept') and fact.concept:
            if hasattr(fact.concept, 'qname') and fact.concept.qname:
                # Use localName for NS-aware extraction (handles "ifrs-full:Assets" -> "Assets")
                concept_name = fact.concept.qname.localName
            else:
                concept_name = str(fact.concept)
        elif hasattr(fact, 'qname') and fact.qname:
            # For ModelInlineFact, fact.concept is None, so use fact.qname
            concept_name = fact.qname.localName
        
        # Also get full QName for reference
        concept_full = ''
        if hasattr(fact, 'concept') and fact.concept:
            if hasattr(fact.concept, 'qname') and fact.concept.qname:
                # Get prefixed name (e.g., "ifrs-full:Assets")
                if hasattr(fact.concept.qname, 'prefixedName'):
                    concept_full = fact.concept.qname.prefixedName
                else:
                    concept_full = str(fact.concept.qname)
            else:
                concept_full = str(fact.concept)
        
        # Get value (Grok's recommendation: use f.value, not f.xValue)
        value = ''
        if hasattr(fact, 'value'):
            value = str(fact.value) if fact.value is not None else ''
        elif hasattr(fact, 'xValue'):
            value = str(fact.xValue) if fact.xValue is not None else ''
        
        # Handle nil
        if hasattr(fact, 'isNil') and fact.isNil:
            value = '0'
        
        # Determine period type
        period_type = 'instant' if ctx_id in contexts_target_instant else 'duration'
        
        # Extract dimensions
        dims = {}
        if hasattr(fact.context, 'qnameDims'):
            for dim_qname, dim_member in fact.context.qnameDims.items():
                dim_name = dim_qname.localName if hasattr(dim_qname, 'localName') else str(dim_qname)
                dim_value = dim_member.qname.localName if hasattr(dim_member, 'qname') and hasattr(dim_member.qname, 'localName') else str(dim_member)
                dims[dim_name] = dim_value
        
        facts_target.append({
            'concept_full': concept_full,
            'concept': concept_name,
            'value': value,
            'dims': dims,
            'ctx': ctx_id,
            'period_type': period_type
        })
    
    print(f"\n  ✅ Extracted {len(facts_target)} facts for {target_year}")
    
    # Step 4: Check for missing concepts
    print("\n[STEP 4] Checking for missing concepts...")
    recovered = 0
    recovered_concepts = []
    
    for fact in facts_target:
        if fact['concept'] in missing_concepts_list:
            recovered += 1
            recovered_concepts.append(fact['concept'])
            print(f"  ✅ Recovered: {fact['concept']} = {fact['value']}")
    
    print(f"\n  ✅ Matched {recovered} concepts from missing list ({len(missing_concepts_list)} total)")
    
    # Step 5: Export to CSV
    print("\n[STEP 5] Exporting to CSV...")
    csv_path = xbrl_path.parent / f'{xbrl_path.stem}_{target_year}_complete.csv'
    
    if facts_target:
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['concept_full', 'concept', 'value', 'period_type', 'ctx', 'dims'])
            writer.writeheader()
            for fact in facts_target:
                fact_copy = fact.copy()
                fact_copy['dims'] = str(fact['dims'])
                writer.writerow(fact_copy)
        print(f"  ✅ Exported to: {csv_path}")
    else:
        print("  ⚠️  No facts to export")
    
    print("\n" + "="*70)
    print("EXTRACTION COMPLETE")
    print("="*70)
    
    return len(facts_target), recovered, facts_target, csv_path

def extract_2022_facts(xbrl_path: Path, target_year: int = 2022):
    """Extract facts for target_year using ModelXbrl (which works and has all data)"""
    return extract_2022_facts_via_modelxbrl(xbrl_path, target_year)

def run_with_sec_validation(xbrl_path: Path, ticker: str = 'NVO', year: int = 2022, extract_year: int = 2022):
    """
    Wrapper function that runs XBRL extraction AND SEC API validation together.
    Keeps them separate so verify_xbrl_2022_data.py can be run standalone for Grok assistance.
    
    Args:
        xbrl_path: Path to XBRL file
        ticker: Company ticker symbol
        year: Year to extract/validate
        
    Returns:
        Tuple of (extraction_results, validation_results)
    """
    print("="*70)
    print("XBRL EXTRACTION + SEC API VALIDATION")
    print("="*70)
    
    # Step 1: Run XBRL extraction
    print("\n[STEP 1] Running XBRL extraction...")
    print("-"*70)
    if not xbrl_path.exists():
        print(f"❌ Error: File not found: {xbrl_path}")
        return None, None
    
    total, recovered, facts, csv_path = extract_2022_facts(xbrl_path, extract_year)
    print(f"\n✅ Extraction complete: {total} facts, {recovered} matched missing list")
    
    # Step 2: Run SEC API validation (if available)
    validation_result = None
    if SEC_API_AVAILABLE:
        print("\n[STEP 2] Running SEC API validation...")
        print("-"*70)
        validation_result = validate_2022_extraction(
            ticker=ticker,
            year=year,
            extracted_csv_path=csv_path
        )
        
        if 'error' in validation_result:
            print(f"\n⚠️  SEC API validation failed: {validation_result['error']}")
        else:
            print(f"\n✅ SEC API validation complete")
    else:
        print("\n⚠️  SEC API validation skipped (module not available)")
    
    print("\n" + "="*70)
    print("COMPLETE")
    print("="*70)
    
    return {
        'total_facts': total,
        'recovered': recovered,
        'facts': facts,
        'csv_path': csv_path
    }, validation_result

if __name__ == '__main__':
    # Parse command line arguments
    validate_with_sec = '--validate' in sys.argv or '-v' in sys.argv
    use_file = '--file' in sys.argv
    
    # Get parameters from args
    file_path = None
    ticker = 'NVO'
    year = 2024  # Default to 2024 (the filing year)
    filing_type = '20-F'
    extract_year = 2022  # Year to extract from the filing
    
    args_list = [a for a in sys.argv[1:] if not a.startswith('-')]
    
    if use_file:
        # Mode: Extract from existing file
        # Usage: --file [file_path] [ticker] [extract_year]
        if args_list:
            file_path = Path(args_list[0])
        if len(args_list) > 1:
            ticker = args_list[1]
        if len(args_list) > 2:
            try:
                extract_year = int(args_list[2])
            except ValueError:
                pass
    else:
        # Mode: Download and extract
        # Usage: [ticker] [year] [filing_type]
        if args_list:
            ticker = args_list[0]
        if len(args_list) > 1:
            try:
                year = int(args_list[1])
            except ValueError:
                filing_type = args_list[1]
        if len(args_list) > 2:
            filing_type = args_list[2]
        
        # Download using sec-edgar-downloader
        try:
            file_path = download_filing_with_sec_edgar_downloader(ticker, year, filing_type)
            extract_year = 2022  # Extract 2022 data from the filing
        except Exception as e:
            print(f"❌ Download failed: {e}")
            print("Falling back to existing file...")
            pattern = f"{ticker}_{year}_{filing_type.replace('-', '')}*.htm"
            existing_files = list(Path('data/raw').glob(pattern))
            if existing_files:
                file_path = existing_files[0]
            else:
                print(f"❌ No existing file found. Please download manually or fix downloader.")
                sys.exit(1)
    
    if file_path is None:
        file_path = Path('data/raw/NVO_2024_20F_.htm')
    
    if not file_path.exists():
        print(f"❌ Error: File not found: {file_path}")
        sys.exit(1)
    
    print(f"\n📄 Using file: {file_path}")
    print(f"📅 Extracting data for year: {extract_year}")
    
    # Run extraction with or without validation
    if validate_with_sec and SEC_API_AVAILABLE:
        extraction_result, validation_result = run_with_sec_validation(
            file_path, ticker, year, extract_year
        )
    else:
        if validate_with_sec and not SEC_API_AVAILABLE:
            print("Warning: --validate flag specified but SEC API validator not available.")
            print("Running extraction only...\n")
        
        total, recovered, facts, csv_path = extract_2022_facts(file_path, extract_year)
        print(f"\n✅ Verdict: {total} facts for {extract_year}, {recovered} from missing list.")
