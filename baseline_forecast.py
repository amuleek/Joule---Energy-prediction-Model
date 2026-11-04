"""
Calibrated baseline forecast: today's settle as the centre + volatility-based price ranges.

Why
  A walk-forward backtest (research/backtest.py, 2014-2026, ~3,200 sessions) found that
  no model on price / inventory / curve / calendar features beats "price stays at the
  settle" on error for crude, RBOB or ULSD at 1/4/7 days, and none has a reliable
  direction edge once contract-roll jumps are removed. The live stack (VAR/Prophet +
  XGBoost + CatBoost + ensemble + day-1 rules) lost to the settle in 8 of 9 cases.

  Volatility *is* forecastable. EWMA volatility with empirical (fat-tailed) quantiles
  gave 80% ranges that contained the outcome 79.6-81.4% of the time and 95% ranges
  93.5-95.0% (research/volatility.py).

What it does
  For every product and horizon (day_1/4/7 plus legacy next_day/next_week/...):
    price          = current settle (centre forecast)
    change_percent = 0, direction = "FLAT"
    range_80 / range_95 = {"low", "high"}  calibrated price bands
  The previous model's numbers are kept under block["legacy_model"] for comparison.

  FORECAST_MODE=legacy disables this and leaves the old stack's output untouched.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

TICKERS = {"Crude_Oil": "CL=F", "RBOB_Gasoline": "RB=F", "ULSD_Diesel": "HO=F"}
HORIZONS = {
    "day_1": 1, "day_4": 4, "day_7": 7,
    "next_day": 1, "next_week": 5, "biweekly": 10, "monthly": 21,
}
EWMA_ALPHA = 0.06          # RiskMetrics lambda = 0.94
HISTORY_START = "2006-01-01"
CACHE = os.path.join("data", "baseline_history.csv")
MODEL_NAME = "Settle + EWMA ranges (calibrated baseline)"


def is_enabled() -> bool:
    return os.getenv("FORECAST_MODE", "baseline").strip().lower() != "legacy"


# --------------------------------------------------------------------------- data
def _load_history(max_age_hours: float = 12.0) -> pd.DataFrame:
    """Daily front-month closes since 2006 (cached, refreshed twice a day)."""
    if os.path.exists(CACHE):
        age_h = (datetime.now().timestamp() - os.path.getmtime(CACHE)) / 3600
        if age_h < max_age_hours:
            return pd.read_csv(CACHE, index_col=0, parse_dates=True)
    import yfinance as yf

    raw = yf.download(list(TICKERS.values()), start=HISTORY_START, progress=False,
                      auto_adjust=False)["Close"]
    px = raw.rename(columns={v: k for k, v in TICKERS.items()})
    px.index = pd.to_datetime(px.index).tz_localize(None)
    px = px.where(px > 0).ffill().dropna(how="all")
    os.makedirs("data", exist_ok=True)
    px.to_csv(CACHE)
    return px


# --------------------------------------------------------------------------- model
def _band_params(prices: pd.Series, h: int, levels=(0.80, 0.95)) -> Dict[str, Any]:
    """sigma for the next h sessions + empirical quantiles of standardized h-day returns."""
    lp = np.log(prices.dropna())
    r1 = lp.diff().dropna()
    var = (r1 ** 2).ewm(alpha=EWMA_ALPHA, adjust=False).mean()
    sig_h = np.sqrt(var * h)
    fwd = lp.shift(-h) - lp                         # realized next-h return
    z = (fwd / sig_h).dropna()                      # only fully realized history
    out = {"sigma_h": float(sig_h.iloc[-1]), "sigma_1d": float(np.sqrt(var.iloc[-1]))}
    for lvl in levels:
        a = (1 - lvl) / 2
        out[f"z_lo_{int(lvl * 100)}"] = float(z.quantile(a))
        out[f"z_hi_{int(lvl * 100)}"] = float(z.quantile(1 - a))
    return out


def price_range(current: float, params: Dict[str, Any], level: int = 80,
                sessions: Optional[int] = None) -> Dict[str, float]:
    """Price band for `level`% (80 or 95). `sessions` rescales sigma by sqrt(time)."""
    sig = params["sigma_h"]
    if sessions is not None:
        sig = params["sigma_1d"] * np.sqrt(sessions)
    lo = current * np.exp(sig * params[f"z_lo_{level}"])
    hi = current * np.exp(sig * params[f"z_hi_{level}"])
    return {"low": float(lo), "high": float(hi)}


# --------------------------------------------------------------------------- apply
def apply_baseline_forecast(predictions_json: Dict[str, Any]) -> Dict[str, Any]:
    """Rewrite predictions in place with the calibrated baseline. Returns a summary."""
    if not is_enabled():
        return {"applied": False, "reason": "FORECAST_MODE=legacy"}
    try:
        hist = _load_history()
    except Exception as e:  # never break the pipeline; keep legacy output
        print(f"  Baseline forecast skipped (history unavailable: {e})")
        return {"applied": False, "reason": str(e)}

    summary: Dict[str, Any] = {"applied": True, "products": {}}
    for pk, block in predictions_json.items():
        if pk.startswith("_") or not isinstance(block, dict) or pk not in hist.columns:
            continue
        try:
            current = float(block.get("current_price") or 0)
        except (TypeError, ValueError):
            current = 0.0
        if current <= 0:
            continue

        legacy: Dict[str, Any] = {}
        prod_summary: Dict[str, Any] = {}
        for hkey, h in HORIZONS.items():
            hd = block.get(hkey)
            if not isinstance(hd, dict):
                continue
            params = _band_params(hist[pk], h)
            legacy[hkey] = {k: hd.get(k) for k in ("price", "change_percent", "direction")}
            r80 = price_range(current, params, 80)
            r95 = price_range(current, params, 95)
            hd.update({
                "price": current,
                "change_percent": 0.0,
                "direction": "FLAT",
                "range_80": r80,
                "range_95": r95,
                "sigma_pct": round(params["sigma_h"] * 100, 3),
            })
            if hkey == "day_1":
                block["baseline_params"] = params
            prod_summary[hkey] = {"range_80": r80, "sigma_pct": hd["sigma_pct"]}

        block["legacy_model"] = legacy
        d7 = (block.get("day_7") or {}).get("range_80")
        if d7:
            block["confidence_range"] = {"lower": d7["low"], "upper": d7["high"], "level": 80}
        # Untested directional calls are replaced with an explicit "no edge" read.
        d1 = block.get("day_1") or {}
        r = d1.get("range_80") or {}
        block["directional"] = {
            "label": "NO EDGE",
            "emoji": "",
            "confidence": 50,
            "score": 0.0,
            "summary": (
                "No tested directional edge. Centre = last settle; "
                f"80% range tomorrow {r.get('low', 0):.4f}-{r.get('high', 0):.4f}."
            ),
        }
        block.pop("trading_signal", None)
        if r:
            block["reasoning"] = (
                "No tested directional edge. Tomorrow's settle is 80% likely between "
                f"{r['low']:.4f} and {r['high']:.4f}."
            )
            predictions_json.setdefault("_meta", {}).setdefault("reasoning", {})[pk] = block["reasoning"]
        block["forecast_uncertainty"] = {
            "level": "RANGE",
            "headline": f"80% range · daily vol {d1.get('sigma_pct', 0):.2f}%",
            "reasons": ["Calibrated EWMA volatility ranges (backtested 2014-2026)"],
        }
        summary["products"][pk] = prod_summary

    meta = predictions_json.setdefault("_meta", {})
    meta["legacy_model"] = meta.get("model")
    meta["model"] = MODEL_NAME
    meta["model_stack"] = ["NYMEX settle", "EWMA volatility", "Empirical quantiles"]
    meta["baseline_forecast"] = summary
    return summary


if __name__ == "__main__":
    import json

    with open(os.path.join("data", "predictions.json")) as f:
        preds = json.load(f)
    s = apply_baseline_forecast(preds)
    for pk, ps in s.get("products", {}).items():
        cur = preds[pk]["current_price"]
        print(pk, f"settle {cur:.4f}")
        for hkey in ("day_1", "day_4", "day_7"):
            r = ps[hkey]["range_80"]
            print(f"   {hkey}: 80% {r['low']:.4f} - {r['high']:.4f}  (sigma {ps[hkey]['sigma_pct']}%)")
