"""
Inventory + prediction intelligence: weekly EIA signals, directional labels, confidence.
Rule-based narratives today; swap in LLM for richer event copy in Phase 2.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import pandas as pd

from market_features import (
    build_buy_recommendation,
    build_horizon_outlook,
    compute_layer_scores,
    latest_feature_snapshot,
)

DISPLAY_NAME = {
    "RBOB_Gasoline": "RBOB / gasoline",
    "ULSD_Diesel": "ULSD / diesel",
    "Crude_Oil": "WTI crude",
}


PRODUCT_INVENTORY_KEY = {
    "RBOB_Gasoline": "gasoline",
    "ULSD_Diesel": "distillate",
    "Crude_Oil": "crude",
}


def _horizon_change_pct(block: Dict[str, Any], key: str, legacy_key: Optional[str] = None) -> float:
    """Read % change from nested horizon dict or flat predictor keys."""
    h = block.get(key)
    if isinstance(h, dict):
        try:
            return float(h.get("change_percent", 0))
        except (TypeError, ValueError):
            return 0.0
    lk = legacy_key or key
    try:
        return float(block.get(f"{lk}_change", block.get(f"{key}_change", 0)))
    except (TypeError, ValueError):
        return 0.0


def _horizon_price(block: Dict[str, Any], key: str) -> Optional[float]:
    h = block.get(key)
    if isinstance(h, dict) and h.get("price") is not None:
        try:
            return float(h["price"])
        except (TypeError, ValueError):
            return None
    if key in block and not isinstance(block.get(key), dict):
        try:
            return float(block[key])
        except (TypeError, ValueError):
            return None
    return None

def load_inventory_history(csv_path: str = "data/inventory.csv") -> Optional[pd.DataFrame]:
    if not os.path.exists(csv_path):
        return None
    df = pd.read_csv(csv_path)
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    return df


def weekly_inventory_snapshot(df: Optional[pd.DataFrame]) -> Dict[str, Any]:
    """
    Latest levels and week-over-week % change for crude / gasoline / distillate.
    """
    out: Dict[str, Any] = {
        "crude": None,
        "gasoline": None,
        "distillate": None,
        "source": "EIA weekly (stocks)",
    }
    if df is None or len(df) < 1:
        return out

    def snap(col: str, name: str) -> Optional[Dict[str, float]]:
        if col not in df.columns:
            return None
        s = df[col].astype(float)
        last = s.iloc[-1]
        prev = s.iloc[-2] if len(df) >= 2 else None
        row: Dict[str, Any] = {
            "level_kbbl": float(last),
            "units": "thousand barrels",
        }
        if prev is not None and prev and not pd.isna(prev):
            wow = ((float(last) - float(prev)) / float(prev)) * 100.0
            row["wow_change_pct"] = round(wow, 3)
            row["direction"] = "DOWN" if wow < 0 else "UP" if wow > 0 else "FLAT"
        return row

    out["gasoline"] = snap("gasoline_inventory", "gasoline")
    out["distillate"] = snap("diesel_inventory", "distillate")
    out["crude"] = snap("crude_inventory", "crude")
    return out


def _inv_signal_strength(wow_pct: Optional[float]) -> float:
    """-1 bearish (build) … +1 bullish (draw)."""
    if wow_pct is None:
        return 0.0
    # Saturate around ±3% weekly move
    return max(-1.0, min(1.0, -wow_pct / 3.0))


def _pred_signal_strength(change_pct: float) -> float:
    return max(-1.0, min(1.0, change_pct / 5.0))


def _geo_signal_strength(geo_risk: Optional[float]) -> float:
    """Higher geo_risk → supportive for petroleum prices."""
    if geo_risk is None:
        return 0.0
    return max(-1.0, min(1.0, float(geo_risk) * 2.0 - 0.5))


def directional_view_for_product(
    product_key: str,
    product_block: Dict[str, Any],
    inv_snapshot: Dict[str, Any],
    sentiment: Optional[float] = None,
    topic_snapshot: Optional[Dict[str, Any]] = None,
    feature_snap: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Combine inventory WoW + model next-week tilt + optional sentiment into
    BULLISH / BEARISH / NEUTRAL with confidence 0–100 and a short rationale.
    """
    inv_name = PRODUCT_INVENTORY_KEY.get(product_key)
    pred_week_pct = _horizon_change_pct(product_block, "day_7", "next_week")
    pred_day_pct = _horizon_change_pct(product_block, "day_1", "next_day")

    inv_part = None
    if inv_name == "gasoline":
        inv_part = inv_snapshot.get("gasoline")
    elif inv_name == "distillate":
        inv_part = inv_snapshot.get("distillate")
    elif inv_name == "crude":
        inv_part = inv_snapshot.get("crude")

    wow = None
    if inv_part and "wow_change_pct" in inv_part:
        wow = float(inv_part["wow_change_pct"])

    s_inv = _inv_signal_strength(wow)
    s_pred = 0.55 * _pred_signal_strength(pred_day_pct) + 0.45 * _pred_signal_strength(pred_week_pct)
    s_sent = 0.0
    if sentiment is not None:
        s_sent = max(-1.0, min(1.0, float(sentiment) * 2.0))
    geo_risk = None
    if topic_snapshot:
        geo_risk = topic_snapshot.get("geo_risk_score")
    s_geo = _geo_signal_strength(geo_risk)

    # Dampen bullish labels when recent tape momentum contradicts the model
    s_tech = 0.0
    if feature_snap and product_key == "RBOB_Gasoline":
        tech = feature_snap.get("technical") or {}
        mom5 = tech.get("momentum_5d_pct")
        if mom5 is not None:
            s_tech = max(-1.0, min(1.0, float(mom5) / 5.0))
            if float(mom5) < -1.0 and pred_day_pct > 0.5:
                s_pred *= 0.45
            if float(mom5) < -1.5 and pred_day_pct > 0:
                s_inv *= 0.6

    score = 0.32 * s_inv + 0.32 * s_pred + 0.12 * s_sent + 0.12 * s_geo + 0.12 * s_tech
    if score > 0.2:
        label = "BULLISH"
    elif score < -0.2:
        label = "BEARISH"
    else:
        label = "NEUTRAL"

    confidence = min(
        0.95,
        0.35
        + 0.25 * abs(s_inv)
        + 0.22 * abs(s_pred)
        + 0.08 * abs(s_sent)
        + 0.08 * abs(s_geo),
    )
    confidence_pct = int(round(confidence * 100))

    reasons: List[str] = []
    if wow is not None:
        if wow < 0:
            reasons.append(f"Weekly {inv_name} inventories drew {abs(wow):.2f}% (typically supportive).")
        elif wow > 0:
            reasons.append(f"Weekly {inv_name} inventories built {wow:.2f}% (typically a headwind).")
    reasons.append(f"Model tomorrow: {pred_day_pct:+.2f}%; day 7 outlook: {pred_week_pct:+.2f}%.")
    if sentiment is not None and abs(sentiment) > 0.05:
        reasons.append(f"News sentiment: {sentiment:+.2f}.")
    if topic_snapshot and topic_snapshot.get("top_drivers"):
        reasons.append("Headlines: " + "; ".join(topic_snapshot["top_drivers"][:2]) + ".")

    summary = " ".join(reasons[:4])

    return {
        "label": label,
        "emoji": {"BULLISH": "📈", "BEARISH": "📉", "NEUTRAL": "⚖️"}.get(label, "⚖️"),
        "confidence": confidence_pct,
        "score": round(score, 4),
        "summary": summary,
        "drivers": {
            "inventory_wow_pct": wow,
            "model_next_day_pct": round(pred_day_pct, 4),
            "model_next_week_pct": round(pred_week_pct, 4),
            "sentiment": sentiment,
            "geo_risk_score": geo_risk,
        },
    }


def build_trading_signal(
    product_key: str,
    predictions_json: Dict[str, Any],
    inv_snapshot: Dict[str, Any],
    topic_snapshot: Optional[Dict[str, Any]] = None,
    *,
    layer_scores: Optional[Dict[str, Any]] = None,
    feature_snap: Optional[Dict[str, Any]] = None,
    rbob_horizons: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Trading-style headline: tomorrow move in cents, confidence %, driver bullets.
    Example: Tomorrow RBOB: +4.2¢ | Confidence: 74% | Drivers: crude +2%, …
    """
    block = predictions_json.get(product_key)
    if not isinstance(block, dict):
        return None
    try:
        current = float(block.get("current_price", 0))
    except (TypeError, ValueError):
        current = 0.0
    next_price = _horizon_price(block, "day_1") or _horizon_price(block, "next_day")
    if next_price is None:
        next_price = current
    day_pct = _horizon_change_pct(block, "day_1", "next_day")
    if current <= 0:
        return None

    # Cents per gallon for RBOB/ULSD; $/bbl for crude
    if product_key in ("RBOB_Gasoline", "ULSD_Diesel"):
        delta = (next_price - current) * 100.0
        delta_fmt = f"{delta:+.1f}\u00a2"
    else:
        delta = next_price - current
        delta_fmt = f"{delta:+.2f} $/bbl"

    dv = block.get("directional") or {}
    confidence = int(dv.get("confidence", 50))

    driver_lines: List[str] = []
    crude = predictions_json.get("Crude_Oil") or {}
    c_nd = crude.get("next_day") or {}
    try:
        c_pct = float(c_nd.get("change_percent", 0))
        if abs(c_pct) >= 0.3 and product_key != "Crude_Oil":
            driver_lines.append(f"crude {c_pct:+.1f}%")
    except (TypeError, ValueError):
        pass

    inv_name = PRODUCT_INVENTORY_KEY.get(product_key)
    if inv_name:
        row = inv_snapshot.get(inv_name) or {}
        wow = row.get("wow_change_pct")
        if wow is not None:
            if float(wow) < -0.5:
                driver_lines.append(f"EIA {inv_name} draw {abs(float(wow)):.1f}% WoW")
            elif float(wow) > 0.5:
                driver_lines.append(f"EIA {inv_name} build {float(wow):.1f}% WoW")

    if topic_snapshot:
        for d in (topic_snapshot.get("top_drivers") or [])[:2]:
            short = d.split("(")[0].strip()
            if short:
                driver_lines.append(short)

    xgb = (predictions_json.get("_meta") or {}).get("xgb_rbob") or {}
    if xgb.get("used") and product_key == "RBOB_Gasoline":
        try:
            xp = float(xgb.get("next_day_price", 0))
            cur = float(block.get("current_price", 0) or 0)
            if cur > 0 and xp > 0:
                cents = (xp - cur) * 100
                driver_lines.insert(0, f"ML outlook tomorrow: {cents:+.1f}¢/gal")
        except (TypeError, ValueError):
            pass

    nice = DISPLAY_NAME.get(product_key, product_key)
    direction = "UP" if delta > 0 else "DOWN" if delta < 0 else "FLAT"

    out: Dict[str, Any] = {
        "product_key": product_key,
        "display": nice,
        "tomorrow_delta": round(delta, 2) if product_key == "Crude_Oil" else round(delta, 1),
        "tomorrow_delta_fmt": delta_fmt,
        "tomorrow_change_pct": round(day_pct, 2),
        "direction": direction,
        "confidence_pct": confidence,
        "drivers": driver_lines[:6],
        "drivers_text": ", ".join(driver_lines[:5]) if driver_lines else "No major drivers flagged",
        "headline": f"Tomorrow {nice}: {delta_fmt}",
        "subhead": f"Confidence: {confidence}%",
    }

    if product_key == "RBOB_Gasoline":
        fs = feature_snap or meta.get("market_features") or {}
        layers = layer_scores or meta.get("layer_scores") or compute_layer_scores(
            predictions_json, inv_snapshot, topic_snapshot, fs
        )
        out["horizons"] = rbob_horizons or meta.get("rbob_horizons") or build_horizon_outlook(
            predictions_json
        )
        buy = build_buy_recommendation(out, layers)
        out["buy_recommendation"] = buy
        if fs.get("basis", {}).get("basis_ny_cash_minus_rbob") is not None:
            driver_lines.insert(
                0,
                f"NY basis ${float(fs['basis']['basis_ny_cash_minus_rbob']):+.3f}/gal vs RBOB proxy",
            )
            out["drivers"] = driver_lines[:6]
            out["drivers_text"] = ", ".join(driver_lines[:5])

    return out


def _sentiment_phrase(s: Optional[float]) -> str:
    if s is None:
        return "neutral"
    if s > 0.1:
        return "positive"
    if s < -0.1:
        return "negative"
    return "neutral"


def compose_scenario_rationale(
    product_key: str,
    directional: Dict[str, Any],
    inv_snapshot: Dict[str, Any],
    product_block: Dict[str, Any],
    *,
    model_name: Optional[str] = None,
    crack_current: Optional[Dict[str, Any]] = None,
    crack_next_day: Optional[Dict[str, Any]] = None,
    dollar_index: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Human-readable explanation of *why* the directional label fits this scenario.
    Used in emails; plain text + bullets (caller escapes for HTML).
    """
    label = directional.get("label", "NEUTRAL")
    drivers = directional.get("drivers") or {}
    wow = drivers.get("inventory_wow_pct")
    pred_w = drivers.get("model_next_week_pct")
    sent = drivers.get("sentiment")

    inv_name = PRODUCT_INVENTORY_KEY.get(product_key)
    inv_row = None
    if inv_name == "gasoline":
        inv_row = inv_snapshot.get("gasoline")
    elif inv_name == "distillate":
        inv_row = inv_snapshot.get("distillate")
    elif inv_name == "crude":
        inv_row = inv_snapshot.get("crude")

    nd_pct = _horizon_change_pct(product_block, "day_1", "next_day")
    pred_d7 = _horizon_change_pct(product_block, "day_7", "biweekly")

    nice = DISPLAY_NAME.get(product_key, product_key.replace("_", " "))

    # Scenario headline
    if label == "BULLISH":
        headline = (
            f"The current scenario for {nice} is bullish: the combined read from "
            f"weekly stocks (where available), the model outlook, and headlines leans toward firmer prices."
        )
    elif label == "BEARISH":
        headline = (
            f"The current scenario for {nice} is bearish: inventories, the model path, and/or sentiment "
            f"are leaning toward softer prices over the near term."
        )
    else:
        headline = (
            f"The current scenario for {nice} is neutral: inventory, model, and sentiment do not "
            f"all point the same way—treat moves as tentative."
        )

    bullets: List[str] = []

    if wow is not None:
        if wow < 0:
            bullets.append(
                f"EIA weekly {inv_name} inventories fell about {abs(wow):.2f}% week-over-week. "
                f"Draws often go with tighter supply if demand holds, which tends to support prices."
            )
        elif wow > 0:
            bullets.append(
                f"EIA weekly {inv_name} inventories rose about {wow:.2f}% week-over-week. "
                f"Stock builds add cushion and can cap rallies unless demand accelerates."
            )
        else:
            bullets.append("Weekly inventories were roughly flat versus last week.")
    elif inv_row and inv_row.get("level_kbbl") is not None and inv_name == "crude":
        bullets.append(
            "Crude inventory week-over-week change was not available for this run; "
            "the crude view leans more on the model and news tone."
        )

    if pred_w is not None:
        bullets.append(
            f"The day-7 forecast expects about {pred_w:+.2f}% vs. today—"
            f"a central part of the directional score."
        )

    bullets.append(
        f"Tomorrow’s modeled move is about {nd_pct:+.2f}% vs. current; day-7 path is about {pred_d7:+.2f}%."
    )

    if dollar_index and dollar_index.get("change_pct_1d") is not None:
        try:
            dxy = float(dollar_index["change_pct_1d"])
            if abs(dxy) >= 0.05:
                if dxy > 0:
                    bullets.append(
                        f"US dollar index rose {dxy:+.2f}% — a firmer dollar often pressures crude and products."
                    )
                else:
                    bullets.append(
                        f"US dollar index fell {dxy:+.2f}% — a softer dollar can support energy prices."
                    )
        except (TypeError, ValueError):
            pass

    sp = _sentiment_phrase(sent)
    if sent is not None:
        bullets.append(
            f"Aggregated energy/news sentiment is {sp} (score {sent:+.2f}). "
            f"That nudges the view {'with' if (sent > 0 and label == 'BULLISH') or (sent < 0 and label == 'BEARISH') else 'against'} a purely inventory-driven story."
        )

    # Crack: only for products and when values look sane ($/bbl)
    if crack_current and product_key in ("RBOB_Gasoline", "ULSD_Diesel"):
        try:
            gc = float(crack_current.get("gasoline_crack_usd_per_bbl", 0))
            dc = float(crack_current.get("diesel_crack_usd_per_bbl", 0))
            if abs(gc) < 500 and abs(dc) < 500:
                if product_key == "RBOB_Gasoline":
                    bullets.append(
                        f"Refining margin proxy (gasoline crack ≈ ${gc:.1f}/bbl vs. WTI): stronger cracks can reward refiners "
                        f"and support product pricing when crude is not collapsing."
                    )
                else:
                    bullets.append(
                        f"Refining margin proxy (diesel crack ≈ ${dc:.1f}/bbl vs. WTI): diesel cracks reflect distillate tightness "
                        f"and margin incentives for supply."
                    )
        except (TypeError, ValueError):
            pass

    # Closing line by scenario
    if label == "BULLISH":
        closing = (
            f"Bottom line: for {nice}, the story is constructive—watch for a reversal if inventories surprise large to the upside "
            f"or sentiment sours on macro/risk."
        )
    elif label == "BEARISH":
        closing = (
            f"Bottom line: for {nice}, risks skew lower near term—confirm with another week of data before treating it as a trend."
        )
    else:
        closing = (
            f"Bottom line: for {nice}, treat direction as balanced until inventories or headlines give a cleaner one-sided signal."
        )

    return {
        "headline": headline,
        "bullets": bullets[:8],
        "closing": closing,
        "scenario": label,
    }


def finalize_email_narratives(predictions_json: Dict[str, Any]) -> None:
    """
    Mutates predictions_json: adds directional['scenario_rationale'] on each product block
    using full `_meta` (model, cracks, inventory).
    """
    meta = predictions_json.get("_meta") or {}
    inv_snap = meta.get("inventory_weekly") or {}
    model_name = meta.get("model")
    crack_c = meta.get("crack_spreads_current")
    cf = meta.get("crack_spreads_forecast_var") or {}
    crack_nd = cf.get("next_day") if isinstance(cf, dict) else None
    dollar_index = meta.get("dollar_index") or {}

    for pk, block in list(predictions_json.items()):
        if pk.startswith("_") or not isinstance(block, dict):
            continue
        dv = block.get("directional")
        if not dv:
            continue
        rationale = compose_scenario_rationale(
            pk,
            dv,
            inv_snap,
            block,
            model_name=model_name,
            crack_current=crack_c if isinstance(crack_c, dict) else None,
            crack_next_day=crack_nd if isinstance(crack_nd, dict) else None,
            dollar_index=dollar_index if isinstance(dollar_index, dict) else None,
        )
        dv["scenario_rationale"] = rationale

    # Mirror into _meta.directional_signals for consumers that only read meta
    ds = meta.get("directional_signals")
    if isinstance(ds, dict):
        for pk, dv in ds.items():
            if not isinstance(dv, dict):
                continue
            blk = predictions_json.get(pk)
            if isinstance(blk, dict) and blk.get("directional", {}).get("scenario_rationale"):
                dv["scenario_rationale"] = blk["directional"]["scenario_rationale"]

    story = _compose_global_market_story(predictions_json, meta)
    meta["market_story"] = story
    predictions_json["_meta"] = meta


def _compose_global_market_story(predictions_json: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, str]:
    """Short email intro: what’s driving the complex this week."""
    inv = meta.get("inventory_weekly") or {}
    model = meta.get("model", "Prophet")
    parts: List[str] = []

    g = inv.get("gasoline") or {}
    d = inv.get("distillate") or {}
    c = inv.get("crude") or {}
    if g.get("wow_change_pct") is not None:
        parts.append(
            f"Gasoline stocks moved {float(g['wow_change_pct']):+.2f}% week-over-week."
        )
    if d.get("wow_change_pct") is not None:
        parts.append(
            f"Distillate stocks moved {float(d['wow_change_pct']):+.2f}% week-over-week."
        )
    if c.get("wow_change_pct") is not None:
        parts.append(
            f"Crude stocks moved {float(c['wow_change_pct']):+.2f}% week-over-week."
        )

    labels = []
    for pk in ("Crude_Oil", "RBOB_Gasoline", "ULSD_Diesel"):
        b = predictions_json.get(pk) or {}
        dv = b.get("directional") or {}
        if dv.get("label"):
            labels.append(f"{DISPLAY_NAME.get(pk, pk)}: {dv['label']}")

    para1 = " ".join(parts) if parts else (
        "Weekly EIA inventory changes were limited or unavailable in this run; lean on model and sentiment."
    )
    para2 = (
        f"Forecasts use the **{model}** pipeline (prices + spreads where applicable). "
        + (" ".join(labels) if labels else "")
    )

    return {
        "paragraph_1": para1,
        "paragraph_2": para2,
    }


def build_intelligence_layer(
    predictions_json: Dict[str, Any],
    sentiment: Optional[float] = None,
    inventory_csv: str = "data/inventory.csv",
    topic_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Attach inventory snapshot + per-product directional views to `_meta` payload.
    """
    if topic_snapshot is None:
        try:
            from news_signals import latest_topic_snapshot

            topic_snapshot = latest_topic_snapshot()
        except Exception:
            topic_snapshot = {}

    hist = load_inventory_history(inventory_csv)
    inv_snap = weekly_inventory_snapshot(hist)

    feature_snap = latest_feature_snapshot()

    directional: Dict[str, Any] = {}
    for pk, block in predictions_json.items():
        if pk.startswith("_") or not isinstance(block, dict):
            continue
        if "day_1" not in block and "next_week" not in block:
            continue
        directional[pk] = directional_view_for_product(
            pk, block, inv_snap, sentiment, topic_snapshot=topic_snapshot,
            feature_snap=feature_snap if pk == "RBOB_Gasoline" else None,
        )

    layer_scores = compute_layer_scores(
        predictions_json, inv_snap, topic_snapshot, feature_snap
    )

    rbob_horizons = build_horizon_outlook(predictions_json, "RBOB_Gasoline")

    trading_signals: Dict[str, Any] = {}
    for pk in ("RBOB_Gasoline", "ULSD_Diesel", "Crude_Oil"):
        sig = build_trading_signal(
            pk,
            predictions_json,
            inv_snap,
            topic_snapshot,
            layer_scores=layer_scores if pk == "RBOB_Gasoline" else None,
            feature_snap=feature_snap if pk == "RBOB_Gasoline" else None,
            rbob_horizons=rbob_horizons if pk == "RBOB_Gasoline" else None,
        )
        if sig:
            trading_signals[pk] = sig

    buy_rec = None
    if trading_signals.get("RBOB_Gasoline"):
        buy_rec = trading_signals["RBOB_Gasoline"].get("buy_recommendation")

    try:
        from scripts.fetch_dollar_index import latest_dollar_index_snapshot

        dollar_index = latest_dollar_index_snapshot()
    except Exception:
        dollar_index = {}

    from forecast_horizons import PREDICTION_HORIZONS

    horizons = {
        key: {"audience": label, "note": f"{days} calendar days ahead", "days_ahead": days}
        for key, days, _, label in PREDICTION_HORIZONS
    }

    return {
        "inventory_weekly": inv_snap,
        "directional_signals": directional,
        "trading_signals": trading_signals,
        "geopolitical_topics": topic_snapshot,
        "market_features": feature_snap,
        "layer_scores": layer_scores,
        "rbob_horizons": rbob_horizons,
        "buy_recommendation": buy_rec,
        "dollar_index": dollar_index,
        "horizons": horizons,
        "agent_layers": {
            "futures": "VAR / Prophet on RBOB, crude, ULSD",
            "inventory": "EIA weekly stocks",
            "cash_market": "NY Harbor & Gulf spot basis vs RBOB proxy",
            "refinery_weather": "News buckets + hurricane season flag",
            "geopolitical": "Topic NLP + geo risk score",
            "macro": "WTI path + DXY proxy",
            "technical": "RSI, MACD, momentum on RBOB series",
        },
        "event_intel": {
            "status": "multi_layer",
            "note": "Layers: futures, inventory, cash basis, refinery/weather, geo news, macro, technical.",
        },
    }


def smart_alert_candidates(
    predictions_json: Dict[str, Any],
    meta_intel: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    High-signal strings for email/dashboard (not separate SMTP sends unless wired in alerts).
    """
    alerts: List[Dict[str, Any]] = []
    directional = meta_intel.get("directional_signals") or {}
    inv = meta_intel.get("inventory_weekly") or {}

    for pk, dv in directional.items():
        if dv.get("label") == "BULLISH" and dv.get("confidence", 0) >= 60:
            alerts.append(
                {
                    "product": pk,
                    "severity": "info",
                    "title": f"{pk.replace('_', ' ')}: constructive setup",
                    "detail": dv.get("summary", ""),
                }
            )

    d_inv = inv.get("distillate") or {}
    if d_inv.get("wow_change_pct") is not None and float(d_inv["wow_change_pct"]) < -1.0:
        alerts.append(
            {
                "product": "ULSD_Diesel",
                "severity": "highlight",
                "title": "Distillate inventories falling",
                "detail": f"Week-over-week change {d_inv['wow_change_pct']:.2f}% — watch diesel strength.",
            }
        )

    return alerts[:8]
