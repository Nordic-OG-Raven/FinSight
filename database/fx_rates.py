"""
FX rates to USD, for normalizing foreign-currency facts to a common reporting currency
(PRD §2.3). Source: ECB daily reference rates (free, no key). Rates are cached in a committed
JSON file (data/fx_rates.json) so loads are reproducible and work offline once a rate is known
— only genuinely-new (currency, date) pairs hit the network.

ECB publishes <CCY> per 1 EUR. So:
    EUR -> USD  = USD_per_EUR                     (series D.USD.EUR)
    CCY -> USD  = USD_per_EUR / CCY_per_EUR        (D.USD.EUR and D.<CCY>.EUR)
Non-trading days have no observation; we take the latest rate on or before the date.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import date, timedelta
from pathlib import Path

# Committed next to this module (data/ is gitignored) so the seed ships with the repo and
# loads stay reproducible/offline; the loader appends newly-fetched rates here.
_CACHE_PATH = Path(__file__).resolve().parent / "fx_rates.json"
_ECB = "https://data-api.ecb.europa.eu/service/data/EXR/D.{ccy}.EUR.SP00.A"


def _load_cache() -> dict:
    if _CACHE_PATH.exists():
        return json.loads(_CACHE_PATH.read_text())
    return {}


def _save_cache(cache: dict) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True))


def _ecb_per_eur(ccy: str, as_of: date) -> float:
    """Latest <ccy>-per-EUR observation on or before `as_of` (10-day lookback for holidays)."""
    url = (_ECB.format(ccy=ccy)
           + f"?startPeriod={as_of - timedelta(days=10)}&endPeriod={as_of}&format=csvdata")
    with urllib.request.urlopen(url, timeout=15) as r:
        text = r.read().decode()
    best_d, best_v = None, None
    for line in text.splitlines():
        parts = line.split(",")
        if len(parts) < 8:
            continue
        try:
            d = date.fromisoformat(parts[6])
            v = float(parts[7])
        except (ValueError, IndexError):
            continue
        if d <= as_of and (best_d is None or d > best_d):
            best_d, best_v = d, v
    if best_v is None:
        raise ValueError(f"no ECB {ccy}/EUR observation on or before {as_of}")
    return best_v


def rate_to_usd(currency: str, as_of: date, _cache: dict | None = None) -> float:
    """Multiplicative rate: value_in_usd = value_in_<currency> * rate_to_usd(currency, date).
    USD -> 1.0. Cached per (currency, date) in data/fx_rates.json."""
    if currency == "USD":
        return 1.0
    cache = _cache if _cache is not None else _load_cache()
    key = as_of.isoformat()
    hit = cache.get(currency, {}).get(key)
    if hit is not None:
        return hit
    usd_per_eur = _ecb_per_eur("USD", as_of)
    rate = usd_per_eur if currency == "EUR" else usd_per_eur / _ecb_per_eur(currency, as_of)
    cache.setdefault(currency, {})[key] = rate
    if _cache is None:
        _save_cache(cache)
    return rate


if __name__ == "__main__":
    import sys
    c = sys.argv[1] if len(sys.argv) > 1 else "DKK"
    d = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date(2025, 12, 31)
    print(f"1 {c} = {rate_to_usd(c, d):.6f} USD  @ {d}")
