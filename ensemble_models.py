"""
Multi-model ensemble: technical, fundamental, and news layers
combined with accuracy-weighted blending.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from config import DEFAULT_ENSEMBLE_WEIGHTS, MODEL_WEIGHTS_PATH

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

FAST_ENSEMBLE = os.getenv("FAST_ENSEMBLE", "true").lower() in ("1", "true", "yes")
TECH_FEATURES = [
    "rsi_14", "macd_hist", "momentum_5d_pct", "momentum_20d_pct",
    "price_vs_sma20_pct", "rbob_return_1d", "ulsd_return_1d", "crude_return_1d", "rbob_volume",
    "rbob_calendar_spread_5d", "natgas_return_1d",
]


def _product_col(product_key: str) -> str:
    return {"RBOB_Gasoline": "RBOB", "ULSD_Diesel": "ULSD", "Crude_Oil": "Crude"}.get(product_key, "RBOB")


def load_model_weights() -> Dict[str, Dict[str, float]]:
    if os.path.exists(MODEL_WEIGHTS_PATH):
        try:
            with open(MODEL_WEIGHTS_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {k: dict(v) for k, v in DEFAULT_ENSEMBLE_WEIGHTS.items()}


def save_model_weights(weights: Dict[str, Dict[str, float]]) -> None:
    os.makedirs(os.path.dirname(MODEL_WEIGHTS_PATH) or "data", exist_ok=True)
    with open(MODEL_WEIGHTS_PATH, "w", encoding="utf-8") as f:
        json.dump(weights, f, indent=2)


def _sign(x: float, eps: float = 0.08) -> int:
    if x > eps:
        return 1
    if x < -eps:
        return -1
    return 0


class TechnicalModel:
    """Short-term (1-3 day): momentum, volume, technical indicators."""

    def predict_return_pct(self, df: pd.DataFrame, product_key: str) -> Tuple[float, Dict[str, float]]:
        col = _product_col(product_key)
        if df is None or df.empty or col not in df.columns:
            return 0.0, {}

        work = df.dropna(subset=[col]).copy()
        if len(work) < 30:
            return 0.0, {}

        feats = [c for c in TECH_FEATURES if c in work.columns]
        if len(feats) < 3:
            mom = work[col].pct_change().tail(5).mean()
            return float(mom * 100) if not np.isnan(mom) else 0.0, {"momentum_fallback": 1.0}

        work["target"] = work[col].pct_change().shift(-1)
        work = work.dropna(subset=["target"])
        if len(work) < 25:
            return 0.0, {}

        X = work[feats].apply(pd.to_numeric, errors="coerce").fillna(0.0)
        y = work["target"].astype(float)
        split = len(work) - 7
        X_train, y_train = X.iloc[:split], y.iloc[:split]
        X_last = X.iloc[[-1]]

        preds: Dict[str, float] = {}
        if FAST_ENSEMBLE:
            mom = work[col].pct_change().tail(5).mean()
            if not np.isnan(mom):
                return float(mom * 100), {"momentum": float(mom * 100)}
            return 0.0, {}

        models = []
        if XGB_OK:
            models.append(("xgb", XGBRegressor(n_estimators=80, max_depth=4, learning_rate=0.08, random_state=42)))
        models.append(("rf", RandomForestRegressor(n_estimators=60, max_depth=5, random_state=42)))
        if LGBM_OK:
            models.append(("lgbm", LGBMRegressor(n_estimators=80, max_depth=4, learning_rate=0.08, random_state=42, verbose=-1)))

        rets = []
        for name, m in models:
            try:
                m.fit(X_train, y_train)
                r = float(m.predict(X_last)[0]) * 100
                preds[name] = r
                rets.append(r)
            except Exception:
                continue

        if not rets:
            return 0.0, preds
        return float(np.mean(rets)), preds


class FundamentalModel:
    """Medium-term: inventories, refinery utilization, crack spreads, seasonality."""

    def predict_return_pct(self, df: pd.DataFrame, product_key: str, meta: Dict[str, Any]) -> Tuple[float, Dict[str, float]]:
        drivers: Dict[str, float] = {}
        score = 0.0

        inv = meta.get("inventory_weekly") or {}
        inv_key = {"RBOB_Gasoline": "gasoline", "ULSD_Diesel": "distillate", "Crude_Oil": "crude"}.get(product_key, "crude")
        wow = (inv.get(inv_key) or {}).get("wow_change_pct")
        if wow is not None:
            w = float(wow)
            # Draws support prices; builds weigh against
            inv_signal = -w * 0.15
            drivers["inventory_wow"] = inv_signal
            score += inv_signal

        surprises = (meta.get("catalyst_calendar") or {}).get("inventory_surprise") or {}
        feat = ((meta.get("catalyst_calendar") or {}).get("product_features") or {}).get(product_key) or {}
        z_row = surprises.get(inv_key) or {}
        z = z_row.get("z_score") if isinstance(z_row, dict) else None
        if feat.get("fresh_print") and z is not None and abs(float(z)) >= 0.50:
            # Standardized surprise vs typical week (not street forecast)
            z_signal = -float(z) * 0.22
            drivers["inventory_surprise_z"] = z_signal
            score += z_signal

        op = meta.get("operational") or {}
        util = op.get("refinery_utilization_pct")
        if util is not None:
            u = float(util)
            # High utilization = strong demand / tight products
            util_signal = (u - 85.0) * 0.02
            drivers["refinery_util"] = util_signal
            score += util_signal

        crack = meta.get("crack_spreads_current") or {}
        if product_key == "RBOB_Gasoline":
            gc = crack.get("gasoline_crack_usd_per_bbl")
            if gc is not None:
                c = float(gc)
                crack_signal = (c - 25.0) * 0.03
                drivers["gasoline_crack"] = crack_signal
                score += crack_signal
        elif product_key == "ULSD_Diesel":
            dc = crack.get("diesel_crack_usd_per_bbl")
            if dc is not None:
                c = float(dc)
                crack_signal = (c - 30.0) * 0.025
                drivers["diesel_crack"] = crack_signal
                score += crack_signal

        if "is_driving_season" in df.columns and product_key == "RBOB_Gasoline":
            if float(df["is_driving_season"].iloc[-1]) > 0:
                drivers["driving_season"] = 0.12
                score += 0.12

        return float(np.clip(score, -3.0, 3.0)), drivers


class NewsModel:
    """News / sentiment layer: headlines, geo risk, topic buckets."""

    def predict_return_pct(self, meta: Dict[str, Any]) -> Tuple[float, Dict[str, float]]:
        drivers: Dict[str, float] = {}
        score = 0.0

        sent = meta.get("sentiment")
        if sent is not None:
            s = float(sent)
            sig = s * 1.5
            drivers["sentiment"] = sig
            score += sig

        topics = meta.get("topic_snapshot") or {}
        geo = meta.get("geo_risk_score") or topics.get("geo_risk_score")
        if geo is not None:
            g = float(geo)
            sent_val = float(sent if sent is not None else topics.get("sentiment") or 0)
            sign = 1.0 if sent_val >= 0 else -0.5
            sig = g * 1.2 * sign
            drivers["geo_risk"] = sig
            score += sig

        for tk in ("topic_opec", "topic_geopolitical", "topic_refinery", "topic_hurricane"):
            v = topics.get(tk)
            if v is not None and float(v) > 0.1:
                sig = float(v) * 0.5
                drivers[tk] = sig
                score += sig

        rag = meta.get("rag_context") or []
        if rag:
            drivers["rag_headlines"] = min(1.0, len(rag) * 0.1)
            score += drivers["rag_headlines"] * 0.3

        hurricane = meta.get("hurricane") or {}
        hr = float(hurricane.get("risk_score", 0) or 0)
        if hr > 0.05:
            sig = hr * 1.8
            drivers["hurricane_risk"] = sig
            score += sig

        freight = meta.get("freight") or {}
        fr_chg = freight.get("freight_return_1d")
        if fr_chg is not None and abs(float(fr_chg)) > 0.005:
            sig = float(fr_chg) * 50
            drivers["freight_proxy"] = sig
            score += sig

        return float(np.clip(score, -2.5, 2.5)), drivers


class EnsembleAgent:
    """
    Combines technical + fundamental + news into a price delta,
    weighted by historical accuracy (model_weights.json).
    """

    def __init__(self):
        self.technical = TechnicalModel()
        self.fundamental = FundamentalModel()
        self.news = NewsModel()

    def forecast(
        self,
        product_key: str,
        current_price: float,
        df: pd.DataFrame,
        meta: Dict[str, Any],
        horizon: str = "day_1",
    ) -> Dict[str, Any]:
        weights_all = load_model_weights()
        w = weights_all.get(product_key, DEFAULT_ENSEMBLE_WEIGHTS.get(product_key, {}))
        w_tech = float(w.get("technical", 0.34))
        w_fund = float(w.get("fundamental", 0.33))
        w_news = float(w.get("news", 0.33))

        tech_ret, tech_detail = self.technical.predict_return_pct(df, product_key)
        fund_ret, fund_detail = self.fundamental.predict_return_pct(df, product_key, meta)
        news_ret, news_detail = self.news.predict_return_pct(meta)

        # When tape disagrees with inventory/geo on RBOB, trust technicals more
        if product_key == "RBOB_Gasoline" and tech_ret < -0.3 and fund_ret > 0.3:
            w_tech, w_fund, w_news = 0.55, 0.20, 0.25

        total_w = w_tech + w_fund + w_news or 1.0
        w_tech, w_fund, w_news = w_tech / total_w, w_fund / total_w, w_news / total_w

        # Scale longer horizons slightly
        horizon_scale = {"day_1": 1.0, "day_4": 1.4, "day_7": 1.8}.get(horizon, 1.0)
        combined_ret = (w_tech * tech_ret + w_fund * fund_ret + w_news * news_ret) * horizon_scale
        delta_price = current_price * (combined_ret / 100.0)

        unit = "cents/gal" if product_key != "Crude_Oil" else "$/bbl"
        if product_key != "Crude_Oil":
            delta_display = delta_price * 100
        else:
            delta_display = delta_price

        return {
            "horizon": horizon,
            "combined_return_pct": round(combined_ret, 4),
            "delta_price": round(delta_price, 6),
            "delta_display": round(delta_display, 2),
            "delta_unit": unit,
            "weights": {"technical": w_tech, "fundamental": w_fund, "news": w_news},
            "components": {
                "technical": {"return_pct": round(tech_ret, 4), "detail": tech_detail},
                "fundamental": {"return_pct": round(fund_ret, 4), "detail": fund_detail},
                "news": {"return_pct": round(news_ret, 4), "detail": news_detail},
            },
        }

    def apply_to_predictions(
        self,
        results: Dict[str, Any],
        df: pd.DataFrame,
        meta: Dict[str, Any],
        blend: float = 0.65,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Blend ensemble day-1 delta with existing model output.
        blend=0.65 means 65% ensemble, 35% VAR/Prophet base (day-1 precision).
        """
        ensemble_meta: Dict[str, Any] = {}
        for product_key, block in results.items():
            if not isinstance(block, dict):
                continue
            current = float(block.get("current_price", 0) or 0)
            if current <= 0:
                continue
            fc = self.forecast(product_key, current, df, meta, horizon="day_1")
            ensemble_meta[product_key] = fc
            base_day1 = float(block.get("day_1", block.get("next_day", current)))
            ensemble_price = current + fc["delta_price"]
            ens_ret = float(fc["combined_return_pct"])
            base_ret = ((base_day1 - current) / current * 100) if current else 0
            use_blend = blend
            if _sign(ens_ret) and _sign(base_ret) and _sign(ens_ret) != _sign(base_ret):
                use_blend = 0.82
            tech_ret = fc["components"]["technical"]["return_pct"]
            fund_ret = fc["components"]["fundamental"]["return_pct"]
            if tech_ret < -0.3 and (fund_ret > 0.3 or base_ret > 1.5):
                use_blend = max(use_blend, 0.78)
            if tech_ret > 0.3 and (fund_ret < -0.3 or base_ret < -1.5):
                use_blend = max(use_blend, 0.78)
            blended = (1 - use_blend) * base_day1 + use_blend * ensemble_price
            block["day_1"] = blended
            block["next_day"] = blended
            chg = ((blended - current) / current * 100) if current else 0
            block["day_1_change"] = float(chg)
            block["day_1_direction"] = "UP" if chg > 0 else "DOWN" if chg < 0 else "FLAT"
            block["next_day_change"] = block["day_1_change"]
            block["next_day_direction"] = block["day_1_direction"]

        return results, ensemble_meta
