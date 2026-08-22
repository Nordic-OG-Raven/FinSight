# XBRL 2022 Data Extraction Status

## Current State

**Parser Status**: ✅ Updated to use multiple inline XBRL discovery methods
- Calls `discoverInlineXbrlDocumentSet()` if available
- Calls `inlineXbrlDiscover(htmlElement)` with document's HTML element
- Forces context resolution by iterating through all contexts

**Extraction Results**: 
- 2022 instant facts: **11 facts** (3 unique concepts)
- 2024 instant facts: **388 facts** (101 unique concepts)
- Ratio: 2.8% of 2024 facts

## Attempted Fixes

1. ✅ **Plugin Loading via PluginManager**: Attempted but `PluginManager.init()` returns None
2. ✅ **Plugin Loading via pluginClassMethods**: Requires `className` argument, not straightforward
3. ✅ **discoverInlineXbrlDocumentSet()**: Method not available on model_xbrl
4. ✅ **inlineXbrlDiscover(htmlElement)**: Successfully called but doesn't increase fact count

## Possible Explanations

1. **XBRL File Structure**: The 2024 filing may only tag 11 facts for 2022 (equity, cash, provisions)
2. **Different Namespaces**: 2022 facts may use IFRS concept names we're not matching
3. **Dimension Facts**: 2022 facts may be in dimensioned contexts that require different extraction
4. **HTML vs XBRL**: Facts may be in HTML tables but not properly XBRL-tagged

## Next Steps

1. **Check IFRS Concept Names**: Expand verification to check for `ifrs-full:*` and `nvo:*` namespaced concepts
2. **Check Dimension Facts**: Verify if 2022 facts are in dimensioned contexts (e.g., `ComponentsOfEquityAxis`)
3. **Direct HTML Parsing**: If XBRL tagging is incomplete, may need to extract from HTML tables as fallback
4. **Contact SEC/Novo Nordisk**: If filing is non-compliant (HTML shows data but XBRL doesn't tag it)

## Files Updated

- `/Users/jonas/FinSight/src/parsing/parse_xbrl.py`: Added multiple inline XBRL discovery methods
- `/Users/jonas/FinSight/scripts/verify_xbrl_2022_data.py`: Enhanced verification with plugin loading attempts

