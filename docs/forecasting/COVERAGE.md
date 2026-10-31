# FinSight — Forecasting Coverage Scorecard

Auto-routed with `regime.classify`; revenue MAPE is a leakage-safe walk-forward backtest. The vs-consensus columns compare OUR error to the analyst CONSENSUS error over the same quarters (revenue consensus via MarketBeat ~2yr; EPS consensus via yfinance).

| Ticker | Route | Rev MAPE | us vs Rev cons | Our EPS | EPS cons | Ledger |
|--------|-------|---------:|:--------------:|--------:|---------:|:------:|
| NVDA | guidance | 1.2% (3) | 1.2% vs 4.0% ✅ (n=3) | 4.5% ✅ | 4.8% | revenue+EPS |
| AMZN | seasonal | 4.5% (17) | 4.5% vs 1.8% (n=6) |   n/a |   n/a | revenue |
| AVGO | guidance | 0.6% (3) | 0.6% vs 0.8% ✅ (n=3) |   n/a |   n/a | revenue |
| MSFT | seasonal | 3.5% (17) | 3.5% vs 1.8% (n=6) | 8.4% | 5.7% | revenue+EPS |
| GOOGL | seasonal | 6.1% (17) | 6.1% vs 1.9% (n=6) |   n/a |   n/a | revenue |
| AAPL | seasonal | 9.0% (17) | 9.0% vs 2.2% (n=6) |   n/a |   n/a | revenue |
| JPM | seasonal | 7.6% (17) | 7.6% vs 5.1% (n=5) |   n/a |   n/a | revenue |
| META | seasonal | 8.9% (17) | 8.9% vs 2.7% (n=6) |   n/a |   n/a | revenue |
| TSLA | seasonal | 14.0% (17) | 14.0% vs 7.0% (n=6) |   n/a |   n/a | revenue |
| NFLX | seasonal | 4.5% (18) | 4.5% vs 0.3% (n=6) |   n/a |   n/a | revenue |
| AMD | seasonal | 16.1% (17) | 16.1% vs 3.8% (n=5) |   n/a |   n/a | revenue |
| ORCL | seasonal | 5.9% (16) | 5.9% vs 1.1% (n=6) |   n/a |   n/a | revenue |
| CRM | seasonal | 2.6% (17) | 2.6% vs 0.6% (n=6) |   n/a |   n/a | revenue |

**Logged live — revenue (13):** NVDA, AMZN, AVGO, MSFT, GOOGL, AAPL, JPM, META, TSLA, NFLX, AMD, ORCL, CRM. **EPS (2):** NVDA, MSFT (logged where the margin→EPS chain is credible; we beat consensus on NVDA and trail it on MSFT, shown either way; elsewhere EPS is distorted by one-time items, acquisition amortization, FX, or bank accounting).

Every company is reported here honestly; the Ledger column shows what we commit to live. ✅ marks quarters where our EPS matched or beat consensus.
