"""
Clean, leakage-free daily dataset for energy futures forecasting.

Sources
  - Yahoo Finance continuous front-month futures (CL, RB, HO, BZ, NG) + DXY, 2006 onward
  - EIA weekly stocks (crude ex-SPR, gasoline, distillate), full history

Leakage rules
  - Every feature on row t uses only information known at the close of day t.
  - EIA weekly data (week ending Friday) is published the following Wednesday 10:30 ET,
    so it becomes visible on period + 5 days and is forward-filled only (never back-filled).
  - Seasonal inventory norms use the 5 *prior* years only.

Targets
  - y_{product}_h{h} = log(P_{t+h} / P_t) in trading days, h in {1, 4, 7}.

Usage
  python research/build_dataset.py            # writes research/data/dataset.csv
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "data"
START = "2006-01-01"
HORIZONS = (1, 4, 7)

TICKERS = {
    "crude": "CL=F",   # WTI $/bbl
    "rbob": "RB=F",    # RBOB $/gal
    "ulsd": "HO=F",    # ULSD $/gal
    "brent": "BZ=F",   # Brent $/bbl
    "natgas": "NG=F",  # Henry Hub $/MMBtu
    "dxy": "DX-Y.NYB", # US dollar index
}
PRODUCTS = ("crude", "rbob", "ulsd")

EIA_SERIES = {
    "inv_crude": "WCESTUS1",  # commercial crude ex-SPR, kb
    "inv_gas": "WGTSTUS1",    # total motor gasoline, kb
    "inv_dist": "WDISTUS1",   # distillate fuel oil, kb
}
EIA_RELEASE_LAG_DAYS = 5  # Friday week-end -> Wednesday release


# --------------------------------------------------------------------------- prices
def fetch_prices() -> pd.DataFrame:
    raw = yf.download(list(TICKERS.values()), start=START, auto_adjust=False,
                      progress=False, group_by="column")
    close = raw["Close"].rename(columns={v: k for k, v in TICKERS.items()})
    close.index = pd.to_datetime(close.index).tz_localize(None)
    # Trading calendar = days WTI traded. Other series forward-filled (never back-filled).
    close = close[close["crude"].notna()].ffill()
    # WTI printed negative in Apr-2020; log returns need positive prices.
    for c in close.columns:
        close.loc[close[c] <= 0, c] = np.nan
    return close.ffill()


# --------------------------------------------------------------------------- EIA
def _eia_series(series_id: str, api_key: str) -> pd.Series:
    url = "https://api.eia.gov/v2/petroleum/stoc/wstk/data/"
    rows, offset = [], 0
    while True:
        params = {
            "api_key": api_key, "frequency": "weekly", "data[0]": "value",
            "facets[series][]": series_id, "start": "2000-01-01",
            "sort[0][column]": "period", "sort[0][direction]": "asc",
            "offset": offset, "length": 5000,
        }
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()["response"]["data"]
        rows += data
        if len(data) < 5000:
            break
        offset += 5000
    s = pd.Series({pd.Timestamp(d["period"]): float(d["value"]) for d in rows if d.get("value") is not None})
    return s.sort_index()


def _seasonal_deviation(weekly: pd.Series) -> pd.Series:
    """% deviation from the same ISO week's average over the 5 prior years."""
    df = weekly.to_frame("v")
    df["year"] = df.index.isocalendar().year.values
    df["week"] = df.index.isocalendar().week.values
    pivot = df.pivot_table(index="year", columns="week", values="v")
    norm = pivot.shift(1).rolling(5, min_periods=3).mean()  # prior 5 years only
    norm_long = norm.stack().rename("norm")
    df = df.join(norm_long, on=["year", "week"])
    return (df["v"] / df["norm"] - 1.0) * 100


def fetch_inventories(api_key: str) -> pd.DataFrame:
    frames = {}
    for name, sid in EIA_SERIES.items():
        s = _eia_series(sid, api_key)
        f = pd.DataFrame({
            f"{name}_level": s,
            f"{name}_chg_pct": s.pct_change() * 100,
            f"{name}_vs5y_pct": _seasonal_deviation(s),
        })
        f.index = f.index + pd.Timedelta(days=EIA_RELEASE_LAG_DAYS)  # date it became public
        frames[name] = f
    inv = pd.concat(frames.values(), axis=1)
    inv["eia_release"] = 1.0
    return inv


# --------------------------------------------------------------------------- features
def build_features(px: pd.DataFrame, inv: pd.DataFrame | None) -> pd.DataFrame:
    f = pd.DataFrame(index=px.index)
    logp = np.log(px)

    for c in px.columns:
        r1 = logp[c].diff()
        f[f"{c}_r1"] = r1
        f[f"{c}_r5"] = logp[c].diff(5)
        f[f"{c}_r20"] = logp[c].diff(20)
        f[f"{c}_vol20"] = r1.rolling(20).std()
    for c in PRODUCTS:
        f[f"{c}_z20"] = (px[c] - px[c].rolling(20).mean()) / px[c].rolling(20).std()
        f[f"{c}_r60"] = logp[c].diff(60)
        f[f"{c}_range_pos60"] = (px[c] - px[c].rolling(60).min()) / (
            px[c].rolling(60).max() - px[c].rolling(60).min())

    # Refining margins ($/bbl)
    crack_321 = (2 * px["rbob"] * 42 + px["ulsd"] * 42 - 3 * px["crude"]) / 3
    crack_gas = px["rbob"] * 42 - px["crude"]
    crack_dist = px["ulsd"] * 42 - px["crude"]
    for name, s in {"crack321": crack_321, "crack_gas": crack_gas, "crack_dist": crack_dist}.items():
        f[name] = s
        f[f"{name}_chg5"] = s.diff(5)
        f[f"{name}_z60"] = (s - s.rolling(60).mean()) / s.rolling(60).std()
    f["brent_wti"] = px["brent"] - px["crude"]
    f["brent_wti_chg5"] = f["brent_wti"].diff(5)
    f["gas_dist_ratio"] = px["rbob"] / px["ulsd"]

    # Calendar
    doy = px.index.dayofyear
    f["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    f["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    f["dow"] = px.index.dayofweek

    # Inventories: as-of join, forward fill only
    if inv is not None and not inv.empty:
        inv = inv.sort_index()
        level_cols = [c for c in inv.columns if c != "eia_release"]
        inv.index = pd.DatetimeIndex(inv.index).astype("datetime64[ns]")
        f.index = pd.DatetimeIndex(f.index).astype("datetime64[ns]")
        # As-of join: last release on or before each trading day (forward fill only)
        aligned = inv[level_cols].reindex(inv.index.union(f.index)).ffill().reindex(f.index)
        for c in aligned.columns:
            if not c.endswith("_level"):
                f[c] = aligned[c].values
        rel = inv["eia_release"].reindex(f.index).fillna(0.0)
        f["eia_release_day"] = rel.values

    # Targets
    for c in PRODUCTS:
        for h in HORIZONS:
            f[f"y_{c}_h{h}"] = logp[c].shift(-h) - logp[c]
        f[f"price_{c}"] = px[c]
    return f


def main() -> int:
    load_dotenv(ROOT.parent / ".env")
    OUT_DIR.mkdir(exist_ok=True)

    print("Downloading futures prices from Yahoo...")
    px = fetch_prices()
    print(f"  {len(px)} trading days, {px.index.min().date()} -> {px.index.max().date()}")

    inv = None
    key = os.getenv("EIA_API_KEY", "")
    if key:
        print("Downloading EIA weekly inventories...")
        try:
            inv = fetch_inventories(key)
            print(f"  {len(inv)} weekly releases")
        except Exception as e:  # keep going with prices only
            print(f"  EIA fetch failed ({e}); continuing without inventories")
    else:
        print("EIA_API_KEY not set; building price-only dataset")

    ds = build_features(px, inv)
    ds.index.name = "date"
    out = OUT_DIR / "dataset.csv"
    ds.to_csv(out)
    feats = [c for c in ds.columns if not c.startswith(("y_", "price_"))]
    print(f"Wrote {out} - {len(ds)} rows, {len(feats)} features")
    return 0


if __name__ == "__main__":
    sys.exit(main())
