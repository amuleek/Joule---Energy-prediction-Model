"""
Regime-tagged learning from day-1 pred vs NYMEX settle.

After each scored forecast, tag the setup that was active at issue time
(pre-EIA rally, product lag vs crude, weekend gap, clear UP/DOWN) and
update magnitude / fade scales that day-1 overlays read next time.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

REGIME_LEARNING_PATH = "data/regime_learning.json"

REGIME_IDS = (
    "product_lag_catchup",
    "pre_eia_extended_rally",
    "weekend_gap",
    "clear_up",
    "clear_down",
    "crude_gas_divergence",
)

PRODUCTS = ("RBOB_Gasoline", "ULSD_Diesel", "Crude_Oil")

# Defaults when no history yet
DEFAULT_REGIME = {
    "n": 0,
    "under_call_count": 0,
    "over_call_count": 0,
    "direction_miss_count": 0,
    "mean_signed_miss_pp": 0.0,  # predicted_pct - actual_pct; <0 = under-called
    "magnitude_scale": 1.0,
    "blend_boost": 0.0,
    "fade_boost": 0.0,
}


def _empty_store() -> Dict[str, Any]:
    return {
        "updated_at": None,
        "regimes": {
            rid: {pk: dict(DEFAULT_REGIME) for pk in PRODUCTS}
            for rid in REGIME_IDS
        },
        "note": (
            "magnitude_scale multiplies lag-catchup / clear-direction size; "
            "fade_boost strengthens pre-EIA caution; blend_boost raises overlay blend."
        ),
    }


def load_regime_learning(path: str = REGIME_LEARNING_PATH) -> Dict[str, Any]:
    if not os.path.exists(path):
        return _empty_store()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return _empty_store()
    store = _empty_store()
    store["updated_at"] = data.get("updated_at")
    for rid in REGIME_IDS:
        src = (data.get("regimes") or {}).get(rid) or {}
        for pk in PRODUCTS:
            row = dict(DEFAULT_REGIME)
            row.update(src.get(pk) or {})
            store["regimes"][rid][pk] = row
    return store


def save_regime_learning(store: Dict[str, Any], path: str = REGIME_LEARNING_PATH) -> None:
    os.makedirs(os.path.dirname(path) or "data", exist_ok=True)
    store["updated_at"] = datetime.now().isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


def get_regime_params(regime_id: str, product_key: str) -> Dict[str, float]:
    """Overlay knobs for one regime × product."""
    store = load_regime_learning()
    row = ((store.get("regimes") or {}).get(regime_id) or {}).get(product_key) or {}
    return {
        "magnitude_scale": float(row.get("magnitude_scale") or 1.0),
        "blend_boost": float(row.get("blend_boost") or 0.0),
        "fade_boost": float(row.get("fade_boost") or 0.0),
        "n": int(row.get("n") or 0),
        "mean_signed_miss_pp": float(row.get("mean_signed_miss_pp") or 0.0),
    }


def _history_asof(issued_date: str):
    try:
        from live_prices import load_official_price_history
        import pandas as pd

        hist = load_official_price_history()
        if hist is None or hist.empty:
            return None
        cutoff = pd.Timestamp(issued_date)
        return hist[pd.to_datetime(hist["date"]) <= cutoff].copy()
    except Exception:
        return None


def _hours_to_eia(meta: Dict[str, Any]) -> Optional[float]:
    cal = meta.get("catalyst_calendar") or {}
    nxt = cal.get("next_high_impact") or cal.get("next") or {}
    if str(nxt.get("event_id") or "") != "eia":
        return None
    try:
        return float(nxt.get("hours_to"))
    except (TypeError, ValueError):
        return None


def detect_issue_regimes(
    product_key: str,
    issued_date: str,
    archive_meta: Optional[Dict[str, Any]] = None,
    *,
    predicted_pct: Optional[float] = None,
) -> List[str]:
    """
    Regimes active when the forecast was issued (from archive meta + settles through issue date).
    """
    meta = archive_meta or {}
    regimes: List[str] = []
    hist = _history_asof(issued_date)

    try:
        from live_prices import recent_session_return_pct
        from day1_precision import (
            LAG_CRUDE_TRIGGER_PCT,
            LAG_GAP_TRIGGER_PP,
            THRUST_LOOKBACK_SESSIONS,
            THRUST_TRIGGER_PCT,
            CRUDE_RALLY_DIVERGENCE_CRUDE_MIN_PCT,
            CRUDE_RALLY_DIVERGENCE_GAS_MAX_PCT,
            CRUDE_RALLY_DIVERGENCE_DIVERGENCE_PP,
        )
    except ImportError:
        recent_session_return_pct = None  # type: ignore
        LAG_CRUDE_TRIGGER_PCT = 1.5
        LAG_GAP_TRIGGER_PP = 1.0
        THRUST_LOOKBACK_SESSIONS = 3
        THRUST_TRIGGER_PCT = 4.0

        CRUDE_RALLY_DIVERGENCE_CRUDE_MIN_PCT = 1.0
        CRUDE_RALLY_DIVERGENCE_GAS_MAX_PCT = 0.35
        CRUDE_RALLY_DIVERGENCE_DIVERGENCE_PP = 1.0

    hours_eia = _hours_to_eia(meta)
    prod_3d = None
    crude_1d = None
    prod_1d = None
    if hist is not None and recent_session_return_pct is not None:
        try:
            prod_3d = recent_session_return_pct(
                product_key, days=THRUST_LOOKBACK_SESSIONS, history=hist
            )
            crude_1d = recent_session_return_pct("Crude_Oil", days=1, history=hist)
            prod_1d = recent_session_return_pct(product_key, days=1, history=hist)
        except Exception:
            pass

    # Pre-EIA + extended rally (Wed Aug 19 style miss)
    if (
        hours_eia is not None
        and 0 < hours_eia <= 20
        and prod_3d is not None
        and prod_3d >= THRUST_TRIGGER_PCT
    ):
        regimes.append("pre_eia_extended_rally")

    # Product lagged crude rally (Fri Aug 21 style under-call)
    if (
        product_key != "Crude_Oil"
        and crude_1d is not None
        and prod_1d is not None
        and crude_1d >= LAG_CRUDE_TRIGGER_PCT
        and (crude_1d - prod_1d) >= LAG_GAP_TRIGGER_PP
    ):
        regimes.append("product_lag_catchup")

    # Weekend / holiday gap into next session
    day1_meta = (meta.get("day1_consensus") or {}).get(product_key) or {}
    gap = day1_meta.get("gap_risk") or meta.get("gap_risk") or {}
    if gap.get("weekend_crossing") or (isinstance(gap.get("reasons"), list) and any(
        "weekend" in str(r).lower() for r in gap["reasons"]
    )):
        regimes.append("weekend_gap")
    else:
        try:
            from live_prices import is_weekend_gap_session

            if hist is not None and is_weekend_gap_session(hist):
                regimes.append("weekend_gap")
        except Exception:
            pass

    # Crude bid / gasoline weak — crack compression (Mon Aug 31 style miss)
    if product_key == "RBOB_Gasoline":
        div_overlay = day1_meta.get("crude_rally_gasoline_divergence")
        if div_overlay:
            regimes.append("crude_gas_divergence")
        elif (
            crude_1d is not None
            and prod_1d is not None
            and crude_1d >= CRUDE_RALLY_DIVERGENCE_CRUDE_MIN_PCT
            and prod_1d <= CRUDE_RALLY_DIVERGENCE_GAS_MAX_PCT
            and (crude_1d - prod_1d) >= CRUDE_RALLY_DIVERGENCE_DIVERGENCE_PP
        ):
            regimes.append("crude_gas_divergence")

    # Clear directional call (for magnitude calibration)
    if predicted_pct is not None:
        if predicted_pct >= 0.40:
            regimes.append("clear_up")
        elif predicted_pct <= -0.40:
            regimes.append("clear_down")

    # Deduplicate preserving order
    seen = set()
    out: List[str] = []
    for r in regimes:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _signed_miss_pp(att: Dict[str, Any]) -> Optional[float]:
    """predicted % change − actual % change (same spot base)."""
    try:
        spot = float(att.get("spot_at_issue") or 0)
        pred = float(att.get("predicted") or 0)
        actual = float(att.get("actual") or 0)
        if spot <= 0:
            # fall back to attribution fields
            actual_move = float(att.get("actual_move_pct") or 0)
            # reconstruct pred move if possible
            if pred > 0 and actual > 0 and actual_move != 0:
                # spot ≈ actual / (1 + move/100)
                spot = actual / (1.0 + actual_move / 100.0)
            else:
                return None
        pred_pct = (pred / spot - 1.0) * 100.0
        act_pct = (actual / spot - 1.0) * 100.0
        return pred_pct - act_pct
    except Exception:
        return None


def _ema(old: float, new: float, n: int, alpha: float = 0.25) -> float:
    if n <= 1:
        return new
    return (1.0 - alpha) * old + alpha * new


def update_regime_learning(attributions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Update regime scales from day-1 attributions that include a `regimes` list
    and predicted/actual prices.
    """
    store = load_regime_learning()
    regimes_root = store.setdefault("regimes", {})

    for att in attributions:
        if att.get("horizon") != "day_1":
            continue
        pk = att.get("product")
        if pk not in PRODUCTS:
            continue
        tags = att.get("regimes") or []
        if not tags:
            continue
        miss = _signed_miss_pp(att)
        if miss is None:
            continue
        dir_miss = not bool(att.get("direction_correct"))

        for rid in tags:
            if rid not in REGIME_IDS:
                continue
            regimes_root.setdefault(rid, {})
            row = dict(DEFAULT_REGIME)
            row.update(regimes_root[rid].get(pk) or {})
            n = int(row.get("n") or 0) + 1
            row["n"] = n
            row["mean_signed_miss_pp"] = round(
                _ema(float(row.get("mean_signed_miss_pp") or 0.0), miss, n), 4
            )

            scale = float(row.get("magnitude_scale") or 1.0)
            blend = float(row.get("blend_boost") or 0.0)
            fade = float(row.get("fade_boost") or 0.0)

            if miss < -0.35:  # under-called (pred too small / not bullish enough)
                row["under_call_count"] = int(row.get("under_call_count") or 0) + 1
                if rid in ("product_lag_catchup", "clear_up", "weekend_gap"):
                    scale = min(1.85, scale + 0.07)
                    blend = min(0.20, blend + 0.025)
                if rid == "pre_eia_extended_rally":
                    # Under-call into EIA is rarer; don't weaken fade
                    fade = max(0.0, fade - 0.01)
            elif miss > 0.35:  # over-called
                row["over_call_count"] = int(row.get("over_call_count") or 0) + 1
                if rid == "pre_eia_extended_rally":
                    fade = min(0.25, fade + 0.04)
                    scale = max(0.75, scale - 0.04)
                if rid in ("product_lag_catchup", "clear_up"):
                    scale = max(0.75, scale - 0.05)
                    blend = max(0.0, blend - 0.02)
                if rid == "clear_down":
                    scale = min(1.6, scale + 0.05)

            if dir_miss:
                row["direction_miss_count"] = int(row.get("direction_miss_count") or 0) + 1
                if rid == "pre_eia_extended_rally":
                    fade = min(0.30, fade + 0.05)
                if rid == "crude_gas_divergence":
                    # Model called gas UP when crude bid + gas weak — trust divergence overlay more
                    blend = min(0.32, blend + 0.05)
                    fade = min(0.22, fade + 0.03)

            if rid == "crude_gas_divergence" and miss > 0.35:
                row["over_call_count"] = int(row.get("over_call_count") or 0) + 1
                blend = min(0.35, blend + 0.04)
                scale = max(0.80, scale - 0.03)
            elif rid == "crude_gas_divergence" and miss < -0.35:
                row["under_call_count"] = int(row.get("under_call_count") or 0) + 1
                scale = min(1.65, scale + 0.05)

            row["magnitude_scale"] = round(scale, 3)
            row["blend_boost"] = round(blend, 3)
            row["fade_boost"] = round(fade, 3)
            regimes_root[rid][pk] = row

    store["regimes"] = regimes_root
    save_regime_learning(store)
    return store


def enrich_attribution_with_regimes(att: Dict[str, Any]) -> Dict[str, Any]:
    """Attach issue-time regimes + signed miss to an attribution row."""
    if att.get("horizon") != "day_1":
        return att
    issued = str(att.get("issued_date") or "")
    pk = att.get("product") or ""
    archive_meta: Dict[str, Any] = {}
    predicted_pct = None
    try:
        path = os.path.join("data", "predictions_archive", f"{issued}.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                archive = json.load(f)
            preds = archive.get("predictions") or {}
            archive_meta = preds.get("_meta") or {}
            block = preds.get(pk) or {}
            spot = float(att.get("spot_at_issue") or block.get("current_price") or 0)
            pred = float(att.get("predicted") or (block.get("day_1") or {}).get("price") or 0)
            if spot > 0 and pred > 0:
                predicted_pct = (pred / spot - 1.0) * 100.0
                att["spot_at_issue"] = spot
    except Exception:
        pass

    att["regimes"] = detect_issue_regimes(
        pk, issued, archive_meta, predicted_pct=predicted_pct
    )
    miss = _signed_miss_pp(att)
    if miss is not None:
        att["signed_miss_pp"] = round(miss, 3)
    return att


def apply_clear_direction_scale(
    product_key: str,
    consensus_pct: float,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """
    Scale a clear directional day-1 consensus using learned clear_up / clear_down
    magnitude (helps systematic under-calls like Fri Aug 21).
    """
    if consensus_pct >= 0.40:
        rid = "clear_up"
    elif consensus_pct <= -0.40:
        rid = "clear_down"
    else:
        return consensus_pct, None
    params = get_regime_params(rid, product_key)
    if int(params.get("n") or 0) < 2:
        return consensus_pct, None
    scale = float(params.get("magnitude_scale") or 1.0)
    # Only amplify under-call regimes; don't explode
    if rid == "clear_up" and scale <= 1.02:
        return consensus_pct, None
    if rid == "clear_down" and scale <= 1.02:
        return consensus_pct, None
    # Cap amplification
    scale = max(0.85, min(1.55, scale))
    adjusted = consensus_pct * scale
    # Extra nudge from mean under-call (half of historical miss, capped)
    mean_miss = float(params.get("mean_signed_miss_pp") or 0.0)
    if rid == "clear_up" and mean_miss < -0.25:
        adjusted += min(0.55, -0.35 * mean_miss)
    if rid == "clear_down" and mean_miss > 0.25:
        adjusted -= min(0.55, 0.35 * mean_miss)
    return adjusted, {
        "regime": rid,
        "magnitude_scale": round(scale, 3),
        "mean_signed_miss_pp": round(mean_miss, 3),
        "n": int(params.get("n") or 0),
        "consensus_before": round(consensus_pct, 4),
        "consensus_after": round(adjusted, 4),
    }


def get_divergence_overlay_params(product_key: str) -> Dict[str, float]:
    """Learned knobs for crude-up / gasoline-weak divergence overlay."""
    if product_key != "RBOB_Gasoline":
        return {"blend_boost": 0.0, "fade_boost": 0.0, "magnitude_scale": 1.0, "n": 0}
    params = get_regime_params("crude_gas_divergence", product_key)
    return {
        "blend_boost": float(params.get("blend_boost") or 0.0),
        "fade_boost": float(params.get("fade_boost") or 0.0),
        "magnitude_scale": float(params.get("magnitude_scale") or 1.0),
        "n": int(params.get("n") or 0),
        "direction_miss_count": int(
            ((load_regime_learning().get("regimes") or {})
             .get("crude_gas_divergence") or {})
            .get(product_key, {})
            .get("direction_miss_count") or 0
        ),
    }
