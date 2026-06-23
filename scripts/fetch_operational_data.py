"""
Fetch EIA operational data: refinery utilization, crude imports/exports.
Saves data/operational.csv (weekly).
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import requests

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config import API_CONFIG, EIA_OPERATIONAL_SERIES

EIA_API_KEY = API_CONFIG.get("eia_api_key", "")
OUT_PATH = "data/operational.csv"


def _fetch_series(series_id: str, frequency: str = "weekly") -> tuple[str, float | None]:
    if not EIA_API_KEY:
        return "", None
    endpoints = {
        "weekly": "https://api.eia.gov/v2/petroleum/sum/sndw/data/",
        "monthly": "https://api.eia.gov/v2/petroleum/move/impcus/data/",
    }
    url = endpoints.get(frequency, endpoints["weekly"])
    params = {
        "api_key": EIA_API_KEY,
        "frequency": frequency,
        "data[0]": "value",
        "facets[series][]": series_id,
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 1,
    }
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        rows = r.json().get("response", {}).get("data") or []
        if rows:
            return str(rows[0].get("period", "")), float(rows[0].get("value", 0))
    except Exception as e:
        print(f"  EIA {series_id}: {e}")
    return "", None


def fetch_operational() -> pd.DataFrame:
    print("Fetching refinery utilization and trade flows...")
    row: dict = {}
    periods = []

    for key, spec in EIA_OPERATIONAL_SERIES.items():
        period, val = _fetch_series(spec["series_id"], spec.get("frequency", "weekly"))
        if period:
            periods.append(period)
        if val is not None:
            row[key] = val
            print(f"  {spec['name']}: {val}")

    if not row:
        print("No operational data fetched.")
        return pd.DataFrame()

    row["date"] = max(periods) if periods else ""
    df_new = pd.DataFrame([row])

    if os.path.exists(OUT_PATH):
        existing = pd.read_csv(OUT_PATH)
        df = pd.concat([existing, df_new], ignore_index=True)
        df = df.drop_duplicates(subset=["date"], keep="last")
    else:
        df = df_new

    os.makedirs("data", exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    print(f"Operational data saved: {len(df)} records -> {OUT_PATH}")
    return df


if __name__ == "__main__":
    fetch_operational()
