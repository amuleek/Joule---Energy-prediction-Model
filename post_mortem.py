"""
Daily post-mortem: compare archived forecasts to realized prices,
explain hits/misses, rank drivers, update feature importance, and
compute bias adjustments for future forecasts.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from forecast_horizons import PREDICTION_HORIZONS

try:
    from live_prices import _row_is_full_session
except ImportError:
    def _row_is_full_session(row) -> bool:  # type: ignore[misc]
        return True

ARCHIVE_DIR = "data/predictions_archive"
REPORT_PATH = "data/post_mortem_report.json"
FEATURE_IMPORTANCE_PATH = "data/feature_importance.json"
ERROR_ADJUSTMENTS_PATH = "data/error_adjustments.json"
EVAL_LOG_PATH = "data/prediction_eval_log.csv"
PRICES_PATH = "data/prices.csv"
FUTURES_PATH = "data/futures_ohlc.csv"

FUTURES_TO_PRICE_COL = {
    "rbob_close": "RBOB",
    "diesel_close": "ULSD",
    "crude_close": "Crude",
}

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

EVAL_HORIZONS = [(k, d) for k, d, _, _ in PREDICTION_HORIZONS]


def archive_predictions(predictions_json: Dict[str, Any], issued_date: Optional[str] = None) -> str:
    """Save dated snapshot for later evaluation."""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    day = issued_date or datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(ARCHIVE_DIR, f"{day}.json")
    payload = {
        "issued_date": day,
        "issued_at": datetime.now().isoformat(),
        "predictions": predictions_json,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


def _load_prices() -> pd.DataFrame:
    """Prefer NYMEX futures closes; fall back to prices.csv."""
    frames = []
    if os.path.exists(FUTURES_PATH):
        try:
            fut = pd.read_csv(FUTURES_PATH)
            fut["date"] = pd.to_datetime(fut["date"], errors="coerce")
            fut = fut.dropna(subset=["date"]).sort_values("date")
            if not fut.empty:
                full = fut[fut.apply(_row_is_full_session, axis=1)]
                if not full.empty:
                    fut = full
                sub = fut[["date"]].copy()
                for fut_col, price_col in FUTURES_TO_PRICE_COL.items():
                    if fut_col in fut.columns:
                        sub[price_col] = pd.to_numeric(fut[fut_col], errors="coerce")
                frames.append(sub.dropna(subset=list(FUTURES_TO_PRICE_COL.values()), how="all"))
        except Exception:
            pass
    if os.path.exists(PRICES_PATH):
        try:
            spot = pd.read_csv(PRICES_PATH)
            spot["date"] = pd.to_datetime(spot["date"], errors="coerce")
            spot = spot.dropna(subset=["date"]).sort_values("date")
            if not spot.empty:
                frames.append(spot)
        except Exception:
            pass
    if not frames:
        return pd.DataFrame()
    fut_df = frames[0]
    if len(frames) > 1:
        spot_df = frames[1]
        spot_only = spot_df[~spot_df["date"].isin(fut_df["date"])]
        combined = pd.concat([fut_df, spot_only], ignore_index=True)
    else:
        combined = fut_df
    price_cols = [c for c in ("RBOB", "ULSD", "Crude") if c in combined.columns]
    if not price_cols:
        return pd.DataFrame()
    return combined.sort_values("date")


def _actual_near_date(
    prices: pd.DataFrame,
    col: str,
    target: pd.Timestamp,
    max_gap_days: int = 2,
) -> Optional[float]:
    """Best available price near target (EIA series is not always daily)."""
    if prices.empty or col not in prices.columns:
        return None
    work = prices.dropna(subset=[col]).copy()
    if work.empty:
        return None
    deltas = (work["date"] - target).dt.days
    mask = deltas.abs() <= max_gap_days
    close = work.loc[mask].copy()
    if close.empty:
        return None
    close = close.assign(abs_delta=deltas.abs())
    row = close.sort_values("abs_delta").iloc[0]
    return float(row[col])


def _load_eval_log() -> pd.DataFrame:
    if not os.path.exists(EVAL_LOG_PATH):
        return pd.DataFrame()
    return pd.read_csv(EVAL_LOG_PATH)


def _eval_key(row: Dict[str, Any]) -> Tuple:
    return (row["issued_date"], row["product"], row["horizon"])


def bootstrap_archive_if_needed() -> None:
    """Seed archive from predictions.json when no history exists yet."""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    if any(f.endswith(".json") for f in os.listdir(ARCHIVE_DIR)):
        return
    path = "data/predictions.json"
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            preds = json.load(f)
        ts = None
        for pk in PRODUCT_COLUMNS:
            block = preds.get(pk) or {}
            ts = block.get("timestamp")
            if ts:
                break
        if ts:
            day = str(ts)[:10]
        else:
            day = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d")
        archive_predictions(preds, issued_date=day)
    except Exception:
        pass


def evaluate_mature_predictions(prices: Optional[pd.DataFrame] = None) -> List[Dict[str, Any]]:
    """Compare archived forecasts to realized prices when horizons have matured."""
    bootstrap_archive_if_needed()
    prices = prices if prices is not None else _load_prices()
    if prices.empty:
        return []

    existing = _load_eval_log()
    seen = set()
    if not existing.empty:
        for _, r in existing.iterrows():
            seen.add((str(r["issued_date"]), r["product"], r["horizon"]))

    today = pd.Timestamp(datetime.now().date())
    results: List[Dict[str, Any]] = []

    if not os.path.isdir(ARCHIVE_DIR):
        return results

    for fname in sorted(os.listdir(ARCHIVE_DIR)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(ARCHIVE_DIR, fname)
        try:
            with open(path, encoding="utf-8") as f:
                archive = json.load(f)
        except Exception:
            continue

        issued_date = pd.Timestamp(archive.get("issued_date", fname.replace(".json", "")))
        preds = archive.get("predictions") or {}
        meta = preds.get("_meta") or {}
        spot_ref = meta.get("spot_reference") or {}
        spot_by_product = spot_ref.get("by_product") or {}

        for product, col in PRODUCT_COLUMNS.items():
            block = preds.get(product)
            if not isinstance(block, dict):
                continue
            ref_spot = spot_by_product.get(product)
            spot = float(ref_spot if ref_spot else block.get("current_price", 0) or 0)

            for hkey, days in EVAL_HORIZONS:
                key = (issued_date.strftime("%Y-%m-%d"), product, hkey)
                if key in seen:
                    continue

                target = issued_date + pd.Timedelta(days=days)
                if target > today:
                    continue

                hd = block.get(hkey)
                if not isinstance(hd, dict):
                    continue
                pred_price = float(hd.get("price", 0))
                if pred_price <= 0:
                    continue

                actual = _actual_near_date(prices, col, target)
                if actual is None or actual <= 0:
                    continue

                error = pred_price - actual
                error_pct = (error / actual) * 100
                pred_dir = hd.get("direction", "FLAT")
                actual_dir = "UP" if actual > spot else "DOWN" if actual < spot else "FLAT"
                direction_ok = pred_dir == actual_dir or abs(error_pct) < 0.5

                meta = preds.get("_meta") or {}
                drivers = _drivers_at_issue(block, meta, product)
                ensemble_block = (meta.get("ensemble") or {}).get(product) or {}
                ensemble_components = (ensemble_block.get("components") or {}) if ensemble_block else {}

                row = {
                    "issued_date": issued_date.strftime("%Y-%m-%d"),
                    "target_date": target.strftime("%Y-%m-%d"),
                    "product": product,
                    "display": DISPLAY.get(product, product),
                    "horizon": hkey,
                    "horizon_days": days,
                    "spot_at_issue": spot,
                    "predicted": pred_price,
                    "actual": actual,
                    "error": error,
                    "error_pct": round(error_pct, 3),
                    "abs_error_pct": round(abs(error_pct), 3),
                    "direction_correct": direction_ok,
                    "predicted_direction": pred_dir,
                    "actual_direction": actual_dir,
                    "drivers_at_issue": drivers,
                    "ensemble_components": ensemble_components,
                    "model": meta.get("model", ""),
                }
                results.append(row)
                seen.add(key)

    return results


def _drivers_at_issue(block: Dict[str, Any], meta: Dict[str, Any], product: str) -> Dict[str, Any]:
    """Snapshot of signals available when the forecast was issued."""
    dv = block.get("directional") or {}
    drivers = dv.get("drivers") or {}
    inv = meta.get("inventory_weekly") or {}
    inv_key = {"RBOB_Gasoline": "gasoline", "ULSD_Diesel": "distillate", "Crude_Oil": "crude"}.get(product)
    inv_row = inv.get(inv_key or "", {}) or {}

    dxy = meta.get("dollar_index") or {}
    crack = meta.get("crack_spreads_current") or {}
    layers = meta.get("layer_scores") or {}

    return {
        "inventory_wow_pct": inv_row.get("wow_change_pct"),
        "sentiment": drivers.get("sentiment"),
        "geo_risk_score": drivers.get("geo_risk_score"),
        "dxy_change_pct": dxy.get("change_pct_1d"),
        "gasoline_crack": crack.get("gasoline_crack_usd_per_bbl"),
        "diesel_crack": crack.get("diesel_crack_usd_per_bbl"),
        "layer_composite": (layers.get("composite") or {}).get("score"),
        "model_next_day_pct": drivers.get("model_next_day_pct"),
        "model_next_week_pct": drivers.get("model_next_week_pct"),
    }


def _explain_row(row: Dict[str, Any]) -> str:
    """Plain-language explanation for one evaluated forecast."""
    ok = row["direction_correct"]
    verdict = "correct direction" if ok else "wrong direction"
    err = row["error_pct"]
    drivers = row.get("drivers_at_issue") or {}

    parts = [
        f"{row['display']} {row['horizon']} ({row['issued_date']} to {row['target_date']}): "
        f"predicted ${row['predicted']:.4f}, actual ${row['actual']:.4f} "
        f"({err:+.1f}% error, {verdict})."
    ]

    reasons: List[str] = []
    wow = drivers.get("inventory_wow_pct")
    if wow is not None:
        w = float(wow)
        if w < -0.3:
            reasons.append(f"gasoline/distillate/crude stocks drew {abs(w):.1f}% WoW (supportive)")
        elif w > 0.3:
            reasons.append(f"stocks built {w:.1f}% WoW (bearish supply cushion)")

    dxy = drivers.get("dxy_change_pct")
    if dxy is not None and abs(float(dxy)) >= 0.05:
        reasons.append(f"USD index moved {float(dxy):+.2f}% (macro headwind/tailwind)")

    sent = drivers.get("sentiment")
    if sent is not None and abs(float(sent)) > 0.05:
        reasons.append(f"news sentiment was {float(sent):+.2f}")

    gc = drivers.get("gasoline_crack")
    if gc is not None and row["product"] == "RBOB_Gasoline":
        reasons.append(f"gasoline crack ~${float(gc):.0f}/bbl")

    if not ok:
        if err > 0:
            parts.append("Model overshot — likely overweighted bullish drivers or underweighted supply builds / stronger dollar.")
        else:
            parts.append("Model undershot — likely missed supportive inventory draws, crude strength, or headline risk.")
    else:
        parts.append("Forecast aligned with the dominant driver mix at issue time.")

    if reasons:
        parts.append("Key factors at issue: " + "; ".join(reasons) + ".")
    return " ".join(parts)


def _rank_variables(
    new_evals: List[Dict[str, Any]],
    df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Rank influential variables from model importance + error correlation."""
    ranked: Dict[str, Any] = {"updated_at": datetime.now().isoformat(), "products": {}}

    # XGB feature importance (optional — trains a model, can be slow)
    if os.getenv("SKIP_XGB_IMPORTANCE", "true").lower() not in ("1", "true", "yes"):
        try:
            from rbob_xgb_model import get_feature_importance_scores
            xgb_imp = get_feature_importance_scores(df)
            if xgb_imp:
                ranked["rbob_xgb"] = xgb_imp
        except Exception:
            pass
    elif os.path.exists(FEATURE_IMPORTANCE_PATH):
        try:
            with open(FEATURE_IMPORTANCE_PATH, encoding="utf-8") as f:
                prior = json.load(f)
            if prior.get("rbob_xgb"):
                ranked["rbob_xgb"] = prior["rbob_xgb"]
        except Exception:
            pass

    # Error-correlation ranking per product from evaluation history
    log = _load_eval_log()
    if new_evals:
        new_df = pd.DataFrame(new_evals)
        log = pd.concat([log, new_df], ignore_index=True) if not log.empty else new_df

    driver_keys = [
        "inventory_wow_pct",
        "sentiment",
        "geo_risk_score",
        "dxy_change_pct",
        "gasoline_crack",
        "diesel_crack",
        "layer_composite",
        "model_next_day_pct",
    ]

    for product in PRODUCT_COLUMNS:
        if log.empty:
            continue
        sub = log[log["product"] == product].tail(30)
        if len(sub) < 2:
            continue

        scores: List[Tuple[str, float]] = []
        for dk in driver_keys:
            vals, errs = [], []
            for _, r in sub.iterrows():
                drivers = r.get("drivers_at_issue")
                if isinstance(drivers, str):
                    try:
                        drivers = json.loads(drivers.replace("'", '"'))
                    except Exception:
                        drivers = {}
                if not isinstance(drivers, dict):
                    continue
                v = drivers.get(dk)
                if v is None or (isinstance(v, float) and np.isnan(v)):
                    continue
                vals.append(float(v))
                errs.append(float(r["error_pct"]))
            if len(vals) >= 3:
                corr = float(np.corrcoef(vals, errs)[0, 1])
                if not np.isnan(corr):
                    scores.append((dk, abs(corr)))

        scores.sort(key=lambda x: x[1], reverse=True)
        ranked["products"][product] = {
            "error_correlation_rank": [{"variable": k, "score": round(s, 4)} for k, s in scores[:8]],
        }

    # Merge with prior scores (EMA)
    if os.path.exists(FEATURE_IMPORTANCE_PATH):
        try:
            with open(FEATURE_IMPORTANCE_PATH, encoding="utf-8") as f:
                prior = json.load(f)
            alpha = 0.35
            if "rbob_xgb" in prior and "rbob_xgb" in ranked:
                merged = {}
                all_keys = set(prior["rbob_xgb"]) | set(ranked["rbob_xgb"])
                for k in all_keys:
                    old = float(prior["rbob_xgb"].get(k, 0))
                    new = float(ranked["rbob_xgb"].get(k, old))
                    merged[k] = round(alpha * new + (1 - alpha) * old, 4)
                ranked["rbob_xgb"] = dict(sorted(merged.items(), key=lambda x: x[1], reverse=True))
        except Exception:
            pass

    return ranked


def compute_error_adjustments(evaluations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Rolling mean signed error (%): positive = model overshot actual.
    Future forecasts subtract this bias.
    """
    log = _load_eval_log()
    if evaluations:
        rows = []
        for e in evaluations:
            row = dict(e)
            row["drivers_at_issue"] = json.dumps(e.get("drivers_at_issue") or {})
            rows.append(row)
        new_df = pd.DataFrame(rows)
        log = pd.concat([log, new_df], ignore_index=True) if not log.empty else new_df
        log.to_csv(EVAL_LOG_PATH, index=False)

    adjustments: Dict[str, Any] = {
        "updated_at": datetime.now().isoformat(),
        "products": {},
        "note": "bias_pct = mean(pred-actual)/actual*100; subtracted from future % change",
    }

    if log.empty:
        return adjustments

    for product in PRODUCT_COLUMNS:
        adjustments["products"][product] = {}
        sub = log[log["product"] == product]
        for hkey, days in EVAL_HORIZONS:
            hsub = sub[sub["horizon"] == hkey].tail(14)
            if len(hsub) < 1:
                continue
            bias = float(hsub["error_pct"].mean())
            mae = float(hsub["abs_error_pct"].mean())
            hit_rate = float(hsub["direction_correct"].mean()) if "direction_correct" in hsub.columns else None
            adjustments["products"][product][hkey] = {
                "bias_pct": round(bias, 3),
                "mae_pct": round(mae, 3),
                "direction_hit_rate": round(hit_rate, 3) if hit_rate is not None else None,
                "n_samples": len(hsub),
            }

    with open(ERROR_ADJUSTMENTS_PATH, "w", encoding="utf-8") as f:
        json.dump(adjustments, f, indent=2)
    return adjustments


def build_post_mortem_report(new_evals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Assemble daily post-mortem report JSON."""
    from model_weights import compute_model_metrics, update_weights_from_evaluations

    explanations = [_explain_row(r) for r in new_evals]
    importance = _rank_variables(new_evals)
    adjustments = compute_error_adjustments(new_evals)
    model_metrics = compute_model_metrics()
    updated_weights = update_weights_from_evaluations(new_evals)

    summary = {
        "generated_at": datetime.now().isoformat(),
        "evaluations_count": len(new_evals),
        "evaluations": new_evals,
        "explanations": explanations,
        "feature_importance": importance,
        "error_adjustments": adjustments,
        "model_metrics": model_metrics,
        "ensemble_weights": updated_weights,
    }

    if new_evals:
        hits = sum(1 for e in new_evals if e["direction_correct"])
        summary["direction_accuracy"] = round(hits / len(new_evals), 3)
        summary["mean_abs_error_pct"] = round(
            float(np.mean([e["abs_error_pct"] for e in new_evals])), 3
        )
    else:
        summary["direction_accuracy"] = None
        summary["mean_abs_error_pct"] = None
        summary["message"] = "No mature forecasts to evaluate yet (need archived predictions + elapsed horizons)."

    with open(FEATURE_IMPORTANCE_PATH, "w", encoding="utf-8") as f:
        json.dump(importance, f, indent=2)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    try:
        from database import init_db, log_outcome, upsert_model_performance
        init_db()
        for ev in new_evals:
            log_outcome(
                ev["issued_date"],
                ev["target_date"],
                ev["product"],
                ev["horizon"],
                float(ev["predicted"]),
                float(ev["actual"]),
                bool(ev["direction_correct"]),
            )
        for product, horizons in (model_metrics.get("products") or {}).items():
            for hkey, stats in horizons.items():
                upsert_model_performance(
                    "ensemble_stack",
                    product,
                    hkey,
                    float(stats.get("mae", 0)),
                    float(stats.get("rmse", 0)),
                    float(stats.get("direction_accuracy", 0)),
                    float(stats.get("bias_pct", 0)),
                    int(stats.get("n_samples", 0)),
                )
    except Exception:
        pass

    return summary


def run_daily_post_mortem(verbose: bool = True) -> Dict[str, Any]:
    """Main entry: evaluate, report, rank variables, update adjustments."""
    new_evals = evaluate_mature_predictions()
    report = build_post_mortem_report(new_evals)

    if verbose:
        print("\n" + "=" * 60)
        print("DAILY POST-MORTEM")
        print("=" * 60)
        if not new_evals:
            print(report.get("message", "Nothing to evaluate."))
        else:
            print(f"Evaluated {len(new_evals)} forecast(s)")
            print(f"Direction accuracy: {report.get('direction_accuracy', 0):.0%}")
            print(f"Mean abs error: {report.get('mean_abs_error_pct', 0):.2f}%")
            for line in report.get("explanations", [])[:6]:
                print(f"  - {line}")
            top = (report.get("feature_importance") or {}).get("rbob_xgb") or {}
            if top:
                items = list(top.items())[:5]
                print("Top RBOB model features:", ", ".join(f"{k} ({v:.2f})" for k, v in items))
        print(f"Report saved: {REPORT_PATH}")

    return report


def load_error_adjustments() -> Dict[str, Any]:
    if not os.path.exists(ERROR_ADJUSTMENTS_PATH):
        return {}
    try:
        with open(ERROR_ADJUSTMENTS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def apply_bias_to_predictions(results: Dict[str, Any]) -> Dict[str, Any]:
    """Subtract rolling bias from raw horizon prices before JSON export."""
    from forecast_horizons import LEGACY_ALIASES, max_frac_for

    adj = load_error_adjustments()
    products = adj.get("products") or {}
    if not products:
        return results

    for product, block in results.items():
        if product.startswith("_") or not isinstance(block, dict):
            continue
        padj = products.get(product) or {}
        current = float(block.get("current_price", 0) or 0)
        if current <= 0:
            continue
        for hkey, _days, max_frac, _label in PREDICTION_HORIZONS:
            if hkey not in padj or hkey not in block:
                continue
            max_frac = max_frac_for(hkey, product)
            try:
                price = float(block[hkey])
            except (TypeError, ValueError):
                continue
            bias_pct = float(padj[hkey].get("bias_pct", 0))
            if hkey == "day_1":
                bias_pct *= 0.25
            adjusted = price * (1 - bias_pct / 100.0)
            lo = current * (1 - max_frac)
            hi = current * (1 + max_frac)
            block[hkey] = max(lo, min(adjusted, hi))
            chg = ((block[hkey] - current) / current * 100) if current else 0
            block[f"{hkey}_change"] = float(chg)
            block[f"{hkey}_direction"] = "UP" if chg > 0 else "DOWN" if chg < 0 else "FLAT"
            for old_key, new_key in LEGACY_ALIASES.items():
                if new_key == hkey:
                    block[old_key] = block[hkey]
                    block[f"{old_key}_change"] = block[f"{hkey}_change"]
                    block[f"{old_key}_direction"] = block[f"{hkey}_direction"]

    return results
