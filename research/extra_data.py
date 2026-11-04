"""
Extra free data sources for the research dataset.

OVX  (CBOE Crude Oil Volatility Index, Yahoo ^OVX, 2007+)
  30-day implied volatility of USO options, in annualized %. Known on the same day.
  Features: level, 5-day change, 60-day z-score, implied/realized ratio.

CFTC Commitments of Traders, disaggregated futures-only (publicreporting.cftc.gov)
  Positions as of Tuesday, published Friday 15:30 ET (after the NYMEX settle), so a
  report is usable for the Friday-close forecast onward: available = report date + 3 days.
  Features per product: managed-money net % of open interest, its weekly change and
  3-year z-score; producer/merchant (commercial) net % of open interest and z-score.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import requests
import yfinance as yf

COT_URL = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
COT_CODES = {"crude": "067651", "rbob": "111659", "ulsd": "022651"}
COT_RELEASE_LAG_DAYS = 3  # Tuesday positions -> Friday release


def fetch_ovx(start: str = "2006-01-01") -> pd.Series:
    s = yf.download("^OVX", start=start, progress=False, auto_adjust=False)["Close"]
    s = s.iloc[:, 0] if isinstance(s, pd.DataFrame) else s
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s.rename("ovx").dropna()


def ovx_features(ovx: pd.Series, index: pd.DatetimeIndex, crude_r1: pd.Series) -> pd.DataFrame:
    o = ovx.reindex(index).ffill(limit=3)
    f = pd.DataFrame(index=index)
    f["ovx"] = o
    f["ovx_chg5"] = o.diff(5)
    f["ovx_z60"] = (o - o.rolling(60).mean()) / o.rolling(60).std()
    realized = crude_r1.rolling(20).std() * np.sqrt(252) * 100
    f["ovx_vs_realized"] = o / realized  # >1: options price more risk than recent moves
    return f


def fetch_cot(product: str) -> pd.DataFrame:
    cols = ["report_date_as_yyyy_mm_dd", "open_interest_all",
            "m_money_positions_long_all", "m_money_positions_short_all",
            "prod_merc_positions_long", "prod_merc_positions_short"]
    r = requests.get(COT_URL, params={
        "cftc_contract_market_code": COT_CODES[product],
        "$select": ",".join(cols),
        "$order": "report_date_as_yyyy_mm_dd",
        "$limit": 50000,
    }, timeout=120)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    df["date"] = pd.to_datetime(df.pop("report_date_as_yyyy_mm_dd"))
    df = df.set_index("date").apply(pd.to_numeric, errors="coerce").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


def cot_features(cot: dict[str, pd.DataFrame], index: pd.DatetimeIndex) -> pd.DataFrame:
    f = pd.DataFrame(index=index)
    for prod, df in cot.items():
        oi = df["open_interest_all"]
        mm = (df["m_money_positions_long_all"] - df["m_money_positions_short_all"]) / oi * 100
        pm = (df["prod_merc_positions_long"] - df["prod_merc_positions_short"]) / oi * 100
        w = pd.DataFrame({
            f"{prod}_mm_net_pct": mm,
            f"{prod}_mm_net_chg1w": mm.diff(),
            f"{prod}_mm_net_z156": (mm - mm.rolling(156, min_periods=52).mean())
                                   / mm.rolling(156, min_periods=52).std(),
            f"{prod}_comm_net_pct": pm,
            f"{prod}_comm_net_z156": (pm - pm.rolling(156, min_periods=52).mean())
                                     / pm.rolling(156, min_periods=52).std(),
        })
        w.index = w.index + pd.Timedelta(days=COT_RELEASE_LAG_DAYS)  # date it became public
        aligned = w.reindex(w.index.union(index)).ffill().reindex(index)
        f = f.join(aligned)
    return f
