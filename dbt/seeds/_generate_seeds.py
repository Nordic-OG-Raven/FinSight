"""Generate dbt seeds from the authoritative Python definitions, so silver's conformance
reference data can never drift from the extraction/loader logic.

Produces:
  seeds/canonical_labels.csv  (concept, canonical_label, priority)  <- canonical_labels.CANONICAL
  seeds/fx_rates.csv          (currency, rate_date, rate_to_usd)    <- database/fx_rates.json

Re-run whenever the canonical map or the FX cache changes:
    .venv/bin/python dbt/seeds/_generate_seeds.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from src.extraction.canonical_labels import CANONICAL  # noqa: E402

SEEDS = Path(__file__).resolve().parent


def gen_canonical() -> int:
    rows = []
    for label, concepts in CANONICAL.items():
        for priority, concept in enumerate(concepts):
            rows.append((concept, label, priority))
    out = SEEDS / "canonical_labels.csv"
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["concept", "canonical_label", "priority"])
        w.writerows(rows)
    return len(rows)


def gen_fx() -> int:
    cache = json.loads((ROOT / "database" / "fx_rates.json").read_text())
    rows = []
    for ccy, by_date in cache.items():
        for d, rate in by_date.items():
            rows.append((ccy, d, rate))
    rows.sort()
    out = SEEDS / "fx_rates.csv"
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["currency", "rate_date", "rate_to_usd"])
        w.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    print(f"canonical_labels.csv: {gen_canonical()} rows")
    print(f"fx_rates.csv:         {gen_fx()} rows")
