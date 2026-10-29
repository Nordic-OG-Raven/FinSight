"""Company forward revenue guidance, extracted point-in-time from earnings-release 8-Ks.

The single most predictive input for a next-quarter revenue forecast is the company's own
guidance — which is NOT in the XBRL; it's in the earnings press release (an EX-99.1 exhibit on the
quarterly 8-K). NVDA, for example, states "Revenue is expected to be $X billion, plus or minus 2%".

This is leakage-safe: guidance given in the 8-K filed at quarter Q-1's earnings (filing_date D)
is for quarter Q, and D is before Q's own report. The guidance-beat model forecasts
`next_guidance * (1 + median historical beat)` — companies guide conservatively and beat by a
fairly stable margin, and the beat rate is computed only from quarters already reported.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import edgar

_GUIDANCE_RE = re.compile(r"[Rr]evenue\s+is\s+expected\s+to\s+be\s+\$?\s*([\d][\d.,]*)\s*billion", re.I)
_PR_ATTACH_RE = re.compile(r"(pr\.htm|press|commentary|exhibit|ex-?99)", re.I)


@dataclass
class Guidance:
    given_date: date          # 8-K filing date (when guidance was issued)
    guided_revenue: float     # USD, for the NEXT quarter


def guidance_history(ticker: str, limit: int = 20,
                     identity: str = "Jonas Haahr itsxidey@gmail.com") -> list[Guidance]:
    """Forward revenue guidance from recent earnings 8-Ks, oldest-first. One per earnings release."""
    edgar.set_identity(identity)
    company = edgar.Company(ticker)
    out: list[Guidance] = []
    seen_dates: set = set()
    for filing in list(company.get_filings(form="8-K").latest(limit)):
        fdate = getattr(filing, "filing_date", None)
        if fdate in seen_dates:
            continue
        guided = _parse_filing_guidance(filing)
        if guided is not None:
            try:
                d = date.fromisoformat(str(fdate)[:10])
            except Exception:  # noqa: BLE001
                continue
            out.append(Guidance(d, guided))
            seen_dates.add(fdate)
    out.sort(key=lambda g: g.given_date)
    return out


def _parse_filing_guidance(filing) -> float | None:
    """Find the press-release exhibit on an 8-K and parse the forward revenue-guidance number."""
    try:
        attachments = filing.attachments
    except Exception:  # noqa: BLE001
        return None
    for a in attachments:
        doc = str(getattr(a, "document", "") or "")
        if not _PR_ATTACH_RE.search(doc):
            continue
        try:
            txt = a.text()
        except Exception:  # noqa: BLE001
            continue
        m = _GUIDANCE_RE.search(txt or "")
        if m:
            try:
                return float(m.group(1).replace(",", "")) * 1e9
            except ValueError:
                continue
    return None


def guidance_asof(hist: list[Guidance], as_of: date) -> Guidance | None:
    """The most recent guidance issued on/before `as_of` (point-in-time)."""
    prior = [g for g in hist if g.given_date <= as_of]
    return prior[-1] if prior else None
