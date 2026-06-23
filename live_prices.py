"""
NYMEX session closes for spot display and prices.csv.
Uses the last completed afternoon settlement — not intraday live quotes.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

import pandas as pd

SESSION_SETTLES_PATH = "data/session_settles.json"
REQUIRED_SETTLE_COLS = ("RBOB", "ULSD", "Crude")

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore

FUTURES_CLOSE_COLS = {
    "rbob_close": "RBOB",
    "diesel_close": "ULSD",
    "crude_close": "Crude",
}

PRODUCT_COL_MAP = {
    "RBOB_Gasoline": "RBOB",
    "ULSD_Diesel": "ULSD",
    "Crude_Oil": "Crude",
}

# Minimum daily volume to treat a futures row as a full NYMEX session (not partial/intraday)
MIN_SESSION_VOLUME = {
    "rbob_volume": 5_000,
    "crude_volume": 50_000,
    "diesel_volume": 3_000,
}

# NYMEX energy futures settle ~2:30 PM ET; use 3:07 PM ET when today's close is available
SETTLE_HOUR_ET = 15
SETTLE_MINUTE_ET = 7


def _now_et() -> datetime:
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo("US/Eastern"))
    return datetime.now()


def _closes_from_row(row: pd.Series) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for fut_col, price_col in FUTURES_CLOSE_COLS.items():
        if fut_col in row.index and pd.notna(row[fut_col]):
            val = float(row[fut_col])
            if val > 0:
                out[price_col] = val
    return out


PRODUCT_KEY_MAP = {price_col: prod_key for prod_key, price_col in PRODUCT_COL_MAP.items()}


def _row_has_valid_closes(row: pd.Series) -> bool:
    return len(_closes_from_row(row)) >= 2


def _row_is_full_session(row: pd.Series) -> bool:
    """True when row looks like a completed NYMEX afternoon session (not a thin intraday print)."""
    closes = _closes_from_row(row)
    if len(closes) < 2:
        return False
    for vol_col, minimum in MIN_SESSION_VOLUME.items():
        if vol_col not in row.index:
            continue
        val = row.get(vol_col)
        if pd.isna(val) or float(val) < minimum:
            return False
    return True


def _load_futures_df(futures_path: str = "data/futures_ohlc.csv") -> pd.DataFrame:
    if not os.path.exists(futures_path):
        return pd.DataFrame()
    df = pd.read_csv(futures_path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.dropna(subset=["date"]).sort_values("date")


def _last_completed_settle_date(now_et: datetime):
    """Most recent NYMEX session whose official close we should anchor to."""
    d = now_et.date()
    if not _session_closed_for_date(d, now_et):
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return d


def _load_session_settle_cache(path: str = SESSION_SETTLES_PATH) -> Dict[str, Dict[str, Any]]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_session_settle_cache(
    settle_date: str,
    closes: Dict[str, float],
    meta: Optional[Dict[str, Any]] = None,
    path: str = SESSION_SETTLES_PATH,
) -> None:
    if not settle_date or not closes:
        return
    cache = _load_session_settle_cache(path)
    cache[settle_date] = {
        "closes": {k: float(v) for k, v in closes.items() if k in REQUIRED_SETTLE_COLS},
        "meta": meta or {},
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    os.makedirs(os.path.dirname(path) or "data", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def _cached_settles_for_date(settle_date: str) -> Tuple[Dict[str, float], str]:
    row = _load_session_settle_cache().get(settle_date) or {}
    closes = row.get("closes") or {}
    closes = {k: float(v) for k, v in closes.items() if k in REQUIRED_SETTLE_COLS and float(v) > 0}
    if len(closes) < len(REQUIRED_SETTLE_COLS):
        return {}, ""
    label = (row.get("meta") or {}).get("label") or f"Barchart settle cached ({settle_date})"
    return closes, label


def _session_closed_for_date(session_date, now_et: datetime) -> bool:
    """True if NYMEX has finished the session for session_date."""
    if session_date < now_et.date():
        return True
    if session_date > now_et.date():
        return False
    if now_et.weekday() >= 5:
        return False
    return now_et.hour > SETTLE_HOUR_ET or (
        now_et.hour == SETTLE_HOUR_ET and now_et.minute >= SETTLE_MINUTE_ET
    )


def refresh_today_futures_row(futures_path: str = "data/futures_ohlc.csv") -> bool:
    """Pull the latest Yahoo daily bar for today after NYMEX settle (volume may lag)."""
    now_et = _now_et()
    today = now_et.date()
    if now_et.weekday() >= 5 or not _session_closed_for_date(today, now_et):
        return False
    try:
        from config import FUTURES_SYMBOLS
        from scripts.fetch_futures_ohlc import fetch_symbol_history
    except ImportError:
        return False

    yahoo_cols = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }
    today_str = today.strftime("%Y-%m-%d")
    row_data: Dict[str, Any] = {"date": today_str}

    for prefix, ticker in FUTURES_SYMBOLS.items():
        if prefix not in ("rbob", "crude", "diesel"):
            continue
        hist = fetch_symbol_history(ticker, period="5d")
        if hist is None or hist.empty:
            continue
        day = hist[hist["date"].dt.date == today]
        if day.empty:
            continue
        bar = day.iloc[-1]
        for out_suffix, src in yahoo_cols.items():
            if src in bar.index and pd.notna(bar[src]):
                row_data[f"{prefix}_{out_suffix}"] = float(bar[src])

    probe = pd.Series(row_data)
    if not _row_has_valid_closes(probe):
        return False

    os.makedirs(os.path.dirname(futures_path) or "data", exist_ok=True)
    if os.path.exists(futures_path):
        df = pd.read_csv(futures_path)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        mask = df["date"].dt.strftime("%Y-%m-%d") == today_str
        if mask.any():
            idx = df.index[mask][-1]
            for k, v in row_data.items():
                if k != "date":
                    df.at[idx, k] = v
        else:
            df = pd.concat([df, pd.DataFrame([row_data])], ignore_index=True)
    else:
        df = pd.DataFrame([row_data])

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.sort_values("date")
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    df.to_csv(futures_path, index=False)
    return True


def _write_settle_to_futures_csv(
    closes: Dict[str, float],
    settle_date: str,
    futures_path: str = "data/futures_ohlc.csv",
) -> None:
    """Persist settlement closes into futures_ohlc.csv on the session date row."""
    if not closes or not settle_date:
        return
    col_to_prefix = {"RBOB": "rbob", "ULSD": "diesel", "Crude": "crude"}
    row_data: Dict[str, Any] = {"date": settle_date}
    for price_col, prefix in col_to_prefix.items():
        if price_col in closes:
            row_data[f"{prefix}_close"] = float(closes[price_col])

    os.makedirs(os.path.dirname(futures_path) or "data", exist_ok=True)
    if os.path.exists(futures_path):
        df = pd.read_csv(futures_path)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        mask = df["date"].dt.strftime("%Y-%m-%d") == settle_date
        if mask.any():
            idx = df.index[mask][-1]
            for k, v in row_data.items():
                if k != "date":
                    df.at[idx, k] = v
        else:
            df = pd.concat([df, pd.DataFrame([row_data])], ignore_index=True)
    else:
        df = pd.DataFrame([row_data])

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.sort_values("date")
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    df.to_csv(futures_path, index=False)


def _fetch_barchart_session_close(
    futures_path: str,
    settle_date,
) -> Tuple[Dict[str, float], str, str, Dict[str, Any]]:
    """Official front-month settlement from Barchart — never Yahoo."""
    try:
        from scripts.fetch_barchart_settle import fetch_barchart_settlement_closes

        closes, as_of, bc_meta = fetch_barchart_settlement_closes()
        if len(closes) < len(REQUIRED_SETTLE_COLS):
            return {}, "", "", bc_meta if isinstance(bc_meta, dict) else {}
        if not all(k in closes for k in REQUIRED_SETTLE_COLS):
            return {}, "", "", bc_meta if isinstance(bc_meta, dict) else {}
        d = as_of or settle_date.strftime("%Y-%m-%d")
        label = f"Barchart settle ({d})"
        bc_meta = dict(bc_meta or {})
        bc_meta["label"] = label
        bc_meta["source"] = "barchart"
        _write_settle_to_futures_csv(closes, d, futures_path)
        _save_session_settle_cache(d, closes, bc_meta)
        return closes, d, label, bc_meta
    except Exception:
        return {}, "", "", {}


def get_nymex_session_close(
    futures_path: str = "data/futures_ohlc.csv",
) -> Tuple[Dict[str, float], str, str]:
    """
    Last completed NYMEX afternoon settlement close — Barchart only (never Yahoo).

    Returns:
        closes: {RBOB, ULSD, Crude}
        as_of_date: YYYY-MM-DD of the settlement session
        label: human-readable source label for emails
    """
    now_et = _now_et()
    target = _last_completed_settle_date(now_et)
    target_str = target.strftime("%Y-%m-%d")

    # After 3:07 PM ET on a weekday: pull fresh Barchart settlement for today
    if (
        target == now_et.date()
        and _session_closed_for_date(target, now_et)
        and now_et.weekday() < 5
    ):
        bc_closes, bc_date, bc_label, _meta = _fetch_barchart_session_close(futures_path, target)
        if bc_closes:
            return bc_closes, bc_date, bc_label

    # Before today's close is final, or live scrape failed: use cached Barchart settle
    cached, cached_label = _cached_settles_for_date(target_str)
    if cached:
        return cached, target_str, cached_label

    # Last resort: most recent cached Barchart session (still never Yahoo)
    cache = _load_session_settle_cache()
    for date_key in sorted(cache.keys(), reverse=True):
        cached, cached_label = _cached_settles_for_date(date_key)
        if cached:
            return cached, date_key, cached_label

    return {}, "", ""


def session_close_by_product(
    futures_path: str = "data/futures_ohlc.csv",
) -> Tuple[Dict[str, float], Dict[str, str]]:
    """Map session closes to prediction product keys + reference metadata."""
    closes, as_of, label = get_nymex_session_close(futures_path)
    by_product = {
        PRODUCT_KEY_MAP[col]: price
        for col, price in closes.items()
        if col in PRODUCT_KEY_MAP
    }
    source = "barchart" if label.lower().startswith("barchart") else "barchart_cache"
    meta = {
        "as_of_date": as_of,
        "label": label,
        "source": source,
        "session": "NYMEX afternoon settle",
        "closes": closes,
        "by_product": by_product,
    }
    return by_product, meta


def patch_final_data_session_closes(
    session_prices: Dict[str, float],
    settle_date: str,
    path: str = "data/final_data.csv",
) -> None:
    """Align model input row with NYMEX afternoon settlement prices."""
    if not session_prices or not settle_date or not os.path.exists(path):
        return
    try:
        df = pd.read_csv(path)
        if df.empty or "date" not in df.columns:
            return
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        settle = pd.to_datetime(settle_date)
        mask = df["date"].dt.normalize() == settle.normalize()
        if not mask.any():
            mask = pd.Series(False, index=df.index)
            mask.iloc[-1] = True
        fut_map = {
            "RBOB_Gasoline": "rbob_close",
            "ULSD_Diesel": "diesel_close",
            "Crude_Oil": "crude_close",
        }
        for product_key, col in PRODUCT_COL_MAP.items():
            if col in df.columns and product_key in session_prices:
                price = float(session_prices[product_key])
                df.loc[mask, col] = price
                fut_col = fut_map.get(product_key)
                if fut_col in df.columns:
                    df.loc[mask, fut_col] = price
        df.to_csv(path, index=False)
    except Exception:
        pass


def apply_session_close_baseline(
    predictions: Dict[str, Any],
    session_prices: Dict[str, float],
) -> Dict[str, Any]:
    """Re-anchor forecast levels and % moves to NYMEX afternoon session close."""
    from forecast_horizons import PREDICTION_HORIZONS, max_frac_for

    for product_key, block in predictions.items():
        if not isinstance(block, dict) or product_key.startswith("_"):
            continue
        spot = session_prices.get(product_key)
        if not spot or spot <= 0:
            continue
        old_current = float(block.get("current_price") or spot)
        block["current_price"] = float(spot)

        for hkey, _days, _max_frac, _label in PREDICTION_HORIZONS:
            chg_key = f"{hkey}_change"
            ret_pct = block.get(chg_key)
            if ret_pct is None and old_current > 0:
                old_p = block.get(hkey, block.get(hkey.replace("day_", "")))
                if old_p is not None:
                    try:
                        old_p = float(old_p)
                        if old_p > 0:
                            ret_pct = (old_p - old_current) / old_current * 100.0
                    except (TypeError, ValueError):
                        ret_pct = None
            if ret_pct is None:
                continue
            cap = max_frac_for(hkey, product_key) * 100.0
            ret_pct = max(-cap, min(cap, float(ret_pct)))
            new_p = spot * (1.0 + ret_pct / 100.0)
            block[hkey] = float(new_p)
            if hkey == "day_1":
                block["next_day"] = float(new_p)
            elif hkey == "day_4":
                block["next_week"] = float(new_p)
            elif hkey == "day_7":
                block["biweekly"] = float(new_p)
                block["monthly"] = float(new_p)
            block[chg_key] = float(ret_pct)
            direction = "UP" if ret_pct > 0.08 else "DOWN" if ret_pct < -0.08 else "FLAT"
            block[f"{hkey}_direction"] = direction
            if hkey == "day_1":
                block["next_day_change"] = float(ret_pct)
                block["next_day_direction"] = direction

    return predictions


def fetch_live_futures_closes() -> Dict[str, float]:
    """Intraday/latest quote from Yahoo (not used for email spot)."""
    try:
        from config import FUTURES_SYMBOLS
        from scripts.fetch_futures_ohlc import fetch_symbol_history
    except ImportError:
        return {}

    prefix_map = {"rbob": "RBOB", "crude": "Crude", "diesel": "ULSD"}
    out: Dict[str, float] = {}
    for prefix, col in prefix_map.items():
        ticker = FUTURES_SYMBOLS.get(prefix)
        if not ticker:
            continue
        hist = fetch_symbol_history(ticker, period="5d")
        if hist is None or hist.empty or "Close" not in hist.columns:
            continue
        val = float(hist["Close"].iloc[-1])
        if val > 0:
            out[col] = val
    return out


def latest_futures_closes(
    futures_path: str = "data/futures_ohlc.csv",
    *,
    prefer_live: bool = False,
    use_session_close: bool = True,
) -> Dict[str, float]:
    """
    Default: last completed NYMEX afternoon close from Barchart settlement.
    Set prefer_live=True only for intraday diagnostics (Yahoo — not for email spot).
    """
    if use_session_close and not prefer_live:
        closes, _, _ = get_nymex_session_close(futures_path)
        return closes

    if prefer_live:
        return fetch_live_futures_closes()

    return {}


def latest_futures_by_product(
    futures_path: str = "data/futures_ohlc.csv",
    *,
    prefer_live: bool = False,
    use_session_close: bool = True,
) -> Dict[str, float]:
    """Map closes to product keys (session settle by default)."""
    closes = latest_futures_closes(
        futures_path,
        prefer_live=prefer_live,
        use_session_close=use_session_close,
    )
    return {
        PRODUCT_KEY_MAP[col]: price
        for col, price in closes.items()
        if col in PRODUCT_KEY_MAP
    }


def sync_prices_csv_from_futures(
    closes: Optional[Dict[str, float]] = None,
    prices_path: str = "data/prices.csv",
    *,
    as_of_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    Write session closes into prices.csv on the settlement date row.
    """
    if closes is None:
        closes, as_of_date, _ = get_nymex_session_close()
    if not closes:
        if os.path.exists(prices_path):
            return pd.read_csv(prices_path)
        return pd.DataFrame()

    row_date = as_of_date or datetime.now().strftime("%Y-%m-%d")
    row = {
        "date": row_date,
        "RBOB": closes.get("RBOB"),
        "ULSD": closes.get("ULSD"),
        "Crude": closes.get("Crude"),
    }

    if os.path.exists(prices_path):
        try:
            df = pd.read_csv(prices_path)
            df = df.dropna(subset=["date"], how="any")
            if row_date in df["date"].astype(str).values:
                idx = df["date"].astype(str) == row_date
                for col in ("RBOB", "ULSD", "Crude"):
                    if row.get(col) is not None:
                        df.loc[idx, col] = row[col]
            else:
                df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        except Exception:
            df = pd.DataFrame([row])
    else:
        df = pd.DataFrame([row])

    df = df.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    os.makedirs(os.path.dirname(prices_path) or "data", exist_ok=True)
    df.to_csv(prices_path, index=False)
    return df
