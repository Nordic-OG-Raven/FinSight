# FinSight — Forecasting Coverage Scorecard

Auto-routed with `regime.classify`; revenue MAPE is a leakage-safe walk-forward backtest; EPS columns compare OUR next-quarter EPS vs analyst CONSENSUS over the same quarters (our EPS = point-in-time revenue x net-margin / current diluted shares).

| Ticker | Route | Regime | Rev MAPE | Rev n | Our EPS | Consensus EPS | EPS n | Ledger |
|--------|-------|--------|---------:|------:|--------:|--------------:|------:|:------:|
| NVDA | guidance | growth | 1.2% | 3 | 4.5% ✅ | 4.8% | 3 | revenue+EPS |
| AMZN | seasonal | seasonal | 4.5% | 17 |   n/a |   n/a | 0 | revenue |
| AVGO | guidance | seasonal | 0.6% | 3 |   n/a |   n/a | 0 | revenue |
| MSFT | seasonal | seasonal | 3.5% | 17 | 8.4% | 5.7% | 17 | revenue+EPS |
| GOOGL | seasonal | seasonal | 6.1% | 17 |   n/a |   n/a | 0 | revenue |
| AAPL | seasonal | seasonal | 9.0% | 17 |   n/a |   n/a | 0 | revenue |
| JPM | seasonal | seasonal | 7.6% | 17 |   n/a |   n/a | 0 | revenue |

**Logged live — revenue (7):** NVDA, AMZN, AVGO, MSFT, GOOGL, AAPL, JPM. **EPS (2):** NVDA, MSFT (logged only where the margin→EPS chain is competitive with consensus; elsewhere it is distorted by one-time items, acquisition amortization, FX, or bank accounting).

Every company is reported here honestly; the Ledger column shows what we commit to live. ✅ marks quarters where our EPS matched or beat consensus.
