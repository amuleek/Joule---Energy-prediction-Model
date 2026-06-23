"""
Hurricane tracking (NHC) and freight/shipping proxy (BDRY ETF).
Saves data/hurricane.json and data/freight.csv with timestamps.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd
import requests

NHC_URL = "https://www.nhc.noaa.gov/CurrentStorms.json"
HURRICANE_PATH = "data/hurricane.json"
FREIGHT_PATH = "data/freight.csv"
# Baltic Dry proxy: Breakwave Dry Bulk Shipping ETF
FREIGHT_TICKER = "BDRY"


def fetch_nhc_storms() -> Dict[str, Any]:
    print("Fetching NHC active storm data...")
    payload: Dict[str, Any] = {
        "fetched_at": datetime.now().isoformat(),
        "active_storm_count": 0,
        "gulf_threat_count": 0,
        "storms": [],
        "risk_score": 0.0,
    }
    try:
        r = requests.get(NHC_URL, timeout=15, headers={"User-Agent": "GillEnergyAI/1.0"})
        r.raise_for_status()
        data = r.json()
        storms = []
        gulf_kws = ("gulf", "caribbean", "atlantic", "florida", "texas", "louisiana")
        for sid, storm in (data.get("activeStorms") or {}).items():
            if not isinstance(storm, dict):
                continue
            name = storm.get("name", sid)
            basin = str(storm.get("basin", "")).upper()
            classification = storm.get("classification", "")
            lat = storm.get("latitude")
            lon = storm.get("longitude")
            movement = storm.get("movementDir", "")
            storms.append({
                "id": sid,
                "name": name,
                "basin": basin,
                "classification": classification,
                "latitude": lat,
                "longitude": lon,
                "movement": movement,
            })
        payload["storms"] = storms
        payload["active_storm_count"] = len(storms)
        gulf = 0
        for s in storms:
            blob = f"{s.get('name','')} {s.get('basin','')} {s.get('classification','')}".lower()
            if any(k in blob for k in gulf_kws) or s.get("basin") in ("AL", "CP", "EP"):
                if "hurricane" in str(s.get("classification", "")).lower() or "storm" in str(s.get("classification", "")).lower():
                    gulf += 1
        payload["gulf_threat_count"] = gulf
        payload["risk_score"] = round(min(1.0, len(storms) * 0.15 + gulf * 0.25), 3)
        os.makedirs("data", exist_ok=True)
        with open(HURRICANE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"  Active storms: {len(storms)}, Gulf/Atlantic threats: {gulf}, risk={payload['risk_score']}")
    except Exception as e:
        print(f"  NHC fetch failed: {e}")
    return payload


def fetch_freight_proxy(period: str = "1y") -> pd.DataFrame:
    print(f"Fetching freight proxy ({FREIGHT_TICKER})...")
    try:
        import yfinance as yf
    except ImportError:
        print("  yfinance not installed")
        return pd.DataFrame()

    try:
        h = yf.Ticker(FREIGHT_TICKER).history(period=period, interval="1d", auto_adjust=True)
        if h is None or h.empty:
            print("  No freight data returned")
            return pd.DataFrame()
        h = h.reset_index()
        if "Date" in h.columns:
            h = h.rename(columns={"Date": "date"})
        h["date"] = pd.to_datetime(h["date"], errors="coerce").dt.tz_localize(None).dt.normalize()
        df = pd.DataFrame({
            "date": h["date"].dt.strftime("%Y-%m-%d"),
            "baltic_dry_proxy": pd.to_numeric(h["Close"], errors="coerce"),
            "freight_volume": pd.to_numeric(h.get("Volume"), errors="coerce"),
        })
        df["freight_return_1d"] = df["baltic_dry_proxy"].pct_change()
        os.makedirs("data", exist_ok=True)
        if os.path.exists(FREIGHT_PATH):
            old = pd.read_csv(FREIGHT_PATH)
            df = pd.concat([old, df], ignore_index=True).drop_duplicates(subset=["date"], keep="last")
        df = df.sort_values("date")
        df.to_csv(FREIGHT_PATH, index=False)
        print(f"  Freight proxy saved: {len(df)} rows, latest=${df['baltic_dry_proxy'].iloc[-1]:.2f}")
        return df
    except Exception as e:
        print(f"  Freight fetch failed: {e}")
        return pd.DataFrame()


def latest_hurricane_snapshot() -> Dict[str, Any]:
    if not os.path.exists(HURRICANE_PATH):
        return {"active_storm_count": 0, "gulf_threat_count": 0, "risk_score": 0.0, "storms": []}
    try:
        with open(HURRICANE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"active_storm_count": 0, "risk_score": 0.0}


def save_hurricane_and_freight() -> None:
    fetch_nhc_storms()
    fetch_freight_proxy()


if __name__ == "__main__":
    save_hurricane_and_freight()
