"""
Tomorrow (day-1) precision: merge ensemble, XGB, and VAR into one consensus move.
When short-term models disagree with VAR, trust ensemble/ML more.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from forecast_horizons import max_frac_for


def _sign(x: float, eps: float = 0.08) -> int:
    if x > eps:
        return 1
    if x < -eps:
        return -1
    return 0


def _clamp_return_pct(return_pct: float, product_key: str) -> float:
    cap = max_frac_for("day_1", product_key) * 100.0
    return max(-cap, min(cap, return_pct))


def _set_day1(block: Dict[str, Any], current: float, return_pct: float, product_key: str) -> None:
    return_pct = _clamp_return_pct(return_pct, product_key)
    price = current * (1.0 + return_pct / 100.0)
    block["day_1"] = float(price)
    block["next_day"] = float(price)
    block["day_1_change"] = float(return_pct)
    block["next_day_change"] = float(return_pct)
    direction = "UP" if return_pct > 0.08 else "DOWN" if return_pct < -0.08 else "FLAT"
    block["day_1_direction"] = direction
    block["next_day_direction"] = direction


def reconcile_day1_precision(
    results: Dict[str, Any],
    ensemble_meta: Optional[Dict[str, Any]] = None,
    xgb_info: Optional[Dict[str, Any]] = None,
    current_prices: Optional[Dict[str, float]] = None,
    context_meta: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Override day_1/next_day using weighted consensus of ensemble + ML + VAR base.
    Returns updated results and reconciliation meta for _meta.day1_consensus.
    """
    ensemble_meta = ensemble_meta or {}
    xgb_info = xgb_info or {}
    current_prices = current_prices or {}
    context_meta = context_meta or {}
    geo_risk = float(context_meta.get("geo_risk_score") or 0)
    meta_out: Dict[str, Any] = {}

    for product_key, block in results.items():
        if not isinstance(block, dict) or product_key.startswith("_"):
            continue
        block["_product_key"] = product_key
        current = float(current_prices.get(product_key) or block.get("current_price") or 0)
        if current <= 0:
            continue
        block["current_price"] = current

        base_ret = float(block.get("day_1_change", block.get("next_day_change", 0)) or 0)
        weighted: list[tuple[float, float, str]] = []

        ens = ensemble_meta.get(product_key) or {}
        ens_ret = ens.get("combined_return_pct")
        ens_sign = _sign(float(ens_ret)) if ens_ret is not None else 0
        base_sign = _sign(base_ret)

        if ens_ret is not None:
            ens_w = 0.55
            if geo_risk >= 0.07:
                ens_w = 0.62
            weighted.append((ens_w, float(ens_ret), "ensemble"))

        if product_key == "RBOB_Gasoline" and xgb_info.get("used"):
            x_ret = xgb_info.get("predicted_return_pct")
            if x_ret is not None:
                weighted.append((0.30, float(x_ret), "xgb"))

        base_w = 0.15
        if ens_sign and base_sign and ens_sign != base_sign:
            base_w = 0.05
        if geo_risk >= 0.07 and ens_sign and base_sign and ens_sign != base_sign:
            base_w = 0.03

        if product_key == "RBOB_Gasoline" and xgb_info.get("used"):
            x_ret = float(xgb_info.get("predicted_return_pct", 0))
            if _sign(x_ret) and ens_sign and _sign(x_ret) == ens_sign:
                base_w = 0.03
                weighted = [(0.50, float(ens_ret), "ensemble"), (0.47, x_ret, "xgb")]

        # Crude & diesel: when geo risk is elevated, lean on ensemble over VAR base
        if product_key in ("Crude_Oil", "ULSD_Diesel") and geo_risk >= 0.07 and ens_ret is not None:
            base_w = 0.08 if ens_sign != base_sign else 0.12
            weighted = [(0.65, float(ens_ret), "ensemble")]

        total_w = sum(w for w, _, _ in weighted) + base_w
        consensus = sum(w * r for w, r, _ in weighted) + base_w * base_ret
        consensus /= total_w if total_w else 1.0

        # When headlines/geopolitics dominate, allow a slightly larger day-1 move
        if geo_risk >= 0.07 and ens_ret is not None and abs(float(ens_ret)) > abs(consensus):
            consensus = 0.72 * float(ens_ret) + 0.28 * consensus

        _set_day1(block, current, consensus, product_key)
        meta_out[product_key] = {
            "consensus_return_pct": round(consensus, 4),
            "base_return_pct": round(base_ret, 4),
            "ensemble_return_pct": round(float(ens_ret), 4) if ens_ret is not None else None,
            "xgb_return_pct": round(float(xgb_info.get("predicted_return_pct")), 4)
            if product_key == "RBOB_Gasoline" and xgb_info.get("used")
            else None,
            "weights": {label: w for w, _, label in weighted},
            "base_weight": base_w,
        }

    return results, meta_out
