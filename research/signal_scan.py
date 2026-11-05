"""
One-signal-at-a-time scan with a discovery / confirmation split.

Testing ~70 features x 9 targets means ~600 tests, so about 30 will look
"significant" at p<0.05 by pure chance. To guard against that:
  1. Discovery   2006-2015: rank correlation (IC) of feature_t with the h-day return,
                 t-stat with Newey-West (HAC) errors because h-day returns overlap.
  2. Confirmation 2016-today: the same test on data never used for discovery.
A signal counts only if |t| >= 2 in BOTH periods with the SAME sign.

Usage
  python research/signal_scan.py [--data research/data/dataset_plus.csv]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

ROOT = Path(__file__).resolve().parent
PRODUCTS = ("crude", "rbob", "ulsd")
HORIZONS = (1, 4, 7)
SPLIT = "2016-01-01"


def hac_t(x: pd.Series, y: pd.Series, lags: int) -> tuple[float, float, int]:
    d = pd.concat([x, y], axis=1).dropna()
    if len(d) < 200 or d.iloc[:, 0].std() == 0:
        return np.nan, np.nan, len(d)
    xr = d.iloc[:, 0].rank(pct=True) - 0.5          # rank transform: robust to outliers
    yr = d.iloc[:, 1]
    m = sm.OLS(yr, sm.add_constant(xr)).fit(cov_type="HAC", cov_kwds={"maxlags": max(lags, 1)})
    ic = float(np.corrcoef(xr, yr.rank(pct=True))[0, 1])
    return float(m.tvalues.iloc[1]), ic, len(d)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data" / "dataset_plus.csv"))
    args = ap.parse_args()
    ds = pd.read_csv(args.data, index_col=0, parse_dates=True)
    feats = [c for c in ds.columns if not c.startswith(("y_", "price_"))]

    rows = []
    for p in PRODUCTS:
        for h in HORIZONS:
            y = ds[f"y_{p}_h{h}"]
            for f in feats:
                x = ds[f]
                t1, ic1, n1 = hac_t(x[:SPLIT], y[:SPLIT], h)
                t2, ic2, n2 = hac_t(x[SPLIT:], y[SPLIT:], h)
                rows.append({"product": p, "h": h, "feature": f,
                             "t_disc": t1, "ic_disc": ic1, "t_conf": t2, "ic_conf": ic2,
                             "n_conf": n2})
    res = pd.DataFrame(rows)
    res["confirmed"] = (res.t_disc.abs() >= 2) & (res.t_conf.abs() >= 2) & (
        np.sign(res.t_disc) == np.sign(res.t_conf))
    out = ROOT / "results" / "signal_scan.csv"
    res.to_csv(out, index=False)

    n_tests = res.t_disc.notna().sum()
    disc = (res.t_disc.abs() >= 2).sum()
    print(f"{n_tests} tests | |t|>=2 in discovery: {disc} (chance ~{int(n_tests * 0.046)})")
    print(f"Confirmed out of sample (same sign, |t|>=2 both): {res.confirmed.sum()} "
          f"(chance ~{max(1, int(disc * 0.023))})\n")
    pd.set_option("display.width", 200)
    show = res[res.confirmed].sort_values("t_conf", key=abs, ascending=False)
    print(show.round(3).to_string(index=False) if len(show) else "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
