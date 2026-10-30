# FinSight — Live Forecast Track Record

*Updated 2026-10-30. Every forecast is made **before** the print and frozen; actuals + consensus are
filled once the quarter reports. `backtest:*` rows are the historical point-in-time record that
seeded the ledger; new rows are logged live each week.*

## Running accuracy — us vs consensus

| Ticker | Metric | Our MAPE | Consensus MAPE | Quarters |
| --- | --- | --- | --- | --- |
| AAPL | revenue | 9.0% | — | 17 |
| AAPL | revenue_q4 | 16.3% | — | 5 |
| AMZN | revenue | 4.5% | — | 17 |
| AMZN | revenue_q4 | 5.8% | — | 5 |
| AVGO | revenue | 0.6% | — | 3 |
| AVGO | revenue_q4 | 3.4% | — | 5 |
| GOOGL | revenue | 6.1% | — | 17 |
| GOOGL | revenue_q4 | 13.7% | — | 5 |
| JPM | revenue | 7.6% | — | 17 |
| JPM | revenue_q4 | 4.2% | — | 5 |
| MSFT | eps | 8.4% | 5.7% | 17 |
| MSFT | revenue | 3.5% | — | 17 |
| MSFT | revenue_q4 | 3.2% | — | 5 |
| NVDA | eps | 4.5% | 4.8% | 3 |
| NVDA | revenue | 1.2% | — | 3 |
| NVDA | revenue_q4 | 18.0% | — | 5 |

## Pending (live, not yet reported)

| Ticker | Quarter | Metric | Forecast | Consensus | Actual | Our APE | Cons APE |
| --- | --- | --- | --- | --- | --- | --- | --- |
| MSFT | FY2027 Q2 | eps | 5.16 | 4.82 | — | — | — |
| NVDA | FY2027 Q3 | eps | 2.86 | 2.47 | — | — | — |
| AAPL | FY2027 Q1 | revenue | $145.2B [127, 165]B | $113.3B | — | — | — |
| AMZN | FY2026 Q3 | revenue | $197.3B [186, 209]B | $202.3B | — | — | — |
| AVGO | FY2027 Q1 | revenue | $35.1B [35, 35]B | $34.9B | — | — | — |
| GOOGL | FY2027 Q1 | revenue | $121.1B [113, 135]B | $142.2B | — | — | — |
| JPM | FY2026 Q3 | revenue | $51.0B [47, 60]B | $51.1B | — | — | — |
| MSFT | FY2027 Q2 | revenue | $95.4B [91, 99]B | $96.6B | — | — | — |
| NVDA | FY2027 Q3 | revenue | $113.1B [113, 114]B | $109.0B | — | — | — |
| AAPL | FY2026 Q4 | revenue_q4 | 116811300079.36 | — | — | — | — |
| AVGO | FY2026 Q4 | revenue_q4 | 26271327795.24 | — | — | — | — |
| GOOGL | FY2026 Q4 | revenue_q4 | 128207021383.54 | — | — | — | — |

## Graded history

| Ticker | Quarter | Metric | Forecast | Consensus | Actual | Our APE | Cons APE |
| --- | --- | --- | --- | --- | --- | --- | --- |
| MSFT | FY2021 Q3 | eps | 1.83 | 1.78 | 1.95 | 6.4% | 8.7% |
| MSFT | FY2022 Q1 | eps | 2.07 | 2.08 | 2.27 | 8.6% | 8.4% |
| MSFT | FY2022 Q2 | eps | 2.63 | 2.32 | 2.48 | 6.2% | 6.5% |
| MSFT | FY2022 Q3 | eps | 2.54 | 2.20 | 2.22 | 14.3% | 0.9% |
| MSFT | FY2023 Q1 | eps | 2.70 | 2.31 | 2.35 | 15.0% | 1.7% |
| MSFT | FY2023 Q2 | eps | 3.00 | 2.32 | 2.32 | 29.2% | 0.0% |
| MSFT | FY2023 Q3 | eps | 2.53 | 2.23 | 2.45 | 3.1% | 9.0% |
| MSFT | FY2024 Q1 | eps | 2.62 | 2.65 | 2.99 | 12.4% | 11.4% |
| MSFT | FY2024 Q2 | eps | 3.03 | 2.77 | 2.93 | 3.4% | 5.5% |
| MSFT | FY2024 Q3 | eps | 2.90 | 2.84 | 2.94 | 1.3% | 3.4% |
| MSFT | FY2025 Q1 | eps | 3.18 | 3.11 | 3.30 | 3.6% | 5.8% |
| MSFT | FY2025 Q2 | eps | 3.62 | 3.12 | 3.23 | 11.9% | 3.4% |
| MSFT | FY2025 Q3 | eps | 3.36 | 3.22 | 3.46 | 2.8% | 6.9% |
| MSFT | FY2026 Q1 | eps | 3.61 | 3.66 | 4.13 | 12.5% | 11.4% |
| MSFT | FY2026 Q2 | eps | 4.02 | 3.92 | 4.14 | 2.9% | 5.3% |
| MSFT | FY2026 Q3 | eps | 4.17 | 4.07 | 4.27 | 2.3% | 4.7% |
| MSFT | FY2027 Q1 | eps | 4.59 | 4.72 | 4.89 | 6.2% | 3.5% |
| NVDA | FY2026 Q3 | eps | 1.20 | 1.26 | 1.30 | 7.6% | 3.1% |
| NVDA | FY2027 Q1 | eps | 1.76 | 1.77 | 1.87 | 5.8% | 5.3% |
| NVDA | FY2027 Q2 | eps | 2.22 | 2.09 | 2.22 | 0.0% | 5.9% |
| AAPL | FY2021 Q1 | revenue | $95.2B | — | $111.4B | 14.6% | — |
| AAPL | FY2021 Q2 | revenue | $73.3B | — | $89.6B | 18.2% | — |
| AAPL | FY2021 Q3 | revenue | $78.7B | — | $81.4B | 3.4% | — |
| AAPL | FY2022 Q1 | revenue | $127.1B | — | $123.9B | 2.6% | — |
| AAPL | FY2022 Q2 | revenue | $99.6B | — | $97.3B | 2.3% | — |
| AAPL | FY2022 Q3 | revenue | $94.4B | — | $83.0B | 13.9% | — |
| AAPL | FY2023 Q2 | revenue | $103.8B | — | $94.8B | 9.5% | — |
| AAPL | FY2023 Q3 | revenue | $94.9B | — | $81.8B | 16.1% | — |
| AAPL | FY2024 Q1 | revenue | $134.9B | — | $119.6B | 12.9% | — |
| AAPL | FY2024 Q2 | revenue | $107.4B | — | $90.8B | 18.4% | — |
| AAPL | FY2024 Q3 | revenue | $96.3B | — | $85.8B | 12.2% | — |
| AAPL | FY2025 Q1 | revenue | $127.3B | — | $124.3B | 2.4% | — |
| AAPL | FY2025 Q2 | revenue | $98.9B | — | $95.4B | 3.7% | — |
| AAPL | FY2025 Q3 | revenue | $94.5B | — | $94.0B | 0.5% | — |
| AAPL | FY2026 Q1 | revenue | $129.7B | — | $143.8B | 9.8% | — |
| AAPL | FY2026 Q2 | revenue | $104.1B | — | $111.2B | 6.4% | — |
| AAPL | FY2026 Q3 | revenue | $102.8B | — | $109.4B | 6.0% | — |
| AMZN | FY2021 Q1 | revenue | $101.1B | — | $108.5B | 6.9% | — |
| AMZN | FY2021 Q2 | revenue | $114.8B | — | $113.1B | 1.5% | — |
| AMZN | FY2021 Q3 | revenue | $121.1B | — | $110.8B | 9.3% | — |
| AMZN | FY2022 Q1 | revenue | $128.0B | — | $116.4B | 9.9% | — |
| AMZN | FY2022 Q2 | revenue | $130.7B | — | $121.2B | 7.8% | — |
| AMZN | FY2022 Q3 | revenue | $130.3B | — | $127.1B | 2.5% | — |
| AMZN | FY2023 Q1 | revenue | $136.7B | — | $127.4B | 7.3% | — |
| AMZN | FY2023 Q2 | revenue | $140.0B | — | $134.4B | 4.2% | — |
| AMZN | FY2023 Q3 | revenue | $142.5B | — | $143.1B | 0.4% | — |
| AMZN | FY2024 Q1 | revenue | $146.6B | — | $143.3B | 2.3% | — |
| AMZN | FY2024 Q2 | revenue | $152.3B | — | $148.0B | 2.9% | — |
| AMZN | FY2024 Q3 | revenue | $157.2B | — | $158.9B | 1.1% | — |
| AMZN | FY2025 Q1 | revenue | $159.9B | — | $155.7B | 2.7% | — |
| AMZN | FY2025 Q2 | revenue | $164.7B | — | $167.7B | 1.8% | — |
| AMZN | FY2025 Q3 | revenue | $173.2B | — | $180.2B | 3.9% | — |
| AMZN | FY2026 Q1 | revenue | $174.8B | — | $181.5B | 3.7% | — |
| AMZN | FY2026 Q2 | revenue | $184.4B | — | $200.6B | 8.1% | — |
| AVGO | FY2026 Q1 | revenue | $19.5B | — | $19.3B | 1.1% | — |
| AVGO | FY2026 Q2 | revenue | $22.2B | — | $22.2B | 0.3% | — |
| AVGO | FY2026 Q3 | revenue | $29.7B | — | $29.6B | 0.4% | — |
| GOOGL | FY2021 Q2 | revenue | $48.6B | — | $61.9B | 21.4% | — |
| GOOGL | FY2021 Q3 | revenue | $61.1B | — | $65.1B | 6.2% | — |
| GOOGL | FY2022 Q1 | revenue | $68.5B | — | $68.0B | 0.7% | — |
| GOOGL | FY2022 Q2 | revenue | $72.7B | — | $69.7B | 4.4% | — |
| GOOGL | FY2022 Q3 | revenue | $75.9B | — | $69.1B | 9.9% | — |
| GOOGL | FY2023 Q1 | revenue | $78.3B | — | $69.8B | 12.2% | — |
| GOOGL | FY2023 Q2 | revenue | $78.4B | — | $74.6B | 5.1% | — |
| GOOGL | FY2023 Q3 | revenue | $79.5B | — | $76.7B | 3.6% | — |
| GOOGL | FY2024 Q1 | revenue | $81.5B | — | $80.5B | 1.2% | — |
| GOOGL | FY2024 Q2 | revenue | $84.7B | — | $84.7B | 0.1% | — |
| GOOGL | FY2024 Q3 | revenue | $86.8B | — | $88.3B | 1.6% | — |
| GOOGL | FY2025 Q1 | revenue | $90.4B | — | $90.2B | 0.1% | — |
| GOOGL | FY2025 Q2 | revenue | $94.1B | — | $96.4B | 2.4% | — |
| GOOGL | FY2025 Q3 | revenue | $97.3B | — | $102.3B | 5.0% | — |
| GOOGL | FY2026 Q1 | revenue | $101.0B | — | $109.9B | 8.1% | — |
| GOOGL | FY2026 Q2 | revenue | $107.6B | — | $119.8B | 10.2% | — |
| GOOGL | FY2026 Q3 | revenue | $114.0B | — | $127.6B | 10.7% | — |
| JPM | FY2021 Q1 | revenue | $30.1B | — | $32.3B | 6.7% | — |
| JPM | FY2021 Q2 | revenue | $34.0B | — | $30.5B | 11.6% | — |
| JPM | FY2021 Q3 | revenue | $30.5B | — | $29.6B | 3.0% | — |
| JPM | FY2022 Q1 | revenue | $31.7B | — | $30.7B | 3.2% | — |
| JPM | FY2022 Q2 | revenue | $31.9B | — | $30.7B | 3.7% | — |
| JPM | FY2022 Q3 | revenue | $30.0B | — | $32.7B | 8.2% | — |
| JPM | FY2023 Q1 | revenue | $32.0B | — | $38.3B | 16.6% | — |
| JPM | FY2023 Q2 | revenue | $34.2B | — | $41.3B | 17.1% | — |
| JPM | FY2023 Q3 | revenue | $36.1B | — | $39.9B | 9.5% | — |
| JPM | FY2024 Q1 | revenue | $40.4B | — | $41.9B | 3.7% | — |
| JPM | FY2024 Q2 | revenue | $42.2B | — | $50.2B | 16.0% | — |
| JPM | FY2024 Q3 | revenue | $43.4B | — | $42.7B | 1.8% | — |
| JPM | FY2025 Q1 | revenue | $46.3B | — | $45.3B | 2.2% | — |
| JPM | FY2025 Q2 | revenue | $50.2B | — | $44.9B | 11.7% | — |
| JPM | FY2025 Q3 | revenue | $45.8B | — | $46.4B | 1.4% | — |
| JPM | FY2026 Q1 | revenue | $48.7B | — | $49.8B | 2.2% | — |
| JPM | FY2026 Q2 | revenue | $51.3B | — | $57.3B | 10.5% | — |
| MSFT | FY2021 Q3 | revenue | $40.1B | — | $41.7B | 3.8% | — |
| MSFT | FY2022 Q1 | revenue | $43.8B | — | $45.3B | 3.3% | — |
| MSFT | FY2022 Q2 | revenue | $50.4B | — | $51.7B | 2.6% | — |
| MSFT | FY2022 Q3 | revenue | $48.9B | — | $49.4B | 0.9% | — |
| MSFT | FY2023 Q1 | revenue | $52.8B | — | $50.1B | 5.3% | — |
| MSFT | FY2023 Q2 | revenue | $59.4B | — | $52.7B | 12.5% | — |
| MSFT | FY2023 Q3 | revenue | $55.2B | — | $52.9B | 4.4% | — |
| MSFT | FY2024 Q1 | revenue | $57.9B | — | $56.5B | 2.5% | — |
| MSFT | FY2024 Q2 | revenue | $64.4B | — | $62.0B | 3.8% | — |
| MSFT | FY2024 Q3 | revenue | $61.5B | — | $61.9B | 0.5% | — |
| MSFT | FY2025 Q1 | revenue | $65.5B | — | $65.6B | 0.2% | — |
| MSFT | FY2025 Q2 | revenue | $72.9B | — | $69.6B | 4.6% | — |
| MSFT | FY2025 Q3 | revenue | $70.1B | — | $70.1B | 0.0% | — |
| MSFT | FY2026 Q1 | revenue | $74.4B | — | $77.7B | 4.2% | — |
| MSFT | FY2026 Q2 | revenue | $82.7B | — | $81.3B | 1.7% | — |
| MSFT | FY2026 Q3 | revenue | $80.4B | — | $82.9B | 3.0% | — |
| MSFT | FY2027 Q1 | revenue | $86.3B | — | $92.3B | 6.5% | — |
| NVDA | FY2026 Q3 | revenue | $55.7B | — | $57.0B | 2.3% | — |
| NVDA | FY2027 Q1 | revenue | $81.4B | — | $81.6B | 0.3% | — |
| NVDA | FY2027 Q2 | revenue | $95.2B | — | $96.2B | 1.0% | — |
| AAPL | FY2021 Q4 | revenue_q4 | 89661157316.28 | — | 83360000000.00 | 7.6% | — |
| AAPL | FY2022 Q4 | revenue_q4 | 93795865139.62 | — | 90146000000.00 | 4.0% | — |
| AAPL | FY2023 Q4 | revenue_q4 | 64096225271.30 | — | 171295000000.00 | 62.6% | — |
| AAPL | FY2024 Q4 | revenue_q4 | 91305286463.92 | — | 94930000000.00 | 3.8% | — |
| AAPL | FY2025 Q4 | revenue_q4 | 98649259869.47 | — | 102466000000.00 | 3.7% | — |
| AMZN | FY2021 Q4 | revenue_q4 | 155368821047.47 | — | 137412000000.00 | 13.1% | — |
| AMZN | FY2022 Q4 | revenue_q4 | 165187256508.79 | — | 149204000000.00 | 10.7% | — |
| AMZN | FY2023 Q4 | revenue_q4 | 175333945691.81 | — | 169961000000.00 | 3.2% | — |
| AMZN | FY2024 Q4 | revenue_q4 | 188997770604.02 | — | 187792000000.00 | 0.6% | — |
| AMZN | FY2025 Q4 | revenue_q4 | 210730648304.30 | — | 213386000000.00 | 1.2% | — |
| AVGO | FY2021 Q4 | revenue_q4 | 7161353303.28 | — | 7407000000.00 | 3.3% | — |
| AVGO | FY2022 Q4 | revenue_q4 | 8970219577.91 | — | 8930000000.00 | 0.5% | — |
| AVGO | FY2023 Q4 | revenue_q4 | 9780114202.70 | — | 9295000000.00 | 5.2% | — |
| AVGO | FY2024 Q4 | revenue_q4 | 13803551270.96 | — | 14054000000.00 | 1.8% | — |
| AVGO | FY2025 Q4 | revenue_q4 | 16914243655.04 | — | 18015000000.00 | 6.1% | — |
| GOOGL | FY2021 Q4 | revenue_q4 | 39281947290.51 | — | 75325000000.00 | 47.9% | — |
| GOOGL | FY2022 Q4 | revenue_q4 | 75861790437.78 | — | 76048000000.00 | 0.2% | — |
| GOOGL | FY2023 Q4 | revenue_q4 | 76777939648.19 | — | 86310000000.00 | 11.0% | — |
| GOOGL | FY2024 Q4 | revenue_q4 | 92547601981.88 | — | 96469000000.00 | 4.1% | — |
| GOOGL | FY2025 Q4 | revenue_q4 | 107823751141.24 | — | 113828000000.00 | 5.3% | — |
| JPM | FY2021 Q4 | revenue_q4 | 29713329915.84 | — | 29257000000.00 | 1.6% | — |
| JPM | FY2022 Q4 | revenue_q4 | 30054506886.20 | — | 34547000000.00 | 13.0% | — |
| JPM | FY2023 Q4 | revenue_q4 | 38440929137.16 | — | 38574000000.00 | 0.3% | — |
| JPM | FY2024 Q4 | revenue_q4 | 43497969647.79 | — | 42768000000.00 | 1.7% | — |
| JPM | FY2025 Q4 | revenue_q4 | 43860239658.63 | — | 45798000000.00 | 4.2% | — |
| MSFT | FY2022 Q4 | revenue_q4 | 55413360779.43 | — | 51865000000.00 | 6.8% | — |
| MSFT | FY2023 Q4 | revenue_q4 | 57678947393.21 | — | 56189000000.00 | 2.7% | — |
| MSFT | FY2024 Q4 | revenue_q4 | 65353708588.14 | — | 64727000000.00 | 1.0% | — |
| MSFT | FY2025 Q4 | revenue_q4 | 74220150529.20 | — | 76441000000.00 | 2.9% | — |
| MSFT | FY2026 Q4 | revenue_q4 | 87611175782.52 | — | 90007000000.00 | 2.7% | — |
| NVDA | FY2022 Q4 | revenue_q4 | 7959377704.58 | — | 7643000000.00 | 4.1% | — |
| NVDA | FY2023 Q4 | revenue_q4 | 8315104953.28 | — | 6051000000.00 | 37.4% | — |
| NVDA | FY2024 Q4 | revenue_q4 | 15411547980.94 | — | 22103000000.00 | 30.3% | — |
| NVDA | FY2025 Q4 | revenue_q4 | 36230696275.44 | — | 39331000000.00 | 7.9% | — |
| NVDA | FY2026 Q4 | revenue_q4 | 61049430641.45 | — | 68127000000.00 | 10.4% | — |
