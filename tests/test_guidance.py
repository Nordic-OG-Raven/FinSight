"""Tests for the generalized guidance extractor — the regex battery + the LLM verify gate.

All offline: real press-release phrasings as fixtures (NVDA/AMZN/AVGO), plus the false-positive
traps that must NOT be picked up (operating income/expense, gross margin, a CEO-quote segment
figure, a dividend-per-share line). The network LLM leg is not exercised here — without a key
`_llm_extract` returns None, so CI stays deterministic — but its pure `_verify_grounded` gate IS
tested directly, since that gate is the thing standing between a hallucinated number and the ledger.
"""
from src.analysis import guidance as gd

# --- real phrasings (abridged from the actual EX-99.1 exhibits) -------------
NVDA = ("Outlook NVIDIA's outlook for the third quarter of fiscal 2027 is as follows: "
        "• Revenue is expected to be $108.0 billion, plus or minus 2%. "
        "• GAAP and non-GAAP gross margins are expected to be 74.0%, plus or minus 50 basis points. "
        "• GAAP and non-GAAP operating expenses are expected to be approximately $9.2 billion.")

AMZN = ("Third Quarter 2026 Guidance "
        "• Net sales are expected to be between $197.0 billion and $202.0 billion, or to grow "
        "between 9% and 12% compared with third quarter 2025. "
        "• Operating income is expected to be between $22.5 billion and $26.5 billion.")

AVGO = ('"In Q4 the momentum continues, and we expect AI semiconductor revenue to accelerate to '
        '$21.7 billion, up 236% year-over-year," said Hock Tan. '
        "Fourth Quarter Fiscal Year 2026 Business Outlook Based on current business trends and "
        "conditions, the outlook for the fourth quarter of fiscal year 2026 is expected to be as "
        "follows: • Fourth quarter revenue guidance of approximately $34.8 billion; "
        "• Fourth quarter non-GAAP operating income guidance of approximately 66 percent of revenue.")

NO_GUIDANCE = ("The company declared a quarterly dividend of $0.65 per share. "
               "The board authorized an additional $10.0 billion share repurchase.")


def _b(x):  # USD -> billions, for readable asserts
    return None if x is None else round(x / 1e9, 2)


def test_nvda_single_value():
    val, method, src = gd.extract_revenue_guidance(NVDA, use_llm=False)
    assert _b(val) == 108.0 and method == "regex"
    assert "operating expenses" not in src.lower()   # not the $9.2B op-ex line


def test_amzn_range_midpoint():
    val, method, _ = gd.extract_revenue_guidance(AMZN, use_llm=False)
    assert _b(val) == 199.5 and method == "regex"     # (197.0 + 202.0) / 2


def test_avgo_prefers_outlook_over_ceo_quote():
    val, _, src = gd.extract_revenue_guidance(AVGO, use_llm=False)
    assert _b(val) == 34.8                            # the $34.8B guidance, NOT the $21.7B AI quote
    assert "21.7" not in src


def test_no_revenue_guidance_returns_none():
    val, method, _ = gd.extract_revenue_guidance(NO_GUIDANCE, use_llm=False)
    assert val is None and method == "none"


def test_clause_disqualifiers():
    # a margin / operating-income / per-share clause must never yield a revenue figure
    assert gd._clause_revenue("Gross margins are expected to be 74.0%.") is None
    assert gd._clause_revenue("Operating income is expected to be between $22.5 billion and $26.5 billion.") is None
    assert gd._clause_revenue("EPS is expected to be approximately $2.00.") is None
    # a narrative revenue mention without a guidance verb is not guidance
    assert gd._clause_revenue("We expect AI semiconductor revenue to accelerate to $21.7 billion.") is None
    # a real revenue-guidance clause does yield
    assert _b(gd._clause_revenue("Revenue is expected to be $108.0 billion, plus or minus 2%.")) == 108.0


def test_verify_gate_grounds_llm_numbers():
    snip = "Revenue is expected to be $108.0 billion, plus or minus 2%."
    assert gd._verify_grounded(108e9, "Revenue is expected to be $108.0 billion", snip) is True
    # quote not present in the source -> rejected (hallucinated quote)
    assert gd._verify_grounded(150e9, "Revenue is expected to be $150.0 billion", snip) is False
    # quote present but the returned value disagrees with it -> rejected
    assert gd._verify_grounded(200e9, "Revenue is expected to be $108.0 billion", snip) is False


def test_llm_noops_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert gd._llm_extract("Revenue is expected to be $108.0 billion.") == (None, "")
