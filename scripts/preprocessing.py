"""
Preprocess Data for Prediction Model
Merges prices, inventory, retail pump (EIA weekly), and news topic/sentiment signals
"""
import os
import sys
import pandas as pd
import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from pipeline_fast import apply_fast_defaults
apply_fast_defaults()

from news_signals import save_processed_news
from market_features import enrich_market_features


def process_news_sentiment():
    """Calculate sentiment + geopolitical topic buckets from news."""
    news_path = "data/news.csv"
    if not os.path.exists(news_path):
        print("No news data found. Creating empty sentiment data.")
        return pd.DataFrame(columns=["date", "sentiment"])

    daily = save_processed_news(news_path, "data/news_processed.csv")
    print(f"Processed news: {len(daily)} days (sentiment + topic buckets)")
    if daily.empty:
        return pd.DataFrame(columns=["date", "sentiment"])
    cols = ["date", "sentiment"] + [c for c in daily.columns if c.startswith("topic_") or c == "geo_risk_score"]
    return daily[[c for c in cols if c in daily.columns]]


def _load_retail_weekly() -> pd.DataFrame:
    path = "data/retail_weekly.csv"
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    if df.empty or "date" not in df.columns:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.dropna(subset=["date"]).sort_values("date")


def _align_retail_to_daily(merged: pd.DataFrame, retail: pd.DataFrame) -> pd.DataFrame:
    if retail.empty:
        return merged
    r = retail.copy()
    for c in ("retail_gasoline", "retail_diesel"):
        if c in r.columns:
            r[c] = pd.to_numeric(r[c], errors="coerce")
    r = r.set_index("date").sort_index()
    merged = merged.copy()
    merged["date"] = pd.to_datetime(merged["date"], errors="coerce")
    merged = merged.sort_values("date")
    for c in ("retail_gasoline", "retail_diesel"):
        if c not in r.columns:
            continue
        merged[c] = r[c].reindex(merged["date"], method="ffill").values
    return merged


def merge_data():
    print("Merging data for prediction model...")

    prices_df = pd.read_csv("data/prices.csv") if os.path.exists("data/prices.csv") else pd.DataFrame()
    inventory_df = pd.read_csv("data/inventory.csv") if os.path.exists("data/inventory.csv") else pd.DataFrame()
    news_df = process_news_sentiment()
    retail_df = _load_retail_weekly()

    if prices_df.empty:
        print("Warning: No price data available")
        return pd.DataFrame()

    prices_df = prices_df.dropna(subset=["date"])
    price_cols = [c for c in ("RBOB", "ULSD", "Crude") if c in prices_df.columns]
    prices_df = prices_df.dropna(subset=price_cols, how="all") if price_cols else prices_df

    merged = prices_df.copy()

    fut_path = "data/futures_ohlc.csv"
    if os.path.exists(fut_path):
        fut = pd.read_csv(fut_path)
        if not fut.empty and "date" in fut.columns:
            fut["date"] = pd.to_datetime(fut["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            merged["date"] = pd.to_datetime(merged["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            merged = merged.merge(fut, on="date", how="left")
            fut_cols = [c for c in merged.columns if c.startswith(("rbob_", "crude_", "diesel_"))]
            for c in fut_cols:
                merged[c] = pd.to_numeric(merged[c], errors="coerce").ffill().bfill()
            print(f"  Merged futures OHLC: {len(fut)} rows ({len(fut_cols)} columns)")

    dxy_path = "data/dollar_index.csv"
    if os.path.exists(dxy_path):
        dxy = pd.read_csv(dxy_path)
        if not dxy.empty and "date" in dxy.columns:
            dxy["date"] = pd.to_datetime(dxy["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            merged["date"] = pd.to_datetime(merged["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            merged = merged.merge(
                dxy[["date", "dxy_close", "dxy_change_1d_pct"]],
                on="date",
                how="left",
            )
            for c in ("dxy_close", "dxy_change_1d_pct"):
                if c in merged.columns:
                    merged[c] = pd.to_numeric(merged[c], errors="coerce").ffill().bfill()
            print(f"  Merged dollar index: {len(dxy)} rows")

    op_path = "data/operational.csv"
    if os.path.exists(op_path):
        op = pd.read_csv(op_path)
        if not op.empty and "date" in op.columns:
            op["date"] = pd.to_datetime(op["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            merged["date"] = pd.to_datetime(merged["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            op_cols = [c for c in op.columns if c != "date"]
            merged = merged.merge(op[ ["date"] + op_cols], on="date", how="left")
            for c in op_cols:
                merged[c] = pd.to_numeric(merged[c], errors="coerce").ffill().bfill()
            print(f"  Merged operational data: {len(op)} rows")

    wx_path = "data/weather.csv"
    if os.path.exists(wx_path):
        wx = pd.read_csv(wx_path)
        if not wx.empty and "date" in wx.columns:
            wx["date"] = pd.to_datetime(wx["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            merged["date"] = pd.to_datetime(merged["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            wx_cols = [c for c in wx.columns if c != "date"]
            merged = merged.merge(wx[["date"] + wx_cols], on="date", how="left")
            for c in wx_cols:
                merged[c] = pd.to_numeric(merged[c], errors="coerce").ffill().bfill()
            print(f"  Merged weather: {len(wx)} rows")

    fr_path = "data/freight.csv"
    if os.path.exists(fr_path):
        fr = pd.read_csv(fr_path)
        if not fr.empty and "date" in fr.columns:
            fr["date"] = pd.to_datetime(fr["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            merged["date"] = pd.to_datetime(merged["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            fr_cols = [c for c in ("baltic_dry_proxy", "freight_return_1d", "freight_volume") if c in fr.columns]
            if fr_cols:
                merged = merged.merge(fr[["date"] + fr_cols], on="date", how="left")
                for c in fr_cols:
                    merged[c] = pd.to_numeric(merged[c], errors="coerce").ffill().bfill()
                print(f"  Merged freight proxy: {len(fr)} rows")

    if not inventory_df.empty and "date" in inventory_df.columns:
        merged = merged.merge(inventory_df, on="date", how="left")

    if not news_df.empty and "date" in news_df.columns:
        merged = merged.merge(news_df, on="date", how="left")

    merged["sentiment"] = merged["sentiment"].fillna(0.0) if "sentiment" in merged.columns else 0.0
    merged["geo_risk_score"] = merged["geo_risk_score"].fillna(0.0) if "geo_risk_score" in merged.columns else 0.0
    for k in merged.columns:
        if str(k).startswith("topic_"):
            merged[k] = merged[k].fillna(0.0)

    for col in ("gasoline_inventory", "diesel_inventory", "crude_inventory"):
        if col in merged.columns:
            merged[col] = merged[col].ffill().bfill()

    merged["date"] = pd.to_datetime(merged["date"], errors="coerce")
    merged = merged.dropna(subset=["date"]).sort_values("date")
    merged = _align_retail_to_daily(merged, retail_df)

    for c in ("RBOB", "ULSD", "Crude"):
        if c in merged.columns:
            merged[c] = pd.to_numeric(merged[c], errors="coerce")
    if all(c in merged.columns for c in ("RBOB", "ULSD", "Crude")):
        merged["crack_gasoline"] = merged["RBOB"] * 42.0 - merged["Crude"]
        merged["crack_diesel"] = merged["ULSD"] * 42.0 - merged["Crude"]
        for col in ("Crude", "RBOB", "ULSD"):
            merged[f"{col}_lag1"] = merged[col].shift(1)
            merged[f"{col}_lag7"] = merged[col].shift(7)
        merged["crack_gasoline_lag1"] = merged["crack_gasoline"].shift(1)
        merged["crack_diesel_lag1"] = merged["crack_diesel"].shift(1)

    merged = enrich_market_features(merged)

    merged["date"] = merged["date"].dt.strftime("%Y-%m-%d")
    merged = merged[merged["date"].notna()]

    merged.to_csv("data/final_data.csv", index=False)
    print(f"Merged data saved: {len(merged)} records")
    return merged


if __name__ == "__main__":
    merge_data()
