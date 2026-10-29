"""Auto-regime routing — decide, from a ticker's OWN data, how to forecast its next-quarter revenue.

Two orthogonal signals, both derived from the warehouse + the company's filings (no per-ticker
hand-tuning), so any newly-ingested ticker can be routed automatically:

  - guides?            Does it issue parseable forward revenue guidance in its earnings 8-K, with
                       enough measured guidance->actual beats to trust a beat rate? If so, the
                       guidance-beat path is available (the single strongest signal for hyper-growth
                       names). Extraction is the hybrid regex+verified-LLM in `guidance.py`.
  - growth / seasonal  Median year-over-year revenue growth. Hyper-growth names are trend-driven;
                       mature names are seasonal.

This picks the *route* (which point-in-time method the live ledger logs, and the regime hint). The
actual model is still chosen by the backtest inside `forecasting_v2.forecast_next` — the regime is a
hint, not an override. Whether a guiding ticker should really be logged live is gated separately by
the ours-vs-consensus scorecard (`scripts/forecast_coverage.py`); this module only proposes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from src.analysis import forecasting_v2 as fv
from src.analysis import guidance as gd
from src.analysis import pit

GROWTH_YOY = 0.25   # median YoY revenue growth above this => "growth" regime
MIN_BEATS = 3       # need at least this many measured guidance->actual beats to trust guidance


@dataclass
class Route:
    ticker: str
    method: str                 # 'guidance' | 'seasonal' — the point-in-time path the ledger uses
    regime: str                 # 'growth' | 'seasonal' — the backtest hint
    guides: bool                # issues parseable revenue guidance (availability, not superiority)
    n_guidance: int
    n_beats: int
    yoy_growth: float | None
    guid_mape: float | None = None     # guidance-beat backtest MAPE (%)
    filings_mape: float | None = None  # best filings-only model backtest MAPE (%)
    components: list = field(default_factory=lambda: ["revenue"])

    def as_dict(self):
        return asdict(self)


def _median_yoy(pts) -> float | None:
    """Median YoY growth of same-fiscal-quarter revenue over the available history."""
    by = {(p.fiscal_year, p.quarter_num): p.value for p in pts}
    rates = [v / by[(fy - 1, qn)] - 1
             for (fy, qn), v in by.items()
             if by.get((fy - 1, qn)) and by[(fy - 1, qn)] > 0]
    return float(np.median(rates)) if rates else None


def classify(db, ticker: str, use_llm: bool = True) -> Route:
    """Propose a forecasting route for `ticker` from its guidance history + revenue growth profile.

    Routes to the guidance-beat method ONLY when it actually backtests better than the best
    filings-only model — guidance *availability* is not the same as guidance being the best
    predictor (AMZN/AVGO guide, but a trend model forecasts their revenue far better than their
    noisy net-sales beat; only NVDA's consistent beat genuinely wins).
    """
    ticker = ticker.upper()
    guid = gd.guidance_history(ticker, limit=16, use_llm=use_llm)
    beats = fv._beat_pairs(db, ticker, guid) if guid else []
    guides = len(beats) >= MIN_BEATS
    yoy = _median_yoy(pit.latest_series(db, ticker, "revenue"))
    regime = "growth" if (yoy is not None and yoy > GROWTH_YOY) else "seasonal"

    method, guid_mape, filings_mape = "seasonal", None, None
    if guides:
        gm = fv.guidance_model(db, ticker)
        bt = fv.backtest(db, ticker, ["revenue"])
        mapes = [v["mape"] for k, v in bt.items() if k != "_n_eval" and v.get("mape")]
        filings_mape = min(mapes) if mapes else None
        guid_mape = gm.get("mape") if gm else None
        if guid_mape is not None and filings_mape is not None and guid_mape < filings_mape:
            method = "guidance"
    return Route(ticker, method, regime, guides, len(guid), len(beats), yoy,
                 guid_mape=guid_mape, filings_mape=filings_mape)


if __name__ == "__main__":
    import sys

    from config import DATABASE_URL
    tickers = sys.argv[1:] or ["NVDA", "AMZN", "AVGO", "MSFT", "GOOGL", "AAPL", "JPM"]
    print(f"{'ticker':7s} {'method':9s} {'regime':9s} {'guides':7s} {'n_beats':>7s} "
          f"{'yoy':>7s} {'guid_mape':>9s} {'filings':>8s}")
    for tk in tickers:
        r = classify(DATABASE_URL, tk)
        yoy = f"{r.yoy_growth*100:5.1f}%" if r.yoy_growth is not None else "   n/a"
        gm = f"{r.guid_mape:7.1f}%" if r.guid_mape is not None else "    n/a"
        fm = f"{r.filings_mape:6.1f}%" if r.filings_mape is not None else "   n/a"
        print(f"{r.ticker:7s} {r.method:9s} {r.regime:9s} {str(r.guides):7s} "
              f"{r.n_beats:7d} {yoy:>7s} {gm:>9s} {fm:>8s}")
