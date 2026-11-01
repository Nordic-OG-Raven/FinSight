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
import os
import re

try:
    from openai import OpenAI  # OpenAI-compatible SDK; also talks to Groq's endpoint
except ImportError:
    OpenAI = None

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


# Canonicalize intent-signalling words so phrasing variants match (this is what embeddings would
# give us for free; a small curated map covers it for a library this size). Applied to BOTH the
# examples and the question. NOTE: the bare word "year" is deliberately NOT mapped, because
# "latest year" means most-recent, not a time series; temporal *phrases* are handled separately.
_SYNONYMS = {
    "quarter": "quarterly", "quarters": "quarterly", "quarterly": "quarterly",
    "grow": "growth", "grew": "growth", "grown": "growth", "growing": "growth", "growth": "growth",
    "increase": "growth", "increased": "growth", "increasing": "growth", "rise": "growth",
    "rose": "growth", "fastest": "growth", "expanded": "growth", "expansion": "growth",
    "margin": "margin", "margins": "margin", "profitability": "margin",
    "compare": "compare", "compared": "compare", "comparison": "compare", "versus": "compare", "vs": "compare",
    "highest": "top", "lowest": "top", "best": "top", "worst": "top", "top": "top", "most": "top",
    "least": "top", "largest": "top", "smallest": "top", "leading": "top",
    "rank": "rank", "ranked": "rank", "ranking": "rank",
    "revenue": "revenue", "sales": "revenue", "turnover": "revenue",
    "cash": "cashflow", "fcf": "cashflow",
}

# Temporal time-series PHRASES -> one "timeseries" token, so "over the years", "over time",
# "revenue trend", "revenue history" all match the trend example, while "latest year" / "in 2024"
# (most-recent, single-period) do NOT.
_TIMESERIES_PATTERNS = [re.compile(p) for p in (
    r"(over|through|across|during) the (last |past |previous )?(years?|time|period|decade)",
    r"over time", r"year[ -]?over[ -]?year", r"each year", r"by year",
    r"\btrends?\b", r"\bhistory\b", r"\bhistorical(ly)?\b",
)]


def _tokens(text: str) -> set[str]:
    t = re.sub(r"\s+", " ", _mask(text))
    for pat in _TIMESERIES_PATTERNS:
        t = pat.sub(" timeseries ", t)
    return {_SYNONYMS.get(w, w) for w in re.findall(r"[a-z]+", t)
            if len(w) > 1 and w not in _STOP}


_EX_TOKENS = [_tokens(e["question"]) for e in EXAMPLES]
_N = len(EXAMPLES)
_DF: dict[str, int] = {}
for _toks in _EX_TOKENS:
    for _w in _toks:
        _DF[_w] = _DF.get(_w, 0) + 1
# IDF so distinctive words ("margin", "quarterly", "growth") outweigh common ones ("revenue").
_IDF = {w: math.log((_N + 1) / (df + 0.5)) for w, df in _DF.items()}


def _score_lexical(question: str) -> list[tuple[float, int]]:
    """IDF-weighted masked-token overlap (the dependency-free fallback)."""
    q_tokens = _tokens(question)
    return [(sum(_IDF.get(w, 0.0) for w in (q_tokens & _EX_TOKENS[i])), i) for i in range(_N)]


# --- embedding retrieval (Groq nomic-embed-text, falling back to lexical if unavailable) ---

_BACKEND_CACHE = "unset"      # lazily resolved to (client, model) or None
_EXAMPLE_VECTORS = None       # cached embeddings of the example questions


def _embed_backend():
    """Embeddings are OPT-IN: set NP2SQL_EMBED_MODEL (plus a usable key) to turn them on; otherwise
    retrieval uses the lexical+synonym matcher. Keeping them off by default means no failed embedding
    call on every request while no embedding-capable provider is configured.

    To activate later with one env var set (and a key): e.g. OpenAI -> NP2SQL_EMBED_MODEL=
    text-embedding-3-small + OPENAI_API_KEY; Groq (once embeddings are enabled on the account) ->
    NP2SQL_EMBED_MODEL=<their embed model> + NP2SQL_EMBED_BASE_URL=https://api.groq.com/openai/v1
    + GROQ_EMBEDDINGS_API_KEY.
    """
    model = os.getenv("NP2SQL_EMBED_MODEL")
    if OpenAI is None or not model:
        return None
    key = (os.getenv("NP2SQL_EMBED_API_KEY") or os.getenv("OPENAI_API_KEY")
           or os.getenv("GROQ_EMBEDDINGS_API_KEY") or os.getenv("GROQ_API_KEY"))
    if not key:
        return None
    kwargs = {"api_key": key, "timeout": 8}
    base_url = os.getenv("NP2SQL_EMBED_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    return (OpenAI(**kwargs), model)


def _get_backend():
    global _BACKEND_CACHE
    if _BACKEND_CACHE == "unset":
        _BACKEND_CACHE = _embed_backend()
    return _BACKEND_CACHE


def _prefix(model: str, text: str, is_query: bool) -> str:
    # nomic-embed-text-v1.5 is trained with task prefixes; apply them for best retrieval quality.
    if model.startswith("nomic"):
        return ("search_query: " if is_query else "search_document: ") + text
    return text


def _embed_texts(client, model: str, texts: list[str]) -> list[list[float]]:
    resp = client.embeddings.create(model=model, input=texts)
    return [d.embedding for d in resp.data]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _score_embedding(question: str):
    """Cosine similarity of masked-question embeddings, or None if no backend / the call fails."""
    backend = _get_backend()
    if backend is None:
        return None
    client, model = backend
    global _EXAMPLE_VECTORS
    try:
        if _EXAMPLE_VECTORS is None:
            docs = [_prefix(model, _mask(e["question"]), is_query=False) for e in EXAMPLES]
            _EXAMPLE_VECTORS = _embed_texts(client, model, docs)
        qv = _embed_texts(client, model, [_prefix(model, _mask(question), is_query=True)])[0]
        return [(_cosine(qv, _EXAMPLE_VECTORS[i]), i) for i in range(_N)]
    except Exception:
        return None  # any failure -> fall back to lexical, never break the feature


def _pick_diverse(scored: list[tuple[float, int]], k: int) -> list[dict]:
    """Take the highest-scored examples, one per intent first (so never k near-duplicates)."""
    ranked = sorted(scored, key=lambda si: (-si[0], si[1]))
    picked: list[int] = []
    seen_intent: set[str] = set()
    for _score, i in ranked:
        if EXAMPLES[i]["intent"] in seen_intent:
            continue
        picked.append(i)
        seen_intent.add(EXAMPLES[i]["intent"])
        if len(picked) >= k:
            break
    if len(picked) < k:                          # fill remaining slots with next best
        for _score, i in ranked:
            if i not in picked:
                picked.append(i)
                if len(picked) >= k:
                    break
    return [EXAMPLES[i] for i in picked]


def select_examples(question: str, k: int = 3) -> list[dict]:
    """Return up to k example pairs most relevant to `question`, kept diverse by intent.

    Scores by embedding similarity (Groq nomic-embed-text, which handles synonyms like
    "over the years" ~ "over time"); if no embedding backend is configured or the call fails,
    falls back to IDF-weighted masked-token overlap. Either way, domain tokens (company names,
    years, numbers) are masked so matching keys on intent, not on which company was named.
    """
    scored = _score_embedding(question)
    if scored is None:
        scored = _score_lexical(question)
    return _pick_diverse(scored, k)


def format_examples(examples: list[dict]) -> str:
    """Render selected examples as a prompt block (empty string if none)."""
    if not examples:
        return ""
    lines = ["## RELEVANT EXAMPLE QUERIES (patterns to learn from; write fresh SQL for the actual question)"]
    for i, e in enumerate(examples, 1):
        lines.append(f"{i}. Q: {e['question']}")
        lines.append(f"   SQL: {e['sql']}")
    return "\n".join(lines)
