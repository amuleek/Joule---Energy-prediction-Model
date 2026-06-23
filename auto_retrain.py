"""
Auto-retrain tabular models when post-mortem metrics exceed thresholds.
Triggered after daily post-mortem in the full pipeline.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd

MODEL_DIR = "data/models"
RETRAIN_LOG = "data/retrain_log.json"
PERFORMANCE_PATH = "data/model_performance_summary.json"

# Retrain when enough samples and MAE% above this (model underperforming)
MAE_RETRAIN_THRESHOLD_PCT = float(os.getenv("RETRAIN_MAE_THRESHOLD_PCT", "4.0"))
MIN_SAMPLES = int(os.getenv("RETRAIN_MIN_SAMPLES", "5"))


def _load_performance() -> Dict[str, Any]:
    if not os.path.exists(PERFORMANCE_PATH):
        return {}
    try:
        with open(PERFORMANCE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _append_log(entry: Dict[str, Any]) -> None:
    log: list = []
    if os.path.exists(RETRAIN_LOG):
        try:
            with open(RETRAIN_LOG, encoding="utf-8") as f:
                log = json.load(f)
        except Exception:
            log = []
    log.append(entry)
    log = log[-50:]
    os.makedirs("data", exist_ok=True)
    with open(RETRAIN_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)


def should_retrain(perf: Optional[Dict[str, Any]] = None) -> bool:
    perf = perf or _load_performance()
    products = perf.get("products") or {}
    for _product, horizons in products.items():
        for _h, stats in horizons.items():
            if int(stats.get("n_samples", 0)) >= MIN_SAMPLES:
                if float(stats.get("mae_pct", 0)) >= MAE_RETRAIN_THRESHOLD_PCT:
                    return True
            if int(stats.get("n_samples", 0)) >= MIN_SAMPLES * 2:
                return True
    return False


def run_auto_retrain(verbose: bool = True) -> Dict[str, Any]:
    """
    Retrain RBOB XGB (day 1) and CatBoost medium-term (day 4/7) on latest final_data.
    """
    result: Dict[str, Any] = {
        "ran_at": datetime.now().isoformat(),
        "triggered": False,
        "xgb_rbob": None,
        "catboost": None,
        "reason": "",
    }

    perf = _load_performance()
    if not should_retrain(perf):
        result["reason"] = "metrics within threshold; skipping retrain"
        if verbose:
            print(f"Auto-retrain: {result['reason']}")
        return result

    fd_path = "data/final_data.csv"
    if not os.path.exists(fd_path):
        result["reason"] = "no final_data.csv"
        if verbose:
            print(f"Auto-retrain: {result['reason']}")
        return result

    df = pd.read_csv(fd_path)
    if len(df) < 60:
        result["reason"] = f"insufficient rows ({len(df)})"
        return result

    result["triggered"] = True
    os.makedirs(MODEL_DIR, exist_ok=True)

    if verbose:
        print("\n" + "=" * 60)
        print("AUTO-RETRAIN (performance-triggered)")
        print("=" * 60)

    try:
        from rbob_xgb_model import train_predict_next_rbob
        xgb_info = train_predict_next_rbob(df)
        result["xgb_rbob"] = {
            "used": xgb_info.get("used"),
            "holdout_mape_pct": xgb_info.get("holdout_mape_pct"),
            "reason": xgb_info.get("reason", ""),
        }
        if verbose and xgb_info.get("used"):
            print(f"  RBOB XGB retrained (holdout MAPE ~{xgb_info.get('holdout_mape_pct')}%)")
    except Exception as e:
        result["xgb_rbob"] = {"error": str(e)}
        if verbose:
            print(f"  RBOB XGB retrain failed: {e}")

    try:
        from medium_term_model import train_product_horizon
        cb_results = {}
        for pk in ("RBOB_Gasoline", "ULSD_Diesel", "Crude_Oil"):
            cb_results[pk] = {}
            for hk in ("day_4", "day_7"):
                cb_results[pk][hk] = train_product_horizon(df, pk, hk)
        result["catboost"] = cb_results
        if verbose:
            n_ok = sum(
                1 for pk in cb_results for hk in cb_results[pk]
                if cb_results[pk][hk].get("used")
            )
            print(f"  CatBoost: {n_ok}/6 product-horizon models retrained")
    except Exception as e:
        result["catboost"] = {"error": str(e)}
        if verbose:
            print(f"  CatBoost retrain failed: {e}")

    _append_log(result)
    if verbose:
        print(f"Retrain log appended -> {RETRAIN_LOG}")
    return result
