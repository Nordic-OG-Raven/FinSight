"""
Tests for database/fx_rates.py. Offline: USD is a no-op, and a pre-seeded cache is served
without touching the network (the cache-hit path the loader relies on for reproducibility).
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.fx_rates import rate_to_usd  # noqa: E402


def test_usd_is_identity():
    assert rate_to_usd("USD", date(2025, 12, 31)) == 1.0


def test_cache_hit_avoids_network():
    cache = {"DKK": {"2025-12-31": 0.157319}, "EUR": {"2025-12-31": 1.175}}
    assert rate_to_usd("DKK", date(2025, 12, 31), _cache=cache) == 0.157319
    assert rate_to_usd("EUR", date(2025, 12, 31), _cache=cache) == 1.175


def test_conversion_math_is_multiplicative():
    cache = {"DKK": {"2025-12-31": 0.157319}}
    dkk_value = 309_100_000_000.0            # NVO FY2025 revenue in DKK
    usd = dkk_value * rate_to_usd("DKK", date(2025, 12, 31), _cache=cache)
    assert 45e9 < usd < 52e9                 # ≈ $48.6B


if __name__ == "__main__":
    import traceback
    fails = 0
    for n, fn in sorted(globals().items()):
        if n.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS {n}")
            except Exception:
                fails += 1; print(f"FAIL {n}"); traceback.print_exc()
    sys.exit(1 if fails else 0)
