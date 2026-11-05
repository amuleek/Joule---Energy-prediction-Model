"""
Daily prediction vs actual attribution: explain market moves and learn from misses.

Compares archived forecasts to realized Barchart settles, scores factor buckets
(geopolitical, weather, inventory, momentum, macro, etc.), identifies missed
signals, and updates learning weights for future day-1 forecasts.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from forecast_horizons import PREDICTION_HORIZONS

ARCHIVE_DIR = "data/predictions_archive"
ATTRIBUTION_LOG_PATH = "data/prediction_attribution_log.jsonl"
TRACKING_SUMMARY_PATH = "data/prediction_tracking.json"
FACTOR_LEARNING_PATH = "data/factor_learning.json"

PRODUCT_COLUMNS = {
    "RBOB_Gasoline": "RBOB",
    "ULSD_Diesel": "ULSD",
    "Crude_Oil": "Crude",
}

DISPLAY = {
    "RBOB_Gasoline": "Gasoline (RBOB)",
    "ULSD_Diesel": "Diesel (ULSD)",
    "Crude_Oil": "WTI Crude",
}

FACTOR_LABELS = {
    "tape_momentum": "Price momentum / tape",
    "inventory": "EIA weekly inventory",
    "geopolitical": "Geopolitical / OPEC / shipping headlines",
    "weather": "Gulf Coast weather (heat / storms)",
    "hurricane": "Hurricane / NHC storm risk",
    "dollar_macro": "US dollar index (DXY)",
    "crack_spread": "Refining crack spread",
    "cross_product_divergence": "Crude vs product tape divergence",
    "news_sentiment": "Aggregated news sentiment",
    "model_overlay": "Model overlay (momentum/consensus)",
}


def _sign(x: float, eps: float = 0.08) -> int:
    if x > eps:
        return 1
    if x < -eps:
        return -1
    return 0


def _load_json(path: str, default: Any = None) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _load_archive(issued_date: str) -> Dict[str, Any]:
    path = os.path.join(ARCHIVE_DIR, f"{issued_date}.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _news_on_date(date_str: str) -> Dict[str, Any]:
    path = "data/news_processed.csv"
    if not os.path.exists(path):
        return {}
    try:
        df = pd.read_csv(path)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        row = df[df["date"].dt.strftime("%Y-%m-%d") == date_str]
        if row.empty:
            return {}
        r = row.iloc[-1]
        topics = {}
        for col in r.index:
            if str(col).startswith("topic_"):
                topics[str(col).replace("topic_", "")] = float(r[col]) if pd.notna(r[col]) else 0.0
        return {
            "sentiment": float(r.get("sentiment", 0) or 0),
            "geo_risk_score": float(r.get("geo_risk_score", 0) or 0),
            "topics": topics,
        }
    except Exception:
        return {}


def _weather_on_date(date_str: str) -> Dict[str, Any]:
    path = "data/weather.csv"
    if not os.path.exists(path):
        return {}
    try:
        df = pd.read_csv(path)
        row = df[df["date"].astype(str).str[:10] == date_str]
        if row.empty:
            return {}
        r = row.iloc[-1]
        return {
            "precip_mm": float(r.get("precip_mm", 0) or 0),
            "heat_index_proxy": float(r.get("heat_index_proxy", 0) or 0),
            "wind_max_kmh": float(r.get("wind_max_kmh", 0) or 0),
        }
    except Exception:
        return {}


def _dxy_on_date(date_str: str) -> Optional[float]:
    path = "data/dollar_index.csv"
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        row = df[df["date"].dt.strftime("%Y-%m-%d") == date_str]
        if row.empty or "dxy_change_1d_pct" not in row.columns:
            return None
        val = row.iloc[-1]["dxy_change_1d_pct"]
        return float(val) if pd.notna(val) else None
    except Exception:
        return None


def _session_return_before(product_key: str, as_of_date: str, days: int = 1) -> Optional[float]:
    try:
        from live_prices import MAX_SESSION_GAP_DAYS, load_official_price_history
        hist = load_official_price_history()
        if hist.empty:
            return None
        hist = hist[hist["date"] <= pd.Timestamp(as_of_date)].sort_values("date")
        col = PRODUCT_COLUMNS.get(product_key)
        if not col or col not in hist.columns or len(hist) < days + 1:
            return None
        d_cur = pd.Timestamp(hist.iloc[-1]["date"]).normalize()
        d_prev = pd.Timestamp(hist.iloc[-(days + 1)]["date"]).normalize()
        if (d_cur - d_prev).days > MAX_SESSION_GAP_DAYS:
            return None
        cur = float(hist.iloc[-1][col])
        prev = float(hist.iloc[-(days + 1)][col])
        if prev <= 0:
            return None
        return (cur - prev) / prev * 100.0
    except Exception:
        return None


def _score_factor(
    factor: str,
    product: str,
    actual_move_pct: float,
    issue_drivers: Dict[str, Any],
    target_ctx: Dict[str, Any],
    archive_meta: Dict[str, Any],
) -> Dict[str, Any]:
    """Score one factor's implied direction vs what the market did."""
    implied_pct = 0.0
    reason = ""
    strength = 0.0

    if factor == "tape_momentum":
        mom1 = _session_return_before(product, issue_drivers.get("_spot_date", ""), 1)
        mom2 = _session_return_before(product, issue_drivers.get("_spot_date", ""), 2)
        if mom1 is not None and abs(mom1) >= 2.0:
            if mom2 is not None and mom1 * mom2 < 0 and abs(mom1) >= 2 and abs(mom2) >= 2:
                implied_pct = -mom1 * 0.15
                reason = f"Reversal day after {mom2:+.1f}% then {mom1:+.1f}% swing"
                strength = min(1.0, abs(mom1) / 6.0)
            elif abs(mom1) >= 3.0:
                implied_pct = mom1 * 0.25
                reason = f"Strong prior session {mom1:+.1f}% — tape continuation"
                strength = min(1.0, abs(mom1) / 8.0)

    elif factor == "inventory":
        wow = issue_drivers.get("inventory_wow_pct")
        if wow is not None:
            w = float(wow)
            if product == "RBOB_Gasoline" or product == "Crude_Oil":
                if w < -0.3:
                    implied_pct = 0.35
                    reason = f"Inventory draw {w:.1f}% WoW (supportive)"
                    strength = min(1.0, abs(w) / 2.0)
                elif w > 0.3:
                    implied_pct = -0.35
                    reason = f"Inventory build {w:.1f}% WoW (bearish)"
                    strength = min(1.0, abs(w) / 2.0)
            elif product == "ULSD_Diesel":
                if w > 0.5:
                    implied_pct = -0.3
                    reason = f"Distillate build {w:.1f}% WoW"
                    strength = min(1.0, abs(w) / 3.0)

    elif factor == "geopolitical":
        geo = target_ctx.get("geo_risk") or issue_drivers.get("geo_risk_score")
        topics = target_ctx.get("topics") or {}
        if geo is not None and float(geo) >= 0.05:
            implied_pct = 0.4 * float(geo) * 10
            top = max(topics.items(), key=lambda x: x[1])[0] if topics else "geopolitical"
            reason = f"Elevated geo risk ({float(geo):.2f}); headlines: {top}"
            strength = min(1.0, float(geo) * 3)

    elif factor == "weather":
        w = target_ctx.get("weather") or {}
        precip = float(w.get("precip_mm", 0) or 0)
        heat = float(w.get("heat_index_proxy", 0) or 0)
        if precip >= 25:
            implied_pct = 0.25 if product != "Crude_Oil" else 0.15
            reason = f"Heavy Gulf precipitation {precip:.0f}mm — refinery/logistics risk"
            strength = min(1.0, precip / 60.0)
        elif heat >= 33:
            implied_pct = 0.15
            reason = f"High Gulf heat index ~{heat:.0f} — demand support"
            strength = 0.4

    elif factor == "hurricane":
        hc = archive_meta.get("hurricane") or {}
        risk = float(hc.get("risk_score", 0) or 0)
        if risk >= 0.15:
            implied_pct = 0.5 * risk * 5
            reason = f"NHC storm risk score {risk:.2f}"
            strength = min(1.0, risk * 2)

    elif factor == "dollar_macro":
        dxy = target_ctx.get("dxy_change") or issue_drivers.get("dxy_change_pct")
        if dxy is not None and abs(float(dxy)) >= 0.05:
            implied_pct = -0.4 * float(dxy) * 5
            reason = f"DXY {float(dxy):+.2f}% — {'headwind' if float(dxy) > 0 else 'tailwind'} for oil"
            strength = min(1.0, abs(float(dxy)) / 0.5)

    elif factor == "crack_spread":
        gc = issue_drivers.get("gasoline_crack")
        dc = issue_drivers.get("diesel_crack")
        if product == "RBOB_Gasoline" and gc is not None and float(gc) > 50:
            implied_pct = 0.2
            reason = f"Wide gasoline crack ${float(gc):.0f}/bbl"
            strength = 0.35
        elif product == "ULSD_Diesel" and dc is not None and float(dc) > 55:
            implied_pct = 0.2
            reason = f"Wide diesel crack ${float(dc):.0f}/bbl"
            strength = 0.35

    elif factor == "cross_product_divergence":
        if product == "RBOB_Gasoline":
            crude_1d = issue_drivers.get("crude_1d_pct")
            prod_1d = issue_drivers.get("product_1d_pct")
            div_pp = issue_drivers.get("cross_divergence_pp")
            if crude_1d is not None and prod_1d is not None:
                c = float(crude_1d)
                p = float(prod_1d)
                gap = float(div_pp) if div_pp is not None else (c - p)
                if (
                    c >= 1.0
                    and p <= 0.35
                    and gap >= 1.0
                ):
                    implied_pct = p if p < -0.15 else -0.35
                    reason = (
                        f"Crude bid +{c:.1f}% but gasoline only {p:+.1f}% "
                        f"(divergence {gap:.1f}pp) — crack compression / profit-taking"
                    )
                    strength = min(1.0, gap / 3.5)

    elif factor == "news_sentiment":
        sent = target_ctx.get("sentiment")
        if sent is not None and abs(float(sent)) >= 0.03:
            implied_pct = float(sent) * 1.5
            reason = f"News sentiment {float(sent):+.2f}"
            strength = min(1.0, abs(float(sent)) * 4)

    elif factor == "model_overlay":
        d1 = archive_meta.get("day1_consensus") or {}
        prod_meta = d1.get(product) or {}
        mom = prod_meta.get("momentum_continuation") or {}
        if mom.get("mode") in ("continuation", "reversal_fade") and mom.get("consensus_before") is not None:
            before = float(mom["consensus_before"])
            after = float(mom.get("consensus_after", before))
            if _sign(before) != _sign(after) and abs(after - before) > 0.3:
                implied_pct = before
                reason = f"Overlay flipped day-1 from {before:+.2f}% to {after:+.2f}% ({mom.get('mode')})"
                strength = min(1.0, abs(after - before) / 2.0)

    implied_dir = _sign(implied_pct)
    actual_dir = _sign(actual_move_pct)
    aligned_with_actual = implied_dir != 0 and implied_dir == actual_dir

    return {
        "factor": factor,
        "label": FACTOR_LABELS.get(factor, factor),
        "implied_move_pct": round(implied_pct, 3),
        "implied_direction": "UP" if implied_dir > 0 else "DOWN" if implied_dir < 0 else "FLAT",
        "aligned_with_actual": aligned_with_actual,
        "strength": round(strength, 3),
        "reason": reason,
    }


def attribute_evaluation_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Full attribution for one evaluated forecast."""
    product = row["product"]
    spot = float(row["spot_at_issue"])
    actual = float(row["actual"])
    actual_move_pct = ((actual - spot) / spot * 100.0) if spot else 0.0

    archive = _load_archive(str(row["issued_date"]))
    preds = archive.get("predictions") or {}
    meta = preds.get("_meta") or {}

    issue_drivers = row.get("drivers_at_issue") or {}
    if isinstance(issue_drivers, str):
        try:
            issue_drivers = json.loads(issue_drivers)
        except Exception:
            issue_drivers = {}
    issue_drivers = dict(issue_drivers)
    issue_drivers["_spot_date"] = str(row["issued_date"])

    target_date = str(row["target_date"])
    news = _news_on_date(target_date)
    target_ctx = {
        "sentiment": news.get("sentiment"),
        "geo_risk": news.get("geo_risk_score"),
        "topics": news.get("topics"),
        "weather": _weather_on_date(target_date),
        "dxy_change": _dxy_on_date(target_date),
    }

    factors = [
        _score_factor(f, product, actual_move_pct, issue_drivers, target_ctx, meta)
        for f in FACTOR_LABELS
    ]
    factors = [f for f in factors if f.get("reason")]

    pred_dir = row.get("predicted_direction", "FLAT")
    actual_dir = row.get("actual_direction", "FLAT")
    direction_ok = bool(row.get("direction_correct"))

    missed = [
        f for f in factors
        if f.get("aligned_with_actual")
        and pred_dir != actual_dir
        and f.get("strength", 0) >= 0.25
    ]
    missed.sort(key=lambda x: x.get("strength", 0), reverse=True)

    matched = [f for f in factors if f.get("aligned_with_actual") and direction_ok]

    summary_parts = [
        f"{DISPLAY.get(product, product)} {row['horizon']}: "
        f"predicted {pred_dir} (${row['predicted']:.4f}), "
        f"actual {actual_dir} (${actual:.4f}, {actual_move_pct:+.2f}%)."
    ]
    if direction_ok:
        summary_parts.append("Direction correct.")
    else:
        summary_parts.append("Direction miss.")
    if missed:
        summary_parts.append(
            "Missed signals: " + "; ".join(f"{m['label']} ({m['reason']})" for m in missed[:3])
        )
    elif factors:
        top = max(factors, key=lambda x: x.get("strength", 0))
        summary_parts.append(f"Dominant context: {top['label']} — {top['reason']}.")

    return {
        "issued_date": row["issued_date"],
        "target_date": target_date,
        "product": product,
        "horizon": row["horizon"],
        "spot_at_issue": spot,
        "predicted": row["predicted"],
        "actual": actual,
        "actual_move_pct": round(actual_move_pct, 3),
        "predicted_direction": pred_dir,
        "actual_direction": actual_dir,
        "direction_correct": direction_ok,
        "error_pct": row.get("error_pct"),
        "abs_error_pct": row.get("abs_error_pct"),
        "factors": factors,
        "missed_factors": [{"factor": m["factor"], "label": m["label"], "reason": m["reason"]} for m in missed],
        "matched_factors": [{"factor": m["factor"], "label": m["label"]} for m in matched],
        "narrative": " ".join(summary_parts),
        "target_context": target_ctx,
    }


def run_daily_attribution(new_evals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Attribute all new evaluations and update learning weights."""
    if not new_evals:
        return refresh_attribution_tracking()

    return _persist_attributions([attribute_evaluation_row(r) for r in new_evals], append=True)


def refresh_attribution_tracking(recent_rows: int = 45) -> Dict[str, Any]:
    """Rebuild tracking + factor weights from recent eval log (daily refresh)."""
    from post_mortem import _load_eval_log

    log = _load_eval_log()
    if log.empty:
        return _load_json(TRACKING_SUMMARY_PATH, {}) or {}

    sub = log.sort_values(["target_date", "issued_date"]).tail(recent_rows)
    rows = [dict(r) for _, r in sub.iterrows()]
    if not rows:
        return _load_json(TRACKING_SUMMARY_PATH, {}) or {}

    return _persist_attributions([attribute_evaluation_row(r) for r in rows], append=False)


def _persist_attributions(attributions: List[Dict[str, Any]], append: bool = True) -> Dict[str, Any]:
    """Write attribution log, update learning weights, return tracking summary."""
    if not attributions:
        return _load_json(TRACKING_SUMMARY_PATH, {}) or {}

    try:
        from regime_learning import enrich_attribution_with_regimes, update_regime_learning

        attributions = [enrich_attribution_with_regimes(dict(a)) for a in attributions]
        regime_store = update_regime_learning(attributions)
    except Exception as exc:
        regime_store = {"error": str(exc)}

    os.makedirs(os.path.dirname(ATTRIBUTION_LOG_PATH) or "data", exist_ok=True)
    mode = "a" if append else "w"
    with open(ATTRIBUTION_LOG_PATH, mode, encoding="utf-8") as f:
        for att in attributions:
            att["logged_at"] = datetime.now().isoformat()
            f.write(json.dumps(att, default=str) + "\n")

    learning = _update_factor_learning(attributions)
    if isinstance(regime_store, dict) and regime_store.get("updated_at"):
        learning["regime_learning_updated_at"] = regime_store.get("updated_at")
    if isinstance(regime_store, dict) and regime_store.get("error"):
        learning["regime_learning_error"] = regime_store.get("error")

    summary = _build_tracking_summary(attributions, learning)

    with open(TRACKING_SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    with open(FACTOR_LEARNING_PATH, "w", encoding="utf-8") as f:
        json.dump(learning, f, indent=2)

    summary["regime_learning"] = {
        "updated_at": (regime_store or {}).get("updated_at") if isinstance(regime_store, dict) else None,
        "regimes": list(((regime_store or {}).get("regimes") or {}).keys()) if isinstance(regime_store, dict) else [],
    }
    return summary


def _update_factor_learning(attributions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Adjust factor weights from recent misses."""
    prior = _load_json(FACTOR_LEARNING_PATH, {}) or {}
    products = prior.get("products") or {}
    for pk in PRODUCT_COLUMNS:
        products.setdefault(pk, {f: {"weight": 1.0, "miss_count": 0, "hit_count": 0} for f in FACTOR_LABELS})

    for att in attributions:
        if att.get("horizon") != "day_1":
            continue
        pk = att["product"]
        for mf in att.get("missed_factors") or []:
            fk = mf["factor"]
            if fk not in products[pk]:
                products[pk][fk] = {"weight": 1.0, "miss_count": 0, "hit_count": 0}
            products[pk][fk]["miss_count"] = products[pk][fk].get("miss_count", 0) + 1
            products[pk][fk]["weight"] = round(
                min(2.0, products[pk][fk].get("weight", 1.0) + 0.08), 3
            )
        for mf in att.get("matched_factors") or []:
            fk = mf["factor"]
            if fk not in products[pk]:
                continue
            products[pk][fk]["hit_count"] = products[pk][fk].get("hit_count", 0) + 1
            products[pk][fk]["weight"] = round(
                max(0.6, products[pk][fk].get("weight", 1.0) - 0.03), 3
            )

    overlay_misses = sum(
        1 for a in attributions
        if a.get("horizon") == "day_1"
        and any(m["factor"] == "model_overlay" for m in (a.get("missed_factors") or []))
    )
    momentum_misses = sum(
        1 for a in attributions
        if a.get("horizon") == "day_1"
        and any(m["factor"] == "tape_momentum" for m in (a.get("missed_factors") or []))
    )
    divergence_misses = sum(
        1 for a in attributions
        if a.get("horizon") == "day_1"
        and a.get("product") == "RBOB_Gasoline"
        and not a.get("direction_correct")
        and any(
            m["factor"] == "cross_product_divergence"
            for m in (a.get("missed_factors") or [])
        )
    )

    rules = prior.get("global_rules") or {}
    prior_mom_misses = int(prior.get("recent_momentum_misses") or 0)
    total_mom_misses = prior_mom_misses + momentum_misses
    if momentum_misses >= 1 or total_mom_misses >= 2:
        rules["momentum_blend_cap"] = max(0.20, float(rules.get("momentum_blend_cap", 0.55)) - 0.05)
    if overlay_misses >= 1:
        rules["trust_ensemble_over_overlay"] = True
    if divergence_misses >= 1:
        rules["divergence_blend_boost"] = min(
            0.25,
            float(rules.get("divergence_blend_boost") or 0.0) + 0.04 * divergence_misses,
        )
        rules["disable_crude_spillover_on_divergence"] = True

    return {
        "updated_at": datetime.now().isoformat(),
        "products": products,
        "global_rules": rules,
        "recent_overlay_misses": overlay_misses,
        "recent_momentum_misses": momentum_misses,
        "recent_divergence_misses": divergence_misses,
    }


def _build_tracking_summary(
    attributions: List[Dict[str, Any]],
    learning: Dict[str, Any],
) -> Dict[str, Any]:
    """Rolling accuracy + latest attribution narratives."""
    from post_mortem import EVAL_LOG_PATH, _load_eval_log

    log = _load_eval_log()
    day1 = log[log["horizon"] == "day_1"] if not log.empty and "horizon" in log.columns else pd.DataFrame()

    per_product = {}
    for pk, label in DISPLAY.items():
        sub = day1[day1["product"] == pk].tail(14) if not day1.empty else pd.DataFrame()
        if sub.empty:
            continue
        per_product[pk] = {
            "label": label,
            "day1_direction_pct": round(float(sub["direction_correct"].mean()) * 100, 1),
            "day1_mae_pct": round(float(sub["abs_error_pct"].mean()), 2),
            "samples": len(sub),
        }

    recent_narratives = [
        {
            "date": f"{a['issued_date']} → {a['target_date']}",
            "product": DISPLAY.get(a["product"], a["product"]),
            "horizon": a["horizon"],
            "ok": a["direction_correct"],
            "narrative": a["narrative"],
            "missed": a.get("missed_factors") or [],
        }
        for a in attributions[-9:]
    ]

    top_misses: Dict[str, int] = {}
    for a in attributions:
        if a.get("horizon") != "day_1" or a.get("direction_correct"):
            continue
        for m in a.get("missed_factors") or []:
            top_misses[m["factor"]] = top_misses.get(m["factor"], 0) + 1

    return {
        "updated_at": datetime.now().isoformat(),
        "accuracy_by_product": per_product,
        "latest_attributions": recent_narratives,
        "top_missed_factors_day1": sorted(
            [{"factor": k, "label": FACTOR_LABELS.get(k, k), "count": v} for k, v in top_misses.items()],
            key=lambda x: x["count"],
            reverse=True,
        ),
        "learning_rules": learning.get("global_rules") or {},
        "recent_divergence_misses": int(learning.get("recent_divergence_misses") or 0),
    }


def load_factor_learning() -> Dict[str, Any]:
    return _load_json(FACTOR_LEARNING_PATH, {}) or {}


def apply_signal_learning(
    product_key: str,
    consensus_pct: float,
    context: Optional[Dict[str, Any]] = None,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """
    Nudge day-1 consensus using learned factor weights and current market signals.
    Applied after model consensus + momentum overlay.
    """
    learning = load_factor_learning()
    products = learning.get("products") or {}
    weights = products.get(product_key) or {}
    if not weights:
        return consensus_pct, None

    ctx = context or {}
    nudges: List[Tuple[float, str]] = []

    wow = ctx.get("inventory_wow_pct")
    if wow is not None:
        w = float(wow)
        wt = float((weights.get("inventory") or {}).get("weight", 1.0))
        if w > 0.4:
            nudges.append((-0.12 * wt, f"inventory build {w:.1f}%"))
        elif w < -0.4:
            nudges.append((0.10 * wt, f"inventory draw {w:.1f}%"))

    geo = ctx.get("geo_risk_score")
    if geo is not None and float(geo) >= 0.06:
        wt = float((weights.get("geopolitical") or {}).get("weight", 1.0))
        nudges.append((0.08 * wt * float(geo) * 5, f"geo risk {float(geo):.2f}"))

    dxy = ctx.get("dxy_change_pct")
    if dxy is not None and abs(float(dxy)) >= 0.05:
        wt = float((weights.get("dollar_macro") or {}).get("weight", 1.0))
        nudges.append((-0.06 * wt * float(dxy) * 3, f"DXY {float(dxy):+.2f}%"))

    sent = ctx.get("sentiment")
    if sent is not None and abs(float(sent)) >= 0.04:
        wt = float((weights.get("news_sentiment") or {}).get("weight", 1.0))
        nudges.append((0.10 * wt * float(sent), f"sentiment {float(sent):+.2f}"))

    hc = ctx.get("hurricane_risk")
    if hc is not None and float(hc) >= 0.15:
        wt = float((weights.get("hurricane") or {}).get("weight", 1.0))
        nudges.append((0.06 * wt * float(hc) * 3, f"hurricane risk {float(hc):.2f}"))

    heat = ctx.get("heat_index_proxy")
    if heat is not None and float(heat) >= 33.0:
        wt = float((weights.get("weather") or {}).get("weight", 1.0))
        nudges.append((0.05 * wt * (float(heat) - 32) / 5, f"Gulf heat {float(heat):.0f}"))

    crack = ctx.get("diesel_crack_usd_per_bbl")
    if product_key == "ULSD_Diesel" and crack is not None and float(crack) >= 65.0:
        wt = float((weights.get("crack_spread") or {}).get("weight", 1.0))
        nudges.append((0.04 * wt * (float(crack) - 60) / 10, f"diesel crack ${float(crack):.0f}/bbl"))
    gc = ctx.get("gasoline_crack_usd_per_bbl")
    if product_key == "RBOB_Gasoline" and gc is not None and float(gc) >= 55.0:
        wt = float((weights.get("crack_spread") or {}).get("weight", 1.0))
        nudges.append((0.03 * wt * (float(gc) - 50) / 10, f"gas crack ${float(gc):.0f}/bbl"))

    if not nudges:
        return consensus_pct, None

    total_nudge = sum(n for n, _ in nudges)
    total_nudge = max(-0.6, min(0.6, total_nudge))
    adjusted = consensus_pct + total_nudge
    return adjusted, {
        "nudge_pct": round(total_nudge, 4),
        "consensus_before": round(consensus_pct, 4),
        "consensus_after": round(adjusted, 4),
        "drivers": [f"{lbl} ({val:+.3f}%)" for val, lbl in nudges],
    }


def build_current_signal_context(
    inventory_weekly: Optional[Dict[str, Any]] = None,
    topic_snapshot: Optional[Dict[str, Any]] = None,
    dollar_index: Optional[Dict[str, Any]] = None,
    hurricane: Optional[Dict[str, Any]] = None,
    weather: Optional[Dict[str, Any]] = None,
    crack_spreads: Optional[Dict[str, Any]] = None,
    product_key: Optional[str] = None,
    catalyst_calendar: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble live signals for apply_signal_learning."""
    inv = inventory_weekly or {}
    inv_key = {"RBOB_Gasoline": "gasoline", "ULSD_Diesel": "distillate", "Crude_Oil": "crude"}.get(
        product_key or "", ""
    )
    inv_row = inv.get(inv_key, {}) if inv_key else {}
    topic = topic_snapshot or {}
    dxy = dollar_index or {}
    hc = hurricane or {}
    wx = weather or {}
    crack = crack_spreads or {}
    cal_feat = ((catalyst_calendar or {}).get("product_features") or {}).get(product_key or "") or {}
    return {
        "inventory_wow_pct": inv_row.get("wow_change_pct"),
        "inventory_z": cal_feat.get("inventory_z"),
        "geo_risk_score": topic.get("geo_risk_score"),
        "sentiment": topic.get("sentiment"),
        "dxy_change_pct": dxy.get("change_pct_1d") or dxy.get("change_1d_pct"),
        "hurricane_risk": hc.get("risk_score"),
        "heat_index_proxy": wx.get("heat_index_proxy"),
        "precip_mm": wx.get("precip_mm"),
        "gasoline_crack_usd_per_bbl": crack.get("gasoline_crack_usd_per_bbl"),
        "diesel_crack_usd_per_bbl": crack.get("diesel_crack_usd_per_bbl"),
    }
