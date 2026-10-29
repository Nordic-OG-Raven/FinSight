# FinSight — Quarterly Earnings Forecast

*Generated 2026-10-29 from the gold warehouse (`gold.earnings`) + Yahoo Finance consensus.*

Can a model built **only on SEC filing history** get near the Wall-Street analyst consensus for
next quarter? This is the experiment. Every FinSight number comes from the medallion warehouse
(bronze 10-K/10-Q XBRL → silver conformance → gold quarterly series); the consensus and actuals
come from Yahoo Finance. Nothing here is investment advice — see the caveats.

**Headline:** revenue forecasts are robust; EPS forecasts are only trustworthy where the
company's own backtest says so (stock splits and one-time items distort the short EPS history —
see the data-quality note). So revenue leads.

## Next-quarter revenue: FinSight model spread

| Ticker | Ensemble | Seasonal-naive | Trend+seasonal | GBM (lags) | #Quarters |
| --- | --- | --- | --- | --- | --- |
| AAPL | $115.1B | $118.9B | $111.8B | $112.3B | 13.00 |
| MSFT | $94.6B | $95.9B | $93.5B | $91.6B | 14.00 |
| NVDA | $92.8B | $102.2B | $85.0B | $92.1B | 14.00 |
| AMZN | $205.7B | $207.4B | $200.3B | $212.2B | 14.00 |
| GOOGL | $133.5B | $140.0B | $130.1B | $125.7B | 13.00 |
| AVGO | $26.3B | $25.7B | $25.1B | $28.5B | 11.00 |
| JPM | $51.5B | $50.8B | $50.7B | $52.8B | 14.00 |

## Next-quarter diluted EPS: FinSight vs consensus

EPS is only shown where the walk-forward backtest error (MAPE) is under 15% — i.e. where the
model actually tracks that company's prints. The rest are suppressed, not fudged.

| Ticker | Reports | FinSight ensemble | Consensus | Lean | Backtest MAPE* | Status |
| --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-11-02 | 2.03 | 1.98 | above consensus (+2.7%) | 12.2% | reliable |
| MSFT | 2027-01-27 | 5.81 | 4.82 | above consensus (+20.6%) | 8.4% | reliable |
| NVDA | 2026-11-17 | — *(suppressed)* | 2.47 | history distorted | 20.2% | ⚠ split / one-off |
| AMZN | 2026-10-29 | — *(suppressed)* | 1.96 | history distorted | 20.9% | ⚠ split / one-off |
| GOOGL | 2027-02-03 | — *(suppressed)* | 3.35 | history distorted | 55.0% | ⚠ split / one-off |
| AVGO | 2026-12-09 | — *(suppressed)* | 3.84 | history distorted | 30.4% | ⚠ split / one-off |
| JPM | 2027-01-14 | 6.20 | 5.90 | above consensus (+5.0%) | 9.9% | reliable |

\* MAPE = mean absolute percentage error of the trend+seasonal model, walk-forward on each
company's own quarterly history (lower = the model tracks that company's prints better).

## Data-quality finding: splits & one-offs distort EPS, not revenue

Noisy EPS forecasts aren't a modelling failure — they're a **data** signal the pipeline surfaced,
and they split into one part we fixed and one part that's inherent:

- **Stock splits — FIXED.** AVGO (10:1, 2024) and NVDA (10:1, 2024) split in-window, so their raw
  EPS history mixed pre- and post-split values (AVGO showed a pre-split ~$8 quarter next to
  post-split ~$1). We now land splits as raw corporate actions in **bronze**
  (`bronze.corporate_actions`, from Yahoo Finance) and **gold** computes a split-adjusted EPS on a
  current-share basis (`gold.earnings.eps_diluted_adj`). Backtest error fell sharply (AVGO
  148%→30%, NVDA 38%→20%) and the warehouse EPS is now comparable to the split-adjusted consensus.
- **One-time items — inherent, not a bug.** Some quarters carry a one-off gain (AMZN's latest; a
  spike in MSFT's recent quarter) that is the *correct* reported GAAP EPS but unrepresentative. A
  trend model inherits it and can sit above the analyst consensus, which normalizes one-offs out.
  "Fixing" this would mean a non-GAAP/normalized EPS, which isn't in the XBRL — so it's a genuine
  limit of forecasting GAAP EPS, flagged rather than papered over.

**Revenue carries neither distortion**, which is why it forecasts cleanly across every filer.

## Spotlight: Apple, next print

- **Reports:** 2026-11-02 (fiscal Q4 2026, quarter ending ~Sept 2026)
- **Wall Street consensus EPS:** 1.98
- **FinSight ensemble forecast:** 2.03 → *above consensus (+2.7%)*

Per-model next-quarter EPS and each model's walk-forward backtest error on Apple's own history:

| Model | Forecast EPS | Backtest MAPE |
| --- | --- | --- |
| seasonal_naive | 2.30 | 14.3% |
| ols_trend_seasonal | 1.81 | 12.2% |
| gbm_lags | 2.02 | 16.2% |

Recent actual vs consensus (Apple has a persistent beat pattern):

| Date | Consensus EPS | Reported EPS | Surprise |
| --- | --- | --- | --- |
| 2026-07-30 | 1.89 | 2.02 | 6.7% |
| 2026-04-30 | 1.94 | 2.01 | 3.5% |
| 2026-01-29 | 2.67 | 2.84 | 6.2% |
| 2025-10-30 | 1.77 | 1.85 | 4.5% |
| 2025-07-31 | 1.43 | 1.57 | 9.5% |

## Method

Three deliberately-transparent models, each respecting quarterly seasonality (which dominates a
short series like this):

1. **seasonal_naive** — same quarter last year, grown by the median recent year-over-year rate.
2. **ols_trend_seasonal** — least-squares linear trend + quarter-of-year dummies.
3. **gbm_lags** — gradient-boosted trees on `[lag1, lag4, quarter, trend]` features.

The **ensemble** is an inverse-MAPE weighting (more-accurate models get more weight). Q4 is never
filed on its own (10-Qs cover Q1–Q3), so the warehouse **derives** it as `annual − (Q1+Q2+Q3)`;
this was validated against a real print (Apple FQ4-FY2025 derived EPS $1.84 vs reported $1.85).

## Caveats (stated, not hidden)

- **Short history.** ~12–14 quarters per filer. These are illustrative nowcasts, not a trading
  signal, and the backtest sample is small.
- **SEC-only inputs.** The models see past reported fundamentals — no guidance, order books,
  macro, or price action that real analysts use. Beating consensus isn't the goal; getting close
  with far less information is the interesting part.
- **Consensus/actuals are third-party** (Yahoo Finance) and may restate.
