# Status Report for Grok - Latest Update

## What I Did (Based on Your Feedback)

1. **Fixed concept extraction**: Changed to use `fact.qname.localName` (since `fact.concept` is None for ModelInlineFact)
2. **Fixed value extraction**: Using `fact.value` instead of `fact.xValue`  
3. **Added period checking**: Using both datetime objects (when available) and XML parsing fallback
4. **Added taxonomy loading attempt**: Tried to load IFRS taxonomy (but ModelManager doesn't have `loadTaxonomy` method - Arelle auto-resolves from instance document)

## Current Status

- **Extraction working**: 597 facts extracted for 2022 (46 instant + 267 duration contexts)
- **Assets still NOT found**: Even using `fact.qname.localName == 'Assets'`, we only find 2 Assets facts (2023 and 2024), not 2022
- **SEC API confirms**: Assets for 2022 exists (value: 241257000000 DKK) in the 2024 filing (filed 2024-01-31)
- **HTML file search**: Value `241257000000` is NOT in the HTML file when searched directly
- **nonFraction search**: No nonFraction elements with Assets concept found in HTML using regex
- **Found separate XBRL files**: The HTML references separate linkbase files (nvo-20241231.xsd, nvo-20241231_pre.xml, etc.)

## The Problem

1. **Arelle finds 2 Assets facts** (context c-9 for 2023, context c-12 for 2024) but NOT 2022
2. **SEC API confirms Assets for 2022 exists** in the 2024 filing
3. **HTML file doesn't contain the value** when searched directly
4. **This suggests**: Either:
   - The fact is in a different format we're not parsing
   - The fact is in a different file (separate instance document?)
   - Arelle's inline discovery isn't finding it
   - The fact exists but with a different context ID that we're not identifying as 2022

## What We've Tried

- ✅ Using `fact.qname.localName` for concept extraction
- ✅ Using `fact.value` for values
- ✅ Calling `inlineXbrlDiscover()` on htmlElement
- ✅ Using `period.stringValue` for period filtering (Grok's latest recommendation)
- ✅ Using `model_xbrl.factsByQname` (Assets QName not in qnameConcepts)
- ✅ Searching for value `241257000000` in all facts (not found)
- ✅ Searching HTML file directly for value (not found)
- ✅ Searching HTML for nonFraction elements with Assets (not found)
- ✅ Verifying we're finding 46 instant + 267 duration contexts for 2022

## Key Finding

- **We found 313 contexts for 2022** using XML parsing (parsing `<xbrli:instant>` and `<xbrli:endDate>` children)
- **We're extracting 597 facts** from those contexts
- **But Assets is NOT among them** - Arelle only finds Assets for 2023 and 2024

## Critical Finding

- **Value `241257000000` is NOT in any fact** in the 2024 filing (searched all 3159 facts)
- **Assets for 2022 is NOT found** even using `period.stringValue` and `fact.qname.localName`
- **SEC API confirms it exists** in the 2024 filing (filed 2024-01-31)
- **Only 2 Assets facts found**: 2023 (314486000000) and 2024 (465795000000)

## Questions for Grok

1. **Why isn't Arelle finding Assets for 2022** when SEC API confirms it exists in the 2024 filing?
2. **Could Assets for 2022 be in the 2023 filing** instead of the 2024 filing? (SEC API aggregates across filings)
3. **Is the value stored differently** (e.g., in millions, with different formatting)?
4. **Does inline XBRL discovery need different settings** or need to be called differently?
5. **Should we be loading the separate linkbase files** (nvo-20241231_pre.xml, etc.) to get all facts?
6. **Could the fact be in a different document** (separate instance document, not in the HTML)?

## Code Location

All changes are in: `/Users/jonas/FinSight/scripts/verify_xbrl_2022_data.py`
