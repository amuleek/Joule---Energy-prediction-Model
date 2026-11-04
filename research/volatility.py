"""
Price-range forecasts: can we say "80% likely between X and Y" and be right ~80% of the time?

Volatility clusters, so (unlike direction) it is forecastable. For each product and
horizon h, we forecast the h-day return distribution as  r_h = sigma_h * z  where
  sigma_h  comes from a volatility model fitted on past data only, and
  z        are the empirical quantiles of past standardized returns (fat tails).

Models compared (all walk-forward, expanding window, refit every 21 days):
  static   trailing 1-year std of h-day returns (no clustering)
  ewma     RiskMetrics EWMA (lambda=0.94) daily variance * h
  har      HAR-RV: log-linear regression of future h-day variance on
           1-day / 5-day / 22-day realized variance

Scored on 2014+ by
  cover80 / cover95  share of outcomes inside the 80% / 95% band (target 0.80 / 0.95)
  width80            average 80% band width, % of price (narrower is better if coverage holds)
  winkler80          interval score: width + penalty for misses (lower is better)

Usage
  python research/volatility.py [--data research/data/dataset.csv]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
PRODUCTS = ("crude", "rbob", "ulsd")
HORIZONS = (1, 4, 7)
TEST_START = "2014-01-01"
REFIT = 21
LEVELS = (0.80, 0.95)


def har_design(r1: pd.Series) -> pd.DataFrame:
    rv = r1 ** 2
    return pd.DataFrame({
        "d": np.log(rv.rolling(1).mean() + 1e-8),
        "w": np.log(rv.rolling(5).mean() + 1e-8),
        "m": np.log(rv.rolling(22).mean() + 1e-8),
        "q": np.log(rv.rolling(66).mean() + 1e-8),
    })


def sigma_forecasts(r1: pd.Series, rh: pd.Series, h: int) -> pd.DataFrame:
    """sigma of the next-h-day log return, using only data up to each date."""
    out = pd.DataFrame(index=r1.index)
    out["static"] = rh.shift(h).rolling(252, min_periods=120).std()

    var = r1.pow(2).ewm(alpha=0.06, adjust=False).mean()
    out["ewma"] = np.sqrt(var * h)

    X = har_design(r1)
    fut_var = (r1 ** 2).rolling(h).mean().shift(-h)  # mean daily var over next h days
    y = np.log(fut_var + 1e-8)
    har = pd.Series(np.nan, index=r1.index)
    pos = np.arange(len(r1))
    first = r1.index.searchsorted(pd.Timestamp(TEST_START)) - 252 * 3
    for start in range(max(first, 300), len(r1), REFIT):
        train = pos < start - h  # targets fully observed before 'start'
        ok = train & X.notna().all(axis=1).to_numpy() & y.notna().to_numpy()
        if ok.sum() < 250:
            continue
        A = np.column_stack([np.ones(ok.sum()), X[ok].to_numpy()])
        beta, *_ = np.linalg.lstsq(A, y[ok].to_numpy(), rcond=None)
        resid_var = np.var(y[ok].to_numpy() - A @ beta)
        sl = slice(start, min(start + REFIT, len(r1)))
        Xs = X.iloc[sl].to_numpy()
        # log-normal bias correction: E[var] = exp(mu + s^2/2)
        har.iloc[sl] = np.exp(np.column_stack([np.ones(len(Xs)), Xs]) @ beta + resid_var / 2)
    out["har"] = np.sqrt(har * h)
    return out


def evaluate(ds: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for p in PRODUCTS:
        price = ds[f"price_{p}"]
        r1 = np.log(price).diff()
        for h in HORIZONS:
            rh = ds[f"y_{p}_h{h}"]                 # future h-day log return (target)
            past_rh = np.log(price).diff(h)        # realized h-day returns (for static)
            sig = sigma_forecasts(r1, past_rh, h)
            for m in sig.columns:
                z = rh / sig[m]
                lo, hi = {}, {}
                # quantiles of z from the past only (expanding, purged by h days)
                for lvl in LEVELS:
                    a = (1 - lvl) / 2
                    lo[lvl] = z.shift(h).expanding(250).quantile(a)
                    hi[lvl] = z.shift(h).expanding(250).quantile(1 - a)
                df = pd.DataFrame({"y": rh, "s": sig[m]}).assign(
                    **{f"lo{int(l*100)}": lo[l] for l in LEVELS},
                    **{f"hi{int(l*100)}": hi[l] for l in LEVELS})
                df = df.loc[TEST_START:].dropna()
                res = {"product": p, "horizon": h, "model": m, "n": len(df)}
                for lvl in LEVELS:
                    k = int(lvl * 100)
                    L, U = df["s"] * df[f"lo{k}"], df["s"] * df[f"hi{k}"]
                    inside = (df["y"] >= L) & (df["y"] <= U)
                    res[f"cover{k}"] = inside.mean()
                    width = (np.exp(U) - np.exp(L)) * 100
                    res[f"width{k}"] = width.mean()
                    a = 1 - lvl
                    miss = (np.exp(L) - np.exp(df["y"])).clip(lower=0) + (np.exp(df["y"]) - np.exp(U)).clip(lower=0)
                    res[f"winkler{k}"] = (width + 2 / a * miss * 100).mean()
                # calibration stability: worst calendar-year 80% coverage
                L, U = df["s"] * df["lo80"], df["s"] * df["hi80"]
                yearly = ((df["y"] >= L) & (df["y"] <= U)).groupby(df.index.year).mean()
                res["cover80_worst_year"] = yearly.min()
                rows.append(res)
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data" / "dataset.csv"))
    args = ap.parse_args()
    ds = pd.read_csv(args.data, index_col=0, parse_dates=True)
    res = evaluate(ds)
    (ROOT / "results").mkdir(exist_ok=True)
    res.to_csv(ROOT / "results" / "volatility_bands.csv", index=False)
    pd.set_option("display.width", 220)
    print(res.round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
