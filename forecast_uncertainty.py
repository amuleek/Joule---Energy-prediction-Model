"""
Day-1 forecast uncertainty: flag low conviction and explain why (all three products).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

PRODUCTS = ("RBOB_Gasoline", "ULSD_Diesel", "Crude_Oil")

GEO_ELEVATED = 0.07
FLAT_MOVE_PCT = 0.35
LOW_CONFIDENCE = 55


def _sign(x: float, eps: float = 0.08) -> int:
    if x > eps:
        return 1
    if x < -eps:
        return -1
    return 0


def _tomorrow_pct(block: Dict[str, Any]) -> float:
    d1 = block.get("day_1") or block.get("next_day") or {}
    if isinstance(d1, dict):
        try:
            return float(d1.get("change_percent", 0))
        except (TypeError, ValueError):
            return 0.0
    return float(block.get("day_1_change", block.get("next_day_change", 0)) or 0)


def _layer_disagreement(ensemble_block: Dict[str, Any]) -> Optional[str]:
    comp = ensemble_block.get("components") or {}
    if not comp:
        return None
    signs: Dict[str, int] = {}
    for layer in ("technical", "fundamental", "news"):
        ret = (comp.get(layer) or {}).get("return_pct")
        if ret is None:
            continue
        s = _sign(float(ret))
        if s:
            signs[layer] = s
    if len(signs) < 2:
        return None
    vals = list(signs.values())
    if len(set(vals)) > 1:
        parts = [f"{k} {'+' if v > 0 else '-'}" for k, v in signs.items()]
        return f"Model layers disagree ({', '.join(parts)})"
    return None


def assess_product_uncertainty(
    product_key: str,
    block: Dict[str, Any],
    meta: Dict[str, Any],
    day1_meta: Optional[Dict[str, Any]] = None,
    ensemble_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Score uncertainty and return human-readable reasons."""
    day1_meta = day1_meta or {}
    ensemble_meta = ensemble_meta or {}
    reasons: List[str] = []
    score = 0

    d1_pct = _tomorrow_pct(block)
    dv = block.get("directional") or {}
    conf = int(dv.get("confidence", 50) or 50)

    geo = meta.get("geo_risk_score")
    if geo is None:
        topic = meta.get("topic_snapshot") or {}
        geo = topic.get("geo_risk_score")
    geo_f = float(geo or 0)

    if geo_f >= GEO_ELEVATED:
        score += 2
        reasons.append(
            f"Geopolitical risk elevated ({geo_f:.0%} of headlines) — "
            "prices can gap beyond the model on news"
        )

    if abs(d1_pct) < FLAT_MOVE_PCT:
        score += 2
        reasons.append(
            f"Model tomorrow move is only {d1_pct:+.2f}% — "
            "recent sessions moved 2–4% on headline days"
        )

    if conf < LOW_CONFIDENCE:
        score += 1
        reasons.append(
            f"Mixed signals (confidence {conf}%) — inventory, model, and headlines don't align"
        )

    ens = ensemble_meta.get(product_key) or {}
    d1m = day1_meta.get(product_key) or {}
    base_ret = d1m.get("base_return_pct")
    ens_ret = d1m.get("ensemble_return_pct")

    gap = d1m.get("gap_risk") or meta.get("gap_risk") or {}
    if gap.get("active"):
        score += 2
        reasons_gap = ", ".join(gap.get("reasons") or []) or "weekend/news shock risk"
        reasons.append(
            f"Gap risk elevated ({reasons_gap}) — Monday opens can move far beyond day-1 caps"
        )
    overnight = d1m.get("overnight_gap") or {}
    if overnight.get("gap_pct") is not None and abs(float(overnight["gap_pct"])) >= 2.0:
        score += 1
        reasons.append(
            f"Overnight tape already {float(overnight['gap_pct']):+.1f}% vs settle — "
            "session close may gap further"
        )
    if base_ret is not None and ens_ret is not None:
        if _sign(float(base_ret)) and _sign(float(ens_ret)) and _sign(float(base_ret)) != _sign(float(ens_ret)):
            score += 1
            reasons.append("Short-term models disagree with the base VAR forecast")

    layer_msg = _layer_disagreement(ens)
    if layer_msg:
        score += 1
        reasons.append(layer_msg)

    inv = meta.get("inventory_weekly") or {}
    inv_key = {"RBOB_Gasoline": "gasoline", "ULSD_Diesel": "distillate", "Crude_Oil": "crude"}.get(
        product_key, "crude"
    )
    wow = (inv.get(inv_key) or {}).get("wow_change_pct")
    if wow is not None and _sign(float(wow)) and _sign(d1_pct):
        if _sign(float(wow)) != _sign(d1_pct):
            score += 1
            word = "build" if float(wow) > 0 else "draw"
            reasons.append(f"Weekly stocks {word} ({float(wow):+.1f}% WoW) vs model direction")

    cal = meta.get("catalyst_calendar") or meta.get("event_intel") or {}
    nxt = cal.get("next_high_impact") or cal.get("next") or {}
    hrs = nxt.get("hours_to")
    if hrs is not None and float(hrs) <= 20 and int(nxt.get("importance") or 0) >= 7:
        score += 2
        reasons.append(
            f"{nxt.get('report')} in {float(hrs):.0f}h — day-1 can gap beyond the model"
        )

    if score >= 4:
        level = "HIGH"
    elif score >= 2:
        level = "MEDIUM"
    elif score >= 1:
        level = "LOW"
    else:
        level = "NONE"

    headline = {
        "HIGH": "Low conviction — tomorrow can differ sharply from the model",
        "MEDIUM": "Moderate uncertainty — treat tomorrow as tentative",
        "LOW": "Some uncertainty on the near-term call",
        "NONE": "",
    }.get(level, "")

    return {
        "level": level,
        "score": score,
        "headline": headline,
        "reasons": reasons[:4],
        "tomorrow_change_pct": round(d1_pct, 4),
        "confidence_pct": conf,
        "geo_risk_score": round(geo_f, 4) if geo_f else None,
    }


def apply_forecast_uncertainty(
    predictions_json: Dict[str, Any],
    day1_meta: Optional[Dict[str, Any]] = None,
    ensemble_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Attach forecast_uncertainty to each product and summarize in _meta."""
    meta = predictions_json.get("_meta") or {}
    day1_meta = day1_meta or meta.get("day1_consensus") or {}
    ensemble_meta = ensemble_meta or meta.get("ensemble") or {}

    summary: Dict[str, Any] = {}
    for pk in PRODUCTS:
        block = predictions_json.get(pk)
        if not isinstance(block, dict):
            continue
        unc = assess_product_uncertainty(pk, block, meta, day1_meta, ensemble_meta)
        block["forecast_uncertainty"] = unc
        summary[pk] = {"level": unc["level"], "headline": unc["headline"]}

        ts = block.get("trading_signal")
        if isinstance(ts, dict) and unc["level"] in ("HIGH", "MEDIUM"):
            ts["subhead"] = f"{unc['headline']} · Confidence: {unc['confidence_pct']}%"

        dv = block.get("directional")
        if isinstance(dv, dict) and unc["level"] in ("HIGH", "MEDIUM"):
            dv["confidence"] = min(int(dv.get("confidence", 50) or 50), 48)

    meta["forecast_uncertainty"] = summary
    predictions_json["_meta"] = meta
    return predictions_json


def build_uncertainty_sentence(unc: Dict[str, Any]) -> str:
    """One line for email / reasoning."""
    if not unc or unc.get("level") in (None, "NONE"):
        return ""
    parts = [unc.get("headline", "")]
    for r in unc.get("reasons") or []:
        parts.append(r)
    return " ".join(p for p in parts if p).strip()
