"""
Append today's futures curve (contracts 1-4) to research/curve_history.csv.

EIA stopped publishing contract 1-4 settlements in April 2024 and Yahoo drops
contracts once they expire, so the only way to keep a curve history going forward
is to record it daily. Run after the 14:30 ET settle (GitHub Actions does this).
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from curve import fetch_live_curve  # noqa: E402

OUT = ROOT / "curve_history.csv"


def main() -> int:
    today = pd.Timestamp.today().normalize()
    live = fetch_live_curve(today)
    live.insert(0, "date", today.date().isoformat())
    live.index.name = "product"
    live = live.reset_index()
    if OUT.exists():
        hist = pd.read_csv(OUT)
        hist = hist[hist["date"] != live["date"].iloc[0]]  # idempotent re-runs
        live = pd.concat([hist, live], ignore_index=True)
    live.to_csv(OUT, index=False)
    print(f"Recorded {today.date()} -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
