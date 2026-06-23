"""
Fetch NYMEX futures daily OHLCV from Yahoo Finance (RB=F, CL=F, HO=F).
Saves data/futures_ohlc.csv for merge into final_data / XGBoost features.

Usage:
  python scripts/fetch_futures_ohlc.py
  python scripts/fetch_futures_ohlc.py --period 2y
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, Optional

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config import FUTURES_SYMBOLS

SYMBOLS = FUTURES_SYMBOLS


def fetch_symbol_history(ticker: str, period: str = "2y") -> Optional[pd.DataFrame]:
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance not installed")
        return None
    try:
        t = yf.Ticker(ticker)
        h = t.history(period=period, interval="1d", auto_adjust=True)
        if h is None or h.empty:
            return None
        h = h.reset_index()
        if "Date" in h.columns:
            h = h.rename(columns={"Date": "date"})
        elif "Datetime" in h.columns:
            h = h.rename(columns={"Datetime": "date"})
        h["date"] = pd.to_datetime(h["date"], errors="coerce").dt.tz_localize(None).dt.normalize()
        return h
    except Exception as e:
        print(f"  {ticker}: {e}")
        return None


def build_futures_frame(period: str = "2y") -> pd.DataFrame:
    frames: Dict[str, pd.DataFrame] = {}
    for prefix, ticker in SYMBOLS.items():
        print(f"  Fetching {ticker} ({period})…")
        h = fetch_symbol_history(ticker, period)
        if h is None or h.empty:
            continue
        sub = pd.DataFrame({"date": h["date"]})
        for col in ("Open", "High", "Low", "Close", "Volume"):
            if col in h.columns:
                sub[f"{prefix}_{col.lower()}"] = pd.to_numeric(h[col], errors="coerce")
        frames[prefix] = sub

    if not frames:
        return pd.DataFrame()

    out = None
    for prefix in ("rbob", "crude", "diesel", "brent", "natgas"):
        if prefix in frames:
            out = frames[prefix] if out is None else out.merge(frames[prefix], on="date", how="outer")
    if out is None:
        return pd.DataFrame()

    out = out.sort_values("date").reset_index(drop=True)

    if "rbob_close" in out.columns:
        out["rbob_calendar_spread_5d"] = out["rbob_close"] - out["rbob_close"].shift(5)
        out["rbob_return_1d"] = out["rbob_close"].pct_change()
    if "crude_close" in out.columns:
        out["crude_return_1d"] = out["crude_close"].pct_change()
    if "rbob_close" in out.columns and "crude_close" in out.columns:
        out["rbob_crude_ratio"] = out["rbob_close"] / out["crude_close"].replace(0, pd.NA)
    if "brent_close" in out.columns and "crude_close" in out.columns:
        out["brent_wti_spread"] = out["brent_close"] - out["crude_close"]
    if "natgas_close" in out.columns:
        out["natgas_return_1d"] = out["natgas_close"].pct_change()

    return out


def save_futures_ohlc(period: str = "2y", path: str = "data/futures_ohlc.csv") -> int:
    os.makedirs(os.path.dirname(path) or "data", exist_ok=True)
    df = build_futures_frame(period)
    if df.empty:
        print("No futures OHLC data retrieved.")
        return 0
    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    if os.path.exists(path):
        try:
            old = pd.read_csv(path)
            old["date"] = pd.to_datetime(old["date"], errors="coerce")
            combined = pd.concat([old, df], ignore_index=True)
            vol_cols = [c for c in combined.columns if c.endswith("_volume")]
            if vol_cols:
                combined["_vol_sum"] = combined[vol_cols].fillna(0).sum(axis=1)
                combined = combined.sort_values(["date", "_vol_sum"]).drop_duplicates(
                    subset=["date"], keep="last"
                )
                combined = combined.drop(columns=["_vol_sum"])
            else:
                combined = combined.drop_duplicates(subset=["date"], keep="last")
            df = combined.sort_values("date").reset_index(drop=True)
        except Exception:
            pass

    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    df.to_csv(path, index=False)
    print(f"Futures OHLC saved: {len(df)} rows -> {path}")
    return len(df)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", default="2y", help="yfinance period (e.g. 1y, 2y, max)")
    args = parser.parse_args()
    os.chdir(_ROOT)
    save_futures_ohlc(period=args.period)


if __name__ == "__main__":
    main()
