"""
Separate RBOB and ULSD next-session models.

Targets are next-session return (direction + magnitude), not dollar price.
Training is expanding walk-forward — never sklearn shuffle split.
Intraday (1h/4h) and LSTM/transformers are out of scope until we have
session/minute history; daily NYMEX settles are the live dataset.

EIA event overlay: when a new weekly stock print lands, add a surprise-driven
next-session return (z < 0 draw vs typical = bullish).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from market_features import enrich_market_features

try:
    from xgboost import XGBRegressor
    XGB_OK = True
except ImportError:
    XGB_OK = False

try:
    from lightgbm import LGBMRegressor
    LGBM_OK = True
except ImportError:
    LGBM_OK = False

MIN_TRAIN = 120
WF_TEST = 21
WF_MIN_FOLDS = 3

SHARED = [
    "Crude", "Crude_lag1", "crude_return_1d", "crude_momentum_5d_pct",
    "brent_wti_spread", "crude_inventory", "crude_inv_wow_pct", "crude_inv_z",
    "crude_inv_vs_mean_pct",
    "refinery_utilization_pct", "util_chg", "crude_imports_kbpd", "crude_exports_kbpd",
    "dxy_change_1d_pct", "sentiment", "geo_risk_score",
    "doy_sin", "doy_cos", "week_of_year", "month", "weekday",
    "is_hurricane_season", "is_turnaround_season",
    "eia_print_day", "api_print_day",
    "temp_max_c", "precip_mm", "hdd_proxy", "cdd_proxy",
]

RBOB_ONLY = [
    "RBOB", "RBOB_lag1", "rbob_return_1d", "momentum_5d_pct", "rsi_14", "macd_hist",
    "crack_gasoline", "crack_gasoline_lag1", "crack_gasoline_chg",
    "gasoline_inventory", "gas_inv_wow_pct", "gas_inv_z", "gas_inv_vs_mean_pct",
    "gas_inv_print_day", "is_driving_season", "is_winter_blend",
    "ULSD_lag1",
]

ULSD_ONLY = [
    "ULSD", "ULSD_lag1", "ulsd_return_1d", "ulsd_momentum_5d_pct",
    "crack_diesel", "crack_diesel_lag1", "crack_diesel_chg",
    "diesel_inventory", "dist_inv_wow_pct", "dist_inv_z", "dist_inv_vs_mean_pct",
    "dist_inv_print_day", "is_winter_heating",
    "RBOB_lag1",
]

PRODUCT_COL = {"RBOB_Gasoline": "RBOB", "ULSD_Diesel": "ULSD"}
PRODUCT_FEATURES = {
    "RBOB_Gasoline": SHARED + RBOB_ONLY,
    "ULSD_Diesel": SHARED + ULSD_ONLY,
}


def _select_cols(df: pd.DataFrame, candidates: List[str]) -> List[str]:
    n = len(df)
    out = []
    seen = set()
    for c in candidates:
        if c not in df.columns or c in seen:
            continue
        if int(df[c].notna().sum()) >= max(40, n // 12):
            out.append(c)
            seen.add(c)
    return out


def _frame(df: pd.DataFrame, product_key: str) -> Tuple[pd.DataFrame, List[str], str]:
    col = PRODUCT_COL[product_key]
    work = enrich_market_features(df.copy())
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work = work.sort_values("date").dropna(subset=["date", col])
    work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work[work[col] > 1.0]
    for c in ("week_of_year", "month", "weekday"):
        if c in work.columns:
            work[c] = pd.to_numeric(work[c], errors="coerce")
    if len(work) > 900:
        work = work.tail(900).reset_index(drop=True)
    else:
        work = work.reset_index(drop=True)
    work["target_return"] = work[col].pct_change().shift(-1)
    feats = _select_cols(work, PRODUCT_FEATURES[product_key])
    return work, feats, col


def _make_xgb():
    if XGB_OK:
        return XGBRegressor(
            n_estimators=180,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.85,
            colsample_bytree=0.75,
            min_child_weight=4,
            objective="reg:squarederror",
            random_state=42,
            n_jobs=-1,
        )
    from sklearn.ensemble import GradientBoostingRegressor
    return GradientBoostingRegressor(n_estimators=140, max_depth=3, learning_rate=0.06, random_state=42)


def _make_lgbm():
    if not LGBM_OK:
        return None
    return LGBMRegressor(
        n_estimators=180,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.85,
        colsample_bytree=0.75,
        random_state=42,
        verbose=-1,
    )


def _sign(x: np.ndarray, eps: float = 0.0008) -> np.ndarray:
    out = np.zeros(len(x), dtype=int)
    out[x > eps] = 1
    out[x < -eps] = -1
    return out


def walk_forward_predict(
    X: pd.DataFrame,
    y: pd.Series,
    min_train: int = MIN_TRAIN,
    test_size: int = WF_TEST,
) -> Dict[str, Any]:
    """Expanding-window OOS: train[:i] test[i:i+test]. No shuffle."""
    n = len(X)
    empty = {"dir_acc": None, "mae": None, "rmse": None, "n_oos": 0}
    if n < min_train + test_size:
        return empty

    oos_pred = np.full(n, np.nan)
    start = max(min_train, n - test_size * 5)
    i = start
    folds = 0
    while i < n:
        j = min(n, i + test_size)
        model = _make_xgb()
        model.fit(X.iloc[:i], y.iloc[:i])
        oos_pred[i:j] = model.predict(X.iloc[i:j])
        i = j
        folds += 1
    mask = np.isfinite(oos_pred)
    if mask.sum() < test_size:
        return empty
    pred = oos_pred[mask]
    actual = y.to_numpy()[mask]
    dir_acc = float(np.mean(_sign(pred) == _sign(actual)))
    mae = float(np.mean(np.abs(pred - actual)))
    rmse = float(np.sqrt(np.mean((pred - actual) ** 2)))
    large = np.abs(actual) >= 0.015
    large_hit = float(np.mean(_sign(pred[large]) == _sign(actual[large]))) if large.sum() >= 8 else None
    return {
        "dir_acc": round(dir_acc, 4),
        "mae": round(mae, 5),
        "rmse": round(rmse, 5),
        "n_oos": int(mask.sum()),
        "folds": folds,
        "large_move_hit": round(large_hit, 4) if large_hit is not None else None,
    }


def _eia_event_return(work: pd.DataFrame, product_key: str) -> Optional[float]:
    """Linear EIA overlay: last print-day surprise → expected next-session return."""
    flag = "gas_inv_print_day" if product_key == "RBOB_Gasoline" else "dist_inv_print_day"
    z_primary = "gas_inv_z" if product_key == "RBOB_Gasoline" else "dist_inv_z"
    if flag not in work.columns or z_primary not in work.columns:
        return None
    rows = work[(work[flag] > 0) & work["target_return"].notna()].copy()
    if len(rows) < 8:
        return None
    zcols = [c for c in (z_primary, "crude_inv_z") if c in rows.columns]
    Z = rows[zcols].apply(pd.to_numeric, errors="coerce").fillna(0.0).to_numpy()
    y = rows["target_return"].astype(float).to_numpy()
    # OLS through origin-ish with intercept
    X = np.column_stack([np.ones(len(Z)), Z])
    try:
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    except Exception:
        return None
    last = work.iloc[-1]
    if float(last.get(flag) or 0) <= 0 and float(work[flag].iloc[-2] if len(work) > 1 else 0) <= 0:
        return 0.0
    z_now = [float(last.get(c) or 0) for c in zcols]
    pred = float(beta[0] + np.dot(beta[1:], z_now))
    return float(np.clip(pred, -0.025, 0.025))


def train_predict_product(df: pd.DataFrame, product_key: str) -> Dict[str, Any]:
    col = PRODUCT_COL.get(product_key)
    out: Dict[str, Any] = {
        "used": False,
        "product": product_key,
        "model": "XGBoost" if XGB_OK else "GBM",
        "reason": "",
    }
    if not col or df is None or df.empty or col not in df.columns:
        out["reason"] = "missing product column"
        return out

    work, feats, col = _frame(df, product_key)
    if len(feats) < 6:
        out["reason"] = f"too few features ({len(feats)})"
        return out

    labeled = work.dropna(subset=["target_return"])
    if len(labeled) < MIN_TRAIN:
        out["reason"] = f"need {MIN_TRAIN}+ labeled rows, have {len(labeled)}"
        return out

    X = labeled[feats].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    y = labeled["target_return"].astype(float)
    live_X = work[feats].apply(pd.to_numeric, errors="coerce").fillna(0.0).iloc[[-1]]
    current = float(work[col].iloc[-1])

    wf = walk_forward_predict(X, y)
    xgb = _make_xgb()
    xgb.fit(X, y)
    pred = float(xgb.predict(live_X)[0])

    lgbm_w = 0.0
    lgbm = _make_lgbm()
    if lgbm is not None:
        try:
            lgbm.fit(X, y)
            lpred = float(lgbm.predict(live_X)[0])
            # Prefer the model with better walk-forward dir acc; default 0.65/0.35 if both exist
            lgbm_w = 0.35
            pred = 0.65 * pred + 0.35 * lpred
            out["model"] = "XGB+LGBM"
        except Exception:
            lgbm_w = 0.0

    event_ret = _eia_event_return(work, product_key) or 0.0
    # Fresh print: blend a little event model into the daily forecast
    print_flag = "gas_inv_print_day" if product_key == "RBOB_Gasoline" else "dist_inv_print_day"
    fresh = float(work.iloc[-1].get(print_flag) or 0) > 0
    if fresh and abs(event_ret) >= 0.001:
        pred = 0.75 * pred + 0.25 * event_ret

    dir_acc = wf.get("dir_acc") or 0.5
    confidence = int(max(42, min(82, 40 + 80 * (dir_acc - 0.50) - 400 * (wf.get("mae") or 0.01))))

    out.update({
        "used": True,
        "predicted_return_pct": round(pred * 100, 3),
        "next_day_price": current * (1.0 + pred),
        "current_price": current,
        "direction": "UP" if pred > 0.0008 else "DOWN" if pred < -0.0008 else "FLAT",
        "magnitude_pct": round(abs(pred) * 100, 3),
        "confidence_pct": confidence,
        "feature_count": len(feats),
        "walk_forward": wf,
        "blend_weights": {"xgb": round(1.0 - lgbm_w, 2), "lgbm": lgbm_w, "eia_event": 0.25 if fresh else 0.0},
        "eia_event_return_pct": round(event_ret * 100, 3) if event_ret else 0.0,
        "eia_fresh_print": fresh,
        "features": feats[:20],
    })
    if hasattr(xgb, "feature_importances_"):
        imp = xgb.feature_importances_
        total = float(imp.sum()) or 1.0
        ranked = sorted(
            ((feats[i], float(imp[i]) / total) for i in range(len(feats))),
            key=lambda x: x[1],
            reverse=True,
        )
        out["feature_importance"] = {k: round(v, 4) for k, v in ranked[:12]}
    return out


def blend_var_ml(var_price: float, current: float, ml_info: Dict[str, Any]) -> Tuple[float, str]:
    if not ml_info.get("used") or ml_info.get("next_day_price") is None or not current:
        return var_price, "VAR"
    ml_p = float(ml_info["next_day_price"])
    var_ret = (float(var_price) - current) / current
    ml_ret = float(ml_info.get("predicted_return_pct", 0)) / 100.0
    dir_acc = ((ml_info.get("walk_forward") or {}).get("dir_acc")) or 0.5
    if dir_acc < 0.50:
        w_ml = 0.12
    elif dir_acc < 0.54:
        w_ml = 0.28
    else:
        w_ml = 0.55
    if var_ret * ml_ret < 0 and abs(ml_ret) > 0.003 and dir_acc >= 0.54:
        w_ml = 0.72
    blended = (1.0 - w_ml) * float(var_price) + w_ml * ml_p
    ml_info["var_ml_weights"] = {"var": round(1.0 - w_ml, 2), "ml": round(w_ml, 2)}
    return blended, "VAR+ML"


def apply_product_ml_overlay(
    df: pd.DataFrame,
    results: Dict[str, Any],
    finalize_fn=None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    infos: Dict[str, Any] = {}
    for pk in ("RBOB_Gasoline", "ULSD_Diesel"):
        if pk not in results or not results[pk]:
            continue
        info = train_predict_product(df, pk)
        infos[pk] = info
        if not info.get("used"):
            continue
        block = results[pk]
        current = float(block.get("current_price") or info.get("current_price") or 0)
        var_nd = float(block.get("next_day", block.get("day_1", current)))
        blended, _ = blend_var_ml(var_nd, current, info)
        raw = {
            "day_1": blended,
            "day_4": float(block.get("day_4", block.get("next_week", current))),
            "day_7": float(block.get("day_7", block.get("biweekly", current))),
            "confidence_lower": block.get("confidence_lower"),
            "confidence_upper": block.get("confidence_upper"),
        }
        if finalize_fn:
            block = finalize_fn(current, raw, product_key=pk)
        else:
            block["next_day"] = blended
            block["day_1"] = blended
        block["next_day_ml"] = float(info["next_day_price"])
        block["next_day_var"] = var_nd
        results[pk] = block
    return results, infos
