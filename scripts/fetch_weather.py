"""
Fetch Gulf Coast weather (Open-Meteo, no API key) for demand/refinery context.
Saves data/weather.csv (daily).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pandas as pd
import requests

# Houston / Gulf Coast refinery hub
LAT, LON = 29.76, -95.37
OUT_PATH = "data/weather.csv"


def fetch_weather(days_back: int = 7) -> pd.DataFrame:
    print("Fetching Gulf Coast weather (Open-Meteo)...")
    end = datetime.now().date()
    start = end - timedelta(days=days_back)
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": LAT,
        "longitude": LON,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max",
        "timezone": "America/Chicago",
    }
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        daily = r.json().get("daily") or {}
        dates = daily.get("time") or []
        if not dates:
            return pd.DataFrame()
        df = pd.DataFrame({
            "date": dates,
            "temp_max_c": daily.get("temperature_2m_max"),
            "temp_min_c": daily.get("temperature_2m_min"),
            "precip_mm": daily.get("precipitation_sum"),
            "wind_max_kmh": daily.get("windspeed_10m_max"),
        })
        df["heat_index_proxy"] = df["temp_max_c"] * 1.05 + df["precip_mm"] * 0.01
        os.makedirs("data", exist_ok=True)
        if os.path.exists(OUT_PATH):
            old = pd.read_csv(OUT_PATH)
            df = pd.concat([old, df], ignore_index=True)
            df = df.drop_duplicates(subset=["date"], keep="last")
        df.to_csv(OUT_PATH, index=False)
        print(f"Weather saved: {len(df)} rows -> {OUT_PATH}")
        return df
    except Exception as e:
        print(f"Weather fetch failed: {e}")
        return pd.DataFrame()


if __name__ == "__main__":
    fetch_weather()
