"""
Slim post-load validation + per-filing data-quality report — the re-architecture's
replacement for the retired, normalized-label-keyed validator stack.

Design (per docs/REARCHITECTURE.md "Keep vs retire"):
- Operates on the clean `ExtractionResult` facts, keyed on RAW XBRL concepts
  (us-gaap:* / ifrs-full:*), which edgartools makes uniform across filers — not on the
  fragile normalized-label vocabulary that made the old checks false-positive.
- Two SOUND checks are HARD GATES: the reported balance-sheet identity
  (Assets = Liabilities + Equity, pinned to the fiscal-year-end) and unit/scale sanity.
- Everything else (income-statement math, EPS, currency mix) is a SOFT WARNING — it informs
  the quality score but never blocks a load. This is the "hard integrity gates, fragile
  heuristics as warnings only" principle the PRD (§2.4, §14.4) and re-arch both call for.

Fulfils PRD §2.4 (validation runs automatically after load, hard-fails on critical issues,
completeness check, per-filing data-quality report) and §8 (data-quality score).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

# ---- concept vocabularies (raw tags, US-GAAP + IFRS) -------------------------
ASSETS = {"us-gaap:Assets", "ifrs-full:Assets"}
# right-hand side of the balance sheet identity (total L&E)
LIAB_AND_EQUITY = {"us-gaap:LiabilitiesAndStockholdersEquity", "us-gaap:LiabilitiesAndEquity",
                   "ifrs-full:EquityAndLiabilities"}
REVENUE = {"us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap:Revenues",
           "us-gaap:RevenuesNetOfInterestExpense", "ifrs-full:Revenue"}
NET_INCOME = {"us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss", "ifrs-full:ProfitLoss"}
LIABILITIES = {"us-gaap:Liabilities", "ifrs-full:Liabilities"}
EQUITY = {"us-gaap:StockholdersEquity",
          "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
          "ifrs-full:Equity"}
OPERATING_CF = {"us-gaap:NetCashProvidedByUsedInOperatingActivities",
                "ifrs-full:CashFlowsFromUsedInOperatingActivities"}
GROSS_PROFIT = {"us-gaap:GrossProfit"}
COST_OF_REVENUE = {"us-gaap:CostOfRevenue", "us-gaap:CostOfGoodsAndServicesSold",
                   "us-gaap:CostOfGoodsSold", "ifrs-full:CostOfSales"}
EPS_DILUTED = {"us-gaap:EarningsPerShareDiluted", "ifrs-full:DilutedEarningsLossPerShare"}
SHARES_DILUTED = {"us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
                  "us-gaap:WeightedAverageNumberOfDilutedSharesOutstandingDEICurrentFlag"}

# critical metrics the PRD requires every filing to carry (§2.4 completeness check)
CRITICAL = {"revenue": REVENUE, "net_income": NET_INCOME, "total_assets": ASSETS,
            "total_liabilities": LIABILITIES, "total_equity": EQUITY,
            "operating_cash_flow": OPERATING_CF}

# tolerances (from config/validation_rules.yaml)
BALANCE_TOL = 0.01
INCOME_TOL = 0.02
EPS_TOL = 0.05        # EPS is reported rounded to the cent
# quality-score weights (from config/validation_rules.yaml)
W = {"completeness": 0.4, "accuracy": 0.3, "consistency": 0.2, "provenance": 0.1}
MIN_PASSING_SCORE = 0.85
MIN_COMPLETENESS = 0.90


@dataclass
class Check:
    name: str
    status: str                      # pass | fail | skip
    detail: str = ""
    expected: Optional[float] = None
    actual: Optional[float] = None
    rel_error: Optional[float] = None


@dataclass
class QualityReport:
    ticker: str
    form: str
    fiscal_year_end: Optional[str]
    currency: Optional[str]
    n_facts: int
    hard_gates: list = field(default_factory=list)      # list[Check]
    soft_checks: list = field(default_factory=list)      # list[Check]
    critical_present: dict = field(default_factory=dict)  # name -> bool
    scores: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    passed: bool = False             # hard-gate verdict — gates persistence

    def summary_line(self) -> str:
        q = self.scores.get("overall", 0.0)
        flag = "PASS" if self.passed else "FAIL"
        return (f"{self.ticker:6} {flag:4} q={q:.2f} "
                f"complete={self.scores.get('completeness', 0):.2f} "
                f"({len(self.warnings)} warn)")

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, default=str)


# ---- fact selection helpers --------------------------------------------------
def _undimensioned(facts):
    return [f for f in facts if not f.dimensions and f.value_numeric is not None]


def _latest_instant(facts, concepts):
    cand = [f for f in _undimensioned(facts)
            if f.concept in concepts and f.period_type == "instant" and f.instant_date]
    return max(cand, key=lambda f: f.instant_date) if cand else None


def _instant_on(facts, concepts, on: date):
    cand = [f for f in _undimensioned(facts)
            if f.concept in concepts and f.period_type == "instant" and f.instant_date == on]
    return cand[0] if cand else None


def _latest_annual(facts, concepts):
    """Latest ~full-year duration fact for a concept set (330-380 day window)."""
    cand = []
    for f in _undimensioned(facts):
        if f.concept in concepts and f.period_type == "duration" and f.period_start and f.period_end:
            if 330 <= (f.period_end - f.period_start).days <= 380:
                cand.append(f)
    return max(cand, key=lambda f: f.period_end) if cand else None


def _rel_error(a: float, b: float) -> float:
    denom = max(abs(a), abs(b), 1.0)
    return abs(a - b) / denom


# ---- the checks --------------------------------------------------------------
def _check_balance_identity(facts) -> Check:
    """HARD GATE: Assets = Liabilities + Equity at the fiscal-year-end, as the filer reports
    the two totals. Keys on the reported total-L&E line, so it audits the filing itself rather
    than a reconstructed sum (robust across US-GAAP and IFRS)."""
    assets = _latest_instant(facts, ASSETS)
    if not assets:
        return Check("balance_identity", "skip", "no total-assets fact to pin the balance-sheet date")
    lse = _instant_on(facts, LIAB_AND_EQUITY, assets.instant_date)
    if not lse:
        return Check("balance_identity", "skip",
                     f"no total liabilities+equity reported at {assets.instant_date}")
    err = _rel_error(assets.value_numeric, lse.value_numeric)
    status = "pass" if err <= BALANCE_TOL else "fail"
    return Check("balance_identity", status,
                 f"Assets={assets.value_numeric:,.0f} vs L&E={lse.value_numeric:,.0f} @ {assets.instant_date}",
                 expected=lse.value_numeric, actual=assets.value_numeric, rel_error=err)


def _check_unit_scale(facts, currency) -> Check:
    """HARD GATE: unit/scale sanity. A clean edgartools extraction reports actual units in one
    dominant currency; a dominant-currency share below 90%, or core totals implausibly tiny,
    signals a scale/unit parse error worth blocking on."""
    monetary = [f for f in _undimensioned(facts)
                if f.unit and len(str(f.unit)) == 3 and str(f.unit).isupper()]
    if not monetary:
        return Check("unit_scale", "skip", "no clearly-monetary facts to assess")
    counts: dict = {}
    for f in monetary:
        counts[f.unit] = counts.get(f.unit, 0) + 1
    dominant = max(counts, key=counts.get)
    share = counts[dominant] / len(monetary)
    assets = _latest_instant(facts, ASSETS)
    tiny = assets is not None and abs(assets.value_numeric) < 1e4
    if share < 0.90:
        return Check("unit_scale", "fail",
                     f"no dominant currency: {dominant} only {share:.0%} of monetary facts")
    if tiny:
        return Check("unit_scale", "fail",
                     f"total assets implausibly small ({assets.value_numeric:,.0f}) — possible scale error")
    return Check("unit_scale", "pass", f"{dominant} dominates {share:.0%} of monetary facts")


def _check_income_math(facts) -> Check:
    """SOFT: Gross profit ~= Revenue - Cost of revenue (skipped for filers that don't tag it,
    e.g. banks)."""
    gp = _latest_annual(facts, GROSS_PROFIT)
    rev = _latest_annual(facts, REVENUE)
    cor = _latest_annual(facts, COST_OF_REVENUE)
    if not (gp and rev and cor):
        return Check("income_math", "skip", "revenue / cost-of-revenue / gross-profit not all tagged")
    expected = rev.value_numeric - cor.value_numeric
    err = _rel_error(gp.value_numeric, expected)
    status = "pass" if err <= INCOME_TOL else "fail"
    return Check("income_math", status,
                 f"GrossProfit={gp.value_numeric:,.0f} vs Rev-CoR={expected:,.0f}",
                 expected=expected, actual=gp.value_numeric, rel_error=err)


def _check_eps(facts) -> Check:
    """SOFT: Diluted EPS ~= Net income / diluted shares."""
    eps = _latest_annual(facts, EPS_DILUTED)
    ni = _latest_annual(facts, NET_INCOME)
    sh = _latest_annual(facts, SHARES_DILUTED)
    if not (eps and ni and sh and sh.value_numeric):
        return Check("eps", "skip", "EPS / net income / diluted shares not all tagged")
    expected = ni.value_numeric / sh.value_numeric
    err = _rel_error(eps.value_numeric, expected)
    status = "pass" if err <= EPS_TOL else "fail"
    return Check("eps", status, f"EPS={eps.value_numeric} vs NI/shares={expected:.2f}",
                 expected=expected, actual=eps.value_numeric, rel_error=err)


# ---- public entrypoint -------------------------------------------------------
def validate(result) -> QualityReport:
    """Validate one ExtractionResult; produce a per-filing data-quality report.

    `passed` reflects the HARD GATES only (balance identity, unit/scale) — that is the
    integrity gate the loader uses to decide whether to persist. A skipped gate does not fail
    the filing (not every filer tags every total), but it is recorded as a warning and lowers
    completeness."""
    facts = result.facts
    rep = QualityReport(
        ticker=result.company.ticker,
        form=result.filing.form,
        fiscal_year_end=str(result.filing.period_end) if result.filing.period_end else None,
        currency=result.company.currency,
        n_facts=len(facts),
    )

    # hard gates
    bal = _check_balance_identity(facts)
    scale = _check_unit_scale(facts, result.company.currency)
    rep.hard_gates = [bal, scale]
    rep.passed = all(c.status != "fail" for c in rep.hard_gates)
    for c in rep.hard_gates:
        if c.status == "fail":
            rep.warnings.append(f"HARD-GATE FAILED — {c.name}: {c.detail}")
        elif c.status == "skip":
            rep.warnings.append(f"gate not verified — {c.name}: {c.detail}")

    # soft checks
    rep.soft_checks = [_check_income_math(facts), _check_eps(facts)]
    for c in rep.soft_checks:
        if c.status == "fail":
            rep.warnings.append(f"soft check failed — {c.name}: {c.detail}")

    # completeness (critical metrics present + adequate fact volume)
    present = {}
    for name, concepts in CRITICAL.items():
        present[name] = any(f.concept in concepts and f.value_numeric is not None
                            and not f.dimensions for f in facts)
    rep.critical_present = present
    for name, ok in present.items():
        if not ok:
            rep.warnings.append(f"missing critical metric: {name}")
    metric_completeness = sum(present.values()) / len(present)
    volume = min(len(facts) / 500.0, 1.0)             # PRD §8 target: 500-2000+ facts
    completeness = 0.8 * metric_completeness + 0.2 * volume

    # scores (weights from config/validation_rules.yaml)
    accuracy = 1.0 if bal.status == "pass" else (0.5 if bal.status == "skip" else 0.0)
    applicable_soft = [c for c in rep.soft_checks if c.status != "skip"]
    consistency = (sum(1 for c in applicable_soft if c.status == "pass") / len(applicable_soft)
                   if applicable_soft else 1.0)
    traced = sum(1 for f in facts if f.concept) / len(facts) if facts else 0.0  # every fact has concept+source+filing
    provenance = traced
    overall = (W["completeness"] * completeness + W["accuracy"] * accuracy
               + W["consistency"] * consistency + W["provenance"] * provenance)
    rep.scores = {"completeness": round(completeness, 3), "accuracy": round(accuracy, 3),
                  "consistency": round(consistency, 3), "provenance": round(provenance, 3),
                  "overall": round(overall, 3)}

    if completeness < MIN_COMPLETENESS:
        rep.warnings.append(f"completeness {completeness:.2f} below target {MIN_COMPLETENESS}")
    if overall < MIN_PASSING_SCORE:
        rep.warnings.append(f"quality score {overall:.2f} below target {MIN_PASSING_SCORE}")
    return rep


def write_report(rep: QualityReport, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fye = (rep.fiscal_year_end or "unknown").replace("-", "")
    path = out / f"{rep.ticker}_{fye}_quality.json"
    path.write_text(rep.to_json())
    return path
