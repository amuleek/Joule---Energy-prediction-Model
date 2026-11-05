"""Load prediction, price, and accuracy data for the web dashboard."""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

PRODUCTS = [
    ("RBOB_Gasoline", "RBOB", "Gasoline (RBOB)", "$/gal", 4),
    ("ULSD_Diesel", "ULSD", "Diesel (ULSD)", "$/gal", 4),
    ("Crude_Oil", "Crude", "WTI Crude", "$/bbl", 2),
]

HORIZONS = [
    ("day_1", "Tomorrow"),
    ("day_4", "Day 4"),
    ("day_7", "Day 7"),
]


def _read_json(path: str) -> Any:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_predictions(path: str = "data/predictions.json") -> Dict[str, Any]:
    raw = _read_json(path) or {}
    out: Dict[str, Any] = {"products": {}, "meta": raw.get("_meta") or {}}
    spot = (raw.get("_meta") or {}).get("spot_reference") or {}

    for key, col, label, unit, decimals in PRODUCTS:
        block = raw.get(key) or {}
        if not block:
            continue
        current = float(block.get("current_price") or 0)
        horizons = {}
        for hkey, hlabel in HORIZONS:
            h = block.get(hkey) or {}
            if not h:
                continue
            horizons[hkey] = {
                "label": hlabel,
                "price": round(float(h.get("price") or 0), decimals),
                "change_pct": round(float(h.get("change_percent") or 0), 2),
                "direction": h.get("direction", "FLAT"),
                "range_80": {
                    k: round(float(v), decimals) for k, v in (h.get("range_80") or {}).items()
                } or None,
            }
        unc = block.get("forecast_uncertainty") or {}
        directional = block.get("directional") or {}
        out["products"][key] = {
            "key": key,
            "column": col,
            "label": label,
            "unit": unit,
            "decimals": decimals,
            "current_price": round(current, decimals),
            "timestamp": block.get("timestamp"),
            "horizons": horizons,
            "uncertainty": unc.get("headline") or unc.get("level"),
            "uncertainty_detail": {
                "level": unc.get("level"),
                "confidence_pct": unc.get("confidence_pct"),
                "reasons": unc.get("reasons") or [],
            },
            "directional": {
                "label": directional.get("label"),
                "emoji": directional.get("emoji"),
                "confidence": directional.get("confidence"),
                "summary": directional.get("summary"),
                "drivers": directional.get("drivers") or {},
                "scenario_rationale": directional.get("scenario_rationale") or {},
            },
            "reasoning": block.get("reasoning"),
            "trading_signal": block.get("trading_signal"),
            "confidence_range": block.get("confidence_range"),
        }

    out["spot_reference"] = spot
    out["generated_at"] = out["meta"].get("generated_at") or _latest_product_ts(out["products"])
    return out


def _latest_product_ts(products: Dict[str, Any]) -> Optional[str]:
    ts = [p.get("timestamp") for p in products.values() if p.get("timestamp")]
    return max(ts) if ts else None


def load_price_history(days: int = 90) -> Dict[str, List[Dict[str, Any]]]:
    """Price history from session settle cache + prices.csv."""
    series: Dict[str, List[Dict[str, Any]]] = {col: [] for _, col, _, _, _ in PRODUCTS}

    cache = _read_json("data/session_settles.json") or {}
    for date_key in sorted(cache.keys()):
        closes = (cache.get(date_key) or {}).get("closes") or {}
        for _, col, _, _, _ in PRODUCTS:
            if col in closes:
                series[col].append({"date": date_key, "price": float(closes[col])})

    if os.path.exists("data/prices.csv"):
        try:
            df = pd.read_csv("data/prices.csv")
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"]).sort_values("date")
            cutoff = df["date"].max() - pd.Timedelta(days=days) if len(df) else None
            if cutoff is not None:
                df = df[df["date"] >= cutoff]
            existing = {col: {r["date"] for r in rows} for col, rows in series.items()}
            for _, col, _, _, _ in PRODUCTS:
                if col not in df.columns:
                    continue
                for _, row in df.iterrows():
                    d = row["date"].strftime("%Y-%m-%d")
                    if d in existing.get(col, set()):
                        continue
                    val = row[col]
                    if pd.notna(val) and float(val) > 0:
                        series[col].append({"date": d, "price": float(val)})
        except Exception:
            pass

    for col in series:
        series[col] = sorted(series[col], key=lambda x: x["date"])[-days:]
    return series


def load_accuracy_summary() -> Dict[str, Any]:
    path = "data/prediction_eval_log.csv"
    if not os.path.exists(path):
        return {"overall": {}, "by_product": {}, "recent": []}

    df = pd.read_csv(path)
    if df.empty:
        return {"overall": {}, "by_product": {}, "recent": []}

    overall = {
        "count": len(df),
        "direction_pct": round(df["direction_correct"].mean() * 100, 1) if "direction_correct" in df else None,
        "mean_abs_error_pct": round(df["abs_error_pct"].mean(), 2) if "abs_error_pct" in df else None,
    }

    day1 = df[df["horizon"] == "day_1"] if "horizon" in df.columns else df
    if not day1.empty:
        overall["day1_direction_pct"] = round(day1["direction_correct"].mean() * 100, 1)
        overall["day1_mean_abs_error_pct"] = round(day1["abs_error_pct"].mean(), 2)

    by_product = {}
    for product in df["product"].unique() if "product" in df.columns else []:
        sub = df[df["product"] == product]
        d1 = sub[sub["horizon"] == "day_1"] if "horizon" in sub.columns else sub
        by_product[product] = {
            "direction_pct": round(sub["direction_correct"].mean() * 100, 1),
            "mean_abs_error_pct": round(sub["abs_error_pct"].mean(), 2),
            "day1_direction_pct": round(d1["direction_correct"].mean() * 100, 1) if not d1.empty else None,
            "count": len(sub),
        }

    recent_cols = [
        c for c in (
            "issued_date", "target_date", "product", "display", "horizon",
            "spot_at_issue", "predicted", "actual", "error_pct",
            "direction_correct", "predicted_direction", "actual_direction",
        )
        if c in df.columns
    ]
    recent = df.tail(20)[recent_cols].to_dict(orient="records")

    chart_rows = day1.tail(60) if not day1.empty else df.tail(60)
    forecast_chart = []
    for _, row in chart_rows.iterrows():
        forecast_chart.append({
            "date": str(row.get("target_date", "")),
            "product": row.get("display") or row.get("product"),
            "predicted": float(row["predicted"]) if pd.notna(row.get("predicted")) else None,
            "actual": float(row["actual"]) if pd.notna(row.get("actual")) else None,
        })

    return {
        "overall": overall,
        "by_product": by_product,
        "recent": recent,
        "forecast_chart": forecast_chart,
    }


def dashboard_status() -> Dict[str, Any]:
    preds = load_predictions()
    return {
        "ok": bool(preds.get("products")),
        "generated_at": preds.get("generated_at"),
        "spot_label": (preds.get("spot_reference") or {}).get("label"),
        "spot_date": (preds.get("spot_reference") or {}).get("as_of_date"),
        "product_count": len(preds.get("products") or {}),
        "server_time": datetime.now().isoformat(timespec="seconds"),
    }


def load_news(limit: int = 40) -> Dict[str, Any]:
    """Recent energy headlines with daily sentiment overlay."""
    news_path = "data/news.csv"
    sent_path = "data/news_processed.csv"
    if not os.path.exists(news_path):
        return {"items": [], "daily_sentiment": [], "summary": {}}

    try:
        news_df = pd.read_csv(news_path)
    except Exception:
        return {"items": [], "daily_sentiment": [], "summary": {}}

    sentiment_by_date: Dict[str, float] = {}
    geo_by_date: Dict[str, float] = {}
    topics_by_date: Dict[str, Dict[str, float]] = {}
    if os.path.exists(sent_path):
        try:
            sent_df = pd.read_csv(sent_path)
            for _, row in sent_df.iterrows():
                d = str(row.get("date", ""))[:10]
                if not d:
                    continue
                sentiment_by_date[d] = float(row.get("sentiment") or 0)
                geo_by_date[d] = float(row.get("geo_risk_score") or 0)
                topics_by_date[d] = {
                    "opec": float(row.get("topic_opec") or 0),
                    "geopolitical": float(row.get("topic_geopolitical") or 0),
                    "hurricane": float(row.get("topic_hurricane") or 0),
                    "shipping": float(row.get("topic_shipping") or 0),
                    "refinery": float(row.get("topic_refinery") or 0),
                    "crude_markets": float(row.get("topic_crude_markets") or 0),
                }
        except Exception:
            pass

    items: List[Dict[str, Any]] = []
    if "date" in news_df.columns:
        news_df = news_df.sort_values("date", ascending=False)
    for _, row in news_df.head(limit).iterrows():
        raw_date = str(row.get("date", ""))
        day = raw_date[:10] if raw_date else ""
        sent = sentiment_by_date.get(day)
        topics = topics_by_date.get(day) or {}
        top_topic = max(topics.items(), key=lambda x: x[1])[0] if topics else None
        items.append({
            "date": raw_date,
            "title": str(row.get("title", ""))[:200],
            "description": str(row.get("description", ""))[:300],
            "source": str(row.get("source", "")),
            "sentiment": round(sent, 3) if sent is not None else None,
            "geo_risk": round(geo_by_date.get(day, 0), 3) if day else None,
            "top_topic": top_topic.replace("_", " ").title() if top_topic else None,
        })

    daily_sentiment: List[Dict[str, Any]] = []
    if os.path.exists(sent_path):
        try:
            sent_df = pd.read_csv(sent_path).tail(30)
            for _, row in sent_df.iterrows():
                daily_sentiment.append({
                    "date": str(row.get("date", ""))[:10],
                    "sentiment": round(float(row.get("sentiment") or 0), 3),
                    "geo_risk": round(float(row.get("geo_risk_score") or 0), 3),
                })
        except Exception:
            pass

    latest_sent = daily_sentiment[-1]["sentiment"] if daily_sentiment else None
    latest_geo = daily_sentiment[-1]["geo_risk"] if daily_sentiment else None
    return {
        "items": items,
        "daily_sentiment": daily_sentiment,
        "summary": {
            "count": len(items),
            "latest_sentiment": latest_sent,
            "latest_geo_risk": latest_geo,
            "sentiment_label": (
                "Bullish" if latest_sent and latest_sent > 0.05
                else "Bearish" if latest_sent and latest_sent < -0.05
                else "Neutral"
            ) if latest_sent is not None else "Unknown",
        },
    }


def load_inventory() -> Dict[str, Any]:
    """EIA weekly inventory levels with week-over-week changes."""
    path = "data/inventory.csv"
    if not os.path.exists(path):
        return {"series": {}, "latest": {}}

    try:
        df = pd.read_csv(path)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date")
    except Exception:
        return {"series": {}, "latest": {}}

    series: Dict[str, List[Dict[str, Any]]] = {
        "gasoline": [],
        "diesel": [],
        "crude": [],
    }
    col_map = {
        "gasoline_inventory": "gasoline",
        "diesel_inventory": "diesel",
        "crude_inventory": "crude",
    }
    for col, key in col_map.items():
        if col not in df.columns:
            continue
        sub = df[["date", col]].dropna()
        for _, row in sub.iterrows():
            series[key].append({
                "date": row["date"].strftime("%Y-%m-%d"),
                "value": float(row[col]),
            })

    latest: Dict[str, Any] = {}
    for col, key in col_map.items():
        if col not in df.columns:
            continue
        sub = df[["date", col]].dropna()
        if len(sub) < 1:
            continue
        cur = sub.iloc[-1]
        wow_pct = None
        if len(sub) >= 2:
            prev = float(sub.iloc[-2][col])
            cur_val = float(cur[col])
            if prev:
                wow_pct = round((cur_val - prev) / prev * 100, 2)
        latest[key] = {
            "date": cur["date"].strftime("%Y-%m-%d"),
            "value": float(cur[col]),
            "wow_pct": wow_pct,
            "unit": "thousand barrels",
        }

    return {"series": series, "latest": latest}


def load_market_context() -> Dict[str, Any]:
    """Fundamentals, crack spreads, dollar index, and operational data."""
    raw = _read_json("data/predictions.json") or {}
    meta = raw.get("_meta") or {}

    dxy_series: List[Dict[str, Any]] = []
    dxy_latest = None
    if os.path.exists("data/dollar_index.csv"):
        try:
            dxy_df = pd.read_csv("data/dollar_index.csv")
            dxy_df["date"] = pd.to_datetime(dxy_df["date"], errors="coerce")
            dxy_df = dxy_df.dropna(subset=["date"]).sort_values("date").tail(90)
            for _, row in dxy_df.iterrows():
                dxy_series.append({
                    "date": row["date"].strftime("%Y-%m-%d"),
                    "close": float(row["dxy_close"]),
                    "change_1d_pct": round(float(row["dxy_change_1d_pct"]), 2)
                    if pd.notna(row.get("dxy_change_1d_pct")) else None,
                })
            if not dxy_df.empty:
                last = dxy_df.iloc[-1]
                dxy_latest = {
                    "close": float(last["dxy_close"]),
                    "change_1d_pct": round(float(last["dxy_change_1d_pct"]), 2)
                    if pd.notna(last.get("dxy_change_1d_pct")) else None,
                    "date": last["date"].strftime("%Y-%m-%d"),
                }
        except Exception:
            pass

    cracks = meta.get("crack_spreads_current") or {}
    cracks_forecast = meta.get("crack_spreads_forecast_var") or {}

    return {
        "model": meta.get("model"),
        "model_stack": meta.get("model_stack") or [],
        "crack_spreads": {
            "current": {
                "gasoline": round(float(cracks.get("gasoline_crack_usd_per_bbl") or 0), 2),
                "diesel": round(float(cracks.get("diesel_crack_usd_per_bbl") or 0), 2),
                "units": cracks.get("units", "$/bbl"),
            },
            "forecast": cracks_forecast,
        },
        "retail_pump": meta.get("retail_pump_weekly") or {},
        "operational": meta.get("operational") or {},
        "hurricane": meta.get("hurricane") or {},
        "freight": meta.get("freight") or {},
        "dollar_index": {"latest": dxy_latest, "series": dxy_series},
        "spot_reference": meta.get("spot_reference") or {},
        "generated_at": meta.get("generated_at"),
    }
