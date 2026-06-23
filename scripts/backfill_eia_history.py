"""
Backfill historical EIA daily spot (RBOB, ULSD, WTI) and weekly retail pump (PADD 1B).
Merges into data/prices.csv and data/retail_weekly.csv for preprocessing.

Usage:
  python scripts/backfill_eia_history.py
  python scripts/backfill_eia_history.py --days 730
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config import API_CONFIG

EIA_API_KEY = API_CONFIG.get("eia_api_key", "")
SPOT_URL = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
RETAIL_URL = "https://api.eia.gov/v2/petroleum/pri/gnd/data/"

SPOT_SERIES = API_CONFIG.get("eia_spot_series") or {
    "RBOB": {"product": "EPMRR", "duoarea": "Y35NY"},
    "ULSD": {"product": "EPD2DXL0", "duoarea": "RGC"},
    "Crude": {"product": "EPCWTI", "duoarea": "YCUOK"},
}

RETAIL_PRODUCTS = {
    "retail_gasoline": "EPMR",
    "retail_diesel": "EPD2DXL0",
}


def _fetch_eia_rows(url: str, params: Dict, max_rows: int = 5000) -> List[Dict]:
    if not EIA_API_KEY:
        print("EIA_API_KEY not set — skipping backfill.")
        return []
    out: List[Dict] = []
    offset = 0
    page = min(5000, max_rows)
    while offset < max_rows:
        p = {**params, "api_key": EIA_API_KEY, "offset": offset, "length": page}
        try:
            r = requests.get(url, params=p, timeout=60)
            r.raise_for_status()
            batch = r.json().get("response", {}).get("data") or []
        except Exception as e:
            print(f"EIA request failed at offset {offset}: {e}")
            break
        if not batch:
            break
        out.extend(batch)
        if len(batch) < page:
            break
        offset += len(batch)
    return out


def fetch_daily_spot_series(col: str, product_code: str, duoarea: str, days: int) -> pd.DataFrame:
    params = {
        "frequency": "daily",
        "data[0]": "value",
        "facets[product][]": product_code,
        "facets[duoarea][]": duoarea,
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
    }
    rows = _fetch_eia_rows(SPOT_URL, params, max_rows=days + 50)
    if not rows:
        return pd.DataFrame(columns=["date", col])
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["period"], errors="coerce")
    df[col] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date", col])
    df = df.groupby("date", as_index=False)[col].mean().sort_values("date")
    return df


def fetch_weekly_retail(duoarea: str, product_code: str, weeks: int) -> pd.DataFrame:
    rows = _fetch_eia_rows(
        RETAIL_URL,
        {
            "frequency": "weekly",
            "data[0]": "value",
            "facets[duoarea][]": duoarea,
            "facets[product][]": product_code,
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
        },
        max_rows=weeks + 20,
    )
    if not rows:
        return pd.DataFrame(columns=["date", "value"])
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["period"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date", "value"])
    return df[["date", "value"]].drop_duplicates("date").sort_values("date")


def build_spot_frame(days: int) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for col, spec in SPOT_SERIES.items():
        product = spec["product"]
        duo = spec.get("duoarea", "")
        print(f"  Fetching daily {col} ({product} @ {duo or 'all hubs'})…")
        s = fetch_daily_spot_series(col, product, duo, days)
        if s.empty:
            print(f"    Warning: no rows for {col}")
            continue
        frames.append(s)
    if not frames:
        return pd.DataFrame()
    merged = frames[0]
    for f in frames[1:]:
        merged = merged.merge(f, on="date", how="outer")
    return merged.sort_values("date").reset_index(drop=True)


def build_retail_frame(duoarea: str, weeks: int) -> pd.DataFrame:
    out = pd.DataFrame()
    for col, code in RETAIL_PRODUCTS.items():
        print(f"  Fetching weekly retail {col} ({code})…")
        s = fetch_weekly_retail(duoarea, code, weeks)
        if s.empty:
            continue
        s = s.rename(columns={"value": col})
        out = s if out.empty else out.merge(s, on="date", how="outer")
    if not out.empty:
        out["duoarea"] = duoarea
    return out


def merge_into_prices_csv(spot: pd.DataFrame, prices_path: str = "data/prices.csv") -> int:
    os.makedirs(os.path.dirname(prices_path) or "data", exist_ok=True)
    spot = spot.copy()
    spot["date"] = spot["date"].dt.strftime("%Y-%m-%d")

    if os.path.exists(prices_path):
        existing = pd.read_csv(prices_path)
        existing = existing.dropna(subset=["date"], how="any")
        existing["date"] = pd.to_datetime(existing["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        existing = existing[existing["date"].notna()]
        for c in spot.columns:
            if c != "date" and c not in existing.columns:
                existing[c] = None
        merged = pd.concat([existing, spot], ignore_index=True)
        merged = merged.drop_duplicates(subset=["date"], keep="last")
    else:
        merged = spot

    merged = merged.sort_values("date")
    merged.to_csv(prices_path, index=False)
    return len(merged)


def run_backfill(days: int = 730, retail_weeks: int = 156) -> Tuple[int, int]:
    duo = API_CONFIG.get("eia_retail_duoarea", "R1Y")
    print(f"EIA spot backfill (~{days} daily rows per series)…")
    spot = build_spot_frame(days)
    n_prices = 0
    if not spot.empty:
        n_prices = merge_into_prices_csv(spot)
        print(f"  prices.csv: {n_prices} rows")
    else:
        print("  No spot data retrieved.")

    print(f"EIA retail backfill (~{retail_weeks} weeks, duoarea={duo})…")
    retail = build_retail_frame(duo, retail_weeks)
    n_retail = 0
    retail_path = "data/retail_weekly.csv"
    if not retail.empty:
        retail["date"] = retail["date"].dt.strftime("%Y-%m-%d")
        retail.to_csv(retail_path, index=False)
        n_retail = len(retail)
        print(f"  retail_weekly.csv: {n_retail} rows")
    else:
        print("  No retail data retrieved.")

    return n_prices, n_retail


def main():
    parser = argparse.ArgumentParser(description="Backfill EIA spot and retail history")
    parser.add_argument("--days", type=int, default=730, help="Daily spot lookback")
    parser.add_argument("--retail-weeks", type=int, default=156, help="Weekly retail lookback")
    args = parser.parse_args()
    os.chdir(_ROOT)
    run_backfill(days=args.days, retail_weeks=args.retail_weeks)


if __name__ == "__main__":
    main()
