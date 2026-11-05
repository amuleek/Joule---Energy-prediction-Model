"""
Pre-specified crude composite: "refined products lead crude" (4- and 7-day horizon).

Signals (sign fixed in advance from the economic story, no weights fitted):
  +crack321_z60        strong 3-2-1 refining margin vs its 60-day norm
  +rbob_r20            20-day gasoline momentum
  +gas_dist_ratio      gasoline rich vs diesel
  -ulsd_comm_net_z156  commercial hedgers unusually net long diesel

Each signal is converted to a percentile rank against its own trailing 3 years
(no look-ahead), centred at 0, then averaged equally.

Caveat: these four were chosen after seeing 2016+ data (research/signal_scan.py),
so 2016+ results are optimistic. The real test is forward (paper) tracking.

Usage
  python research/crude_composite.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binomtest

ROOT = Path(__file__).resolve().parent
SIGNALS = {"crack321_z60": 1, "rbob_r20": 1, "gas_dist_ratio": 1, "ulsd_comm_net_z156": -1}
WINDOW = 756  # ~3 years


def trailing_rank(s: pd.Series, window: int = WINDOW) -> pd.Series:
    """Percentile of today's value within the trailing window (inclusive), minus 0.5."""
    return s.rolling(window, min_periods=252).apply(
        lambda a: (a[:-1] < a[-1]).mean() if len(a) > 1 else np.nan, raw=True) - 0.5


def composite(ds: pd.DataFrame) -> pd.Series:
    parts = [sign * trailing_rank(ds[col]) for col, sign in SIGNALS.items()]
    return pd.concat(parts, axis=1).mean(axis=1, skipna=False)


def evaluate(ds: pd.DataFrame, comp: pd.Series, label: str) -> list[dict]:
    rows = []
    for h in (4, 7):
        y = ds[f"y_crude_h{h}"]
        for period, sl in (("2010-2015", slice("2010", "2015")), ("2016+", slice("2016", None))):
            d = pd.DataFrame({"c": comp, "y": y}).loc[sl].dropna()
            d = d[d.y != 0]
            hit = np.sign(d.c) == np.sign(d.y)
            strong = d.c.abs() >= d.c.abs().quantile(0.7)
            # non-overlapping sample for an honest p-value
            nov = d.iloc[::h]
            hit_nov = np.sign(nov.c) == np.sign(nov.y)
            top = d[d.c >= d.c.quantile(2 / 3)].y.mean() * 100
            bot = d[d.c <= d.c.quantile(1 / 3)].y.mean() * 100
            rows.append({
                "data": label, "h": h, "period": period, "n": len(d),
                "dir_acc": hit.mean(), "dir_acc_strong30": hit[strong].mean(),
                "p_nonoverlap": binomtest(int(hit_nov.sum()), len(hit_nov), 0.5,
                                          alternative="greater").pvalue,
                "ret_top_third_pct": top, "ret_bottom_third_pct": bot,
                "spread_pct": top - bot,
            })
    return rows


def main() -> int:
    rows = []
    for name in ("dataset_plus.csv", "dataset_rolladj_plus.csv"):
        path = ROOT / "data" / name
        if not path.exists():
            continue
        ds = pd.read_csv(path, index_col=0, parse_dates=True)
        rows += evaluate(ds, composite(ds), name.replace(".csv", ""))
    res = pd.DataFrame(rows)
    res.to_csv(ROOT / "results" / "crude_composite.csv", index=False)
    pd.set_option("display.width", 200)
    print(res.round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
