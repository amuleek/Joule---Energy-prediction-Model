"""
Shared forecast horizons: calendar days ahead from today.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

try:
    from config import PRODUCT_HORIZON_CAPS
except ImportError:
    PRODUCT_HORIZON_CAPS = {}

# (key, days_ahead, max_abs_change_fraction, display_label)
PREDICTION_HORIZONS: List[Tuple[str, int, float, str]] = [
    ("day_1", 1, 0.03, "Tomorrow (Day 1)"),
    ("day_4", 4, 0.08, "Day 4"),
    ("day_7", 7, 0.10, "Day 7"),
]


def max_frac_for(horizon_key: str, product_key: Optional[str] = None) -> float:
    """Per-product cap overrides (tighter for RBOB day-1)."""
    if product_key and product_key in PRODUCT_HORIZON_CAPS:
        cap = PRODUCT_HORIZON_CAPS[product_key].get(horizon_key)
        if cap is not None:
            return float(cap)
    for key, _days, max_frac, _label in PREDICTION_HORIZONS:
        if key == horizon_key:
            return max_frac
    return 0.03

# Backward compatibility for older code paths
LEGACY_ALIASES = {
    "next_day": "day_1",
    "next_week": "day_4",
    "biweekly": "day_7",
    "monthly": "day_7",
}

MAX_FORECAST_PERIODS = max(h[1] for h in PREDICTION_HORIZONS)


def step_index(days_ahead: int) -> int:
    """0-based model step for the Nth calendar day ahead (day 1 → 0)."""
    return max(0, days_ahead - 1)


def horizon_keys() -> List[str]:
    return [h[0] for h in PREDICTION_HORIZONS]
