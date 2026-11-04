"""
Fetch NYMEX futures daily OHLCV from Yahoo Finance.

Continuous RB=F / HO=F / CL=F are used only as a long-history scaffold.
Product closes (rbob/diesel/crude) are then overwritten with named-month
contracts (e.g. RBV26.NYM) so early continuous rolls cannot poison settles.

Usage:
  python scripts/fetch_futures_ohlc.py
  python scripts/fetch_futures_ohlc.py --period 2y
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Optional, Tuple

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config import FUTURES_SYMBOLS

SYMBOLS = FUTURES_SYMBOLS
# Prefixes whose Close must be named-month (never leave continuous after overlay)
NAMED_PRODUCT_PREFIXES = ("rbob", "crude", "diesel")
PREFIX_TO_COL = {"rbob": "RBOB", "crude": "Crude", "diesel": "ULSD"}


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


def _named_contract_candidates() -> Dict[str, List[str]]:
    """Current front + prior named contracts per product prefix (no lead month)."""
    out: Dict[str, List[str]] = {p: [] for p in NAMED_PRODUCT_PREFIXES}
    try:
        from contract_roll import (
            MONTH_CODES,
            _add_months,
            infer_resolved_contracts,
            nymex_symbol,
        )

        inferred = infer_resolved_contracts()
        for prefix, col in PREFIX_TO_COL.items():
            primary = inferred.get(col)
            if not primary:
                continue
            cands = [primary]
            root = primary[:2]
            mi = MONTH_CODES.find(primary[2])
            yy = int("20" + primary[-2:]) if primary[-2:].isdigit() else 0
            if mi >= 0 and yy >= 2000:
                y, m = _add_months(yy, mi + 1, -1)
                prior = nymex_symbol(root, y, m)
                if prior not in cands:
                    cands.append(prior)
            out[prefix] = cands
    except Exception as e:
        print(f"  Named-month contract infer failed: {e}")
    return out


def overlay_named_month_closes(df: pd.DataFrame, period: str = "6mo") -> Tuple[pd.DataFrame, int]:
    """
    Overwrite rbob/diesel/crude OHLC with the *current front* named-month Yahoo history.
    Never fill gaps with lead-month (RBX) — that re-introduces the continuous-roll bug.
    Prior month may fill only dates *before* the front contract's first bar.
    """
    if df is None or df.empty:
        return df, 0
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.tz_localize(None).dt.normalize()
    patched = 0
    candidates = _named_contract_candidates()

    for prefix in NAMED_PRODUCT_PREFIXES:
        cands = candidates.get(prefix) or []
        if not cands:
            continue
        primary = cands[0]
        prior = cands[1] if len(cands) > 1 else None
        primary_start = None

        ticker = f"{primary}.NYM"
        print(f"  Overlay named-month front {ticker}…")
        h = fetch_symbol_history(ticker, period=period)
        if h is not None and not h.empty:
            primary_start = pd.to_datetime(h["date"]).min()
            sub = pd.DataFrame({"date": h["date"]})
            for col in ("Open", "High", "Low", "Close", "Volume"):
                if col in h.columns:
                    sub[f"{prefix}_{col.lower()}"] = pd.to_numeric(h[col], errors="coerce")
            out = out.merge(sub, on="date", how="left", suffixes=("", "_named"))
            for col in [c for c in out.columns if c.endswith("_named")]:
                base = col[: -len("_named")]
                named_vals = out[col]
                mask = named_vals.notna()
                if base not in out.columns:
                    out[base] = named_vals
                else:
                    out.loc[mask, base] = named_vals.loc[mask]
                patched += int(mask.sum())
                out = out.drop(columns=[col])

        # Prior month only for dates before front lists (do not touch recent front dates)
        if prior and primary_start is not None:
            pticker = f"{prior}.NYM"
            print(f"  Overlay prior-month backfill {pticker}…")
            ph = fetch_symbol_history(pticker, period=period)
            if ph is not None and not ph.empty:
                sub = pd.DataFrame({"date": ph["date"]})
                for col in ("Open", "High", "Low", "Close", "Volume"):
                    if col in ph.columns:
                        sub[f"{prefix}_{col.lower()}"] = pd.to_numeric(ph[col], errors="coerce")
                out = out.merge(sub, on="date", how="left", suffixes=("", "_named"))
                for col in [c for c in out.columns if c.endswith("_named")]:
                    base = col[: -len("_named")]
                    named_vals = out[col]
                    mask = named_vals.notna() & (out["date"] < primary_start)
                    if base in out.columns:
                        out.loc[mask, base] = named_vals.loc[mask]
                        patched += int(mask.sum())
                    out = out.drop(columns=[col])

    out = out.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    return out, patched


def _recompute_derived(out: pd.DataFrame) -> pd.DataFrame:
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
    # Always replace product closes with named-month (continuous is scaffold only)
    out, n_patch = overlay_named_month_closes(out, period="6mo")
    if n_patch:
        print(f"  Named-month overlay applied ({n_patch} cell updates)")
    out = _recompute_derived(out)
    return out


def save_futures_ohlc(period: str = "2y", path: str = "data/futures_ohlc.csv") -> int:
    os.makedirs(os.path.dirname(path) or "data", exist_ok=True)
    df = build_futures_frame(period)
    if df.empty:
        print("No futures OHLC data retrieved.")
        return 0
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.tz_localize(None).dt.normalize()

    if os.path.exists(path):
        try:
            old = pd.read_csv(path)
            old["date"] = pd.to_datetime(old["date"], errors="coerce").dt.tz_localize(None).dt.normalize()
            # Keep history only for dates NOT in the new pull (new pull already
            # has named-month product closes — never let old continuous win).
            new_dates = set(df["date"].dropna().tolist())
            old_only = old[~old["date"].isin(new_dates)].copy()
            df = pd.concat([old_only, df], ignore_index=True)
            df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        except Exception as e:
            print(f"  Merge with existing OHLC skipped: {e}")

    # Final named-month pass on the full file (fixes any residual continuous cells)
    df, n_patch = overlay_named_month_closes(df, period="6mo")
    if n_patch:
        print(f"  Final named-month overlay ({n_patch} cell updates)")
    df = _recompute_derived(df)

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.tz_localize(None).dt.normalize()
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
