"""
Fetch U.S. Dollar Index history (DXY proxy) via Yahoo Finance and optional Alpha Vantage.
Saves data/dollar_index.csv for merge into final_data.

Usage:
  python scripts/fetch_dollar_index.py
  python scripts/fetch_dollar_index.py --period 2y
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

import pandas as pd
import requests

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config import API_CONFIG

YAHOO_TICKER = "DX-Y.NYB"
AV_ETF_PROXY = "UUP"  # Invesco DB USD Index Bullish Fund (liquid AV symbol)
OUT_PATH = "data/dollar_index.csv"


def _fetch_yahoo(period: str = "2y") -> Optional[pd.DataFrame]:
    try:
        import yfinance as yf
    except ImportError:
        print("  yfinance not installed")
        return None
    try:
        h = yf.Ticker(YAHOO_TICKER).history(period=period, interval="1d", auto_adjust=True)
        if h is None or h.empty:
            return None
        h = h.reset_index()
        col = "Date" if "Date" in h.columns else "Datetime"
        h["date"] = pd.to_datetime(h[col], errors="coerce").dt.tz_localize(None).dt.normalize()
        out = pd.DataFrame({
            "date": h["date"],
            "dxy_close": pd.to_numeric(h["Close"], errors="coerce"),
            "source": "yahoo",
        })
        out["dxy_change_1d_pct"] = out["dxy_close"].pct_change() * 100
        return out.dropna(subset=["date", "dxy_close"])
    except Exception as e:
        print(f"  Yahoo {YAHOO_TICKER}: {e}")
        return None


def _fetch_alpha_vantage_daily(api_key: str, symbol: str = AV_ETF_PROXY) -> Optional[pd.DataFrame]:
    """Alpha Vantage TIME_SERIES_DAILY (ETF proxy when DXY not available on AV)."""
    if not api_key:
        return None
    try:
        url = "https://www.alphavantage.co/query"
        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": "full",
            "apikey": api_key,
        }
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        if "Note" in data or "Information" in data:
            print(f"  Alpha Vantage rate limit / info: {data.get('Note') or data.get('Information')}")
            return None
        series = data.get("Time Series (Daily)")
        if not series:
            return None
        rows = []
        for dt, vals in series.items():
            rows.append({
                "date": pd.to_datetime(dt),
                "dxy_close": float(vals.get("4. close", 0)),
                "source": "alpha_vantage",
            })
        out = pd.DataFrame(rows).sort_values("date")
        out["dxy_change_1d_pct"] = out["dxy_close"].pct_change() * 100
        return out.dropna(subset=["dxy_close"])
    except Exception as e:
        print(f"  Alpha Vantage {symbol}: {e}")
        return None


def fetch_dollar_index_frame(period: str = "2y") -> pd.DataFrame:
    api_key = API_CONFIG.get("alpha_vantage_api_key", "")
    df = _fetch_yahoo(period)
    if df is None or df.empty:
        print("  Trying Alpha Vantage ETF proxy…")
        av = _fetch_alpha_vantage_daily(api_key)
        if av is not None and not av.empty:
            df = av.tail(504) if len(av) > 504 else av
    if df is None or df.empty:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df[["date", "dxy_close", "dxy_change_1d_pct", "source"]].drop_duplicates("date", keep="last")


def save_dollar_index(period: str = "2y", path: str = OUT_PATH) -> pd.DataFrame:
    os.makedirs(os.path.dirname(path) or "data", exist_ok=True)
    df = fetch_dollar_index_frame(period)
    if df.empty:
        print("No dollar index data fetched.")
        return df
    df.to_csv(path, index=False)
    last = df.iloc[-1]
    print(
        f"Dollar index saved: {len(df)} rows -> {path} "
        f"(last {last['date']}: {last['dxy_close']:.3f}, 1d {last['dxy_change_1d_pct']:+.2f}%)"
    )
    return df


def latest_dollar_index_snapshot(path: str = OUT_PATH) -> dict:
    """Latest row for email / intelligence meta."""
    if not os.path.exists(path):
        return {}
    try:
        df = pd.read_csv(path)
        if df.empty:
            return {}
        row = df.iloc[-1]
        close = float(row["dxy_close"])
        chg = row.get("dxy_change_1d_pct")
        chg_f = float(chg) if pd.notna(chg) else None
        return {
            "as_of": str(row.get("date", "")),
            "close": round(close, 3),
            "change_pct_1d": round(chg_f, 3) if chg_f is not None else None,
            "source": str(row.get("source", "")),
            "ticker": YAHOO_TICKER,
        }
    except Exception:
        return {}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--period", default="2y")
    p.add_argument("--out", default=OUT_PATH)
    args = p.parse_args()
    save_dollar_index(period=args.period, path=args.out)
