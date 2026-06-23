"""
Sync CSV pipeline outputs into the timestamped SQLite database.
"""
from __future__ import annotations

import os

import pandas as pd

from database import init_db, sync_dataframe


def _sync_file(source: str, path: str, n: int) -> int:
    if not os.path.exists(path):
        return n
    df = pd.read_csv(path)
    cols = [c for c in df.columns if c != "date"]
    added = sync_dataframe(source, df, cols)
    print(f"  {path}: {added} observations")
    return n + added


def sync_all_csv_to_db() -> None:
    init_db()
    n = 0
    n = _sync_file("eia_spot", "data/prices.csv", n)
    n = _sync_file("futures_yahoo", "data/futures_ohlc.csv", n)
    n = _sync_file("eia_inventory", "data/inventory.csv", n)
    n = _sync_file("eia_operational", "data/operational.csv", n)
    n = _sync_file("openmeteo", "data/weather.csv", n)
    n = _sync_file("dollar_index", "data/dollar_index.csv", n)
    n = _sync_file("freight_bdry", "data/freight.csv", n)
    print(f"Database sync complete ({n} observation upserts)")


if __name__ == "__main__":
    sync_all_csv_to_db()
