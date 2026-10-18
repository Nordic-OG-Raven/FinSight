"""
EdgarTools extraction adapter — Phase 1 of the re-architecture (see docs/REARCHITECTURE.md).

This is the SEAM: it turns edgartools output into FinSight's own `ExtractionResult`, so the
warehouse/loader never depends on edgartools internals (pin the version, swap later if ever
needed). The skeleton + dimensional detail both come from the filing's XBRL, which edgartools
parses cleanly for every filer — including the Nov-fiscal-year, bank, and IFRS-20F cases that
defeated the custom Arelle pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Protocol

import edgar


# ---- FinSight's own fact model (independent of edgartools) -------------------

@dataclass
class Fact:
    concept: str                      # raw tag, e.g. "us-gaap:Revenues"
    label: Optional[str]
    value_numeric: Optional[float]
    value_text: Optional[str]
    unit: Optional[str]               # USD, shares, kr, USD/share
    period_start: Optional[date]
    period_end: Optional[date]
    instant_date: Optional[date]
    period_type: Optional[str]        # duration | instant
    fiscal_year: Optional[int]
    fiscal_period: Optional[str]      # FY, Q1…
    statement_type: Optional[str]     # income_statement | balance_sheet | cash_flow | ...
    dimensions: Optional[dict]        # {axis: member} — None when undimensioned
    is_dimensioned: bool
    standard_label: Optional[str] = None  # edgartools cross-company/standard concept, e.g. "Revenue"


@dataclass
class CompanyMeta:
    cik: str
    ticker: str
    name: str
    currency: Optional[str]
    is_financial_institution: bool


@dataclass
class FilingMeta:
    accession: str
    form: str
    filing_date: Optional[date]
    period_end: Optional[date]


@dataclass
class ExtractionResult:
    company: CompanyMeta
    filing: FilingMeta
    facts: list[Fact] = field(default_factory=list)
    source: str = "edgartools"


class FactExtractor(Protocol):
    def extract(self, ticker: str, filing_type: str = "10-K") -> ExtractionResult: ...


# ---- edgartools implementation ----------------------------------------------

_DIM_PREFIX = "dim_"


def _as_date(v):
    if v is None:
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except Exception:
        return None


def _statement_type(raw) -> Optional[str]:
    """Map edgartools statement_type to FinSight's vocabulary."""
    if not raw:
        return None
    s = str(raw).lower()
    if "income" in s and "comprehensive" not in s:
        return "income_statement"
    if "comprehensive" in s:
        return "comprehensive_income"
    if "balance" in s or "financial_position" in s:
        return "balance_sheet"
    if "cash" in s:
        return "cash_flow"
    if "equity" in s or "stockholders" in s:
        return "equity_statement"
    return "other"


def _standard_concept_map(xb) -> dict:
    """Build {raw concept -> edgartools standard concept} from the filing's rendered statements.

    edgartools maps company-specific us-gaap/ifrs concepts onto a common standardized vocabulary
    (e.g. us-gaap:AccountsReceivableNetCurrent -> TradeReceivables, ifrs-full:Goodwill -> Goodwill)
    — this is what lets different filers' (and different accounting standards') statements line up
    for cross-company comparison. Covers ~50-70% of statement lines; niche / company-specific /
    disclosure concepts have no standard mapping and keep their own label.
    """
    out = {}
    for method in ("income_statement", "balance_sheet", "cash_flow_statement", "comprehensive_income"):
        try:
            df = getattr(xb.statements, method)().to_dataframe()
        except Exception:
            continue
        for con, std in zip(df.get("concept", []), df.get("standard_concept", [])):
            if isinstance(con, str) and isinstance(std, str) and std:
                # statement df uses "us-gaap_X"/"ifrs-full_X"; facts use "us-gaap:X"/"ifrs-full:X"
                out[con.replace("_", ":", 1)] = std
    return out


class EdgarToolsExtractor:
    """Extract one filing's facts (with dimensions) into an ExtractionResult."""

    def __init__(self, identity: str = "Jonas Haahr itsxidey@gmail.com"):
        edgar.set_identity(identity)

    # Annual-report forms, in preference order: domestic 10-K, then foreign-filer 20-F / 40-F.
    _ANNUAL_FORMS = ("10-K", "20-F", "40-F")

    def extract(self, ticker: str, filing_type: Optional[str] = None) -> ExtractionResult:
        company = edgar.Company(ticker)
        forms = (filing_type,) if filing_type else self._ANNUAL_FORMS
        filing = None
        for form in forms:
            filing = company.latest(form)
            if filing is not None:
                break
        if filing is None:
            raise ValueError(f"No annual report ({'/'.join(forms)}) found for {ticker}")
        xb = filing.xbrl()
        df = xb.facts.to_dataframe()
        std_map = _standard_concept_map(xb)  # {raw concept -> edgartools standard concept}

        dim_cols = [c for c in df.columns if c.startswith(_DIM_PREFIX)]

        facts: list[Fact] = []
        for row in df.to_dict("records"):
            dims = {
                c[len(_DIM_PREFIX):]: row[c]
                for c in dim_cols
                if row.get(c) not in (None, "") and str(row.get(c)) != "nan"
            }
            nv = row.get("numeric_value")
            try:
                nv = float(nv) if nv is not None and str(nv) != "nan" else None
            except Exception:
                nv = None
            pt = row.get("period_type")
            # Instants carry their date in `period_instant` (period_start/period_end are NaN);
            # durations carry period_start/period_end. Read the right column per period type.
            instant = _as_date(row.get("period_instant")) if pt == "instant" else None
            facts.append(Fact(
                concept=row.get("concept"),
                label=row.get("label") or row.get("original_label"),
                value_numeric=nv,
                value_text=None if nv is not None else row.get("value"),
                unit=row.get("currency") or row.get("unit_ref"),
                period_start=_as_date(row.get("period_start")),
                period_end=_as_date(row.get("period_end")),
                instant_date=instant,
                period_type=pt,
                fiscal_year=int(row["fiscal_year"]) if row.get("fiscal_year") not in (None, "", "nan") else None,
                fiscal_period=row.get("fiscal_period"),
                statement_type=_statement_type(row.get("statement_type")),
                dimensions=dims or None,
                is_dimensioned=bool(row.get("is_dimensioned")),
                standard_label=std_map.get(row.get("concept")),
            ))

        meta = CompanyMeta(
            cik=str(getattr(company, "cik", "")),
            ticker=ticker,
            name=getattr(company, "name", ticker),
            currency=None,
            is_financial_institution=bool(company.is_financial_institution()),
        )
        fmeta = FilingMeta(
            accession=getattr(filing, "accession_no", ""),
            form=getattr(filing, "form", filing_type),
            filing_date=_as_date(getattr(filing, "filing_date", None)),
            # Authoritative fiscal-year-end = dei:DocumentPeriodEndDate (edgartools'
            # period_of_report). Do NOT derive it from max(period_end) — forward-looking
            # disclosures (lease maturities, revenue-remaining-performance-obligation timing)
            # carry dates past the year-end and would overstate it.
            period_end=(_as_date(getattr(filing, "period_of_report", None))
                        or max((f.period_end for f in facts if f.period_end), default=None)),
        )
        # derive reporting currency from the modal currency unit of numeric facts
        cur = {}
        for f in facts:
            if f.value_numeric is not None and f.unit and len(str(f.unit)) <= 4:
                cur[f.unit] = cur.get(f.unit, 0) + 1
        if cur:
            meta.currency = max(cur, key=cur.get)
        return ExtractionResult(company=meta, filing=fmeta, facts=facts)


if __name__ == "__main__":
    # Phase-1 proof: run the extractor across deliberately-hard filers and show that it
    # yields clean, uniform facts (core + dimensions) for every one — no DB required.
    import sys

    ex = EdgarToolsExtractor()
    tests = ["AAPL", "AVGO", "JPM", "NVO", "GOOGL", "MSFT", "AMZN", "NVDA"]
    if len(sys.argv) > 1:
        tests = sys.argv[1:]

    def latest_val(facts, concepts, undimensioned=True):
        cand = [f for f in facts if f.concept in concepts and f.value_numeric is not None
                and (not undimensioned or not f.dimensions)]
        if not cand:
            return None
        f = max(cand, key=lambda x: (x.period_end or date.min))
        return f.value_numeric, f.period_end

    REV = {"us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap:Revenues",
           "ifrs-full:Revenue"}
    NI = {"us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss", "ifrs-full:ProfitLoss"}
    ASSETS = {"us-gaap:Assets", "ifrs-full:Assets"}

    print(f"{'TICKER':6} {'FI?':3} {'CUR':4} {'FACTS':>6} {'DIM':>5} {'REVENUE':>14} {'NET INC':>13} {'ASSETS':>13}  LATEST_FYE")
    for tk in tests:
        try:
            r = ex.extract(tk)
            n = len(r.facts)
            ndim = sum(1 for f in r.facts if f.dimensions)
            rev = latest_val(r.facts, REV)
            ni = latest_val(r.facts, NI)
            ast = latest_val(r.facts, ASSETS)
            def fmt(x):
                return f"{x[0]/1e9:>11,.2f}B" if x else f"{'—':>12}"
            fye = rev[1] if rev else (ast[1] if ast else None)
            print(f"{tk:6} {str(r.company.is_financial_institution)[0]:3} {str(r.company.currency or '?'):4} "
                  f"{n:>6} {ndim:>5} {fmt(rev):>14} {fmt(ni):>13} {fmt(ast):>13}  {fye}")
        except Exception as e:
            print(f"{tk:6} ❌ {type(e).__name__}: {str(e)[:70]}")
