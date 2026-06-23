"""
XGBoost next-day RBOB forecast using tabular features from final_data (+ futures OHLC).
Blends with VAR/Prophet for tomorrow only; longer horizons stay on the time-series model.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    from xgboost import XGBRegressor

    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False
    from sklearn.ensemble import GradientBoostingRegressor

MIN_TRAIN_ROWS = 90
HOLDOUT_ROWS = 21
VAR_WEIGHT = 0.45
XGB_WEIGHT = 0.55

# Features used when present in final_data (target leakage columns excluded)
FEATURE_CANDIDATES = [
    "RBOB",
    "ULSD",
    "Crude",
    "crack_gasoline",
    "crack_diesel",
    "RBOB_lag1",
    "RBOB_lag7",
    "Crude_lag1",
    "Crude_lag7",
    "ULSD_lag1",
    "crack_gasoline_lag1",
    "sentiment",
    "geo_risk_score",
    "rsi_14",
    "macd_hist",
    "momentum_5d_pct",
    "momentum_20d_pct",
    "price_vs_sma20_pct",
    "calendar_spread_proxy",
    "basis_ny_cash_minus_rbob",
    "basis_gulf_cash_minus_rbob",
    "brent_wti_spread",
    "is_driving_season",
    "is_hurricane_season",
    "rbob_close",
    "rbob_volume",
    "rbob_calendar_spread_5d",
    "rbob_return_1d",
    "crude_close",
    "crude_return_1d",
    "rbob_crude_ratio",
    "gasoline_inventory",
    "diesel_inventory",
    "crude_inventory",
    "retail_gasoline",
]
TOPIC_PREFIX = "topic_"


def _select_features(df: pd.DataFrame) -> List[str]:
    cols = []
    n = len(df)
    for c in FEATURE_CANDIDATES:
        if c not in df.columns:
            continue
        non_null = int(df[c].notna().sum())
        if c.startswith("rbob_") and non_null < max(30, n // 10):
            continue
        if non_null >= MIN_TRAIN_ROWS // 2:
            cols.append(c)
    for c in df.columns:
        if str(c).startswith(TOPIC_PREFIX) and df[c].notna().sum() >= MIN_TRAIN_ROWS // 4:
            cols.append(c)
    return cols


def _prepare_xy(df: pd.DataFrame, feature_cols: List[str]) -> Tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Features at t; target = next-day % return on RBOB (more stationary than price level)."""
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work = work.sort_values("date").dropna(subset=["date", "RBOB"])
    work["RBOB"] = pd.to_numeric(work["RBOB"], errors="coerce")
    work = work[work["RBOB"] > 1.0]
    if len(work) > 800:
        work = work.tail(800)
    work["target_return"] = work["RBOB"].pct_change().shift(-1)
    work = work.dropna(subset=["target_return"])
    X = work[feature_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    y = work["target_return"].astype(float)
    prices = work["RBOB"].astype(float)
    return X, y, prices


def _make_regressor():
    if XGB_AVAILABLE:
        return XGBRegressor(
            n_estimators=200,
            max_depth=5,
            learning_rate=0.06,
            subsample=0.85,
            colsample_bytree=0.85,
            objective="reg:squarederror",
            random_state=42,
            n_jobs=-1,
        )
    return GradientBoostingRegressor(
        n_estimators=150,
        max_depth=4,
        learning_rate=0.08,
        random_state=42,
    )


def train_predict_next_rbob(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Train on all but last HOLDOUT_ROWS; predict next-day RBOB from the latest feature row.
    Returns diagnostics + predicted price.
    """
    out: Dict[str, Any] = {
        "used": False,
        "model": "XGBoost" if XGB_AVAILABLE else "GradientBoosting",
        "next_day_price": None,
        "confidence_pct": None,
        "holdout_mape_pct": None,
        "feature_count": 0,
        "reason": "",
    }
    if df is None or df.empty or "RBOB" not in df.columns:
        out["reason"] = "no RBOB column"
        return out

    feature_cols = _select_features(df)
    if len(feature_cols) < 5:
        out["reason"] = f"too few features ({len(feature_cols)})"
        return out

    X, y, prices = _prepare_xy(df, feature_cols)
    if len(X) < MIN_TRAIN_ROWS:
        out["reason"] = f"need {MIN_TRAIN_ROWS}+ rows, have {len(X)}"
        return out

    n = len(X)
    train_end = n - HOLDOUT_ROWS
    X_train, y_train = X.iloc[:train_end], y.iloc[:train_end]
    X_hold, y_hold = X.iloc[train_end:], y.iloc[train_end:]
    p_hold = prices.iloc[train_end:]

    model = _make_regressor()
    try:
        model.fit(X_train, y_train)
    except Exception as e:
        out["reason"] = f"fit failed: {e}"
        return out

    if len(X_hold) > 5:
        pred_ret = model.predict(X_hold)
        pred_prices = p_hold.values * (1 + pred_ret)
        mape = float(np.mean(np.abs((pred_prices - p_hold.values) / p_hold.values)) * 100)
        out["holdout_mape_pct"] = round(mape, 2)
        out["confidence_pct"] = int(max(40, min(88, 100 - mape * 2)))

    last_X = X.iloc[[-1]]
    pred_ret = float(model.predict(last_X)[0])
    current = float(pd.to_numeric(df["RBOB"].iloc[-1], errors="coerce"))
    pred_next = current * (1 + pred_ret)

    out["used"] = True
    out["next_day_price"] = pred_next
    out["predicted_return_pct"] = round(pred_ret * 100, 3)
    out["current_price"] = current
    out["feature_count"] = len(feature_cols)
    out["top_features"] = feature_cols[:12]
    if hasattr(model, "feature_importances_"):
        imp = model.feature_importances_
        total = float(imp.sum()) or 1.0
        ranked = sorted(
            ((feature_cols[i], float(imp[i]) / total) for i in range(len(feature_cols))),
            key=lambda x: x[1],
            reverse=True,
        )
        out["feature_importance"] = {k: round(v, 4) for k, v in ranked[:15]}
    if out["confidence_pct"] is None:
        out["confidence_pct"] = 60
    return out


def get_feature_importance_scores(df: Optional[pd.DataFrame] = None) -> Dict[str, float]:
    """Return normalized feature importance from a fresh RBOB model fit."""
    if df is None:
        path = "data/final_data.csv"
        if not os.path.exists(path):
            return {}
        df = pd.read_csv(path)

    feature_cols = _select_features(df)
    if len(feature_cols) < 5:
        return {}
    X, y, _ = _prepare_xy(df, feature_cols)
    if len(X) < MIN_TRAIN_ROWS:
        return {}

    model = _make_regressor()
    try:
        model.fit(X, y)
    except Exception:
        return {}

    if not hasattr(model, "feature_importances_"):
        return {}
    imp = model.feature_importances_
    total = float(imp.sum()) or 1.0
    scores = {
        feature_cols[i]: round(float(imp[i]) / total, 4) for i in range(len(feature_cols))
    }
    return dict(sorted(scores.items(), key=lambda x: x[1], reverse=True))


def blend_rbob_next_day(
    var_next_day: float,
    current_price: float,
    xgb_info: Dict[str, Any],
) -> Tuple[float, str]:
    """Blend VAR and XGB for tomorrow's RBOB; favor XGB when signs disagree."""
    if not xgb_info.get("used") or xgb_info.get("next_day_price") is None:
        return var_next_day, "VAR"
    xgb_p = float(xgb_info["next_day_price"])
    var_ret = (float(var_next_day) - current_price) / current_price if current_price else 0
    xgb_ret = float(xgb_info.get("predicted_return_pct", 0)) / 100.0
    if var_ret * xgb_ret < 0 and abs(xgb_ret) > 0.003:
        w_var, w_xgb = 0.20, 0.80
    else:
        w_var, w_xgb = VAR_WEIGHT, XGB_WEIGHT
    blended = w_var * float(var_next_day) + w_xgb * xgb_p
    label = "VAR+XGBoost" if XGB_AVAILABLE else "VAR+GBM"
    xgb_info["blend_weights"] = {"var": w_var, "xgb": w_xgb}
    return blended, label


def apply_xgboost_rbob_overlay(
    df: pd.DataFrame,
    results: Dict[str, Any],
    finalize_fn=None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Adjust RBOB_Gasoline next_day using XGB; optionally re-clamp via predictor finalize."""
    xgb_info = train_predict_next_rbob(df)
    if "RBOB_Gasoline" not in results or not results["RBOB_Gasoline"]:
        return results, xgb_info

    block = results["RBOB_Gasoline"]
    current = float(block.get("current_price") or df["RBOB"].iloc[-1])
    var_nd = float(block.get("next_day", current))

    if xgb_info.get("used"):
        blended, _ = blend_rbob_next_day(var_nd, current, xgb_info)
        raw = {
            "day_1": blended,
            "day_4": float(block.get("day_4", block.get("next_week", current))),
            "day_7": float(block.get("day_7", block.get("biweekly", current))),
            "confidence_lower": block.get("confidence_lower"),
            "confidence_upper": block.get("confidence_upper"),
        }
        if finalize_fn:
            block = finalize_fn(current, raw, product_key="RBOB_Gasoline")
            block["next_day_xgb"] = float(xgb_info["next_day_price"])
            block["next_day_var"] = var_nd
            results["RBOB_Gasoline"] = block
        else:
            block["next_day"] = blended
            block["next_day_xgb"] = float(xgb_info["next_day_price"])
            block["next_day_var"] = var_nd
        if not finalize_fn:
            xgb_info["blend_weights"] = {"var": VAR_WEIGHT, "xgb": XGB_WEIGHT}

    return results, xgb_info
