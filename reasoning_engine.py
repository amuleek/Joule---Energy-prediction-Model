"""
Short, crisp market reasoning for emails (1–2 sentences max).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _tomorrow_pct(pred: Dict[str, Any]) -> float:
    d1 = pred.get("day_1") or pred.get("next_day") or {}
    if isinstance(d1, dict):
        return float(d1.get("change_percent", 0))
    cur = float(pred.get("current_price", 0) or 0)
    if cur <= 0:
        return 0.0
    return ((float(d1) - cur) / cur * 100) if d1 else 0.0


def _pick_drivers(
    product_key: str,
    pred: Dict[str, Any],
    meta: Dict[str, Any],
    all_preds: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Return up to 3 short driver clauses, highest signal first."""
    drivers: List[str] = []
    dv = pred.get("directional") or {}
    dd = dv.get("drivers") or {}

    inv = meta.get("inventory_weekly") or {}
    inv_key = {"RBOB_Gasoline": "gasoline", "ULSD_Diesel": "distillate", "Crude_Oil": "crude"}.get(
        product_key, "crude"
    )
    wow = (inv.get(inv_key) or {}).get("wow_change_pct")
    if wow is not None:
        w = float(wow)
        if w < -0.25:
            drivers.append(f"{inv_key.title()} stocks drew {abs(w):.1f}% WoW")
        elif w > 0.25:
            drivers.append(f"{inv_key.title()} build +{w:.1f}% WoW adds supply")
        elif abs(w) >= 0.1:
            drivers.append(f"Stocks stable ({w:+.1f}% WoW)")

    if product_key != "Crude_Oil" and all_preds:
        crude = all_preds.get("Crude_Oil") or {}
        cp = _tomorrow_pct(crude)
        if abs(cp) >= 0.4:
            word = "firm" if cp > 0 else "soft"
            drivers.append(f"WTI {word} ({cp:+.1f}% path) anchors products")

    crack = meta.get("crack_spreads_current") or {}
    if product_key == "RBOB_Gasoline":
        gc = crack.get("gasoline_crack_usd_per_bbl")
        if gc is not None and float(gc) > 20:
            drivers.append(f"Gas crack ${float(gc):.0f}/bbl supports margins")
    elif product_key == "ULSD_Diesel":
        dc = crack.get("diesel_crack_usd_per_bbl")
        if dc is not None and float(dc) > 25:
            drivers.append(f"Diesel crack ${float(dc):.0f}/bbl")

    dxy = meta.get("dollar_index") or {}
    chg = dxy.get("change_pct_1d")
    if chg is not None and abs(float(chg)) >= 0.05:
        c = float(chg)
        drivers.append(f"USD {c:+.2f}% ({'headwind' if c > 0 else 'tailwind'})")

    geo = meta.get("geopolitical_topics") or {}
    for d in (geo.get("top_drivers") or [])[:1]:
        short = d.split("(")[0].strip()[:45]
        if short:
            drivers.append(short)

    sent = dd.get("sentiment") or meta.get("sentiment")
    if sent is not None and abs(float(sent)) > 0.12:
        drivers.append(f"Headline tone {'risk-on' if float(sent) > 0 else 'cautious'}")

    util = (meta.get("operational") or {}).get("refinery_utilization_pct")
    if util is not None and product_key == "RBOB_Gasoline":
        u = float(util)
        if u >= 88:
            drivers.append(f"Refinery runs high ({u:.0f}%)")
        elif u <= 82:
            drivers.append(f"Refinery runs muted ({u:.0f}%)")

    return drivers[:3]


def build_crisp_product_reasoning(
    product_key: str,
    pred: Dict[str, Any],
    meta: Dict[str, Any],
    all_preds: Optional[Dict[str, Any]] = None,
    **_kwargs: Any,
) -> str:
    """One crisp line: verdict + uncertainty (if any) + top drivers."""
    chg = _tomorrow_pct(pred)
    unc = pred.get("forecast_uncertainty") or {}
    unc_level = unc.get("level", "NONE")

    if unc_level in ("HIGH", "MEDIUM"):
        verdict = f"Low conviction — model {chg:+.1f}% tomorrow"
        unc_bits = unc.get("reasons") or []
        if unc_bits:
            return f"{verdict}. {unc_bits[0]}."
        return f"{verdict}. Mixed signals — actual move may be larger than shown."

    if chg > 0.35:
        verdict = f"Lean bullish - tomorrow {chg:+.1f}%"
    elif chg < -0.35:
        verdict = f"Lean bearish - tomorrow {chg:+.1f}%"
    else:
        verdict = f"Neutral tone - tomorrow {chg:+.1f}%"

    drivers = _pick_drivers(product_key, pred, meta, all_preds)
    if not drivers:
        label = (pred.get("directional") or {}).get("label", "NEUTRAL")
        return f"{verdict}. View: {label.lower()}."

    return f"{verdict}. {', '.join(drivers)}."


def build_all_reasoning(
    predictions_json: Dict[str, Any],
    ensemble_meta: Optional[Dict[str, Any]] = None,
    rag_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    meta = predictions_json.get("_meta") or {}
    out = {}
    for pk in ("RBOB_Gasoline", "ULSD_Diesel", "Crude_Oil"):
        pred = predictions_json.get(pk)
        if not isinstance(pred, dict):
            continue
        out[pk] = build_crisp_product_reasoning(pk, pred, meta, predictions_json)
    return out
