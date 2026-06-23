"""
CatBoost medium-term forecaster for day 4 and day 7 horizons.
Uses inventories, cracks, seasonality, refinery/weather when available.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    from catboost import CatBoostRegressor
    CATBOOST_OK = True
except ImportError:
    CATBOOST_OK = False

from forecast_horizons import PREDICTION_HORIZONS

MIN_ROWS = 60
HOLDOUT = 14
MODEL_DIR = "data/models"
HORIZON_DAYS = {h[0]: h[1] for h in PREDICTION_HORIZONS if h[0] in ("day_4", "day_7")}

FUND_FEATURES = [
    "RBOB", "ULSD", "Crude", "crack_gasoline", "crack_diesel",
    "gasoline_inventory", "diesel_inventory", "crude_inventory",
    "refinery_utilization_pct", "crude_imports_kbpd", "crude_exports_kbpd",
    "sentiment", "geo_risk_score", "dxy_change_1d_pct",
    "is_driving_season", "is_hurricane_season",
    "temp_max_c", "precip_mm", "baltic_dry_proxy",
    "RBOB_lag7", "Crude_lag7", "momentum_20d_pct",
]
TOPIC_PREFIX = "topic_"


def _product_col(product_key: str) -> str:
    return {"RBOB_Gasoline": "RBOB", "ULSD_Diesel": "ULSD", "Crude_Oil": "Crude"}.get(product_key, "RBOB")


def _select_features(df: pd.DataFrame) -> List[str]:
    cols = []
    for c in FUND_FEATURES:
        if c in df.columns and df[c].notna().sum() >= MIN_ROWS // 2:
            cols.append(c)
    for c in df.columns:
        if str(c).startswith(TOPIC_PREFIX) and df[c].notna().sum() >= MIN_ROWS // 3:
            cols.append(c)
    return cols


def _prepare_targets(df: pd.DataFrame, col: str, horizon_days: int) -> pd.DataFrame:
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work = work.sort_values("date").dropna(subset=[col])
    work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work[work[col] > 1.0]
    work[f"target_{horizon_days}d"] = work[col].pct_change(horizon_days).shift(-horizon_days)
    return work.dropna(subset=[f"target_{horizon_days}d"])


def _make_model() -> Any:
    if not CATBOOST_OK:
        raise ImportError("catboost not installed")
    return CatBoostRegressor(
        iterations=300,
        depth=5,
        learning_rate=0.06,
        loss_function="RMSE",
        random_seed=42,
        verbose=0,
    )


def predict_product_horizon(
    df: pd.DataFrame,
    product_key: str,
    horizon_key: str,
    retrain: bool = False,
) -> Dict[str, Any]:
    col = _product_col(product_key)
    days = HORIZON_DAYS.get(horizon_key, 4)
    out: Dict[str, Any] = {"used": False, "horizon": horizon_key, "product": product_key, "reason": ""}

    if not CATBOOST_OK:
        out["reason"] = "catboost not installed"
        return out

    work = _prepare_targets(df, col, days)
    if len(work) < MIN_ROWS:
        out["reason"] = f"need {MIN_ROWS}+ rows, have {len(work)}"
        return out

    features = _select_features(df)
    if len(features) < 4:
        out["reason"] = f"too few features ({len(features)})"
        return out

    model_path = os.path.join(MODEL_DIR, f"catboost_{product_key}_{horizon_key}.cbm")
    X = work[features].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    current = float(work[col].iloc[-1])
    last_X = X.iloc[[-1]]

    if not retrain and os.path.exists(model_path):
        try:
            model = CatBoostRegressor()
            model.load_model(model_path)
            pred_ret = float(model.predict(last_X)[0])
            out.update({
                "used": True,
                "predicted_return_pct": round(pred_ret * 100, 3),
                "predicted_price": current * (1 + pred_ret),
                "current_price": current,
                "model_path": model_path,
                "from_cache": True,
            })
            return out
        except Exception:
            pass

    y = work[f"target_{days}d"].astype(float)
    split = len(work) - HOLDOUT
    model = _make_model()
    try:
        model.fit(X.iloc[:split], y.iloc[:split])
    except Exception as e:
        out["reason"] = str(e)
        return out

    holdout_mape = None
    if split < len(work) - 3:
        pred = model.predict(X.iloc[split:])
        actual_prices = work[col].iloc[split:].values
        pred_prices = actual_prices * (1 + pred)
        mape = float(np.mean(np.abs((pred_prices - actual_prices) / actual_prices)) * 100)
        holdout_mape = round(mape, 2)

    pred_ret = float(model.predict(last_X)[0])
    pred_price = current * (1 + pred_ret)

    os.makedirs(MODEL_DIR, exist_ok=True)
    model.save_model(model_path)

    out.update({
        "used": True,
        "predicted_return_pct": round(pred_ret * 100, 3),
        "predicted_price": pred_price,
        "current_price": current,
        "holdout_mape_pct": holdout_mape,
        "feature_count": len(features),
        "model_path": model_path,
    })
    return out


train_product_horizon = predict_product_horizon


def apply_medium_term_overlay(
    df: pd.DataFrame,
    results: Dict[str, Any],
    finalize_fn=None,
    blend: float = 0.40,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Blend CatBoost day_4 / day_7 into product blocks.
    blend=0.40 → 40% CatBoost, 60% VAR/Prophet base.
    """
    info: Dict[str, Any] = {"products": {}, "model": "CatBoost" if CATBOOST_OK else "none"}

    if not CATBOOST_OK or not results:
        info["reason"] = "catboost not installed"
        return results, info

    for product_key, block in results.items():
        if not isinstance(block, dict):
            continue
        current = float(block.get("current_price", 0) or 0)
        if current <= 0:
            continue
        pinfo: Dict[str, Any] = {}
        for hkey in ("day_4", "day_7"):
            retrain = os.getenv("CATBOOST_RETRAIN_EACH_RUN", "false").lower() in ("1", "true", "yes")
            trained = predict_product_horizon(df, product_key, hkey, retrain=retrain)
            pinfo[hkey] = trained
            if not trained.get("used"):
                continue
            base = float(block.get(hkey, block.get("next_week" if hkey == "day_4" else "biweekly", current)))
            cb_price = float(trained["predicted_price"])
            blended = (1 - blend) * base + blend * cb_price
            block[hkey] = blended
            if hkey == "day_4":
                block["next_week"] = blended
            if hkey == "day_7":
                block["biweekly"] = blended
                block["monthly"] = blended
        if finalize_fn and pinfo:
            raw = {
                "day_1": float(block.get("day_1", block.get("next_day", current))),
                "day_4": float(block.get("day_4", current)),
                "day_7": float(block.get("day_7", current)),
                "confidence_lower": block.get("confidence_lower"),
                "confidence_upper": block.get("confidence_upper"),
            }
            block.update(finalize_fn(current, raw))
        info["products"][product_key] = pinfo

    return results, info
