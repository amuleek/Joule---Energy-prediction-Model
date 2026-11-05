"""
Walk-forward backtest: does any model beat "price won't change"?

For each product x horizon:
  - Expanding training window, retrained every RETRAIN_EVERY trading days.
  - Purged: training rows whose target window overlaps the test period are dropped
    (last usable train row = test_start - h - 1).
  - Out-of-sample period: TEST_START onward (~12 years).

Models
  naive   predicted return = 0           (random walk; the bar to beat)
  drift   mean training return
  ridge   linear model on standardized features
  lgbm    regularized LightGBM

Metrics (out-of-sample)
  mae_pct       mean |error| in % of price
  mae_vs_naive  < 1.00 means better than the naive forecast
  dir_acc       share of correct up/down calls
  dir_acc_top30 direction accuracy on the 30% most confident calls
  dir_pvalue    one-sided binomial p-value that dir_acc > 50% (h>1 overlaps -> optimistic)

Usage
  python research/backtest.py
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binomtest
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")
try:
    import lightgbm as lgb
except ImportError:
    lgb = None

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "dataset.csv"
OUT = ROOT / "results"
PRODUCTS = ("crude", "rbob", "ulsd")
HORIZONS = (1, 4, 7)
TEST_START = "2014-01-01"
TEST_END = None
RETRAIN_EVERY = 63  # ~quarterly
MIN_TRAIN = 750


def make_models():
    models = {
        "ridge": lambda: make_pipeline(StandardScaler(), Ridge(alpha=50.0)),
    }
    if lgb is not None:
        models["lgbm"] = lambda: lgb.LGBMRegressor(
            n_estimators=300, learning_rate=0.02, num_leaves=15, min_child_samples=100,
            subsample=0.8, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0,
            verbose=-1, random_state=42, n_jobs=4,
        )
    return models


def walk_forward(X: pd.DataFrame, y: pd.Series, h: int) -> pd.DataFrame:
    idx = X.index
    test_pos = np.where(idx >= pd.Timestamp(TEST_START))[0]
    preds = {name: pd.Series(np.nan, index=idx) for name in ["naive", "drift", *make_models()]}
    models = make_models()

    for start in range(test_pos[0], len(idx), RETRAIN_EVERY):
        end = min(start + RETRAIN_EVERY, len(idx))
        train_end = start - h  # purge overlapping targets
        if train_end < MIN_TRAIN:
            continue
        Xtr, ytr = X.iloc[:train_end], y.iloc[:train_end]
        ok = ytr.notna()
        Xtr, ytr = Xtr[ok], ytr[ok]
        Xte = X.iloc[start:end]
        med = Xtr.median()
        Xtr_f, Xte_f = Xtr.fillna(med), Xte.fillna(med)

        preds["naive"].iloc[start:end] = 0.0
        preds["drift"].iloc[start:end] = float(ytr.mean())
        for name, factory in models.items():
            m = factory()
            m.fit(Xtr_f, ytr)
            preds[name].iloc[start:end] = m.predict(Xte_f)

    out = pd.DataFrame(preds)
    out["actual"] = y
    return out.dropna()


def score(df: pd.DataFrame, model: str) -> dict:
    a, p = df["actual"].to_numpy(), df[model].to_numpy()
    err = (np.exp(p) - np.exp(a)) * 100  # % of current price, approx
    naive_err = (1 - np.exp(a)) * 100
    mae, naive_mae = np.mean(np.abs(err)), np.mean(np.abs(naive_err))
    rmse, naive_rmse = np.sqrt(np.mean(err ** 2)), np.sqrt(np.mean(naive_err ** 2))
    res = {"model": model, "n": len(a), "mae_pct": mae, "mae_vs_naive": mae / naive_mae,
           "rmse_vs_naive": rmse / naive_rmse}
    if model != "naive":
        moved = a != 0
        hit = np.sign(p[moved]) == np.sign(a[moved])
        res["dir_acc"] = hit.mean()
        res["dir_pvalue"] = binomtest(int(hit.sum()), int(hit.size), 0.5, alternative="greater").pvalue
        conf = np.abs(p[moved]) >= np.quantile(np.abs(p[moved]), 0.7)
        res["dir_acc_top30"] = hit[conf].mean() if conf.sum() else np.nan
    return res


def main() -> int:
    global TEST_START
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA))
    ap.add_argument("--start", default=TEST_START)
    ap.add_argument("--end", default=None, help="last date used (inclusive)")
    ap.add_argument("--tag", default="", help="suffix for output files")
    args = ap.parse_args()
    TEST_START = args.start
    data = Path(args.data)
    if not data.exists():
        print("Run research/build_dataset.py first")
        return 1
    ds = pd.read_csv(data, index_col=0, parse_dates=True)
    if args.end:
        ds = ds.loc[:args.end]
        # drop targets that would look past the end date
        for h in HORIZONS:
            for p in PRODUCTS:
                ds.loc[ds.index[-h:], f"y_{p}_h{h}"] = np.nan
    sfx = f"_{args.tag}" if args.tag else ""
    feats = [c for c in ds.columns if not c.startswith(("y_", "price_"))]
    X = ds[feats].replace([np.inf, -np.inf], np.nan)
    OUT.mkdir(exist_ok=True)

    rows, yearly = [], []
    for prod in PRODUCTS:
        for h in HORIZONS:
            y = ds[f"y_{prod}_h{h}"]
            df = walk_forward(X, y, h)
            df.to_csv(OUT / f"oos{sfx}_{prod}_h{h}.csv")
            for m in [c for c in df.columns if c != "actual"]:
                rows.append({"product": prod, "horizon": h, **score(df, m)})
            if "lgbm" in df:
                g = df.groupby(df.index.year)
                yr = g.apply(lambda d: np.mean(np.sign(d["lgbm"]) == np.sign(d["actual"])))
                yearly.append(yr.rename(f"{prod}_h{h}"))
            print(f"  done {prod} h={h} ({len(df)} OOS days)")

    summary = pd.DataFrame(rows)
    summary.to_csv(OUT / f"backtest_summary{sfx}.csv", index=False)
    pd.set_option("display.width", 200)
    print(f"\n=== Out-of-sample results from {TEST_START} [{data.name}] ===")
    print(summary.round(3).to_string(index=False))
    if yearly:
        yr = pd.concat(yearly, axis=1)
        yr.to_csv(OUT / f"lgbm_dir_acc_by_year{sfx}.csv")
        print("\n=== LightGBM direction accuracy by year ===")
        print(yr.round(2).to_string())
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ci import run
    run(main)
