"""
Curated, execution-verified EXAMPLE queries for the Ask (NL->SQL) layer.

These are *example* (few-shot) queries, NOT verbatim "verified" answers: the few most relevant pairs
are injected into the prompt to teach the warehouse's idioms, and the model still generates fresh SQL
for the actual question. This follows the research consensus (DAIL-SQL and successors):

  - retrieve a SMALL, closest set (~3), never the whole library;
  - match on intent/structure, so domain tokens (company names, years, numbers) are MASKED before
    scoring and matching keys on "margin / quarterly / ranking", not on which company was named;
  - keep the selected set DIVERSE (distinct intents) to avoid the copy-bias trap where the model
    parrots one near-identical example instead of reasoning.

Every pair below has been run against the live warehouse and returns sensible rows. Treat this file
as a tested, version-controlled asset: tests/test_np2sql.py validates and (locally) executes each pair.
"""
from __future__ import annotations

import math
import re

from .schema_metadata import COMPANIES

# (intent, question, sql). intent drives the diversity guard in select_examples().
EXAMPLES: list[dict] = [
    {"intent": "single_metric", "question": "What was Apple's revenue in 2024?",
     "sql": "SELECT value_usd FROM v_facts_consolidated WHERE ticker = 'AAPL' AND normalized_label = 'revenue' AND fiscal_year = 2024 AND period_grain = 'annual'"},
    {"intent": "compare", "question": "Compare net income across all companies in 2024",
     "sql": "SELECT ticker, value_usd FROM v_facts_consolidated WHERE normalized_label = 'net_income' AND fiscal_year = 2024 AND period_grain = 'annual' ORDER BY value_usd DESC"},
    {"intent": "balance_sheet", "question": "What were Microsoft's total assets in 2024?",
     "sql": "SELECT value_usd FROM v_facts_consolidated WHERE ticker = 'MSFT' AND normalized_label = 'total_assets' AND fiscal_year = 2024 AND period_grain = 'instant'"},
    {"intent": "cross_currency", "question": "Compare Novo Nordisk and Apple revenue in USD for 2024",
     "sql": "SELECT ticker, value_usd FROM v_facts_consolidated WHERE ticker IN ('NVO','AAPL') AND normalized_label = 'revenue' AND fiscal_year = 2024 AND period_grain = 'annual' ORDER BY value_usd DESC"},
    {"intent": "ratio", "question": "What was Meta's operating margin in 2023?",
     "sql": "SELECT operating_margin FROM ratios WHERE ticker = 'META' AND fiscal_year = 2023"},
    {"intent": "superlative", "question": "Which company has the highest net margin in the latest year?",
     "sql": "SELECT ticker, net_margin FROM peers ORDER BY net_margin DESC NULLS LAST LIMIT 1"},
    {"intent": "rank", "question": "Rank companies by revenue growth in 2024",
     "sql": "SELECT ticker, revenue_growth FROM ratios WHERE fiscal_year = 2024 ORDER BY revenue_growth DESC NULLS LAST"},
    {"intent": "quarterly", "question": "Show NVIDIA's quarterly revenue over time",
     "sql": "SELECT fiscal_year, fiscal_period, revenue_usd FROM earnings WHERE ticker = 'NVDA' ORDER BY quarter_index"},
    {"intent": "quarterly", "question": "Show Apple's quarterly diluted EPS",
     "sql": "SELECT fiscal_year, fiscal_period, eps_diluted FROM earnings WHERE ticker = 'AAPL' ORDER BY quarter_index"},
    {"intent": "trend", "question": "Show Tesla's annual revenue over time",
     "sql": "SELECT fiscal_year, value_usd FROM v_facts_consolidated WHERE ticker = 'TSLA' AND normalized_label = 'revenue' AND period_grain = 'annual' ORDER BY fiscal_year"},
    {"intent": "ratio_wide", "question": "Show Amazon's margins in 2024",
     "sql": "SELECT gross_margin, operating_margin, net_margin FROM ratios WHERE ticker = 'AMZN' AND fiscal_year = 2024"},
    {"intent": "cashflow", "question": "What was Alphabet's operating cash flow in 2024?",
     "sql": "SELECT value_usd FROM v_facts_consolidated WHERE ticker = 'GOOGL' AND normalized_label = 'net_cash_from_operating_activities' AND fiscal_year = 2024 AND period_grain = 'annual'"},
    {"intent": "ratio", "question": "What was Microsoft's free cash flow in 2024?",
     "sql": "SELECT free_cash_flow_usd FROM ratios WHERE ticker = 'MSFT' AND fiscal_year = 2024"},
    {"intent": "rank", "question": "Rank companies by return on equity in the latest year",
     "sql": "SELECT ticker, return_on_equity FROM peers ORDER BY return_on_equity DESC NULLS LAST"},
    {"intent": "growth", "question": "Which company grew revenue fastest in 2024?",
     "sql": "SELECT ticker, revenue_growth FROM ratios WHERE fiscal_year = 2024 ORDER BY revenue_growth DESC NULLS LAST LIMIT 1"},
    {"intent": "growth", "question": "How much did NVIDIA's revenue grow in 2024?",
     "sql": "SELECT revenue_growth FROM ratios WHERE ticker = 'NVDA' AND fiscal_year = 2024"},
]


# --- intent-masked lexical retrieval (dependency-free; right-sized for a ~16-item library) ---

_STOP = {
    "the", "a", "an", "of", "in", "for", "me", "show", "what", "was", "is", "were", "are", "how",
    "much", "many", "did", "give", "tell", "to", "and", "or", "on", "over", "by", "with", "do",
    "does", "their", "its", "that", "us", "usd", "i", "we", "it", "at", "as", "this", "these",
    "those", "per", "each", "all", "from", "have", "has", "between", "about", "which", "who",
}

# Domain tokens to MASK out before matching, so similarity keys on intent, not on the entity named.
_COMPANY_TERMS = set()
for _t, _info in COMPANIES.items():
    _COMPANY_TERMS.add(_t.lower())
    _COMPANY_TERMS.add(_info["name"].lower())
    _COMPANY_TERMS.update(a.lower() for a in _info["aliases"])
_COMPANY_TERMS_SORTED = sorted(_COMPANY_TERMS, key=len, reverse=True)  # multiword first


def _mask(text: str) -> str:
    t = " " + text.lower() + " "
    for term in _COMPANY_TERMS_SORTED:
        t = re.sub(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", " ", t)
    t = re.sub(r"\b\d+(\.\d+)?\b", " ", t)   # years and other numbers
    return t


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", _mask(text)) if len(w) > 1 and w not in _STOP}


_EX_TOKENS = [_tokens(e["question"]) for e in EXAMPLES]
_N = len(EXAMPLES)
_DF: dict[str, int] = {}
for _toks in _EX_TOKENS:
    for _w in _toks:
        _DF[_w] = _DF.get(_w, 0) + 1
# IDF so distinctive words ("margin", "quarterly", "growth") outweigh common ones ("revenue").
_IDF = {w: math.log((_N + 1) / (df + 0.5)) for w, df in _DF.items()}


def select_examples(question: str, k: int = 3) -> list[dict]:
    """Return up to k example pairs most relevant to `question`, matched on masked intent tokens
    and kept diverse by intent (never k near-duplicates)."""
    q_tokens = _tokens(question)
    scored = []
    for i, ex_tokens in enumerate(_EX_TOKENS):
        shared = q_tokens & ex_tokens
        score = sum(_IDF.get(w, 0.0) for w in shared)
        scored.append((score, i))
    scored.sort(key=lambda si: (-si[0], si[1]))

    picked: list[int] = []
    seen_intent: set[str] = set()
    for score, i in scored:                      # first pass: positive matches, one per intent
        if score <= 0:
            break
        if EXAMPLES[i]["intent"] in seen_intent:
            continue
        picked.append(i)
        seen_intent.add(EXAMPLES[i]["intent"])
        if len(picked) >= k:
            break
    if len(picked) < k:                          # backfill (sparse/no overlap) with next best
        for score, i in scored:
            if i not in picked:
                picked.append(i)
                if len(picked) >= k:
                    break
    return [EXAMPLES[i] for i in picked]


def format_examples(examples: list[dict]) -> str:
    """Render selected examples as a prompt block (empty string if none)."""
    if not examples:
        return ""
    lines = ["## RELEVANT EXAMPLE QUERIES (patterns to learn from; write fresh SQL for the actual question)"]
    for i, e in enumerate(examples, 1):
        lines.append(f"{i}. Q: {e['question']}")
        lines.append(f"   SQL: {e['sql']}")
    return "\n".join(lines)
