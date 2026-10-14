# FinSight — Roadmap

v1.0 (see [`README.md`](README.md)) does one thing well: turn a US-GAAP 10-K into a clean,
validated, queryable set of annual financials. This document holds the fuller ambition — the
direction FinSight is headed, without time commitments. Items are roughly ordered by the
leverage they'd add.

## Data integrity (highest priority)

- **Fix period assignment.** Facts are keyed to a shared `period_id` by date range, so filers
  with different fiscal calendars can collide, and some comparative/quarterly facts land on
  the wrong fiscal period. Scope periods per company (or per filing) so multi-year and
  comparative queries are trustworthy, not just current-year headlines.
- **Consolidate the normalized-label vocabulary.** Remove the inconsistencies v1.0 documents
  (e.g. several labels for "Total liabilities & equity"; equity concepts that over-aggregate).
  One canonical label per economic line, with a tested mapping per taxonomy.

## Validation that actually audits

- Replace the heuristic reconciliation checks (income-statement math, cash-flow
  reconciliation, normalization-conflict count) — which currently false-positive and are
  therefore downgraded to warnings — with per-filer-robust logic that reconciles against the
  statement as the filer reports it. Goal: "validated" means audited, not just integrity-gated.
- Cross-statement consistency and outlier/anomaly detection.

## Multi-taxonomy support

- **IFRS / 20-F parity.** Verify and fix foreign filers (Novo Nordisk, Sanofi, etc.) — the
  taxonomy, statement structure, and tax/equity concepts differ from US-GAAP and were the
  source of the original failures that led to excluding them from v1.0.
- ESEF and company-specific extension handling.

## Scale & breadth

- Grow the curated reference dataset well beyond six companies, deliberately including other
  industries (banks and insurers have materially different statements) to surface and fix
  edge cases.
- Currency normalization to a common reporting currency.

## Serving & product

- **Re-host** the API and database (the earlier Railway/Azure/Fly.io deployment was retired —
  see `docs/archive/deployment-history/`) and restore a live demo.
- Wire up and verify the existing Next.js frontend against a deployed backend.
- Natural-language query (NP2SQL) endpoint, fully tested.

## Analysis features

- Multi-year comparative analysis and common financial ratios (P/E, ROE, debt-to-equity).
- Peer-comparison module.
- Export (Excel / CSV), and a GraphQL API.
- ML-based anomaly detection on the normalized facts.
