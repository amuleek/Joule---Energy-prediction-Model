"""
Paper-track experimental signals on new data (no forecasts are changed).

Appends today's crude "products lead crude" composite (research/crude_composite.py)
to research/signal_log.csv, and scores older entries once their 4/7-day outcome exists.
Promote the signal to the live forecast only if, after ~6 months of new data,
direction accuracy stays >= 54% (see research/README.md).

Usage (after build_dataset.py):  python research/track_signals.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from crude_composite import composite  # noqa: E402

LOG = ROOT / "signal_log.csv"


def main() -> int:
    ds = pd.read_csv(ROOT / "data" / "dataset_plus.csv", index_col=0, parse_dates=True)
    comp = composite(ds)
    today = comp.dropna().index[-1]
    row = pd.DataFrame([{
        "date": today.date().isoformat(),
        "crude_composite": round(float(comp.loc[today]), 4),
        "crude_price": float(ds.loc[today, "price_crude"]),
    }])
    log = pd.read_csv(LOG) if LOG.exists() else pd.DataFrame(columns=row.columns)
    log = pd.concat([log[log["date"] != row["date"].iloc[0]], row], ignore_index=True)

    # Score entries whose outcome is now known
    px = ds["price_crude"]
    for h in (4, 7):
        outs = []
        for d, c in zip(pd.to_datetime(log["date"]), log["crude_composite"]):
            i = px.index.searchsorted(d)
            if i + h < len(px):
                ret = np.log(px.iloc[i + h] / px.iloc[i])
                outs.append(bool(np.sign(ret) == np.sign(c)) if ret != 0 else np.nan)
            else:
                outs.append(np.nan)
        log[f"hit_h{h}"] = outs
    log.to_csv(LOG, index=False)
    scored = log["hit_h7"].dropna()
    print(f"{today.date()} composite {row['crude_composite'].iloc[0]:+.3f} | "
          f"forward 7-day hit rate {scored.mean():.1%} over {len(scored)} days" if len(scored)
          else f"{today.date()} composite {row['crude_composite'].iloc[0]:+.3f} | no scored days yet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
