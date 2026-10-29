"""Company forward revenue guidance, extracted point-in-time from earnings-release 8-Ks.

The single most predictive input for a next-quarter revenue forecast is the company's own
guidance — which is NOT in the XBRL; it lives in the earnings press release (an EX-99.1 exhibit on
the quarterly 8-K). Different companies phrase it differently:

    NVDA : "Revenue is expected to be $108.0 billion, plus or minus 2%."
    AMZN : "Net sales are expected to be between $197.0 billion and $202.0 billion ..."   (range)
    AVGO : "Fourth quarter revenue guidance of approximately $34.8 billion"

So extraction is a **hybrid**:
  1. Regex battery — locate the Outlook/Guidance section, split into clauses, and accept a clause
     only if it has a revenue cue AND a guidance verb AND no disqualifier (operating income/expense,
     margin, per-share, full-year, dividend, ...). Ranges collapse to their midpoint. This handles
     the common phrasings for free, deterministically, offline.
  2. LLM fallback — only when regex finds nothing, and only on the tiny located snippet (a few
     hundred tokens, not the whole filing), with structured JSON output and a **verify gate**: the
     returned number must be reconstructable from a quote that appears verbatim in the source, else
     it is discarded. Key-gated: silently skipped when ANTHROPIC_API_KEY is absent, so CI stays
     deterministic and nothing untested can leak a number in.

Leakage-safe: guidance given in the 8-K filed at quarter Q-1's earnings (filing_date D) is for
quarter Q, and D precedes Q's own report. The guidance-beat model forecasts
`next_guidance * (1 + median historical beat)` — companies guide conservatively and beat by a
fairly stable margin, and the beat rate is computed only from quarters already reported.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

import edgar

# ---------------------------------------------------------------------------
# phrasing battery
# ---------------------------------------------------------------------------
_REV_CUE = re.compile(r"\b(net sales|net revenues?|total revenues?|revenues?)\b", re.I)
# a clause must be GOVERNED by a guidance verb/noun — this is what separates real guidance
# ("revenue is expected to be", "revenue guidance of") from narrative mentions of revenue
# (e.g. a CEO quote "... AI revenue to accelerate to $21.7 billion").
_GOV = re.compile(r"(expected to be|guidance|outlook|projected|we are guiding|to range)", re.I)
# lines about something OTHER than total revenue, or about the wrong period
_DISQUAL = re.compile(
    r"(operating expense|operating income|operating margin|gross margin|gross profit|"
    r"\bmargins?\b|tax rate|per share|\bdiluted\b|dividend|free cash flow|cash flow|"
    r"capital expenditure|capex|net interest|interest income|\beps\b|earnings per|"
    r"full[- ]year|full fiscal year|stock[- ]based|share count|segment)", re.I)

_UNIT = {"billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mn": 1e6, "m": 1e6}
_NUM = r"\$?\s*([0-9][0-9,]*\.?[0-9]*)"
_U = r"(billion|million|bn|mn)"
# ranges first (most specific) — "between X and Y", "range of X to Y", "X to Y", "X - Y"
_RANGE_PATTERNS = [
    re.compile(rf"between\s+{_NUM}\s*{_U}?\s+and\s+{_NUM}\s*{_U}", re.I),
    re.compile(rf"range of\s+{_NUM}\s*{_U}?\s+(?:to|and)\s+{_NUM}\s*{_U}", re.I),
    re.compile(rf"{_NUM}\s*{_U}?\s*(?:to|[-–—])\s*{_NUM}\s*{_U}", re.I),
]
_SINGLE = re.compile(rf"{_NUM}\s*{_U}", re.I)

# section headers that introduce forward guidance; we scope extraction to each, in document order
_SECTION = re.compile(
    r"(business outlook|financial outlook|\boutlook\b|guidance|outlook for the)", re.I)

_PR_ATTACH_RE = re.compile(r"(pr\.htm|press|commentary|exhibit|ex-?99)", re.I)

_LLM_MODEL = os.getenv("GUIDANCE_LLM_MODEL", "claude-haiku-4-5-20251001")


@dataclass
class Guidance:
    given_date: date          # 8-K filing date (when guidance was issued)
    guided_revenue: float     # USD, for the NEXT quarter
    method: str = "regex"     # 'regex' | 'llm' — how the number was extracted (auditability)
    source: str = ""          # the clause/quote the number came from


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def _clause_revenue(clause: str) -> float | None:
    """USD revenue figure from one outlook clause, or None. A range collapses to its midpoint.

    Accepts only clauses that (a) mention revenue/net sales, (b) are governed by a guidance verb,
    and (c) contain no disqualifier (margin, operating income/expense, per-share, full-year, ...).
    """
    if not _REV_CUE.search(clause) or _DISQUAL.search(clause) or not _GOV.search(clause):
        return None
    for pat in _RANGE_PATTERNS:
        m = pat.search(clause)
        if m:
            lo = float(m.group(1).replace(",", ""))
            hi = float(m.group(3).replace(",", ""))
            unit = _UNIT[(m.group(4) or m.group(2) or "billion").lower()]
            return (lo + hi) / 2 * unit
    m = _SINGLE.search(clause)
    if m:
        return float(m.group(1).replace(",", "")) * _UNIT[m.group(2).lower()]
    return None


def _split_clauses(window: str) -> list[str]:
    return [c.strip() for c in re.split(r"[•\n]|(?<=[.;])\s+", window) if len(c.strip()) >= 10]


def extract_revenue_guidance(txt: str, use_llm: bool = True) -> tuple[float | None, str, str]:
    """(value_usd, method, source_clause) from a press-release text. Regex first; LLM only on the
    located outlook snippet when regex misses (and only if a key is present)."""
    txt = txt.replace("\xa0", " ")
    # candidate windows: each outlook/guidance header → the ~1.6k chars after it, in doc order;
    # whole text last as a final fallback.
    windows = [txt[m.start(): m.start() + 1600] for m in _SECTION.finditer(txt)]
    windows.append(txt)
    first_section = windows[0] if len(windows) > 1 else ""
    for win in windows:
        for cl in _split_clauses(win):
            val = _clause_revenue(cl)
            if val is not None:
                return val, "regex", _norm(cl)[:300]
    # regex found nothing — fall back to the LLM on just the located snippet
    if use_llm and first_section:
        val, quote = _llm_extract(first_section)
        if val is not None:
            return val, "llm", _norm(quote)[:300]
    return None, "none", ""


# ---------------------------------------------------------------------------
# LLM fallback — tiny snippet, structured output, verify-the-number-is-verbatim
# ---------------------------------------------------------------------------
def _verify_grounded(value: float, quote: str, snippet: str) -> bool:
    """A returned number is trusted only if (a) its quote appears verbatim in the source and
    (b) a dollar amount parsed from that quote matches the returned value (within 1%)."""
    if value is None or not quote:
        return False
    if _norm(quote).lower() not in _norm(snippet).lower():
        return False
    reconstructed = _clause_revenue(quote)
    if reconstructed is None:               # quote itself must contain the parseable amount
        m = _SINGLE.search(quote)
        reconstructed = (float(m.group(1).replace(",", "")) * _UNIT[m.group(2).lower()]) if m else None
    return reconstructed is not None and abs(reconstructed - value) <= 0.01 * abs(value)


def _llm_extract(snippet: str) -> tuple[float | None, str]:
    """Extract next-quarter total revenue guidance from a short snippet via the LLM, grounded by a
    verify gate. Returns (None, '') on missing key, import/API error, or a failed verify."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None, ""
    try:
        import anthropic
    except ImportError:
        return None, ""
    try:
        # the shared key is org-scoped, so an org-level key needs the workspace header
        ws = os.getenv("ANTHROPIC_WORKSPACE_ID")
        headers = {"anthropic-workspace-id": ws} if ws else {}
        client = anthropic.Anthropic(default_headers=headers)
        resp = client.messages.create(
            model=_LLM_MODEL,
            max_tokens=300,
            system=(
                "Extract a company's forward NEXT-QUARTER total revenue (or net sales) guidance from "
                "an earnings press-release excerpt. Return ONLY minified JSON: "
                '{"revenue_usd": <number|null>, "quote": "<the exact sentence from the text, verbatim>"}. '
                "Use TOTAL company revenue/net-sales guidance only — never a segment, margin, operating "
                "income, EPS, or full-year figure. If a range is given, use its midpoint but quote the "
                "full range sentence. If the excerpt does not state next-quarter revenue guidance, "
                'return {"revenue_usd": null, "quote": ""}.'
            ),
            messages=[{"role": "user", "content": snippet[:6000]}],
        )
        raw = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None, ""
        data = json.loads(m.group(0))
        value, quote = data.get("revenue_usd"), data.get("quote", "")
        if value is None:
            return None, ""
        value = float(value)
        return (value, quote) if _verify_grounded(value, quote, snippet) else (None, "")
    except Exception:  # noqa: BLE001  — any API/parse failure degrades to "no guidance"
        return None, ""


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
@lru_cache(maxsize=256)
def guidance_history(ticker: str, limit: int = 20, use_llm: bool = True,
                     identity: str = "Jonas Haahr itsxidey@gmail.com") -> list[Guidance]:
    """Forward revenue guidance from recent earnings 8-Ks, oldest-first. One per earnings release.
    Cached: it is fetched from EDGAR repeatedly (routing, the guidance-beat model, scoring, backfill)
    for the same ticker within a run; filings are static, so caching returns the identical result
    without re-hitting the network. Read-only result."""
    edgar.set_identity(identity)
    company = edgar.Company(ticker)
    out: list[Guidance] = []
    seen_dates: set = set()
    for filing in list(company.get_filings(form="8-K").latest(limit)):
        fdate = getattr(filing, "filing_date", None)
        if fdate in seen_dates:
            continue
        value, method, source = _parse_filing_guidance(filing, use_llm=use_llm)
        if value is not None:
            try:
                d = date.fromisoformat(str(fdate)[:10])
            except Exception:  # noqa: BLE001
                continue
            out.append(Guidance(d, value, method, source))
            seen_dates.add(fdate)
    out.sort(key=lambda g: g.given_date)
    return out


def _parse_filing_guidance(filing, use_llm: bool = True) -> tuple[float | None, str, str]:
    """Find the press-release exhibit on an 8-K and extract forward revenue guidance from it."""
    try:
        attachments = filing.attachments
    except Exception:  # noqa: BLE001
        return None, "none", ""
    for a in attachments:
        doc = str(getattr(a, "document", "") or "")
        if not _PR_ATTACH_RE.search(doc):
            continue
        try:
            txt = a.text()
        except Exception:  # noqa: BLE001
            continue
        if not txt or "revenue" not in txt.lower() and "net sales" not in txt.lower():
            continue
        value, method, source = extract_revenue_guidance(txt, use_llm=use_llm)
        if value is not None:
            return value, method, source
    return None, "none", ""


def guidance_asof(hist: list[Guidance], as_of: date) -> Guidance | None:
    """The most recent guidance issued on/before `as_of` (point-in-time)."""
    prior = [g for g in hist if g.given_date <= as_of]
    return prior[-1] if prior else None
