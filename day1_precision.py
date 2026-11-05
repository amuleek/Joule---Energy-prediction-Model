"""
Tomorrow (day-1) precision: merge ensemble, XGB, and VAR into one consensus move.
When short-term models disagree with VAR, trust ensemble/ML more.
After sharp prior-session moves, lean toward tape momentum (continuation).
After extreme single-session spikes (+4%+), lean toward modest pullback (fade).
Across weekend/holiday gaps with elevated news risk, widen caps and blend overnight tape.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from forecast_horizons import max_frac_for

# Pull day-1 forecast toward recent session move when |1d change| exceeds this
MOMENTUM_TRIGGER_PCT = 2.0
MOMENTUM_CONTINUATION = 0.35
MAX_MOMENTUM_BLEND = 0.55
# After a large single-session rally, expect mean-reversion next day
POST_SPIKE_TRIGGER_PCT = 3.5
POST_SPIKE_FADE_RATIO = 0.38
MAX_POST_SPIKE_BLEND = 0.72
# When crude blows off, fade the whole complex (RBOB can lag the spike %)
COMPLEX_SPIKE_TRIGGER_PCT = 4.0
COMPLEX_FADE_RATIO = 0.28
MAX_COMPLEX_FADE_BLEND = 0.55
# Weekend / holiday gap risk: allow larger day-1 moves and use overnight tape
GAP_RISK_THRESHOLD = 0.40
GAP_CAP_MULT = 1.85
OVERNIGHT_GAP_TRIGGER_PCT = 1.5
WEEKEND_OVERNIGHT_GAP_TRIGGER_PCT = 1.0
OVERNIGHT_GAP_KEEP = 0.55
MAX_OVERNIGHT_BLEND = 0.70
# Multi-day thrust: quiet 1d inside a strong 3-session trend
THRUST_LOOKBACK_SESSIONS = 3
THRUST_TRIGGER_PCT = 4.0
THRUST_KEEP = 0.30
MAX_THRUST_BLEND = 0.50
# After a hard washout (not spike->dump), expect a modest rebound
WASHOUT_1D_TRIGGER_PCT = -2.5
WASHOUT_2D_TRIGGER_PCT = -4.0
WASHOUT_3D_TRIGGER_PCT = -5.5
WASHOUT_BOUNCE_RATIO = 0.32
MAX_WASHOUT_BOUNCE_BLEND = 0.58
# Multi-day selloff: continue lower (don't bounce-call) — Aug 24→25 miss
SELLOFF_CONT_1D_PCT = -1.5
SELLOFF_CONT_2D_PCT = -3.0
SELLOFF_CONT_PREV_PCT = -0.75
SELLOFF_HARD_1D_PCT = -2.3
SELLOFF_CONT_KEEP = 0.50
MAX_SELLOFF_CONT_BLEND = 0.58
# Crude-led selloff on products: require product weakness, not just crude grind
SELLOFF_CRUDE_LED_PRODUCT_MIN_PCT = -0.75
SELLOFF_PRODUCT_MILD_ABS_PCT = 1.0
SELLOFF_CRUDE_LED_BLEND_CAP = 0.28
# After a hard down day, overnight tape flips day-1 sooner
PRIOR_DOWN_OVERNIGHT_TRIGGER_PCT = -2.0
PRIOR_DOWN_OVERNIGHT_GAP_PCT = 1.0
# Product lagged a crude rally → expect catch-up (Fri Aug 21 RBOB miss)
LAG_CRUDE_TRIGGER_PCT = 1.5
LAG_GAP_TRIGGER_PP = 1.0
LAG_CATCHUP_KEEP = 0.42
MAX_LAG_CATCHUP_BLEND = 0.58
# Flat XGB should not cancel a clear ensemble bid
FLAT_XGB_ABS_PCT = 0.15
ENSEMBLE_CLEAR_PCT = 0.50
FLAT_XGB_WEIGHT = 0.10
# Clear ML bearish should not be drowned by bullish ensemble + overnight tape
CLEAR_XGB_BEARISH_PCT = 0.50
CLEAR_XGB_BEARISH_WEIGHT = 0.48
# Crude complex rip: size ULSD toward crude/live tape (Sep 1 +6% diesel miss)
DISTILLATE_CRUDE_RALLY_TRIGGER_PCT = 2.0
DISTILLATE_CRUDE_RALLY_KEEP = 0.72
MAX_DISTILLATE_CRUDE_RALLY_BLEND = 0.68
# Fresh inventory draw + strong product tape: preserve event follow-through
POST_INVENTORY_MOMENTUM_Z = -0.50
POST_INVENTORY_MOMENTUM_TRIGGER_PCT = 1.25
POST_INVENTORY_MOMENTUM_KEEP = 0.70
MAX_POST_INVENTORY_MOMENTUM_BLEND = 0.50
# Crude bid on live tape but RBOB flat/down — crack compression (Mon Aug 31 miss)
CRUDE_RALLY_DIVERGENCE_CRUDE_MIN_PCT = 1.0
CRUDE_RALLY_DIVERGENCE_GAS_MAX_PCT = 0.35
CRUDE_RALLY_DIVERGENCE_DIVERGENCE_PP = 1.0
CRUDE_RALLY_DIVERGENCE_KEEP = 0.58
MAX_CRUDE_RALLY_DIVERGENCE_BLEND = 0.78
CRUDE_RALLY_DIVERGENCE_PRIOR_RALLY_PCT = 2.0
# Gas bounce + diesel fade after product rotation day (Wed Sep 3 miss)
GAS_ROTATION_PRIOR_MAX_PCT = -1.5
GAS_ROTATION_CRUDE_FLOOR_PCT = -0.75
GAS_ROTATION_DIVERGENCE_PP = 1.0
GAS_ROTATION_BOUNCE_RATIO = 0.48
MAX_GAS_ROTATION_BLEND = 0.72
DIESEL_ROTATION_CRACK_MIN = 95.0
DIESEL_ROTATION_PRIOR_MAX_PCT = -0.75
DIESEL_ROTATION_FADE_RATIO = 0.55
MAX_DIESEL_ROTATION_BLEND = 0.70
DIESEL_ROTATION_INV_BUILD_PCT = 0.30
DIESEL_ROTATION_THRUST_LOOKBACK_PCT = 4.0


def _momentum_blend_cap() -> float:
    try:
        from prediction_attribution import load_factor_learning
        rules = (load_factor_learning() or {}).get("global_rules") or {}
        return float(rules.get("momentum_blend_cap", MAX_MOMENTUM_BLEND))
    except Exception:
        return MAX_MOMENTUM_BLEND


def _skip_momentum_overlays() -> bool:
    try:
        from prediction_attribution import load_factor_learning
        rules = (load_factor_learning() or {}).get("global_rules") or {}
        return bool(rules.get("trust_ensemble_over_overlay"))
    except Exception:
        return False
CRUDE_SPILLOVER_TRIGGER_PCT = 3.0
CRUDE_SPILLOVER_FACTOR = 0.22
MAX_CRUDE_SPILLOVER_BLEND = 0.40

BEARISH_SUPPLY_PHRASES = (
    "price cut",
    "cuts oil",
    "cuts prices",
    "cut oil prices",
    "oversupply",
    "supply glut",
    "production increase",
    "output hike",
    "surplus",
    "demand weak",
    "demand slump",
)


def _sign(x: float, eps: float = 0.08) -> int:
    if x > eps:
        return 1
    if x < -eps:
        return -1
    return 0


def _clamp_return_pct(
    return_pct: float,
    product_key: str,
    *,
    cap_mult: float = 1.0,
) -> float:
    cap = max_frac_for("day_1", product_key) * 100.0 * max(1.0, float(cap_mult))
    return max(-cap, min(cap, return_pct))


def _is_forecasting_weekend_gap() -> bool:
    """
    True when the day-1 *target* session crosses a weekend/holiday from last settle.
    Mon evening after Mon settle → Tue is next → False (do not reuse Fri→Mon history).
    """
    try:
        from live_prices import get_nymex_session_close, load_official_price_history, trading_session_offset
        import pandas as pd

        _, as_of, _ = get_nymex_session_close()
        if not as_of:
            from live_prices import _now_et
            return _now_et().weekday() >= 4

        last = pd.Timestamp(as_of).normalize()
        hist = load_official_price_history()
        next_sess = trading_session_offset(last, 1, hist)
        if next_sess is None:
            next_sess = last + pd.offsets.BDay(1)
        gap_days = int((pd.Timestamp(next_sess).normalize() - last).days)
        return gap_days >= 2
    except Exception:
        try:
            from live_prices import _now_et
            return _now_et().weekday() >= 4
        except Exception:
            return False


def assess_gap_risk(
    context_meta: Optional[Dict[str, Any]] = None,
    signal_context: Optional[Dict[str, Any]] = None,
    *,
    weekend_crossing: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Score risk of a large overnight/weekend gap into the next session.
    Used to widen day-1 caps and tilt toward news / overnight tape.
    """
    context_meta = context_meta or {}
    signal_context = signal_context or {}
    if weekend_crossing is None:
        weekend_crossing = _is_forecasting_weekend_gap()

    geo = float(context_meta.get("geo_risk_score") or 0)
    topic = signal_context.get("topic_snapshot") or context_meta.get("topic_snapshot") or {}
    if geo <= 0:
        geo = float(topic.get("geo_risk_score") or 0)
    buckets = topic.get("buckets") or {}
    geo_bucket = float((buckets.get("geopolitical") or {}).get("intensity") or 0)
    shipping = float((buckets.get("shipping") or {}).get("intensity") or 0)
    opec = float((buckets.get("opec") or {}).get("intensity") or 0)

    score = 0.0
    reasons: list[str] = []
    if weekend_crossing:
        score += 0.35
        reasons.append("weekend/holiday gap into next session")
    if geo >= 0.07:
        score += 0.30
        reasons.append(f"elevated geo_risk ({geo:.0%})")
    elif geo >= 0.05:
        score += 0.15
        reasons.append(f"moderate geo_risk ({geo:.0%})")
    if geo_bucket >= 0.25:
        score += 0.20
        reasons.append(f"geopolitical headlines ({geo_bucket:.0%})")
    if shipping >= 0.20:
        score += 0.10
        reasons.append(f"shipping/logistics ({shipping:.0%})")
    if opec >= 0.20:
        score += 0.08
        reasons.append(f"OPEC/supply headlines ({opec:.0%})")

    cal = signal_context.get("catalyst_calendar") or context_meta.get("catalyst_calendar") or {}
    bump = float(cal.get("gap_bump") or 0)
    if bump > 0:
        score += bump
        for r in (cal.get("gap_reasons") or [])[:2]:
            reasons.append(str(r))

    score = min(1.0, score)
    # Strong geo/news alone (midweek shock risk) still widens caps
    active = score >= GAP_RISK_THRESHOLD
    if not active and geo >= 0.08 and geo_bucket >= 0.30:
        active = True
        reasons.append("midweek geo shock risk")
        score = max(score, GAP_RISK_THRESHOLD)
    # EIA/API/CPI print window — always treat as gap-capable
    if bump >= 0.20:
        active = True
        score = max(score, GAP_RISK_THRESHOLD)
    # Weekend into Monday is always elevated gap risk (soft Friday != Monday open)
    if weekend_crossing and not active:
        active = True
        score = max(score, GAP_RISK_THRESHOLD)
        reasons.append("weekend session gap")
    cap_mult = GAP_CAP_MULT if active else 1.0
    if active and score >= 0.70:
        cap_mult = max(cap_mult, 2.1)
    if weekend_crossing:
        cap_mult = max(cap_mult, 2.0)
    return {
        "score": round(score, 3),
        "active": active,
        "weekend_crossing": bool(weekend_crossing),
        "cap_mult": cap_mult,
        "reasons": reasons,
    }


def _inventory_print_context(catalyst_calendar: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """EIA/API timing for day-1 — avoid chasing rallies into the print."""
    cal = catalyst_calendar or {}
    nxt = cal.get("next_high_impact") or cal.get("next") or {}
    event_id = str(nxt.get("event_id") or "")
    try:
        hours_to = float(nxt.get("hours_to")) if nxt.get("hours_to") is not None else None
    except (TypeError, ValueError):
        hours_to = None
    pre_eia = event_id == "eia" and hours_to is not None and 0 < hours_to <= 18
    eia_imminent = event_id == "eia" and hours_to is not None and 0 < hours_to <= 20
    post_eia = event_id == "eia" and hours_to is not None and -8 <= hours_to <= 0
    return {
        "pre_eia": pre_eia,
        "eia_imminent": eia_imminent,
        "post_eia": post_eia,
        "hours_to_print": hours_to,
        "event_id": event_id,
        "report": nxt.get("report"),
    }


def _apply_pre_eia_caution(
    product_key: str,
    consensus: float,
    price_history: Optional[Any],
    print_ctx: Dict[str, Any],
    inventory_wow_pct: Optional[float],
    crude_inventory_wow_pct: Optional[float],
    cap_mult: float = 1.0,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """
    Fade extended rallies into EIA/API — chasing a multi-day run into the print
    often reverses (Aug 18 +1.2% gas call into Aug 19 EIA selloff).
    """
    if not print_ctx.get("eia_imminent"):
        return consensus, None
    try:
        from live_prices import recent_session_return_pct
    except ImportError:
        return consensus, None

    mom_3d = recent_session_return_pct(
        product_key, days=THRUST_LOOKBACK_SESSIONS, history=price_history
    )
    adjusted = consensus
    reasons: list[str] = []

    if mom_3d is not None and mom_3d >= THRUST_TRIGGER_PCT and adjusted > 0:
        fade = _clamp_return_pct(-mom_3d * 0.14, product_key, cap_mult=cap_mult)
        blend = min(0.62, mom_3d / 9.0)
        try:
            from regime_learning import get_regime_params

            rp = get_regime_params("pre_eia_extended_rally", product_key)
            fade_boost = max(0.0, min(0.30, float(rp.get("fade_boost") or 0.0)))
            if int(rp.get("n") or 0) >= 1 and fade_boost > 0:
                blend = min(0.78, blend + fade_boost)
                reasons.append(f"learned pre-EIA fade +{fade_boost:.2f}")
        except Exception:
            pass
        adjusted = (1.0 - blend) * adjusted + blend * fade
        reasons.append(f"3-session +{mom_3d:.1f}% into inventory print")

    if product_key != "Crude_Oil" and crude_inventory_wow_pct is not None:
        cw = float(crude_inventory_wow_pct)
        if cw > 3.0 and adjusted > 0:
            cap = 0.15 if product_key == "RBOB_Gasoline" else 0.20
            if adjusted > cap:
                adjusted = cap
                reasons.append(f"crude build +{cw:.1f}% WoW before EIA")
        elif cw > 2.0 and adjusted > 0.25:
            cap = 0.20 if product_key == "RBOB_Gasoline" else 0.30
            if adjusted > cap:
                adjusted = cap
                reasons.append(f"crude build +{cw:.1f}% WoW before EIA")

    if print_ctx.get("pre_eia") and adjusted > 0.55:
        if inventory_wow_pct is None or float(inventory_wow_pct) > -0.8:
            adjusted = min(adjusted, 0.40)
            reasons.append("no sharp product draw — cap pre-EIA bid")

    if abs(adjusted - consensus) < 0.05:
        return consensus, None
    adjusted = _clamp_return_pct(adjusted, product_key, cap_mult=cap_mult)
    return adjusted, {
        "mode": "pre_eia_caution",
        "consensus_before": round(consensus, 4),
        "consensus_after": round(adjusted, 4),
        "three_session_pct": round(mom_3d, 3) if mom_3d is not None else None,
        "hours_to_print": print_ctx.get("hours_to_print"),
        "reasons": reasons,
    }


def _apply_overnight_gap(
    product_key: str,
    consensus: float,
    settle_price: float,
    live_by_product: Optional[Dict[str, float]],
    *,
    gap_risk: Optional[Dict[str, Any]] = None,
    cap_mult: float = 1.0,
    prior_session_pct: Optional[float] = None,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """Blend day-1 toward live overnight move vs last official settle."""
    if not live_by_product or settle_price <= 0:
        return consensus, None

    live = live_by_product.get(product_key)
    gap_pct = None
    source = "own"
    if live is not None and float(live) > 0:
        gap_pct = (float(live) - settle_price) / settle_price * 100.0

    # Missing/weak product tape: follow crude overnight (complex gap into Monday)
    crude_live = live_by_product.get("Crude_Oil")
    crude_gap = None
    if product_key != "Crude_Oil" and crude_live and float(crude_live) > 0:
        try:
            from live_prices import get_nymex_session_close
            closes, _, _ = get_nymex_session_close()
            c_settle = closes.get("Crude")
            if c_settle and float(c_settle) > 0:
                crude_gap = (float(crude_live) - float(c_settle)) / float(c_settle) * 100.0
        except Exception:
            crude_gap = None
        weak_own = gap_pct is None or abs(gap_pct) < OVERNIGHT_GAP_TRIGGER_PCT
        product_opposes_crude = (
            gap_pct is not None
            and crude_gap is not None
            and _sign(gap_pct)
            and _sign(crude_gap)
            and _sign(gap_pct) != _sign(crude_gap)
        )
        if product_opposes_crude:
            # Product tape diverges from crude — follow the product, not crude spill
            source = "product_divergence"
        elif crude_gap is not None and abs(crude_gap) >= OVERNIGHT_GAP_TRIGGER_PCT and weak_own:
            gap_pct = crude_gap * 0.85
            source = "crude_spill"
            live = settle_price * (1.0 + gap_pct / 100.0)

    weekend = bool(gap_risk and gap_risk.get("weekend_crossing"))
    prior_down = (
        prior_session_pct is not None
        and float(prior_session_pct) <= PRIOR_DOWN_OVERNIGHT_TRIGGER_PCT
    )
    trigger = WEEKEND_OVERNIGHT_GAP_TRIGGER_PCT if weekend else OVERNIGHT_GAP_TRIGGER_PCT
    # After a hard down day, trust softer overnight continuation lower
    if prior_down:
        trigger = min(trigger, PRIOR_DOWN_OVERNIGHT_GAP_PCT)

    if gap_pct is None or abs(gap_pct) < trigger:
        return consensus, None

    keep = OVERNIGHT_GAP_KEEP
    blend_cap = MAX_OVERNIGHT_BLEND
    active = bool(gap_risk and gap_risk.get("active"))

    # Sunday night / overnight shock: trust the live tape as primary signal
    if abs(gap_pct) >= 2.0:
        keep = 0.95 if abs(gap_pct) >= 3.5 else 0.90
        blend_cap = 0.97 if abs(gap_pct) >= 3.5 else 0.93
    elif active or weekend:
        keep = 0.85 if abs(gap_pct) >= 2.5 else 0.75
        blend_cap = 0.92
    if weekend and abs(gap_pct) >= trigger:
        keep = max(keep, 0.95)
        blend_cap = max(blend_cap, 0.98)
    if prior_down and gap_pct < 0:
        keep = max(keep, 0.88)
        blend_cap = max(blend_cap, 0.92)

    wide_cap = max(cap_mult, 2.6 if abs(gap_pct) >= 2.5 else 2.2 if weekend else cap_mult)
    target = _clamp_return_pct(gap_pct * keep, product_key, cap_mult=wide_cap)
    blend = min(blend_cap, abs(gap_pct) / 4.0)
    if active or weekend:
        blend = min(blend_cap, blend + 0.30)
    if prior_down and gap_pct < 0:
        blend = min(blend_cap, blend + 0.20)
    adjusted = (1.0 - blend) * consensus + blend * target

    # Never leave day-1 opposite the overnight tape when gap is meaningful
    flip_trigger = trigger
    if abs(gap_pct) >= flip_trigger and _sign(gap_pct) and (
        not _sign(adjusted) or _sign(adjusted) != _sign(gap_pct)
    ):
        floor = max(0.60, abs(target) * 0.70) * (1 if gap_pct > 0 else -1)
        if gap_pct > 0:
            adjusted = max(adjusted, floor, target * 0.85)
        else:
            adjusted = min(adjusted, floor, target * 0.85)
    # Weekend: once overnight dominates, stay near the live gap (don't half-size it)
    if weekend and abs(gap_pct) >= trigger:
        if gap_pct > 0:
            adjusted = max(adjusted, target * 0.90)
        else:
            adjusted = min(adjusted, target * 0.90)
    # After a hard down day, don't leave day-1 UP when overnight is still selling
    if prior_down and gap_pct <= -PRIOR_DOWN_OVERNIGHT_GAP_PCT and adjusted > -0.35:
        adjusted = min(adjusted, target * 0.85, -0.35)

    adjusted = _clamp_return_pct(adjusted, product_key, cap_mult=wide_cap)
    dominates = (
        abs(gap_pct) >= 2.0
        or (weekend and abs(gap_pct) >= 1.0)
        or (prior_down and gap_pct <= -PRIOR_DOWN_OVERNIGHT_GAP_PCT)
    )
    return adjusted, {
        "settle_price": round(settle_price, 4),
        "live_price": round(float(live), 4) if live else None,
        "gap_pct": round(gap_pct, 3),
        "target_pct": round(target, 3),
        "blend": round(blend, 3),
        "source": source,
        "prior_down": bool(prior_down),
        "consensus_before": round(consensus, 4),
        "consensus_after": round(adjusted, 4),
        "dominates": dominates,
    }


def _apply_thrust_continuation(
    product_key: str,
    consensus: float,
    price_history: Optional[Any] = None,
    ensemble_return: Optional[float] = None,
    *,
    gap_risk: Optional[Dict[str, Any]] = None,
    cap_mult: float = 1.0,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """
    Quiet prior session inside a strong multi-day trend — don't flatten day-1.
    Fixes undershoots like Thu soft close -> Fri +3% thrust.
    """
    if _skip_momentum_overlays():
        return consensus, None
    try:
        from live_prices import recent_session_return_pct
    except ImportError:
        return consensus, None

    mom_3d = recent_session_return_pct(
        product_key, days=THRUST_LOOKBACK_SESSIONS, history=price_history
    )
    mom_1d = recent_session_return_pct(product_key, days=1, history=price_history)
    if mom_3d is None or abs(mom_3d) < THRUST_TRIGGER_PCT:
        return consensus, None
    # Strong 1d already handled by momentum / post-spike paths
    if mom_1d is not None and abs(mom_1d) >= MOMENTUM_TRIGGER_PCT:
        return consensus, None

    thrust_sign = _sign(mom_3d)
    ens_sign = _sign(float(ensemble_return)) if ensemble_return is not None else 0
    cons_sign = _sign(consensus)
    if ens_sign and thrust_sign and ens_sign != thrust_sign:
        return consensus, None
    if cons_sign and thrust_sign and cons_sign != thrust_sign and abs(consensus) >= 0.55:
        return consensus, None

    target = _clamp_return_pct(mom_3d * THRUST_KEEP, product_key, cap_mult=cap_mult)
    blend = min(MAX_THRUST_BLEND, abs(mom_3d) / 14.0)
    if gap_risk and gap_risk.get("active"):
        blend = min(MAX_THRUST_BLEND, blend + 0.12)
    # If consensus is nearly flat vs a big week, pull harder toward thrust
    if abs(consensus) < 0.8:
        blend = min(MAX_THRUST_BLEND, blend + 0.10)

    adjusted = (1.0 - blend) * consensus + blend * target
    # Floor: don't leave day-1 below ~22% of the 3-session move when aligned
    floor = abs(mom_3d) * 0.22
    if thrust_sign and abs(adjusted) < floor:
        adjusted = thrust_sign * min(floor, abs(target) if abs(target) > 0 else floor)
    adjusted = _clamp_return_pct(adjusted, product_key, cap_mult=cap_mult)
    return adjusted, {
        "mode": "multi_day_thrust",
        "three_session_pct": round(mom_3d, 3),
        "prior_session_pct": round(mom_1d, 3) if mom_1d is not None else None,
        "target_pct": round(target, 3),
        "blend": round(blend, 3),
        "consensus_before": round(consensus, 4),
        "consensus_after": round(adjusted, 4),
    }


def _multi_day_selloff_stats(
    product_key: str,
    price_history: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Detect 2+ session selloff (grind lower, not spike->dump bounce setup)."""
    try:
        from live_prices import prior_session_return_pct, recent_session_return_pct
    except ImportError:
        return None

    mom_1d = recent_session_return_pct(product_key, days=1, history=price_history)
    mom_2d = recent_session_return_pct(product_key, days=2, history=price_history)
    mom_prev = prior_session_return_pct(product_key, history=price_history)
    if mom_1d is None:
        return None

    # Spike then dump is handled elsewhere as selloff_after_spike
    if (
        mom_prev is not None
        and mom_prev >= POST_SPIKE_TRIGGER_PCT
        and mom_1d <= -MOMENTUM_TRIGGER_PCT
    ):
        return None

    consecutive = (
        mom_prev is not None
        and mom_prev <= SELLOFF_CONT_PREV_PCT
        and mom_1d <= SELLOFF_CONT_1D_PCT
    )
    two_day = (
        mom_2d is not None
        and mom_2d <= SELLOFF_CONT_2D_PCT
        and mom_1d <= SELLOFF_CONT_1D_PCT
    )
    hard_1d = mom_1d <= SELLOFF_HARD_1D_PCT and (
        mom_prev is None or mom_prev < POST_SPIKE_TRIGGER_PCT
    )
    if not consecutive and not two_day and not hard_1d:
        # Crude-led grind: products can lag but still continue lower
        if product_key != "Crude_Oil":
            c1 = recent_session_return_pct("Crude_Oil", days=1, history=price_history)
            c2 = recent_session_return_pct("Crude_Oil", days=2, history=price_history)
            c_prev = prior_session_return_pct("Crude_Oil", history=price_history)
            crude_grind = (
                c1 is not None
                and c1 <= SELLOFF_CONT_1D_PCT
                and (
                    (c_prev is not None and c_prev <= SELLOFF_CONT_PREV_PCT)
                    or (c2 is not None and c2 <= SELLOFF_CONT_2D_PCT)
                    or c1 <= SELLOFF_HARD_1D_PCT
                )
            )
            # Product must be meaningfully weak — don't drag gas/diesel DOWN on a mild -0.5% day
            if crude_grind and mom_1d <= SELLOFF_CRUDE_LED_PRODUCT_MIN_PCT:
                return {
                    "mom_1d": mom_1d,
                    "mom_2d": mom_2d,
                    "mom_prev": mom_prev,
                    "source": "crude_led",
                    "crude_1d": c1,
                    "product_mild": abs(mom_1d) < SELLOFF_PRODUCT_MILD_ABS_PCT,
                }
        return None

    if consecutive:
        source = "consecutive"
    elif two_day:
        source = "two_day"
    else:
        source = "hard_1d"
    return {
        "mom_1d": mom_1d,
        "mom_2d": mom_2d,
        "mom_prev": mom_prev,
        "source": source,
    }


def _apply_selloff_continuation(
    product_key: str,
    consensus: float,
    price_history: Optional[Any] = None,
    *,
    cap_mult: float = 1.0,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """
    After 2+ down sessions, lean toward continuation lower.
    Disables washout-bounce thinking that caused Aug 24→25 UP miss.
    """
    if _skip_momentum_overlays():
        return consensus, None

    stats = _multi_day_selloff_stats(product_key, price_history)
    if not stats:
        return consensus, None

    mom_1d = float(stats["mom_1d"])
    source = stats.get("source")
    product_mild = bool(stats.get("product_mild"))

    target = _clamp_return_pct(mom_1d * SELLOFF_CONT_KEEP, product_key, cap_mult=cap_mult)
    blend = min(MAX_SELLOFF_CONT_BLEND, abs(mom_1d) / 5.0 + 0.25)

    # Crude-led on products: follow product tape, not full crude spill
    if source == "crude_led":
        target = _clamp_return_pct(mom_1d * SELLOFF_CONT_KEEP * 0.85, product_key, cap_mult=cap_mult)
        if product_mild:
            blend = min(SELLOFF_CRUDE_LED_BLEND_CAP, abs(mom_1d) / 10.0 + 0.06)
        else:
            blend = min(SELLOFF_CRUDE_LED_BLEND_CAP + 0.12, abs(mom_1d) / 6.0 + 0.15)
        if stats.get("crude_1d") is not None and not product_mild:
            crude_target = float(stats["crude_1d"]) * SELLOFF_CONT_KEEP * 0.70
            target = _clamp_return_pct(
                min(target, crude_target), product_key, cap_mult=cap_mult
            )
    elif stats.get("mom_2d") is not None and float(stats["mom_2d"]) <= -5.0:
        blend = min(MAX_SELLOFF_CONT_BLEND, blend + 0.10)

    adjusted = (1.0 - blend) * consensus + blend * target
    # Hard DOWN floor only when product itself is clearly selling off
    if source != "crude_led" or not product_mild:
        if adjusted > -0.40:
            adjusted = min(adjusted, target, -0.40)
    adjusted = _clamp_return_pct(adjusted, product_key, cap_mult=cap_mult)
    return adjusted, {
        "mode": "selloff_continuation",
        "source": source,
        "product_mild": product_mild,
        "prior_session_pct": round(mom_1d, 3),
        "two_day_pct": round(float(stats["mom_2d"]), 3) if stats.get("mom_2d") is not None else None,
        "previous_session_pct": round(float(stats["mom_prev"]), 3)
        if stats.get("mom_prev") is not None
        else None,
        "target_pct": round(target, 3),
        "blend": round(blend, 3),
        "consensus_before": round(consensus, 4),
        "consensus_after": round(adjusted, 4),
    }


def _apply_post_inventory_momentum(
    product_key: str,
    consensus: float,
    price_history: Optional[Any] = None,
    *,
    signal_context: Optional[Dict[str, Any]] = None,
    cap_mult: float = 1.0,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """
    Preserve bullish follow-through after a fresh inventory draw.

    This is intentionally narrower than a generic momentum boost: it requires
    a fresh inventory print, a draw-vs-typical z-score, and a strong prior
    session in the same refined product. It addresses under-sized post-EIA
    gasoline moves without lifting every bullish forecast.
    """
    if _skip_momentum_overlays() or consensus <= 0:
        return consensus, None

    feat = (
        ((signal_context or {}).get("catalyst_calendar") or {})
        .get("product_features", {})
        .get(product_key)
        or {}
    )
    if not feat.get("fresh_print"):
        return consensus, None

    try:
        inventory_z = float(feat.get("inventory_z"))
    except (TypeError, ValueError):
        return consensus, None
    if inventory_z > POST_INVENTORY_MOMENTUM_Z:
        return consensus, None

    try:
        from live_prices import recent_session_return_pct

        prior_pct = recent_session_return_pct(
            product_key, days=1, history=price_history
        )
    except (ImportError, TypeError, ValueError):
        return consensus, None
    if prior_pct is None or prior_pct < POST_INVENTORY_MOMENTUM_TRIGGER_PCT:
        return consensus, None

    target = _clamp_return_pct(
        prior_pct * POST_INVENTORY_MOMENTUM_KEEP,
        product_key,
        cap_mult=cap_mult,
    )
    blend = min(
        MAX_POST_INVENTORY_MOMENTUM_BLEND,
        0.28 + max(0.0, prior_pct - POST_INVENTORY_MOMENTUM_TRIGGER_PCT) / 8.0,
    )
    adjusted = max(consensus, (1.0 - blend) * consensus + blend * target)
    adjusted = _clamp_return_pct(adjusted, product_key, cap_mult=cap_mult)
    return adjusted, {
        "mode": "post_inventory_momentum",
        "inventory_z": round(inventory_z, 3),
        "prior_session_pct": round(prior_pct, 3),
        "target_pct": round(target, 3),
        "blend": round(blend, 3),
        "consensus_before": round(consensus, 4),
        "consensus_after": round(adjusted, 4),
    }


def _apply_washout_bounce(
    product_key: str,
    consensus: float,
    price_history: Optional[Any] = None,
    *,
    live_by_product: Optional[Dict[str, float]] = None,
    settle_price: float = 0.0,
    cap_mult: float = 1.0,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """
    After a hard washout (not spike->dump), lean toward a modest rebound.
    Fixes Aug 5 bearish call into Aug 6 +3–4% bounce.
    Skipped when multi-day selloff continuation is active.
    """
    if _skip_momentum_overlays():
        return consensus, None
    # Multi-day grind lower → continuation, not bounce
    if _multi_day_selloff_stats(product_key, price_history):
        return consensus, None
    try:
        from live_prices import prior_session_return_pct, recent_session_return_pct
    except ImportError:
        return consensus, None

    mom_1d = recent_session_return_pct(product_key, days=1, history=price_history)
    mom_2d = recent_session_return_pct(product_key, days=2, history=price_history)
    mom_3d = recent_session_return_pct(product_key, days=3, history=price_history)
    mom_prev = prior_session_return_pct(product_key, history=price_history)

    # Spike then dump = continuation lower, not bounce
    if (
        mom_prev is not None
        and mom_prev >= POST_SPIKE_TRIGGER_PCT
        and mom_1d is not None
        and mom_1d <= -MOMENTUM_TRIGGER_PCT
    ):
        return consensus, None

    washout = None
    source = ""
    if mom_2d is not None and mom_2d <= WASHOUT_2D_TRIGGER_PCT:
        washout, source = mom_2d, "2d"
    elif mom_1d is not None and mom_1d <= WASHOUT_1D_TRIGGER_PCT:
        washout, source = mom_1d, "1d"
    elif mom_3d is not None and mom_3d <= WASHOUT_3D_TRIGGER_PCT:
        washout, source = mom_3d, "3d"

    # Crude-led washout: lift products even if their own 2d was milder
    if washout is None and product_key != "Crude_Oil":
        crude_2d = recent_session_return_pct("Crude_Oil", days=2, history=price_history)
        crude_1d = recent_session_return_pct("Crude_Oil", days=1, history=price_history)
        crude_prev = prior_session_return_pct("Crude_Oil", history=price_history)
        if (
            crude_prev is not None
            and crude_prev >= POST_SPIKE_TRIGGER_PCT
            and crude_1d is not None
            and crude_1d <= -MOMENTUM_TRIGGER_PCT
        ):
            return consensus, None
        if crude_2d is not None and crude_2d <= WASHOUT_2D_TRIGGER_PCT:
            washout, source = crude_2d, "crude_2d"
        elif crude_1d is not None and crude_1d <= WASHOUT_1D_TRIGGER_PCT:
            washout, source = crude_1d, "crude_1d"

    if washout is None:
        return consensus, None

    # Don't fight a live overnight continuation lower
    if live_by_product and settle_price > 0:
        live = live_by_product.get(product_key)
        if live and float(live) > 0:
            gap_pct = (float(live) - settle_price) / settle_price * 100.0
            if gap_pct <= -2.0:
                return consensus, None

    # Already clearly bullish — leave it
    if consensus >= 1.2:
        return consensus, None

    bounce = _clamp_return_pct(-washout * WASHOUT_BOUNCE_RATIO, product_key, cap_mult=cap_mult)
    blend = min(MAX_WASHOUT_BOUNCE_BLEND, abs(washout) / 10.0)
    if abs(washout) >= 6.0:
        blend = min(MAX_WASHOUT_BOUNCE_BLEND, blend + 0.10)
    # If models are still deeply bearish after a washout, pull harder toward bounce
    if consensus <= -0.5:
        blend = min(MAX_WASHOUT_BOUNCE_BLEND, blend + 0.12)

    adjusted = (1.0 - blend) * consensus + blend * bounce
    floor = 0.35 + min(1.8, abs(washout) * 0.18)
    if adjusted < floor:
        adjusted = floor
    adjusted = _clamp_return_pct(adjusted, product_key, cap_mult=cap_mult)
    return adjusted, {
        "mode": "washout_bounce",
        "washout_pct": round(washout, 3),
        "washout_source": source,
        "bounce_pct": round(bounce, 3),
        "blend": round(blend, 3),
        "consensus_before": round(consensus, 4),
        "consensus_after": round(adjusted, 4),
    }


def _post_spike_fade(
    mom_1d: float,
    product_key: str,
    inventory_wow_pct: Optional[float] = None,
    *,
    gasoline_crack: Optional[float] = None,
) -> tuple[float, float]:
    """Return (fade_target_pct, blend) for a prior-session rally spike."""
    ratio = POST_SPIKE_FADE_RATIO
    if mom_1d >= 6.0:
        ratio = 0.48
    elif mom_1d >= 4.5:
        ratio = 0.42
    # RBOB often holds after complex bounce days — fade less aggressively
    if product_key == "RBOB_Gasoline":
        ratio *= 0.70
    fade = _clamp_return_pct(-mom_1d * ratio, product_key)
    blend = min(MAX_POST_SPIKE_BLEND, abs(mom_1d) / 6.5)
    if mom_1d >= 6.0:
        blend = min(MAX_POST_SPIKE_BLEND, blend + 0.12)
    if product_key == "RBOB_Gasoline":
        blend = min(blend, 0.42)
    if inventory_wow_pct is not None and float(inventory_wow_pct) < -0.5:
        blend *= 0.72 if product_key == "RBOB_Gasoline" else 0.85
    if (
        product_key == "RBOB_Gasoline"
        and gasoline_crack is not None
        and float(gasoline_crack) >= 40.0
    ):
        blend *= 0.75
    return fade, blend


def _rbob_supportive_after_bounce(
    inventory_wow_pct: Optional[float],
    gasoline_crack: Optional[float],
) -> bool:
    """True when gas fundamentals argue against a hard fade with crude/diesel."""
    if inventory_wow_pct is not None and float(inventory_wow_pct) < -0.5:
        return True
    if gasoline_crack is not None and float(gasoline_crack) >= 40.0:
        return True
    return False


def _apply_complex_spike_fade(
    product_key: str,
    consensus: float,
    price_history: Optional[Any] = None,
    *,
    cap_mult: float = 1.0,
    inventory_wow_pct: Optional[float] = None,
    gasoline_crack: Optional[float] = None,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """
    After a crude blow-off, pull RBOB/diesel down even if their own 1d move was milder.
    Fixes Jul 23->24: gas still called UP while complex sold off hard.
    """
    if product_key == "Crude_Oil":
        return consensus, None
    if _skip_momentum_overlays():
        return consensus, None
    try:
        from live_prices import recent_session_return_pct
    except ImportError:
        return consensus, None

    crude_mom = recent_session_return_pct("Crude_Oil", days=1, history=price_history)
    own_mom = recent_session_return_pct(product_key, days=1, history=price_history)
    if crude_mom is None or crude_mom < COMPLEX_SPIKE_TRIGGER_PCT:
        return consensus, None
    # Don't double-apply if own product already got a strong post-spike fade
    if own_mom is not None and own_mom >= POST_SPIKE_TRIGGER_PCT:
        return consensus, None

    fade = _clamp_return_pct(-crude_mom * COMPLEX_FADE_RATIO, product_key, cap_mult=cap_mult)
    blend = min(MAX_COMPLEX_FADE_BLEND, crude_mom / 10.0)
    if crude_mom >= 6.0:
        blend = min(MAX_COMPLEX_FADE_BLEND, blend + 0.12)
    rbob_support = product_key == "RBOB_Gasoline" and _rbob_supportive_after_bounce(
        inventory_wow_pct, gasoline_crack
    )
    if rbob_support:
        blend *= 0.45
    adjusted = (1.0 - blend) * consensus + blend * fade
    if rbob_support:
        if adjusted < -0.15:
            adjusted = -0.15
        if adjusted < 0.15:
            adjusted = max(adjusted, 0.15)
    elif adjusted > -0.35:
        # Force non-positive day-1 after a crude blow-off unless gas supportive
        adjusted = min(adjusted, -0.35 - min(1.5, (crude_mom - COMPLEX_SPIKE_TRIGGER_PCT) * 0.25))
    adjusted = _clamp_return_pct(adjusted, product_key, cap_mult=cap_mult)
    return adjusted, {
        "mode": "complex_spike_fade",
        "crude_prior_session_pct": round(crude_mom, 3),
        "own_prior_session_pct": round(own_mom, 3) if own_mom is not None else None,
        "fade_pct": round(fade, 3),
        "blend": round(blend, 3),
        "rbob_support": rbob_support,
        "consensus_before": round(consensus, 4),
        "consensus_after": round(adjusted, 4),
    }


def _bearish_supply_headline_score(signal_context: Optional[Dict[str, Any]]) -> float:
    """0-1 score for bearish supply headlines (e.g. Saudi price cuts, oversupply)."""
    if not signal_context:
        return 0.0
    topic = signal_context.get("topic_snapshot") or {}
    buckets = topic.get("buckets") or {}
    opec = buckets.get("opec") or {}
    opec_intensity = float(opec.get("intensity") or 0)
    sentiment = float(topic.get("sentiment") or 0)
    score = 0.0
    if opec_intensity >= 0.18 and sentiment <= 0.08:
        score += 0.32
    phrase_hits = 0
    try:
        import os
        import pandas as pd
        news_path = signal_context.get("news_csv") or "data/news.csv"
        if os.path.exists(news_path):
            df = pd.read_csv(news_path)
            if not df.empty:
                recent = df.tail(40)
                for _, row in recent.iterrows():
                    text = f"{row.get('title', '')} {row.get('description', '')}".lower()
                    if any(kw in text for kw in BEARISH_SUPPLY_PHRASES):
                        phrase_hits += 1
    except Exception:
        pass
    if phrase_hits:
        score += min(0.48, phrase_hits * 0.16)
    return min(1.0, score)


def _apply_headline_pullback(
    product_key: str,
    consensus: float,
    prior_session_pct: Optional[float],
    signal_context: Optional[Dict[str, Any]],
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """After a spike rally, nudge down when bearish supply headlines dominate."""
    if prior_session_pct is None or prior_session_pct < POST_SPIKE_TRIGGER_PCT:
        return consensus, None
    bear = _bearish_supply_headline_score(signal_context)
    if bear < 0.22:
        return consensus, None
    nudge = _clamp_return_pct(-prior_session_pct * 0.08 * bear, product_key)
    adjusted = consensus + nudge
    if consensus > 0.15:
        cap = consensus * (1.0 - 0.38 * bear)
        adjusted = min(adjusted, cap)
    adjusted = _clamp_return_pct(adjusted, product_key)
    return adjusted, {
        "bearish_supply_score": round(bear, 3),
        "prior_session_pct": round(prior_session_pct, 3),
        "nudge_pct": round(nudge, 3),
        "consensus_before": round(consensus, 4),
        "consensus_after": round(adjusted, 4),
    }


def _set_day1(
    block: Dict[str, Any],
    current: float,
    return_pct: float,
    product_key: str,
    *,
    cap_mult: float = 1.0,
) -> None:
    return_pct = _clamp_return_pct(return_pct, product_key, cap_mult=cap_mult)
    price = current * (1.0 + return_pct / 100.0)
    block["day_1"] = float(price)
    block["next_day"] = float(price)
    block["day_1_change"] = float(return_pct)
    block["next_day_change"] = float(return_pct)
    block["_day1_cap_mult"] = float(cap_mult)
    direction = "UP" if return_pct > 0.08 else "DOWN" if return_pct < -0.08 else "FLAT"
    block["day_1_direction"] = direction
    block["next_day_direction"] = direction


def _apply_momentum_continuation(
    product_key: str,
    consensus: float,
    price_history: Optional[Any] = None,
    ensemble_return: Optional[float] = None,
    inventory_wow_pct: Optional[float] = None,
    gasoline_crack: Optional[float] = None,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """Blend toward tape momentum only when models agree; fade sharp bounce days."""
    if _skip_momentum_overlays():
        return consensus, None
    try:
        from live_prices import (
            load_official_price_history,
            prior_session_return_pct,
            recent_session_return_pct,
        )
    except ImportError:
        return consensus, None

    hist = price_history if price_history is not None else load_official_price_history()
    mom_1d = recent_session_return_pct(product_key, days=1, history=hist)
    if mom_1d is None or abs(mom_1d) < MOMENTUM_TRIGGER_PCT:
        return consensus, None

    ens_sign = _sign(float(ensemble_return)) if ensemble_return is not None else 0
    mom_sign = _sign(mom_1d)
    cons_sign = _sign(consensus)

    mom_2d = recent_session_return_pct(product_key, days=2, history=hist)
    mom_3d = recent_session_return_pct(product_key, days=3, history=hist)
    mom_prev = prior_session_return_pct(product_key, history=hist)

    # Spike day then hard selloff = profit-taking CONTINUATION, not a bounce setup.
    # (Jul 23 spike -> Jul 24 dump -> model wrongly bounce-called Monday up)
    if (
        mom_prev is not None
        and mom_prev >= POST_SPIKE_TRIGGER_PCT
        and mom_1d <= -MOMENTUM_TRIGGER_PCT
    ):
        cont = _clamp_return_pct(mom_1d * 0.55, product_key)
        blend = min(0.65, abs(mom_1d) / 6.0)
        adjusted = (1.0 - blend) * consensus + blend * cont
        if adjusted > -0.6:
            adjusted = min(adjusted, -0.6 - min(1.8, abs(mom_1d) * 0.25))
        adjusted = _clamp_return_pct(adjusted, product_key)
        return adjusted, {
            "mode": "selloff_after_spike",
            "prior_session_pct": round(mom_1d, 3),
            "previous_session_pct": round(mom_prev, 3),
            "continuation_pct": round(cont, 3),
            "blend": round(blend, 3),
            "consensus_before": round(consensus, 4),
            "consensus_after": round(adjusted, 4),
        }

    # Sharp reversal day — only fade if prior was NOT a blow-off spike
    if (
        mom_prev is not None
        and abs(mom_1d) >= MOMENTUM_TRIGGER_PCT
        and abs(mom_prev) >= MOMENTUM_TRIGGER_PCT
        and _sign(mom_1d) != _sign(mom_prev)
    ):
        fade = _clamp_return_pct(-mom_1d * 0.12, product_key)
        blend = min(0.30, abs(mom_1d) / 12.0)
        adjusted = (1.0 - blend) * consensus + blend * fade
        return adjusted, {
            "mode": "reversal_fade",
            "prior_session_pct": round(mom_1d, 3),
            "previous_session_pct": round(mom_prev, 3),
            "fade_pct": round(fade, 3),
            "blend": round(blend, 3),
            "consensus_before": round(consensus, 4),
            "consensus_after": round(adjusted, 4),
        }

    # Sharp rally while still net down over 2 sessions
    if mom_1d > MOMENTUM_TRIGGER_PCT and mom_2d is not None and mom_2d < 0:
        fade = _clamp_return_pct(-mom_1d * 0.12, product_key)
        blend = min(0.30, abs(mom_1d) / 12.0)
        adjusted = (1.0 - blend) * consensus + blend * fade
        return adjusted, {
            "mode": "bounce_fade",
            "prior_session_pct": round(mom_1d, 3),
            "two_day_pct": round(mom_2d, 3),
            "fade_pct": round(fade, 3),
            "blend": round(blend, 3),
            "consensus_before": round(consensus, 4),
            "consensus_after": round(adjusted, 4),
        }

    # Large single-session rally — expect pullback (mean reversion)
    if mom_1d >= POST_SPIKE_TRIGGER_PCT and mom_1d > 0:
        fade, blend = _post_spike_fade(
            mom_1d,
            product_key,
            inventory_wow_pct,
            gasoline_crack=gasoline_crack,
        )
        adjusted = (1.0 - blend) * consensus + blend * fade
        rbob_support = product_key == "RBOB_Gasoline" and _rbob_supportive_after_bounce(
            inventory_wow_pct, gasoline_crack
        )
        # Bounce off a washout (recovery) — don't treat like a blow-off top for RBOB
        recovery_bounce = (
            product_key == "RBOB_Gasoline"
            and (
                (mom_prev is not None and mom_prev <= -1.5)
                or (mom_3d is not None and mom_3d <= -3.0)
                or (mom_2d is not None and mom_2d <= 1.0 and mom_prev is not None and mom_prev < 0)
            )
        )
        if rbob_support or recovery_bounce:
            # Soft fade only: allow flat / slight up; never force -2% gas dump
            if adjusted < -0.25:
                adjusted = -0.25
            if rbob_support and adjusted < 0.20:
                adjusted = max(adjusted, 0.20)
            elif recovery_bounce and adjusted < 0.0:
                adjusted = 0.0
            mode = "rbob_soft_fade"
        else:
            # Hard floor for crude/diesel blow-offs: don't leave day-1 net bullish
            if adjusted > -0.25:
                adjusted = min(
                    adjusted,
                    -0.25 - min(2.0, (mom_1d - POST_SPIKE_TRIGGER_PCT) * 0.35),
                )
            mode = "post_spike_fade"
        adjusted = _clamp_return_pct(adjusted, product_key)
        return adjusted, {
            "mode": mode,
            "prior_session_pct": round(mom_1d, 3),
            "fade_pct": round(fade, 3),
            "blend": round(blend, 3),
            "rbob_support": rbob_support,
            "recovery_bounce": recovery_bounce,
            "consensus_before": round(consensus, 4),
            "consensus_after": round(adjusted, 4),
        }

    # Don't chase a rally when the model call is essentially flat
    if mom_1d > MOMENTUM_TRIGGER_PCT and abs(consensus) < 0.55:
        return consensus, None

    # Upside continuation only when ensemble/consensus already lean clearly up
    if mom_1d > 0 and (ens_sign < 0 or cons_sign < 0):
        return consensus, None
    if mom_1d > 0 and ens_sign <= 0 and cons_sign <= 0:
        return consensus, None

    # Selloff continuation only when ensemble is not clearly bullish
    if mom_1d < 0 and ens_sign > 0 and cons_sign >= 0:
        return consensus, None

    # Don't chase upside when weekly inventory built (supply cushion)
    if inventory_wow_pct is not None and float(inventory_wow_pct) > 0.8 and mom_1d > 0:
        return consensus, None
    # Don't chase downside when inventory drew sharply (supportive)
    if inventory_wow_pct is not None and float(inventory_wow_pct) < -0.8 and mom_1d < 0:
        return consensus, None

    continuation = _clamp_return_pct(mom_1d * MOMENTUM_CONTINUATION, product_key)
    blend = min(_momentum_blend_cap(), abs(mom_1d) / 7.0)
    # Only strengthen blend when models and tape already agree
    if mom_sign == ens_sign and mom_sign == cons_sign:
        blend = min(_momentum_blend_cap(), blend + 0.10)

    adjusted = (1.0 - blend) * consensus + blend * continuation
    return adjusted, {
        "mode": "continuation",
        "prior_session_pct": round(mom_1d, 3),
        "continuation_pct": round(continuation, 3),
        "blend": round(blend, 3),
        "consensus_before": round(consensus, 4),
        "consensus_after": round(adjusted, 4),
    }


def _apply_crude_rally_gasoline_divergence(
    product_key: str,
    consensus: float,
    settle_price: float,
    live_by_product: Optional[Dict[str, float]],
    *,
    prior_session_pct: Optional[float] = None,
    cap_mult: float = 1.0,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """
    Live crude bid but RBOB flat/down — crack compression / post-rally profit-taking.
    Pull a bullish gasoline day-1 toward the product tape (Mon Aug 31 miss).
    """
    if product_key != "RBOB_Gasoline":
        return consensus, None
    if _skip_momentum_overlays():
        return consensus, None
    if not live_by_product or settle_price <= 0:
        return consensus, None

    live = live_by_product.get("RBOB_Gasoline")
    crude_live = live_by_product.get("Crude_Oil")
    if not live or not crude_live or float(live) <= 0 or float(crude_live) <= 0:
        return consensus, None

    gas_gap = (float(live) - settle_price) / settle_price * 100.0
    crude_gap = None
    try:
        from live_prices import get_nymex_session_close

        closes, _, _ = get_nymex_session_close()
        c_settle = closes.get("Crude")
        if c_settle and float(c_settle) > 0:
            crude_gap = (float(crude_live) - float(c_settle)) / float(c_settle) * 100.0
    except Exception:
        crude_gap = None

    if crude_gap is None or crude_gap < CRUDE_RALLY_DIVERGENCE_CRUDE_MIN_PCT:
        return consensus, None
    if gas_gap > CRUDE_RALLY_DIVERGENCE_GAS_MAX_PCT:
        return consensus, None

    divergence_pp = float(crude_gap) - float(gas_gap)
    if divergence_pp < CRUDE_RALLY_DIVERGENCE_DIVERGENCE_PP:
        return consensus, None
    if consensus <= 0.15:
        return consensus, None

    target = _clamp_return_pct(
        gas_gap * CRUDE_RALLY_DIVERGENCE_KEEP,
        product_key,
        cap_mult=cap_mult,
    )
    if gas_gap < -0.35:
        target = min(target, gas_gap * 0.80)
    elif gas_gap <= 0:
        target = min(target, -0.18)

    blend = min(
        MAX_CRUDE_RALLY_DIVERGENCE_BLEND,
        divergence_pp / 3.5 + 0.28,
    )
    if (
        prior_session_pct is not None
        and float(prior_session_pct) >= CRUDE_RALLY_DIVERGENCE_PRIOR_RALLY_PCT
    ):
        blend = min(MAX_CRUDE_RALLY_DIVERGENCE_BLEND, blend + 0.14)

    try:
        from regime_learning import get_divergence_overlay_params
        from prediction_attribution import load_factor_learning

        learned = get_divergence_overlay_params(product_key)
        if int(learned.get("n") or 0) >= 1:
            blend = min(
                MAX_CRUDE_RALLY_DIVERGENCE_BLEND + 0.08,
                blend + float(learned.get("blend_boost") or 0.0),
            )
            if int(learned.get("direction_miss_count") or 0) >= 2:
                blend = min(MAX_CRUDE_RALLY_DIVERGENCE_BLEND + 0.12, blend + 0.06)
            fade_boost = float(learned.get("fade_boost") or 0.0)
            if fade_boost > 0 and consensus > 0:
                target = target - min(0.45, fade_boost * 2.0)
        rules = (load_factor_learning() or {}).get("global_rules") or {}
        blend = min(
            MAX_CRUDE_RALLY_DIVERGENCE_BLEND + 0.15,
            blend + float(rules.get("divergence_blend_boost") or 0.0),
        )
    except Exception:
        pass

    adjusted = (1.0 - blend) * consensus + blend * target

    if gas_gap <= -0.50 and adjusted > -0.30:
        adjusted = min(adjusted, target * 0.92, -0.30)
    elif gas_gap <= 0 and adjusted > 0.20:
        adjusted = min(adjusted, 0.12)

    adjusted = _clamp_return_pct(adjusted, product_key, cap_mult=cap_mult)
    return adjusted, {
        "crude_gap_pct": round(crude_gap, 3),
        "gas_gap_pct": round(gas_gap, 3),
        "divergence_pp": round(divergence_pp, 3),
        "target_pct": round(target, 3),
        "blend": round(blend, 3),
        "prior_session_pct": round(float(prior_session_pct), 3)
        if prior_session_pct is not None
        else None,
        "consensus_before": round(consensus, 4),
        "consensus_after": round(adjusted, 4),
    }


def _apply_gas_diesel_rotation(
    product_key: str,
    consensus: float,
    *,
    price_history: Optional[Any] = None,
    diesel_crack: Optional[float] = None,
    distillate_wow: Optional[float] = None,
    live_by_product: Optional[Dict[str, float]] = None,
    settle_price: float = 0.0,
    cap_mult: float = 1.0,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """
    After a product-rotation session: gasoline washed out while crude held →
    bounce gas; elevated diesel crack + soft prior diesel → fade ULSD.
    Fixes Wed Sep 3 miss (gas DOWN/actual UP, diesel UP/actual DOWN).
    """
    if product_key not in ("RBOB_Gasoline", "ULSD_Diesel"):
        return consensus, None
    if _skip_momentum_overlays():
        return consensus, None
    try:
        from live_prices import recent_session_return_pct
    except ImportError:
        return consensus, None

    prior_gas = recent_session_return_pct("RBOB_Gasoline", days=1, history=price_history)
    prior_diesel = recent_session_return_pct("ULSD_Diesel", days=1, history=price_history)
    prior_crude = recent_session_return_pct("Crude_Oil", days=1, history=price_history)
    diesel_3d = recent_session_return_pct(
        "ULSD_Diesel", days=THRUST_LOOKBACK_SESSIONS, history=price_history
    )

    crude_live_gap = None
    if live_by_product and settle_price > 0:
        crude_live = live_by_product.get("Crude_Oil")
        if crude_live:
            try:
                from live_prices import get_nymex_session_close, PRODUCT_COL_MAP

                crude_settle = None
                if price_history is not None and not getattr(price_history, "empty", True):
                    col = PRODUCT_COL_MAP.get("Crude_Oil", "Crude")
                    if col in price_history.columns:
                        cs = price_history[col].dropna()
                        if len(cs):
                            crude_settle = float(cs.iloc[-1])
                if crude_settle is None:
                    closes, _, _ = get_nymex_session_close()
                    c_settle = closes.get("Crude")
                    if c_settle and float(c_settle) > 0:
                        crude_settle = float(c_settle)
                if crude_settle and crude_settle > 0:
                    crude_live_gap = (float(crude_live) - crude_settle) / crude_settle * 100.0
            except Exception:
                crude_live_gap = None

    crude_holds = (
        (prior_crude is not None and float(prior_crude) >= GAS_ROTATION_CRUDE_FLOOR_PCT)
        or (crude_live_gap is not None and float(crude_live_gap) >= 1.0)
    )

    if product_key == "RBOB_Gasoline":
        if prior_gas is None or float(prior_gas) > GAS_ROTATION_PRIOR_MAX_PCT:
            return consensus, None
        if not crude_holds:
            return consensus, None
        divergence_pp = float(prior_crude or 0.0) - float(prior_gas)
        if divergence_pp < GAS_ROTATION_DIVERGENCE_PP and float(prior_gas) > -2.2:
            return consensus, None
        # Already clearly bullish — leave it
        if consensus >= 1.0:
            return consensus, None

        bounce = _clamp_return_pct(
            -float(prior_gas) * GAS_ROTATION_BOUNCE_RATIO,
            product_key,
            cap_mult=cap_mult,
        )
        bounce = max(bounce, 0.45)
        if crude_live_gap is not None and crude_live_gap >= 1.5:
            bounce = max(bounce, min(1.8, float(crude_live_gap) * 0.55))

        blend = min(MAX_GAS_ROTATION_BLEND, abs(float(prior_gas)) / 4.0 + 0.38)
        if divergence_pp >= 1.5:
            blend = min(MAX_GAS_ROTATION_BLEND, blend + 0.10)
        if consensus <= -0.4:
            blend = min(MAX_GAS_ROTATION_BLEND, blend + 0.12)

        adjusted = (1.0 - blend) * consensus + blend * bounce
        if adjusted < 0.35:
            adjusted = 0.35
        adjusted = _clamp_return_pct(adjusted, product_key, cap_mult=cap_mult)
        return adjusted, {
            "mode": "gas_bounce_after_washout",
            "prior_gas_pct": round(float(prior_gas), 3),
            "prior_crude_pct": round(float(prior_crude), 3) if prior_crude is not None else None,
            "crude_live_gap_pct": round(float(crude_live_gap), 3) if crude_live_gap is not None else None,
            "divergence_pp": round(divergence_pp, 3),
            "target_pct": round(bounce, 3),
            "blend": round(blend, 3),
            "consensus_before": round(consensus, 4),
            "consensus_after": round(adjusted, 4),
        }

    # ULSD: fade elevated crack after soft prior / post-thrust giveback
    if prior_diesel is None:
        return consensus, None
    crack = float(diesel_crack) if diesel_crack is not None else None
    elevated_crack = crack is not None and crack >= DIESEL_ROTATION_CRACK_MIN
    soft_prior = float(prior_diesel) <= DIESEL_ROTATION_PRIOR_MAX_PCT
    post_thrust_fade = (
        diesel_3d is not None
        and float(diesel_3d) >= DIESEL_ROTATION_THRUST_LOOKBACK_PCT
        and float(prior_diesel) <= -0.40
    )
    inv_build = (
        distillate_wow is not None and float(distillate_wow) >= DIESEL_ROTATION_INV_BUILD_PCT
    )
    if not elevated_crack:
        return consensus, None
    if not (soft_prior or post_thrust_fade):
        return consensus, None
    # Already clearly bearish — leave it
    if consensus <= -0.80:
        return consensus, None

    fade = _clamp_return_pct(
        float(prior_diesel) * DIESEL_ROTATION_FADE_RATIO,
        product_key,
        cap_mult=cap_mult,
    )
    fade = min(fade, -0.35)
    if inv_build:
        fade = min(fade, -0.55)
    if post_thrust_fade and diesel_3d is not None:
        fade = min(fade, -min(1.6, float(diesel_3d) * 0.18))

    blend = min(MAX_DIESEL_ROTATION_BLEND, (crack - DIESEL_ROTATION_CRACK_MIN) / 25.0 + 0.40)
    if soft_prior:
        blend = min(MAX_DIESEL_ROTATION_BLEND, blend + 0.10)
    if inv_build:
        blend = min(MAX_DIESEL_ROTATION_BLEND, blend + 0.08)
    if consensus >= 0.5:
        blend = min(MAX_DIESEL_ROTATION_BLEND, blend + 0.10)

    adjusted = (1.0 - blend) * consensus + blend * fade
    if adjusted > -0.25:
        adjusted = -0.25
    adjusted = _clamp_return_pct(adjusted, product_key, cap_mult=cap_mult)
    return adjusted, {
        "mode": "diesel_crack_fade",
        "prior_diesel_pct": round(float(prior_diesel), 3),
        "diesel_3d_pct": round(float(diesel_3d), 3) if diesel_3d is not None else None,
        "diesel_crack": round(crack, 2) if crack is not None else None,
        "distillate_wow_pct": round(float(distillate_wow), 3) if distillate_wow is not None else None,
        "target_pct": round(fade, 3),
        "blend": round(blend, 3),
        "consensus_before": round(consensus, 4),
        "consensus_after": round(adjusted, 4),
    }


def _apply_distillate_crude_rally(
    product_key: str,
    consensus: float,
    settle_price: float,
    live_by_product: Optional[Dict[str, float]],
    *,
    price_history: Optional[Any] = None,
    cap_mult: float = 1.0,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """
    Crude ripping on live/history tape — size ULSD day-1 toward the complex
    (Sep 1: crude +5%, diesel +6%, model only +1%).
    """
    if product_key != "ULSD_Diesel":
        return consensus, None
    if _skip_momentum_overlays():
        return consensus, None
    if settle_price <= 0:
        return consensus, None
    try:
        from live_prices import get_nymex_session_close, recent_session_return_pct
    except ImportError:
        return consensus, None

    crude_mom = recent_session_return_pct("Crude_Oil", days=1, history=price_history)
    diesel_mom = recent_session_return_pct("ULSD_Diesel", days=1, history=price_history)

    crude_gap = None
    diesel_gap = None
    crude_settle = None
    if price_history is not None and not getattr(price_history, "empty", True):
        crude_col = None
        try:
            from live_prices import PRODUCT_COL_MAP

            crude_col = PRODUCT_COL_MAP.get("Crude_Oil", "Crude")
        except ImportError:
            crude_col = "Crude"
        if crude_col in price_history.columns:
            cs = price_history[crude_col].dropna()
            if len(cs):
                crude_settle = float(cs.iloc[-1])
    if live_by_product:
        diesel_live = live_by_product.get("ULSD_Diesel")
        crude_live = live_by_product.get("Crude_Oil")
        if diesel_live and float(diesel_live) > 0:
            diesel_gap = (float(diesel_live) - settle_price) / settle_price * 100.0
        if crude_live and crude_settle is None:
            try:
                closes, _, _ = get_nymex_session_close()
                c_settle = closes.get("Crude")
                if c_settle and float(c_settle) > 0:
                    crude_settle = float(c_settle)
            except Exception:
                crude_settle = None
        if crude_live and crude_settle and crude_settle > 0:
            crude_gap = (float(crude_live) - crude_settle) / crude_settle * 100.0

    crude_sig = max(
        float(crude_gap) if crude_gap is not None and crude_gap > 0 else 0.0,
        float(crude_mom) if crude_mom is not None and crude_mom > 0 else 0.0,
    )
    if crude_sig < DISTILLATE_CRUDE_RALLY_TRIGGER_PCT:
        return consensus, None

    target_parts = [crude_sig * DISTILLATE_CRUDE_RALLY_KEEP]
    if diesel_gap is not None and diesel_gap > 0:
        target_parts.append(diesel_gap * 0.82)
    if diesel_mom is not None and diesel_mom > 0:
        target_parts.append(diesel_mom * 0.68)
    target = _clamp_return_pct(max(target_parts), product_key, cap_mult=cap_mult)

    if consensus >= target * 0.88:
        return consensus, None

    blend = min(MAX_DISTILLATE_CRUDE_RALLY_BLEND, crude_sig / 4.5 + 0.32)
    if diesel_mom is not None and diesel_mom > crude_sig * 0.9:
        blend = min(MAX_DISTILLATE_CRUDE_RALLY_BLEND + 0.08, blend + 0.08)

    adjusted = (1.0 - blend) * consensus + blend * target
    if crude_sig >= 4.0 and adjusted < target * 0.72:
        adjusted = max(adjusted, target * 0.72)
    adjusted = _clamp_return_pct(adjusted, product_key, cap_mult=cap_mult)
    return adjusted, {
        "crude_gap_pct": round(crude_gap, 3) if crude_gap is not None else None,
        "crude_prior_session_pct": round(crude_mom, 3) if crude_mom is not None else None,
        "diesel_gap_pct": round(diesel_gap, 3) if diesel_gap is not None else None,
        "diesel_prior_session_pct": round(diesel_mom, 3) if diesel_mom is not None else None,
        "target_pct": round(target, 3),
        "blend": round(blend, 3),
        "consensus_before": round(consensus, 4),
        "consensus_after": round(adjusted, 4),
    }


def _apply_crude_spillover(
    product_key: str,
    consensus: float,
    price_history: Optional[Any] = None,
    ensemble_return: Optional[float] = None,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """When crude moved sharply, nudge products only if models lean the same way."""
    if _skip_momentum_overlays():
        return consensus, None
    if product_key == "Crude_Oil":
        return consensus, None
    try:
        from prediction_attribution import load_factor_learning

        rules = (load_factor_learning() or {}).get("global_rules") or {}
        if rules.get("disable_crude_spillover_on_divergence") and product_key == "RBOB_Gasoline":
            return consensus, None
    except Exception:
        pass
    try:
        from live_prices import recent_session_return_pct
    except ImportError:
        return consensus, None

    crude_mom = recent_session_return_pct("Crude_Oil", days=1, history=price_history)
    if crude_mom is None or abs(crude_mom) < CRUDE_SPILLOVER_TRIGGER_PCT:
        return consensus, None

    # Don't spill bullish crude into products the day after a crude spike rally
    if crude_mom >= POST_SPIKE_TRIGGER_PCT:
        return consensus, None

    ens_sign = _sign(float(ensemble_return)) if ensemble_return is not None else 0
    crude_sign = _sign(crude_mom)
    cons_sign = _sign(consensus)

    # Don't force crude spill when ensemble/consensus disagree with crude direction
    if crude_sign > 0 and (ens_sign < 0 or cons_sign < 0):
        return consensus, None
    if crude_sign < 0 and ens_sign > 0 and cons_sign >= 0:
        return consensus, None

    spill = _clamp_return_pct(crude_mom * CRUDE_SPILLOVER_FACTOR, product_key)
    blend = min(MAX_CRUDE_SPILLOVER_BLEND, abs(crude_mom) / 12.0)

    adjusted = (1.0 - blend) * consensus + blend * spill
    return adjusted, {
        "crude_prior_session_pct": round(crude_mom, 3),
        "spillover_pct": round(spill, 3),
        "blend": round(blend, 3),
        "consensus_before": round(consensus, 4),
        "consensus_after": round(adjusted, 4),
    }


def _apply_product_lag_catchup(
    product_key: str,
    consensus: float,
    price_history: Optional[Any] = None,
    ensemble_return: Optional[float] = None,
    *,
    print_ctx: Optional[Dict[str, Any]] = None,
    gasoline_crack: Optional[float] = None,
    distillate_wow_pct: Optional[float] = None,
    cap_mult: float = 1.0,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """
    When crude rallied hard and RBOB/ULSD lagged, expect product catch-up next session
    (Aug 20 crude +2.3% / RBOB flat → Aug 21 RBOB +2.6% while crude faded).
    """
    if _skip_momentum_overlays():
        return consensus, None
    if product_key == "Crude_Oil":
        return consensus, None
    if print_ctx and print_ctx.get("eia_imminent"):
        return consensus, None
    try:
        from live_prices import recent_session_return_pct
    except ImportError:
        return consensus, None

    crude_mom = recent_session_return_pct("Crude_Oil", days=1, history=price_history)
    prod_mom = recent_session_return_pct(product_key, days=1, history=price_history)
    if crude_mom is None or prod_mom is None:
        return consensus, None
    if crude_mom < LAG_CRUDE_TRIGGER_PCT:
        return consensus, None

    lag_pp = float(crude_mom) - float(prod_mom)
    if lag_pp < LAG_GAP_TRIGGER_PP:
        return consensus, None

    # Don't chase catch-up if product already spiked or consensus is clearly bearish
    if prod_mom >= POST_SPIKE_TRIGGER_PCT:
        return consensus, None
    if _sign(consensus) < 0 and (ensemble_return is None or _sign(float(ensemble_return)) < 0):
        return consensus, None

    target = _clamp_return_pct(lag_pp * LAG_CATCHUP_KEEP, product_key, cap_mult=cap_mult)
    # Floor: at least a meaningful bid when lag is wide
    target = max(target, min(1.8, lag_pp * 0.55))
    blend = min(MAX_LAG_CATCHUP_BLEND, lag_pp / 5.0)

    # Crack / distillate support strengthens catch-up (products can rip vs crude)
    if gasoline_crack is not None and float(gasoline_crack) >= 45.0:
        blend = min(MAX_LAG_CATCHUP_BLEND, blend + 0.08)
    if distillate_wow_pct is not None and float(distillate_wow_pct) <= -1.0:
        blend = min(MAX_LAG_CATCHUP_BLEND, blend + 0.06)

    if ensemble_return is not None and float(ensemble_return) > 0.4:
        blend = min(MAX_LAG_CATCHUP_BLEND, blend + 0.05)

    # Learned regime scale from past pred vs settle in this setup
    regime_note = None
    try:
        from regime_learning import get_regime_params

        rp = get_regime_params("product_lag_catchup", product_key)
        if int(rp.get("n") or 0) >= 1:
            scale = max(0.85, min(1.85, float(rp.get("magnitude_scale") or 1.0)))
            boost = max(0.0, min(0.20, float(rp.get("blend_boost") or 0.0)))
            target = _clamp_return_pct(target * scale, product_key, cap_mult=cap_mult)
            blend = min(MAX_LAG_CATCHUP_BLEND + 0.12, blend + boost)
            regime_note = {
                "magnitude_scale": round(scale, 3),
                "blend_boost": round(boost, 3),
                "n": int(rp.get("n") or 0),
            }
    except Exception:
        pass

    adjusted = (1.0 - blend) * consensus + blend * target
    # Wide lag: don't leave day-1 near a timid half-percent bid
    if lag_pp >= 1.5:
        floor = min(1.85, 0.55 * lag_pp + 0.15)
        if adjusted < floor:
            adjusted = floor
    adjusted = _clamp_return_pct(adjusted, product_key, cap_mult=cap_mult)

    if abs(adjusted - consensus) < 0.08:
        return consensus, None
    out = {
        "mode": "product_lag_catchup",
        "crude_prior_session_pct": round(float(crude_mom), 3),
        "product_prior_session_pct": round(float(prod_mom), 3),
        "lag_pp": round(lag_pp, 3),
        "target_pct": round(target, 3),
        "blend": round(blend, 3),
        "consensus_before": round(consensus, 4),
        "consensus_after": round(adjusted, 4),
    }
    if regime_note:
        out["regime_learning"] = regime_note
    return adjusted, out


def reconcile_day1_precision(
    results: Dict[str, Any],
    ensemble_meta: Optional[Dict[str, Any]] = None,
    xgb_info: Optional[Dict[str, Any]] = None,
    current_prices: Optional[Dict[str, float]] = None,
    context_meta: Optional[Dict[str, Any]] = None,
    signal_context: Optional[Dict[str, Any]] = None,
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

    price_history = None
    try:
        from live_prices import load_official_price_history
        price_history = load_official_price_history()
    except ImportError:
        price_history = None

    # Only flag weekend when day-1 *target* crosses Fri→Mon/holiday — not historical Fri→Mon after Mon settled
    weekend_crossing = _is_forecasting_weekend_gap()
    weekend_gap = weekend_crossing
    gap_risk = assess_gap_risk(
        context_meta,
        signal_context,
        weekend_crossing=weekend_crossing,
    )
    cap_mult = float(gap_risk.get("cap_mult") or 1.0)
    live_by_product = (signal_context or {}).get("live_by_product") or {}
    catalyst_cal = (signal_context or {}).get("catalyst_calendar") or (context_meta or {}).get(
        "catalyst_calendar"
    ) or {}
    print_ctx = _inventory_print_context(catalyst_cal)
    crude_inv_wow = None
    inv_weekly = (signal_context or {}).get("inventory_weekly") or (context_meta or {}).get(
        "inventory_weekly"
    ) or {}
    crude_row = inv_weekly.get("crude") or {}
    if isinstance(crude_row, dict):
        crude_inv_wow = crude_row.get("wow_change_pct")

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
                x_w = 0.30
                # Flat / near-zero XGB should not cancel a clear ensemble bid
                if (
                    ens_ret is not None
                    and abs(float(x_ret)) < FLAT_XGB_ABS_PCT
                    and abs(float(ens_ret)) >= ENSEMBLE_CLEAR_PCT
                ):
                    x_w = FLAT_XGB_WEIGHT
                weighted.append((x_w, float(x_ret), "xgb"))

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
            elif (
                ens_ret is not None
                and abs(x_ret) < FLAT_XGB_ABS_PCT
                and abs(float(ens_ret)) >= ENSEMBLE_CLEAR_PCT
            ):
                base_w = 0.08
                weighted = [
                    (0.72, float(ens_ret), "ensemble"),
                    (FLAT_XGB_WEIGHT, x_ret, "xgb"),
                ]
            elif (
                ens_ret is not None
                and x_ret <= -CLEAR_XGB_BEARISH_PCT
                and float(ens_ret) >= 0.20
            ):
                base_w = 0.05
                weighted = [
                    (CLEAR_XGB_BEARISH_WEIGHT, x_ret, "xgb"),
                    (0.47, float(ens_ret), "ensemble"),
                ]
        # Crude & diesel: when geo risk is elevated, lean on ensemble over VAR base
        if product_key in ("Crude_Oil", "ULSD_Diesel") and geo_risk >= 0.07 and ens_ret is not None:
            base_w = 0.08 if ens_sign != base_sign else 0.12
            weighted = [(0.65, float(ens_ret), "ensemble")]

        total_w = sum(w for w, _, _ in weighted) + base_w
        consensus = sum(w * r for w, r, _ in weighted) + base_w * base_ret
        consensus /= total_w if total_w else 1.0

        # When headlines/geopolitics dominate, allow a slightly larger day-1 move
        inv_wow = None
        gas_crack = None
        diesel_crack = None
        distillate_wow = None
        if signal_context:
            per_ctx = signal_context
            if signal_context.get("inventory_weekly") is not None:
                from prediction_attribution import build_current_signal_context
                per_ctx = build_current_signal_context(
                    inventory_weekly=signal_context.get("inventory_weekly"),
                    topic_snapshot=signal_context.get("topic_snapshot"),
                    dollar_index=signal_context.get("dollar_index"),
                    hurricane=signal_context.get("hurricane"),
                    weather=signal_context.get("weather"),
                    crack_spreads=signal_context.get("crack_spreads"),
                    product_key=product_key,
                    catalyst_calendar=signal_context.get("catalyst_calendar"),
                )
            inv_wow = per_ctx.get("inventory_wow_pct")
            gas_crack = per_ctx.get("gasoline_crack_usd_per_bbl")
            if gas_crack is None:
                cracks = signal_context.get("crack_spreads") or {}
                gas_crack = cracks.get("gasoline_crack_usd_per_bbl") or cracks.get("gasoline")
            diesel_crack = per_ctx.get("diesel_crack_usd_per_bbl")
            if diesel_crack is None:
                cracks = signal_context.get("crack_spreads") or {}
                diesel_crack = (
                    cracks.get("diesel_crack_usd_per_bbl")
                    or cracks.get("diesel")
                    or cracks.get("ulsd_crack_usd_per_bbl")
                )
            dist_row = (signal_context.get("inventory_weekly") or {}).get("distillate") or {}
            if isinstance(dist_row, dict):
                distillate_wow = dist_row.get("wow_change_pct")
            if distillate_wow is None:
                distillate_wow = (inv_weekly.get("distillate") or {}).get("wow_change_pct")
        else:
            diesel_crack = None

        if geo_risk >= 0.07 and ens_ret is not None and abs(float(ens_ret)) > abs(consensus):
            # Don't let geo headlines override a bearish inventory signal
            if inv_wow is None or not (float(inv_wow) > 0.8 and float(ens_ret) > 0):
                consensus = 0.72 * float(ens_ret) + 0.28 * consensus

        # Weekend/holiday + elevated geo: lean harder into news/ensemble (shock opens)
        # Skip bullish lean the day after a blow-off (mean reversion setup)
        skip_bullish_gap_lean = False
        try:
            from live_prices import recent_session_return_pct as _rsr
            _cm = _rsr("Crude_Oil", days=1, history=price_history)
            _om = _rsr(product_key, days=1, history=price_history)
            _o3 = _rsr(product_key, days=THRUST_LOOKBACK_SESSIONS, history=price_history)
            if print_ctx.get("eia_imminent") and _o3 is not None and _o3 >= THRUST_TRIGGER_PCT:
                skip_bullish_gap_lean = True
            if (_cm is not None and _cm >= COMPLEX_SPIKE_TRIGGER_PCT) or (
                _om is not None and _om >= POST_SPIKE_TRIGGER_PCT
            ):
                skip_bullish_gap_lean = True
            # Also skip bounce lean after spike->selloff Friday into weekend
            try:
                from live_prices import prior_session_return_pct as _psr
                _prev = _psr(product_key, history=price_history)
                if (
                    _prev is not None
                    and _prev >= POST_SPIKE_TRIGGER_PCT
                    and _om is not None
                    and _om <= -MOMENTUM_TRIGGER_PCT
                ):
                    skip_bullish_gap_lean = True
            except Exception:
                pass
        except Exception:
            pass
        if gap_risk.get("active") and ens_ret is not None and not skip_bullish_gap_lean:
            w = 0.55 + 0.25 * float(gap_risk.get("score") or 0)
            if inv_wow is None or not (float(inv_wow) > 0.8 and float(ens_ret) > 0):
                consensus = w * float(ens_ret) + (1.0 - w) * consensus

        consensus, mom_meta = _apply_momentum_continuation(
            product_key,
            consensus,
            price_history=price_history,
            ensemble_return=float(ens_ret) if ens_ret is not None else None,
            inventory_wow_pct=inv_wow,
            gasoline_crack=float(gas_crack) if gas_crack is not None else None,
        )

        complex_fade_meta = None
        consensus, complex_fade_meta = _apply_complex_spike_fade(
            product_key,
            consensus,
            price_history=price_history,
            cap_mult=cap_mult,
            inventory_wow_pct=inv_wow,
            gasoline_crack=float(gas_crack) if gas_crack is not None else None,
        )

        washout_meta = None
        selloff_cont_meta = None
        selloff_mode = mom_meta and mom_meta.get("mode") == "selloff_after_spike"
        if not selloff_mode and not complex_fade_meta:
            consensus, selloff_cont_meta = _apply_selloff_continuation(
                product_key,
                consensus,
                price_history=price_history,
                cap_mult=cap_mult,
            )
        if not selloff_mode and not complex_fade_meta and not selloff_cont_meta:
            consensus, washout_meta = _apply_washout_bounce(
                product_key,
                consensus,
                price_history=price_history,
                live_by_product=live_by_product,
                settle_price=current,
                cap_mult=cap_mult,
            )

        thrust_meta = None
        fading = bool(
            (mom_meta and mom_meta.get("mode") in (
                "post_spike_fade",
                "rbob_soft_fade",
                "bounce_fade",
                "reversal_fade",
                "selloff_after_spike",
            ))
            or complex_fade_meta
            or washout_meta
            or selloff_cont_meta
        )
        if not fading and not print_ctx.get("eia_imminent"):
            consensus, thrust_meta = _apply_thrust_continuation(
                product_key,
                consensus,
                price_history=price_history,
                ensemble_return=float(ens_ret) if ens_ret is not None else None,
                gap_risk=gap_risk,
                cap_mult=cap_mult,
            )

        prior_session_pct = None
        if mom_meta and mom_meta.get("prior_session_pct") is not None:
            prior_session_pct = float(mom_meta["prior_session_pct"])
        else:
            try:
                from live_prices import recent_session_return_pct
                prior_session_pct = recent_session_return_pct(product_key, days=1, history=price_history)
            except ImportError:
                prior_session_pct = None

        headline_meta = None
        consensus, headline_meta = _apply_headline_pullback(
            product_key,
            consensus,
            prior_session_pct,
            signal_context,
        )

        pre_eia_meta = None
        consensus, pre_eia_meta = _apply_pre_eia_caution(
            product_key,
            consensus,
            price_history=price_history,
            print_ctx=print_ctx,
            inventory_wow_pct=inv_wow,
            crude_inventory_wow_pct=crude_inv_wow,
            cap_mult=cap_mult,
        )

        lag_meta = None
        if not fading:
            consensus, lag_meta = _apply_product_lag_catchup(
                product_key,
                consensus,
                price_history=price_history,
                ensemble_return=float(ens_ret) if ens_ret is not None else None,
                print_ctx=print_ctx,
                gasoline_crack=float(gas_crack) if gas_crack is not None else None,
                distillate_wow_pct=float(distillate_wow) if distillate_wow is not None else None,
                cap_mult=cap_mult,
            )

        if weekend_gap:
            spill_meta = None
        else:
            consensus, spill_meta = _apply_crude_spillover(
                product_key,
                consensus,
                price_history=price_history,
                ensemble_return=float(ens_ret) if ens_ret is not None else None,
            )

        learn_meta = None
        try:
            from prediction_attribution import apply_signal_learning, build_current_signal_context
            sig_ctx = signal_context or {}
            if sig_ctx.get("inventory_wow_pct") is not None and not sig_ctx.get("inventory_weekly"):
                per_product_ctx = sig_ctx
            else:
                per_product_ctx = build_current_signal_context(
                    inventory_weekly=sig_ctx.get("inventory_weekly"),
                    topic_snapshot=sig_ctx.get("topic_snapshot"),
                    dollar_index=sig_ctx.get("dollar_index"),
                    hurricane=sig_ctx.get("hurricane"),
                    weather=sig_ctx.get("weather"),
                    crack_spreads=sig_ctx.get("crack_spreads"),
                    product_key=product_key,
                    catalyst_calendar=sig_ctx.get("catalyst_calendar"),
                )
            consensus, learn_meta = apply_signal_learning(product_key, consensus, per_product_ctx)
        except Exception:
            learn_meta = None

        catalyst_meta = None
        feat = ((signal_context or {}).get("catalyst_calendar") or {}).get("product_features") or {}
        feat = feat.get(product_key) or {}
        cat_nudge = feat.get("day1_nudge_pct")
        if feat.get("fresh_print") and cat_nudge is not None and abs(float(cat_nudge)) >= 0.04:
            nudge = float(cat_nudge)
            # Soften mild inventory WAIT/bearish nudges when products are set up to catch crude
            # or distillate is drawing into a clear ensemble bid (Fri Aug 21 under-call).
            soft_inv = (
                nudge < 0
                and abs(nudge) <= 0.20
                and (inv_wow is None or float(inv_wow) < 0.8)
                and (
                    bool(lag_meta)
                    or (
                        distillate_wow is not None
                        and float(distillate_wow) <= -1.0
                        and ens_ret is not None
                        and float(ens_ret) >= 0.50
                    )
                )
            )
            if soft_inv:
                nudge *= 0.35
            before = consensus
            consensus = consensus + nudge
            catalyst_meta = {
                "nudge_pct": round(float(nudge), 4),
                "inventory_z": feat.get("inventory_z"),
                "lean": feat.get("lean"),
                "consensus_before": round(before, 4),
                "consensus_after": round(consensus, 4),
                "rule": "z<0 draw-vs-typical bullish; not actual>forecast",
                "softened_for_lag_catchup": bool(soft_inv and float(cat_nudge) < 0),
            }

        event_momentum_meta = None
        consensus, event_momentum_meta = _apply_post_inventory_momentum(
            product_key,
            consensus,
            price_history=price_history,
            signal_context=signal_context,
            cap_mult=cap_mult,
        )

        divergence_meta = None
        consensus, divergence_meta = _apply_crude_rally_gasoline_divergence(
            product_key,
            consensus,
            current,
            live_by_product,
            prior_session_pct=prior_session_pct,
            cap_mult=cap_mult,
        )

        distillate_rally_meta = None
        consensus, distillate_rally_meta = _apply_distillate_crude_rally(
            product_key,
            consensus,
            current,
            live_by_product,
            price_history=price_history,
            cap_mult=cap_mult,
        )

        rotation_meta = None
        consensus, rotation_meta = _apply_gas_diesel_rotation(
            product_key,
            consensus,
            price_history=price_history,
            diesel_crack=float(diesel_crack) if diesel_crack is not None else None,
            distillate_wow=float(distillate_wow) if distillate_wow is not None else None,
            live_by_product=live_by_product,
            settle_price=current,
            cap_mult=cap_mult,
        )

        overnight_meta = None
        consensus, overnight_meta = _apply_overnight_gap(
            product_key,
            consensus,
            current,
            live_by_product,
            gap_risk=gap_risk,
            cap_mult=cap_mult,
            prior_session_pct=prior_session_pct,
        )
        overnight_dominates = bool(overnight_meta and overnight_meta.get("dominates"))

        ml_overnight_anchor = None
        # Don't force bearish ML over a gas-rotation bounce when overnight is already green
        # Also don't undo a dominating overnight bid (Sep 7: live Oct +6% vs wrong settle)
        overnight_gap_pct = float((overnight_meta or {}).get("gap_pct") or 0)
        skip_ml_overnight_anchor = bool(
            (rotation_meta and rotation_meta.get("mode") == "gas_bounce_after_washout")
            or (
                overnight_meta
                and overnight_meta.get("dominates")
                and overnight_gap_pct >= 1.5
            )
        )
        xgb_bearish_clear = (
            product_key == "RBOB_Gasoline"
            and xgb_info.get("used")
            and float(xgb_info.get("predicted_return_pct") or 0) <= -CLEAR_XGB_BEARISH_PCT
        )
        if (
            xgb_bearish_clear
            and overnight_meta
            and consensus > 0
            and not skip_ml_overnight_anchor
        ):
            before_ml = consensus
            x_ret = float(xgb_info.get("predicted_return_pct") or 0)
            anchor = x_ret * 0.72
            consensus = 0.58 * anchor + 0.42 * consensus
            if _sign(consensus) > 0 and x_ret <= -0.80:
                consensus = min(consensus, -0.25)
            consensus = _clamp_return_pct(consensus, product_key, cap_mult=cap_mult)
            ml_overnight_anchor = {
                "xgb_pct": round(x_ret, 3),
                "consensus_before": round(before_ml, 4),
                "consensus_after": round(consensus, 4),
            }
            overnight_dominates = False

        mag_meta = None
        if not overnight_dominates and not print_ctx.get("eia_imminent"):
            try:
                from regime_learning import apply_clear_direction_scale

                consensus, mag_meta = apply_clear_direction_scale(product_key, consensus)
            except Exception:
                mag_meta = None

        # Large overnight move into a risky weekend: allow near shock-sized day-1
        if (
            overnight_meta
            and gap_risk.get("active")
            and abs(float(overnight_meta.get("gap_pct") or 0)) >= 2.0
        ):
            cap_mult = max(cap_mult, 2.4)
            consensus = _clamp_return_pct(consensus, product_key, cap_mult=cap_mult)

        # Only dampen tape when weekend gap but NOT elevated shock risk
        # Never undo overnight direction with ensemble/weekend floors
        if overnight_dominates:
            pass
        elif weekend_gap and not gap_risk.get("active"):
            consensus = consensus * 0.72
        elif weekend_crossing and gap_risk.get("active") and abs(consensus) < 0.8 and not xgb_bearish_clear:
            # Quiet consensus into a risky weekend: nudge magnitude toward wider floor
            floor = 1.0 + 1.5 * float(gap_risk.get("score") or 0)
            if ens_ret is not None and abs(float(ens_ret)) >= abs(consensus):
                consensus = float(ens_ret)
            if abs(consensus) < floor and _sign(consensus or (ens_ret or 0)):
                direction = _sign(consensus) or _sign(float(ens_ret or 0))
                consensus = direction * max(abs(consensus), floor * 0.55)

        consensus = _clamp_return_pct(consensus, product_key, cap_mult=cap_mult)
        _set_day1(block, current, consensus, product_key, cap_mult=cap_mult)
        meta_out[product_key] = {
            "consensus_return_pct": round(consensus, 4),
            "base_return_pct": round(base_ret, 4),
            "ensemble_return_pct": round(float(ens_ret), 4) if ens_ret is not None else None,
            "xgb_return_pct": round(float(xgb_info.get("predicted_return_pct")), 4)
            if product_key == "RBOB_Gasoline" and xgb_info.get("used")
            else None,
            "weights": {label: w for w, _, label in weighted},
            "base_weight": base_w,
            "gap_risk": gap_risk,
            "cap_mult": round(cap_mult, 3),
        }
        if weekend_gap:
            meta_out[product_key]["weekend_gap"] = True
            meta_out[product_key]["weekend_gap_dampen"] = (
                None if gap_risk.get("active") else 0.72
            )
        if weekend_crossing:
            meta_out[product_key]["weekend_crossing"] = True
        if mom_meta:
            meta_out[product_key]["momentum_continuation"] = mom_meta
        if complex_fade_meta:
            meta_out[product_key]["complex_spike_fade"] = complex_fade_meta
        if washout_meta:
            meta_out[product_key]["washout_bounce"] = washout_meta
        if event_momentum_meta:
            meta_out[product_key]["post_inventory_momentum"] = event_momentum_meta
        if divergence_meta:
            meta_out[product_key]["crude_rally_gasoline_divergence"] = divergence_meta
        if distillate_rally_meta:
            meta_out[product_key]["distillate_crude_rally"] = distillate_rally_meta
        if rotation_meta:
            meta_out[product_key]["gas_diesel_rotation"] = rotation_meta
        if selloff_cont_meta:
            meta_out[product_key]["selloff_continuation"] = selloff_cont_meta
        if thrust_meta:
            meta_out[product_key]["thrust_continuation"] = thrust_meta
        if pre_eia_meta:
            meta_out[product_key]["pre_eia_caution"] = pre_eia_meta
        if lag_meta:
            meta_out[product_key]["product_lag_catchup"] = lag_meta
        if headline_meta:
            meta_out[product_key]["headline_pullback"] = headline_meta
        if spill_meta:
            meta_out[product_key]["crude_spillover"] = spill_meta
        if learn_meta:
            meta_out[product_key]["signal_learning"] = learn_meta
        if catalyst_meta:
            meta_out[product_key]["inventory_surprise"] = catalyst_meta
        if overnight_meta:
            meta_out[product_key]["overnight_gap"] = overnight_meta
        if ml_overnight_anchor:
            meta_out[product_key]["ml_overnight_anchor"] = ml_overnight_anchor
        if mag_meta:
            meta_out[product_key]["regime_magnitude"] = mag_meta

    return results, meta_out
