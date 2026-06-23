"""
Futures + physical market feature engineering for RBOB / energy predictions.
Technical indicators, seasonality, cash basis, macro (DXY), layer scores for the decision agent.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def _seasonality_flags(dt: pd.Series) -> pd.DataFrame:
    month = dt.dt.month
    return pd.DataFrame(
        {
            "is_driving_season": month.isin([5, 6, 7, 8, 9]).astype(int),
            "is_hurricane_season": month.isin([6, 7, 8, 9, 10, 11]).astype(int),
            "is_winter_blend": month.isin([10, 11, 12, 1, 2]).astype(int),
        },
        index=dt.index,
    )


def fetch_dxy_change_pct() -> Optional[float]:
    """Latest daily % change in U.S. Dollar Index proxy (DX-Y.NYB)."""
    if yf is None:
        return None
    try:
        t = yf.Ticker("DX-Y.NYB")
        h = t.history(period="5d")
        if h is None or len(h) < 2:
            return None
        c = h["Close"]
        return float((c.iloc[-1] - c.iloc[-2]) / c.iloc[-2] * 100)
    except Exception:
        return None


def enrich_market_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add technical, basis, calendar-spread proxy, and seasonality columns."""
    out = df.copy()
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        out = out.sort_values("date").reset_index(drop=True)

    price_col = "RBOB" if "RBOB" in out.columns else None
    if price_col:
        p = pd.to_numeric(out[price_col], errors="coerce")
        out["rsi_14"] = _rsi(p, 14)
        macd_line, macd_sig = _macd(p)
        out["macd"] = macd_line
        out["macd_signal"] = macd_sig
        out["macd_hist"] = macd_line - macd_sig
        out["sma_20"] = p.rolling(20).mean()
        out["price_vs_sma20_pct"] = (p / out["sma_20"] - 1) * 100
        out["momentum_5d_pct"] = p.pct_change(5) * 100
        out["momentum_20d_pct"] = p.pct_change(20) * 100
        out["calendar_spread_proxy"] = p - p.shift(5)

    if "spot_ny" in out.columns and price_col:
        out["basis_ny_cash_minus_rbob"] = pd.to_numeric(out["spot_ny"], errors="coerce") - pd.to_numeric(
            out[price_col], errors="coerce"
        )
    if "spot_gulf" in out.columns and price_col:
        out["basis_gulf_cash_minus_rbob"] = pd.to_numeric(out["spot_gulf"], errors="coerce") - pd.to_numeric(
            out[price_col], errors="coerce"
        )

    if "date" in out.columns:
        seas = _seasonality_flags(out["date"])
        for c in seas.columns:
            out[c] = seas[c].values

    if "Brent" in out.columns and "Crude" in out.columns:
        out["brent_wti_spread"] = pd.to_numeric(out["Brent"], errors="coerce") - pd.to_numeric(
            out["Crude"], errors="coerce"
        )

    return out


def latest_feature_snapshot(csv_path: str = "data/final_data.csv") -> Dict[str, Any]:
    """Last-row feature summary for intelligence / email layers."""
    empty: Dict[str, Any] = {"available": False}
    if not os.path.exists(csv_path):
        return empty
    df = pd.read_csv(csv_path)
    if df.empty:
        return empty
    df = enrich_market_features(df)
    row = df.iloc[-1]
    snap: Dict[str, Any] = {
        "available": True,
        "as_of": str(row.get("date", "")),
        "technical": {},
        "basis": {},
        "seasonality": {},
        "macro": {},
    }
    for k in ("rsi_14", "macd_hist", "momentum_5d_pct", "momentum_20d_pct", "price_vs_sma20_pct"):
        if k in row and pd.notna(row[k]):
            snap["technical"][k] = round(float(row[k]), 4)
    for k in ("basis_ny_cash_minus_rbob", "basis_gulf_cash_minus_rbob", "calendar_spread_proxy"):
        if k in row and pd.notna(row[k]):
            snap["basis"][k] = round(float(row[k]), 4)
    for k in ("is_driving_season", "is_hurricane_season", "is_winter_blend"):
        if k in row:
            snap["seasonality"][k] = bool(int(row[k]))
    if "brent_wti_spread" in row and pd.notna(row["brent_wti_spread"]):
        snap["macro"]["brent_wti_spread"] = round(float(row["brent_wti_spread"]), 2)
    if "dxy_change_1d_pct" in row and pd.notna(row["dxy_change_1d_pct"]):
        snap["macro"]["dxy_change_pct"] = round(float(row["dxy_change_1d_pct"]), 3)
    elif "dxy_close" in row and pd.notna(row["dxy_close"]):
        snap["macro"]["dxy_close"] = round(float(row["dxy_close"]), 3)
    else:
        dxy = fetch_dxy_change_pct()
        if dxy is not None:
            snap["macro"]["dxy_change_pct"] = round(dxy, 3)
    return snap


def compute_layer_scores(
    predictions_json: Dict[str, Any],
    inv_snapshot: Dict[str, Any],
    topic_snapshot: Optional[Dict[str, Any]],
    feature_snap: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Multi-agent layer scores in [-1, +1] (bullish = higher RBOB).
    Maps to: futures, inventory, cash, refinery_weather, geopolitical, macro, technical.
    """
    layers: Dict[str, Any] = {}
    rbob = predictions_json.get("RBOB_Gasoline") or {}
    nd = rbob.get("next_day") or {}
    nw = rbob.get("next_week") or {}
    try:
        day_pct = float(nd.get("change_percent", 0))
        week_pct = float(nw.get("change_percent", 0))
    except (TypeError, ValueError):
        day_pct = week_pct = 0.0

    layers["futures"] = {
        "label": "Futures / VAR-Prophet",
        "score": max(-1.0, min(1.0, 0.6 * day_pct / 3 + 0.4 * week_pct / 5)),
        "detail": f"Model 1d {day_pct:+.2f}%, 1w {week_pct:+.2f}%",
    }

    g = inv_snapshot.get("gasoline") or {}
    wow = g.get("wow_change_pct")
    inv_score = 0.0
    if wow is not None:
        inv_score = max(-1.0, min(1.0, -float(wow) / 3.0))
    layers["inventory"] = {
        "label": "EIA inventories",
        "score": round(inv_score, 3),
        "detail": f"Gasoline WoW {wow:+.2f}%" if wow is not None else "No WoW data",
    }

    cash_score = 0.0
    cash_detail = "Cash hubs not in latest row"
    fs = feature_snap or {}
    basis = fs.get("basis") or {}
    if basis.get("basis_ny_cash_minus_rbob") is not None:
        b = float(basis["basis_ny_cash_minus_rbob"])
        cash_score = max(-1.0, min(1.0, b / 0.15))
        cash_detail = f"NY Harbor basis vs RBOB proxy ${b:+.3f}/gal"
    layers["cash_market"] = {"label": "Cash / NY basis", "score": round(cash_score, 3), "detail": cash_detail}

    geo = float((topic_snapshot or {}).get("geo_risk_score") or 0)
    refinery_topic = float((topic_snapshot or {}).get("buckets", {}).get("refinery", {}).get("intensity", 0))
    hurricane_topic = float((topic_snapshot or {}).get("buckets", {}).get("hurricane", {}).get("intensity", 0))
    seas = fs.get("seasonality") or {}
    rw_score = geo * 0.5 + refinery_topic * 0.3 + hurricane_topic * 0.2
    if seas.get("is_hurricane_season"):
        rw_score = min(1.0, rw_score + 0.15)
    layers["refinery_weather"] = {
        "label": "Refinery / weather",
        "score": round(max(-1.0, min(1.0, rw_score)), 3),
        "detail": "Hurricane season / outage headline weight",
    }

    sent = float((topic_snapshot or {}).get("sentiment") or 0)
    layers["geopolitical"] = {
        "label": "News / geopolitical",
        "score": round(max(-1.0, min(1.0, geo * 0.7 - sent * 0.3)), 3),
        "detail": f"Geo risk {geo:.2f}, sentiment {sent:+.2f}",
    }

    macro_score = 0.0
    macro_parts = []
    macro = fs.get("macro") or {}
    if macro.get("dxy_change_pct") is not None:
        dxy = float(macro["dxy_change_pct"])
        macro_score -= max(-1.0, min(1.0, dxy / 1.5))
        macro_parts.append(f"DXY {dxy:+.2f}%")
    crude = predictions_json.get("Crude_Oil") or {}
    c_pct = float((crude.get("next_day") or {}).get("change_percent", 0) or 0)
    macro_score += max(-1.0, min(1.0, c_pct / 5)) * 0.5
    macro_parts.append(f"WTI 1d {c_pct:+.1f}%")
    layers["macro"] = {
        "label": "Macro / crude linkage",
        "score": round(max(-1.0, min(1.0, macro_score)), 3),
        "detail": ", ".join(macro_parts) or "n/a",
    }

    tech = fs.get("technical") or {}
    tech_score = 0.0
    if tech.get("momentum_5d_pct") is not None:
        tech_score += max(-1.0, min(1.0, float(tech["momentum_5d_pct"]) / 5)) * 0.4
    if tech.get("rsi_14") is not None:
        rsi = float(tech["rsi_14"])
        if rsi > 70:
            tech_score -= 0.2
        elif rsi < 30:
            tech_score += 0.2
    if tech.get("macd_hist") is not None:
        tech_score += max(-1.0, min(1.0, float(tech["macd_hist"]) * 10)) * 0.3
    layers["technical"] = {
        "label": "Technical (RSI/MACD/momentum)",
        "score": round(max(-1.0, min(1.0, tech_score)), 3),
        "detail": ", ".join(f"{k}={v}" for k, v in list(tech.items())[:3]) or "n/a",
    }

    scores = [layers[k]["score"] for k in layers if isinstance(layers[k], dict)]
    layers["composite"] = {
        "label": "All layers (weighted)",
        "score": round(float(np.mean(scores)) if scores else 0.0, 3),
    }
    return layers


def build_horizon_outlook(predictions_json: Dict[str, Any], product_key: str = "RBOB_Gasoline") -> Dict[str, Any]:
    """Outlook for day 1, 4, 7 from stored predictions."""
    from forecast_horizons import PREDICTION_HORIZONS

    block = predictions_json.get(product_key) or {}
    if not block:
        return {}

    def _pack(hkey: str, label: str) -> Dict[str, Any]:
        h = block.get(hkey) if isinstance(block.get(hkey), dict) else {}
        legacy = {"day_1": "next_day", "day_4": "next_week", "day_7": "biweekly"}
        if not h and hkey in legacy:
            leg = block.get(legacy[hkey])
            h = leg if isinstance(leg, dict) else {}
        try:
            pct = float(h.get("change_percent", block.get(f"{hkey}_change", 0)))
            price = float(h.get("price", block.get(hkey, 0)))
        except (TypeError, ValueError):
            pct, price = 0.0, 0.0
        cur = float(block.get("current_price", 0) or 0)
        if cur and product_key != "Crude_Oil":
            cents = (price - cur) * 100
        else:
            cents = price - cur
        return {
            "horizon": label,
            "change_percent": round(pct, 2),
            "direction": "UP" if pct > 0.3 else "DOWN" if pct < -0.3 else "FLAT",
            "move_cents": round(cents, 1) if product_key != "Crude_Oil" else round(cents, 2),
        }

    out = {}
    for hkey, _days, _, label in PREDICTION_HORIZONS:
        out[hkey] = _pack(hkey, label)
    out["next_day"] = out.get("day_1", {})
    return out


def build_buy_recommendation(
    trading_signal: Optional[Dict[str, Any]],
    layer_scores: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Operational buy timing for fuel loaders (not financial advice).
    BUY_TODAY | WAIT | HEDGE | MONITOR
    """
    if not trading_signal:
        return {
            "action": "MONITOR",
            "label": "Monitor",
            "rationale": "Insufficient RBOB signal data.",
        }

    day_pct = float(trading_signal.get("tomorrow_change_pct", 0))
    conf = int(trading_signal.get("confidence_pct", 50))
    composite = float((layer_scores.get("composite") or {}).get("score", 0))
    geo = float((layer_scores.get("geopolitical") or {}).get("score", 0))

    if conf < 52:
        return {
            "action": "MONITOR",
            "label": "Monitor — mixed signals",
            "rationale": f"Confidence is only {conf}%; wait for inventory or a clearer model tilt.",
        }

    if geo >= 0.45 and day_pct > 0.5:
        return {
            "action": "HEDGE",
            "label": "Consider hedge / cap price",
            "rationale": "Geopolitical supply risk is elevated and the model leans higher — "
            "protect margin if loading large volumes.",
        }

    if day_pct >= 1.2 and conf >= 58:
        return {
            "action": "WAIT",
            "label": "Wait to buy (if you can)",
            "rationale": f"Model expects ~{day_pct:+.1f}% tomorrow; delaying a day may avoid paying today's move.",
        }

    if day_pct <= -0.8 and conf >= 55:
        return {
            "action": "BUY_TODAY",
            "label": "Favorable to buy today",
            "rationale": f"Near-term model tilt is lower ({day_pct:+.1f}% tomorrow); "
            "composite layer score {composite:+.2f}.",
        }

    if composite >= 0.25 and day_pct > 0:
        return {
            "action": "WAIT",
            "label": "Wait — tightening setup",
            "rationale": "Futures, inventory, and news layers lean firm; short-term dip less likely.",
        }

    if composite <= -0.2 and day_pct < 0:
        return {
            "action": "BUY_TODAY",
            "label": "Buy bias today",
            "rationale": "Layers lean softer; model not pointing to a strong near-term rally.",
        }

    return {
        "action": "NEUTRAL",
        "label": "Neutral — no strong timing edge",
        "rationale": f"Tomorrow {day_pct:+.1f}% with {conf}% confidence — no clear buy/wait edge.",
    }
