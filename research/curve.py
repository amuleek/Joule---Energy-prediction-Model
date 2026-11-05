"""
Futures curve (contracts 1-4) and roll-adjusted front-month returns.

History: EIA daily NYMEX settlements for contracts 1-4 (CL, RBOB, HO), which EIA
published through 2024-04-05. Live: Yahoo quotes for the active contract months.

Why roll adjustment matters
  A continuous "front month" series (e.g. Yahoo RB=F) jumps on roll days from the
  expiring contract to the next one. Those jumps are a spread between two contracts,
  not a price move. RBOB's spring/autumn grade switch makes the jump large and
  seasonal, so a model can "predict" it from the calendar without any tradable edge.
  Roll-adjusted returns compare each day's price to the *same* contract's prior price.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import requests

EIA_FUT_SERIES = {
    "crude": [f"RCLC{i}" for i in range(1, 5)],
    "rbob": [f"EER_EPMRR_PE{i}_Y35NY_DPG" for i in range(1, 5)],
    "ulsd": [f"EER_EPD2F_PE{i}_Y35NY_DPG" for i in range(1, 5)],
}
# Calendar windows (day of month) where the EIA "contract 1" can roll
ROLL_WINDOW = {"crude": range(16, 28), "rbob": range(1, 5), "ulsd": range(1, 5)}


def _eia_daily(series_id: str, api_key: str, start: str) -> pd.Series:
    url = "https://api.eia.gov/v2/petroleum/pri/fut/data/"
    rows, offset = [], 0
    while True:
        params = {
            "api_key": api_key, "frequency": "daily", "data[0]": "value",
            "facets[series][]": series_id, "start": start,
            "sort[0][column]": "period", "sort[0][direction]": "asc",
            "offset": offset, "length": 5000,
        }
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()["response"]["data"]
        rows += data
        if len(data) < 5000:
            break
        offset += 5000
    return pd.Series({pd.Timestamp(d["period"]): float(d["value"])
                      for d in rows if d.get("value") not in (None, "")}).sort_index()


def fetch_curve(api_key: str, start: str = "2005-10-01") -> dict[str, pd.DataFrame]:
    """{product: DataFrame[c1..c4]} of daily settlements."""
    out = {}
    for prod, ids in EIA_FUT_SERIES.items():
        cols = {f"c{i + 1}": _eia_daily(sid, api_key, start) for i, sid in enumerate(ids)}
        df = pd.DataFrame(cols).sort_index()
        df = df[(df > 0).all(axis=1)]  # drop gaps / the Apr-2020 negative print
        out[prod] = df
    return out


def _expiry_dates(product: str, start: pd.Timestamp, end: pd.Timestamp,
                  trading_days: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """NYMEX last-trade dates, using the actual trading calendar in the data.

    RBOB / HO: last business day of the month before delivery.
    WTI: 3 business days before the 25th (or before the last business day
         preceding the 25th when the 25th is not a business day).
    """
    days = pd.DatetimeIndex(trading_days)
    out = []
    for m in pd.period_range(start, end, freq="M"):
        in_month = days[(days.year == m.year) & (days.month == m.month)]
        if len(in_month) == 0:
            continue
        if product == "crude":
            d25 = pd.Timestamp(m.year, m.month, 25)
            on_or_before = in_month[in_month <= d25]
            if len(on_or_before) == 0:
                continue
            # anchor = the 25th, or the last business day before it; then 3 business days back
            k = len(on_or_before) - 1 - 3
            if k >= 0:
                out.append(on_or_before[k])
        else:
            out.append(in_month[-1])
    return out


def detect_rolls(curve: pd.DataFrame, product: str) -> pd.Series:
    """Boolean Series: True on the first trading day after a contract-1 expiry,
    i.e. when EIA's contract 1 switches to the next delivery month."""
    idx = curve.index
    expiries = _expiry_dates(product, idx.min(), idx.max(), idx)
    pos = idx.searchsorted(pd.DatetimeIndex(expiries), side="right")
    flag = pd.Series(False, index=idx)
    flag.iloc[[p for p in pos if 0 < p < len(idx)]] = True
    return flag


def roll_adjusted_index(curve: pd.DataFrame, product: str) -> tuple[pd.Series, pd.Series]:
    """Return (index, roll_flag). Index ends at the last c1 price; daily log changes
    never include a roll gap."""
    rolls = detect_rolls(curve, product)
    lc = np.log(curve)
    r = lc["c1"] - lc["c1"].shift()
    r[rolls] = (lc["c1"] - lc["c2"].shift())[rolls]
    r = r.fillna(0.0)
    idx = np.exp(r.cumsum() - r.sum()) * curve["c1"].iloc[-1]
    return idx, rolls.astype(float)


def curve_features(curves: dict[str, pd.DataFrame], index: pd.DatetimeIndex) -> pd.DataFrame:
    f = pd.DataFrame(index=index)
    for prod, c in curves.items():
        c = c.reindex(index).ffill()
        slope1 = np.log(c["c2"] / c["c1"]) * 100   # >0 contango, <0 backwardation
        slope3 = np.log(c["c4"] / c["c1"]) * 100 / 3
        f[f"{prod}_slope1"] = slope1
        f[f"{prod}_slope3"] = slope3
        f[f"{prod}_curvature"] = slope1 - slope3
        f[f"{prod}_slope3_chg5"] = slope3.diff(5)
        f[f"{prod}_slope3_z120"] = (slope3 - slope3.rolling(120).mean()) / slope3.rolling(120).std()
    return f


# --------------------------------------------------------------------------- live
MONTH_CODES = "FGHJKMNQUVXZ"
YAHOO_ROOT = {"crude": "CL", "rbob": "RB", "ulsd": "HO"}


def fetch_live_curve(asof: pd.Timestamp | None = None, n: int = 4) -> pd.DataFrame:
    """Latest settlements for the first n listed contracts of each product (Yahoo).

    Yahoo only lists contracts that are still trading, so expired months simply
    return nothing and the next ones become c1, c2, ...
    Returns DataFrame index=product, columns c1..cn plus the contract symbols.
    """
    import yfinance as yf

    asof = pd.Timestamp(asof or pd.Timestamp.today()).normalize()
    months = pd.period_range(asof, periods=n + 3, freq="M")
    rows = {}
    for prod, root in YAHOO_ROOT.items():
        syms = [f"{root}{MONTH_CODES[m.month - 1]}{str(m.year)[-2:]}.NYM" for m in months]
        raw = yf.download(syms, period="10d", progress=False, auto_adjust=False)["Close"]
        last = raw.ffill().iloc[-1].dropna()
        live = [s for s in syms if s in last.index][:n]  # keeps calendar order
        row = {f"c{i + 1}": float(last[s]) for i, s in enumerate(live)}
        row.update({f"sym{i + 1}": s for i, s in enumerate(live)})
        rows[prod] = row
    return pd.DataFrame(rows).T
