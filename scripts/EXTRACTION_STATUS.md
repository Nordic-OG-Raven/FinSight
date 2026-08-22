# 2022 Data Extraction Status

## Current Status

**Script**: `scripts/verify_xbrl_2022_data.py`

**Results**:
- ✅ Found 46 instant contexts (2022-12-31) for balance sheet
- ✅ Found 267 duration contexts (2022-01-01 to 2022-12-31) for income statement/cash flow
- ✅ Extracted 586 total facts (up from 72)
- ⚠️  Still missing: All 168 concepts from missing list (0 exact matches)

## Issues Identified

1. **"Assets" Concept Not Present for 2022**: 
   - ✅ "Assets" exists for 2023 and 2024 in the filing
   - ❌ "Assets" does NOT exist for 2022 in the filing
   - ✅ Component concepts (IntangibleAssets, PropertyPlantAndEquipment, etc.) ARE present for 2022
   - **Conclusion**: The missing concepts list is looking for concepts that don't exist for 2022, not concepts we're failing to extract

2. **Concept Name Mismatch**: The missing concepts list uses different names than what's actually in the XBRL
   - Example: Missing list has "Assets", but this concept simply doesn't exist for 2022
   - Fuzzy matching found 55 potential matches, but many are false positives

3. **Nil Facts**: Now handling nil facts as "0" per Grok's recommendation ✅

4. **Dimension Extraction**: Using iteration-based approach (XPath doesn't work well with html.parse)

## Next Steps

### Immediate (Current Script)

1. ✅ Fixed nil handling (treat nil as "0")
2. ⏳ Add SEC API validation to compare results
3. ⏳ Investigate why exact concept names don't match
4. ⏳ Check if concepts are dimensioned differently

### Short-term (Verify Script)

1. Integrate SEC API validator into verify script
2. Compare extracted concepts with SEC API concepts
3. Identify which concepts are actually missing vs. just named differently
4. Fix parser to extract all concepts correctly

### Long-term (Main Pipeline)

1. Apply fixes to `src/parsing/parse_xbrl.py`
2. Test with full pipeline
3. Consider optional SEC API validation step (see `docs/SEC_API_INTEGRATION_PLAN.md`)

## Files Created

1. **`scripts/verify_xbrl_2022_data.py`**: Standalone extraction script with Grok's fixes
2. **`scripts/sec_api_validator.py`**: SEC API validation tool (standalone)
3. **`docs/SEC_API_INTEGRATION_PLAN.md`**: Plan for integrating SEC API validation
4. **`scripts/EXTRACTION_STATUS.md`**: This file

## Usage

### Extract 2022 Data
```bash
python scripts/verify_xbrl_2022_data.py
```

### Validate with SEC API
```bash
python scripts/sec_api_validator.py NVO 2022 data/raw/NVO_2024_20F__2022_complete.csv
```

## Notes

- The verify script is a **debugging tool**, not part of the main pipeline
- Once we get it working correctly, we'll apply the fixes to the main parser
- SEC API is for **validation only**, not as a data source

