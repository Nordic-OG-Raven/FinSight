# 2022 Data Extraction Analysis

## Key Finding: "Assets" Concept Not Present for 2022

**Discovery**: The "Assets" concept (`ifrs-full:Assets`) exists in the filing for 2023 and 2024, but **NOT for 2022**.

**Evidence**:
- Found "Assets" in contexts c-12 (2024-12-31) and c-9 (2023-12-31)
- Searched all 313 contexts with 2022 dates - no "Assets" found
- Searched all 46 instant contexts (2022-12-31) - no "Assets" found

## What We ARE Extracting for 2022

### Balance Sheet Components (72 instant facts):
- ✅ `IntangibleAssetsOtherThanGoodwill` (multiple values)
- ✅ `PropertyPlantAndEquipmentIncludingRightofuseAssets` (multiple values)
- ✅ `Equity` (multiple values)
- ✅ `OtherProvisions` (multiple values)
- ✅ `DeferredTaxLiabilityAsset` (multiple values)
- ✅ `FinancialAssets`
- ✅ `CashAndCashEquivalents`
- ✅ And 201 total unique concepts

### Income Statement / Cash Flow (514 duration facts):
- ✅ Extracted from 267 duration contexts (2022-01-01 to 2022-12-31)

## Implications

1. **The 2022 data EXISTS** - we're extracting 586 facts
2. **The aggregate "Assets" concept is NOT tagged** for 2022 in this filing
3. **Component concepts ARE present** - we have the building blocks
4. **The missing concepts list may be incorrect** - it's looking for concepts that don't exist for 2022

## Possible Explanations

1. **Comparative Period Structure**: Companies sometimes don't tag aggregate totals in comparative periods
2. **Presentation Differences**: 2022 might use a different presentation structure
3. **Taxonomy Changes**: IFRS taxonomy might have changed between 2022 and 2024
4. **Company-Specific Reporting**: Novo Nordisk might structure 2022 data differently

## Next Steps

1. ✅ **Verify extraction is working** - We're getting 586 facts, which is good
2. ⏳ **Update missing concepts list** - Remove concepts that don't exist for 2022
3. ⏳ **Check if totals can be calculated** - Can we sum components to get "Assets"?
4. ⏳ **Compare with 2023/2024 structure** - Understand why 2022 is different
5. ⏳ **Validate with SEC API** - Once we fix the CIK/endpoint issue

## SEC API Status

- ❌ SEC API returned 404 - Need to verify CIK or API endpoint
- ⏳ Will retry once we have correct endpoint

## Conclusion

The extraction script is working correctly. The "missing" concepts (like "Assets") are not actually missing from our extraction - they're simply not present in the 2022 filing. The missing concepts list needs to be updated to reflect what's actually missing vs. what's just not tagged in 2022.

