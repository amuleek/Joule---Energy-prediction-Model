"""
NYMEX session closes for spot display and prices.csv.
Uses the last completed afternoon settlement — not intraday live quotes.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

SESSION_SETTLES_PATH = "data/session_settles.json"
REQUIRED_SETTLE_COLS = ("RBOB", "ULSD", "Crude")
CONTINUOUS_YAHOO = frozenset({"RB=F", "HO=F", "CL=F", "BZ=F", "NG=F"})
# Reject a settle if it matches continuous within this band (wrong-month roll)
CONTINUOUS_MATCH_PCT = 0.015
# Prefer named front over cached value when they diverge by more than this
NAMED_MONTH_REPLACE_PCT = 0.012

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

# When Barchart settle vs session close exceeds this, the scrape is stale (big crude days).
STALE_BARCHART_SETTLE_GAP_PCT = 2.4
# Between min and stale gap: Barchart settle is official NYMEX settlement (≠ last trade).
OFFICIAL_SETTLE_MIN_GAP_PCT = 0.8

PREFIX_TO_SETTLE_COL = {"rbob": "RBOB", "crude": "Crude", "diesel": "ULSD"}
COL_TO_PREFIX = {v: k for k, v in PREFIX_TO_SETTLE_COL.items()}

# Calendar days between consecutive settle rows above this → weekend/holiday gap
MAX_SESSION_GAP_DAYS = 1

# NYMEX official settle window (ET) — after this, today's session is complete
SETTLE_HOUR_ET = 15
SETTLE_MINUTE_ET = 7

# Settle trust for scoring / calendar actuals (never infer from futures_ohlc OHLC or returns).
TRUSTED_SETTLE_SOURCES = frozenset({"verified", "nymex_official", "barchart"})
# Sources allowed in prediction emails (Yahoo daily last is NOT official settle).
PUBLISHABLE_SETTLE_SOURCES = frozenset(
    {"verified", "nymex_official", "barchart", "yahoo_settle_vwap"}
)
# NYMEX energy settle window used for CME Globex VWAP (ET)
SETTLE_VWAP_START = "14:28"
SETTLE_VWAP_END = "14:30"
MIN_SETTLE_VWAP_BARS = 2


def _settle_trust_level(meta: Optional[Dict[str, Any]]) -> int:
    """
    3 = Gill-verified manual settle
    2 = Barchart / NYMEX official / Yahoo 14:28–14:30 named-month VWAP
    1 = Yahoo daily last / history backfill (last≠settle — models only, never email)
    0 = untrusted OHLC-guess labels — ignore
    """
    meta = meta or {}
    src = str(meta.get("source") or "")
    label = str(meta.get("label") or "").lower()
    if "ohlc-validated" in label and "repaired" in label:
        return 0
    if src == "verified":
        return 3
    if src == "yahoo_settle_vwap":
        return 2
    # Yahoo daily Close is after-hours last, not NYMEX official settle
    if src in ("yahoo_history_backfill", "yahoo_named_month"):
        return 1
    if src in TRUSTED_SETTLE_SOURCES:
        reconcile = meta.get("reconcile") or {}
        picks = reconcile.get("picks") or {}
        if picks:
            methods = [
                p.get("method")
                for p in picks.values()
                if isinstance(p, dict) and p.get("method")
            ]
            reasons = [
                str(p.get("reason") or "")
                for p in picks.values()
                if isinstance(p, dict)
            ]
            if any("stale_barchart" in r for r in reasons):
                # Replaced with Yahoo daily — not publishable as official
                return 1
            if methods and all(m == "nymex_settle" for m in methods):
                return 2
            if any(m == "nymex_settle" for m in methods):
                return 2
            if any(m == "session_close" for m in methods):
                return 1
        return 2
    return 0


def _is_verified_settle(settle_date: str) -> bool:
    row = _load_session_settle_cache().get(settle_date) or {}
    return _settle_trust_level(row.get("meta")) >= 3


def _is_trusted_settle(settle_date: str, min_trust: int = 2) -> bool:
    row = _load_session_settle_cache().get(settle_date) or {}
    closes = row.get("closes") or {}
    if len(closes) < len(REQUIRED_SETTLE_COLS):
        return False
    return _settle_trust_level(row.get("meta")) >= min_trust


def is_publishable_settle(
    settle_date: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    True only when closes are safe to put in a prediction email.
    Yahoo named-month daily last is never publishable (last ≠ official settle).
    """
    if meta is None and settle_date:
        row = _load_session_settle_cache().get(str(settle_date)[:10]) or {}
        meta = row.get("meta") or {}
        closes = row.get("closes") or {}
        if len(closes) < len(REQUIRED_SETTLE_COLS):
            return False
    meta = meta or {}
    src = str(meta.get("source") or "")
    if src not in PUBLISHABLE_SETTLE_SOURCES:
        return False
    return _settle_trust_level(meta) >= 2


def trading_session_dates(history: Optional[pd.DataFrame] = None) -> List[pd.Timestamp]:
    """Sorted NYMEX session dates from official settle history (weekdays only)."""
    hist = history if history is not None else load_official_price_history()
    if hist.empty or "date" not in hist.columns:
        return []
    sub = hist.copy()
    sub["date"] = pd.to_datetime(sub["date"], errors="coerce")
    mask = pd.Series(False, index=sub.index)
    for col in REQUIRED_SETTLE_COLS:
        if col in sub.columns:
            mask = mask | sub[col].notna()
    sub = sub.loc[mask]
    # NYMEX RBOB/HO/CL afternoon settles are Mon–Fri only — drop weekend Globex labels
    dates = sorted(sub["date"].dt.normalize().dropna().unique().tolist())
    return [d for d in dates if pd.Timestamp(d).weekday() < 5]


def trading_session_offset(
    anchor: pd.Timestamp,
    sessions_ahead: int,
    history: Optional[pd.DataFrame] = None,
) -> Optional[pd.Timestamp]:
    """Nth trading session after anchor (day_1 = next session, not calendar tomorrow)."""
    sessions = trading_session_dates(history)
    if not sessions or sessions_ahead < 1:
        return None
    anchor = pd.Timestamp(anchor).normalize()
    idx = 0
    for i, d in enumerate(sessions):
        if d <= anchor:
            idx = i
    target_idx = idx + sessions_ahead
    if target_idx >= len(sessions):
        return None
    return sessions[target_idx]


def calendar_gap_between_sessions(history: Optional[pd.DataFrame] = None) -> int:
    """Calendar days between the last two settle rows (0/1 = normal, 3+ = weekend/holiday)."""
    sessions = trading_session_dates(history)
    if len(sessions) < 2:
        return 0
    return int((sessions[-1] - sessions[-2]).days)


def is_weekend_gap_session(history: Optional[pd.DataFrame] = None) -> bool:
    return calendar_gap_between_sessions(history) > MAX_SESSION_GAP_DAYS


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
    meta = dict(meta or {})
    cache = _load_session_settle_cache(path)
    existing = cache.get(settle_date) or {}
    old_level = _settle_trust_level(existing.get("meta"))
    new_level = _settle_trust_level(meta)

    # Never overwrite Gill-verified settles with Yahoo/scrape.
    if old_level >= 3 and new_level < 3:
        return
    # Never overwrite publishable VWAP/Barchart with Yahoo daily last
    old_src = str((existing.get("meta") or {}).get("source") or "")
    if (
        old_level >= 2
        and old_src in PUBLISHABLE_SETTLE_SOURCES
        and new_level < old_level
    ):
        return
    if (
        old_level >= 2
        and old_src in PUBLISHABLE_SETTLE_SOURCES
        and str(meta.get("source") or "") not in PUBLISHABLE_SETTLE_SOURCES
    ):
        return

    coerce_meta: Dict[str, Any] = {"coerced": False}
    src = str(meta.get("source") or "")
    # Do not Yahoo-coerce verified / Barchart / settle-window VWAP — last≠settle.
    skip_coerce = (
        new_level >= 2 and src in PUBLISHABLE_SETTLE_SOURCES
    ) or src == "verified"
    if not skip_coerce and new_level < 3 and src != "verified":
        tickers = meta.get("yahoo_tickers") or {}
        resolved = meta.get("resolved") or {}
        closes, coerce_meta = _coerce_named_month_settles(
            closes, settle_date, tickers=tickers, resolved=resolved
        )
        if coerce_meta.get("coerced"):
            meta["named_month_coercion"] = coerce_meta.get("replacements")
            meta["source"] = "yahoo_named_month"
            meta["trust_level"] = 1
            if "continuous" in str(meta.get("label") or "").lower() or "RB=F" in str(meta):
                meta["label"] = (
                    f"NYMEX ({settle_date}) — named-month daily last (continuous rejected)"
                )
        if coerce_meta.get("yahoo_tickers"):
            meta["yahoo_tickers"] = coerce_meta["yahoo_tickers"]
            rec = dict(meta.get("reconcile") or {})
            rec["yahoo_tickers"] = coerce_meta["yahoo_tickers"]
            rec["yahoo_closes"] = {
                k: closes.get(k) for k in REQUIRED_SETTLE_COLS if closes.get(k)
            }
            meta["reconcile"] = rec
        if coerce_meta.get("resolved"):
            meta["resolved"] = coerce_meta["resolved"]
        new_level = _settle_trust_level(meta)

    if old_level > new_level:
        return
    meta_out = dict(meta or {})
    meta_out["trust_level"] = new_level
    cache[settle_date] = {
        "closes": {k: float(v) for k, v in closes.items() if k in REQUIRED_SETTLE_COLS},
        "meta": meta_out,
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
    """Pull front-month Yahoo O/H/L/V for ML features — never write settle close here."""
    now_et = _now_et()
    today = now_et.date()
    if now_et.weekday() >= 5 or not _session_closed_for_date(today, now_et):
        return False
    try:
        from scripts.fetch_futures_ohlc import fetch_symbol_history
        from scripts.fetch_barchart_settle import fetch_barchart_settlement_closes
    except ImportError:
        return False

    resolved: Dict[str, str] = {}
    try:
        _, _, bc_meta = fetch_barchart_settlement_closes()
        resolved = (bc_meta or {}).get("resolved") or {}
    except Exception:
        pass

    yahoo_cols = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "volume": "Volume",
    }
    today_str = today.strftime("%Y-%m-%d")
    row_data: Dict[str, Any] = {"date": today_str}

    for prefix in ("rbob", "crude", "diesel"):
        ticker = _yahoo_ticker(prefix, resolved)
        if not ticker:
            continue
        hist = fetch_symbol_history(ticker, period="5d")
        if hist is None or hist.empty:
            continue
        day = hist[hist["date"].dt.date == today]
        if day.empty:
            continue
        bar = day.iloc[-1]
        vol_col = f"{prefix}_volume"
        min_vol = MIN_SESSION_VOLUME.get(vol_col, 0)
        if "Volume" in bar.index and pd.notna(bar["Volume"]):
            if float(bar["Volume"]) < min_vol:
                continue
        for out_suffix, src in yahoo_cols.items():
            if src in bar.index and pd.notna(bar[src]):
                row_data[f"{prefix}_{out_suffix}"] = float(bar[src])

    if sum(1 for p in ("rbob", "crude", "diesel") if f"{p}_open" in row_data) < 2:
        return False

    os.makedirs(os.path.dirname(futures_path) or "data", exist_ok=True)
    if os.path.exists(futures_path):
        df = pd.read_csv(futures_path)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        mask = df["date"].dt.strftime("%Y-%m-%d") == today_str
        if mask.any():
            idx = df.index[mask][-1]
            for k, v in row_data.items():
                if k != "date" and not str(k).endswith("_close"):
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


def _is_continuous_yahoo_ticker(ticker: Optional[str]) -> bool:
    t = str(ticker or "").strip().upper()
    if not t:
        return False
    if t in CONTINUOUS_YAHOO:
        return True
    return t.endswith("=F") and ".NYM" not in t


def _coerce_named_month_settles(
    closes: Dict[str, float],
    settle_date: str,
    *,
    tickers: Optional[Dict[str, str]] = None,
    resolved: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """
    Hard gate: RBOB/ULSD settles are always the inferred named-month Yahoo close
    (e.g. RBV26.NYM), never continuous RB=F / HO=F or a stale scrape labeled as named.
    """
    out = {k: float(v) for k, v in (closes or {}).items() if k in REQUIRED_SETTLE_COLS and float(v) > 0}
    meta: Dict[str, Any] = {
        "coerced": False,
        "replacements": {},
        "yahoo_tickers": dict(tickers or {}),
        "resolved": dict(resolved or {}),
    }
    if not settle_date:
        return out, meta

    try:
        from contract_roll import infer_resolved_contracts

        inferred = infer_resolved_contracts(pd.Timestamp(settle_date).to_pydatetime())
    except Exception:
        inferred = {}

    named_closes, _named_bars, named_tickers = _fetch_yahoo_session_bars(
        settle_date, resolved_contracts=inferred
    )
    if not named_closes:
        for col in ("RBOB", "ULSD"):
            t = (meta["yahoo_tickers"] or {}).get(col) or ""
            if _is_continuous_yahoo_ticker(t):
                meta["yahoo_tickers"].pop(col, None)
        return out, meta

    # Always trust named-month Yahoo for RBOB/ULSD when the bar exists.
    for col in ("RBOB", "ULSD"):
        named = named_closes.get(col)
        if not named or named <= 0:
            continue
        cur = out.get(col)
        ticker = (
            (tickers or {}).get(col)
            or (meta.get("yahoo_tickers") or {}).get(col)
            or ""
        )
        diverged = (not cur) or abs(float(cur) - float(named)) / max(float(named), 1e-9) >= 0.0005
        continuous_meta = _is_continuous_yahoo_ticker(ticker)
        if diverged or continuous_meta:
            if cur and diverged:
                meta["replacements"][col] = {
                    "from": round(float(cur), 4),
                    "to": round(float(named), 4),
                    "ticker": named_tickers.get(col),
                    "reason": (
                        "reject_continuous_ticker"
                        if continuous_meta
                        else "prefer_named_month_close"
                    ),
                }
                meta["coerced"] = True
            out[col] = round(float(named), 4)
        meta["yahoo_tickers"][col] = named_tickers.get(col) or f"{inferred.get(col, '')}.NYM"
        if inferred.get(col):
            meta["resolved"][col] = inferred[col]
        elif named_tickers.get(col):
            meta["resolved"][col] = str(named_tickers[col]).replace(".NYM", "")

    # Crude: prefer named when missing or labeled continuous
    named_crude = named_closes.get("Crude")
    crude_ticker = (tickers or {}).get("Crude") or (meta.get("yahoo_tickers") or {}).get("Crude") or ""
    if named_crude and named_crude > 0:
        cur_c = out.get("Crude")
        if (
            not cur_c
            or _is_continuous_yahoo_ticker(crude_ticker)
            or abs(float(cur_c) - float(named_crude)) / max(float(named_crude), 1e-9) >= 0.0005
        ):
            if cur_c and abs(float(cur_c) - float(named_crude)) / max(float(named_crude), 1e-9) >= 0.0005:
                meta["replacements"]["Crude"] = {
                    "from": round(float(cur_c), 4),
                    "to": round(float(named_crude), 4),
                    "ticker": named_tickers.get("Crude"),
                    "reason": "prefer_named_month_close",
                }
                meta["coerced"] = True
            out["Crude"] = round(float(named_crude), 4)
        meta["yahoo_tickers"]["Crude"] = named_tickers.get("Crude") or f"{inferred.get('Crude', '')}.NYM"
        if inferred.get("Crude"):
            meta["resolved"]["Crude"] = inferred["Crude"]

    return out, meta


def _yahoo_ticker(prefix: str, resolved_contracts: Optional[Dict[str, str]] = None) -> str:
    """Named-month Yahoo ticker (RBV26.NYM). Never use RB=F continuous for settles."""
    col = PREFIX_TO_SETTLE_COL.get(prefix)
    contract = (resolved_contracts or {}).get(col) if col else None
    if contract:
        return f"{contract}.NYM"
    # Infer calendar front/lead — continuous RB=F rolls early and breaks settles
    try:
        from contract_roll import infer_resolved_contracts

        inferred = infer_resolved_contracts()
        contract = inferred.get(col) if col else None
        if contract:
            return f"{contract}.NYM"
    except Exception:
        pass
    return ""


def _fetch_yahoo_session_bars(
    settle_date: str,
    resolved_contracts: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, float], Dict[str, Dict[str, float]], Dict[str, str]]:
    """Yahoo named-month OHLC for one session (never RB=F continuous)."""
    closes: Dict[str, float] = {}
    bars: Dict[str, Dict[str, float]] = {}
    tickers_used: Dict[str, str] = {}
    try:
        from scripts.fetch_futures_ohlc import fetch_symbol_history
    except ImportError:
        return closes, bars, tickers_used

    target = pd.Timestamp(settle_date).date()

    # Prefer explicit resolved; else infer calendar front (RB*1 / RB*2 in roll window)
    try:
        from contract_roll import infer_resolved_contracts

        as_of = pd.Timestamp(settle_date).to_pydatetime()
        inferred = infer_resolved_contracts(as_of)
    except Exception:
        inferred = {}

    resolved = dict(inferred)
    if resolved_contracts:
        for k, v in resolved_contracts.items():
            if not v or _is_continuous_yahoo_ticker(str(v)) or str(v).endswith("=F"):
                continue
            resolved[k] = v

    for prefix, col in PREFIX_TO_SETTLE_COL.items():
        # Only the inferred contract (RB*1 / RB*2 from roll map). Never probe lead
        # as a fallback — that re-selects Nov/continuous when prior cache is wrong.
        contract = resolved.get(col)
        if not contract or _is_continuous_yahoo_ticker(str(contract)):
            continue
        contract = str(contract).replace(".NYM", "")
        ticker = f"{contract}.NYM"
        hist = fetch_symbol_history(ticker, period="1mo")
        if hist is None or hist.empty:
            continue
        day = hist[hist["date"].dt.date == target]
        if day.empty:
            # Holiday / no bar — skip (do not invent from another month)
            continue
        bar = day.iloc[-1]
        ohlc: Dict[str, float] = {}
        for out_key, src in (
            ("open", "Open"),
            ("high", "High"),
            ("low", "Low"),
            ("close", "Close"),
            ("volume", "Volume"),
        ):
            if src in bar.index and pd.notna(bar[src]):
                ohlc[out_key] = float(bar[src])
        close_px = ohlc.get("close") or 0.0
        if close_px <= 0:
            continue
        bars[prefix] = ohlc
        closes[col] = round(close_px, 4)
        tickers_used[col] = ticker
        resolved[col] = contract

    return closes, bars, tickers_used


def _fetch_yahoo_settle_vwap(
    settle_date: str,
    resolved_contracts: Optional[Dict[str, str]] = None,
    futures_path: str = "data/futures_ohlc.csv",
) -> Tuple[Dict[str, float], str, str, Dict[str, Any]]:
    """
    Approximate NYMEX official settle via named-month Globex VWAP 14:28–14:30 ET.

    Yahoo daily Close is often the after-hours last print — not the exchange settle.
    When Barchart scrape is empty, this is the publishable fallback.
    """
    target_str = str(settle_date)[:10]
    closes: Dict[str, float] = {}
    tickers_used: Dict[str, str] = {}
    bar_counts: Dict[str, int] = {}
    empty: Dict[str, Any] = {}

    try:
        import yfinance as yf
        from contract_roll import infer_resolved_contracts

        as_of = pd.Timestamp(target_str).to_pydatetime()
        inferred = infer_resolved_contracts(as_of)
    except Exception:
        return {}, "", "", empty

    resolved = dict(inferred or {})
    if resolved_contracts:
        for k, v in resolved_contracts.items():
            if v and not _is_continuous_yahoo_ticker(str(v)):
                resolved[k] = str(v).replace(".NYM", "")

    start = pd.Timestamp(target_str)
    end = start + pd.Timedelta(days=1)

    for col in REQUIRED_SETTLE_COLS:
        contract = resolved.get(col)
        if not contract:
            continue
        contract = str(contract).replace(".NYM", "")
        ticker = f"{contract}.NYM"
        try:
            hist = yf.Ticker(ticker).history(
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval="1m",
                auto_adjust=False,
            )
        except Exception:
            continue
        if hist is None or hist.empty:
            continue
        if getattr(hist.index, "tz", None) is not None:
            hist.index = hist.index.tz_convert("US/Eastern")
        day = hist[hist.index.strftime("%Y-%m-%d") == target_str]
        if day.empty:
            continue
        win = day.between_time(SETTLE_VWAP_START, SETTLE_VWAP_END)
        if len(win) < MIN_SETTLE_VWAP_BARS:
            continue
        vol = float(win["Volume"].sum()) if "Volume" in win.columns else 0.0
        if vol > 0:
            vwap = float((win["Close"] * win["Volume"]).sum() / vol)
        else:
            vwap = float(win["Close"].iloc[-1])
        if vwap <= 0:
            continue
        closes[col] = round(vwap, 4)
        tickers_used[col] = ticker
        bar_counts[col] = int(len(win))

    if len(closes) < len(REQUIRED_SETTLE_COLS):
        return {}, "", "", empty

    label = f"NYMEX ({target_str}) — 14:28–14:30 ET named-month VWAP"
    meta: Dict[str, Any] = {
        "source": "yahoo_settle_vwap",
        "label": label,
        "method": "globex_settle_window_vwap",
        "yahoo_tickers": tickers_used,
        "resolved": {
            col: (tickers_used.get(col) or "").replace(".NYM", "")
            for col in REQUIRED_SETTLE_COLS
            if tickers_used.get(col)
        },
        "vwap_bars": bar_counts,
        "trust_level": 2,
    }
    _write_settle_to_futures_csv(closes, target_str, futures_path)
    _save_session_settle_cache(target_str, closes, meta)
    return closes, target_str, label, meta


def _pick_official_close(
    col: str,
    barchart_settle: float,
    yahoo_close: float,
    live_last: Optional[float],
    *,
    prior_settle: Optional[float] = None,
    settle_date: Optional[str] = None,
    yahoo_bar: Optional[Dict[str, float]] = None,
) -> Tuple[float, str, Dict[str, Any]]:
    """
    NYMEX official settlement from Barchart (lastPrice - priceChange on front month).

    Prefer Barchart settle when fresh. If Barchart still equals yesterday's settle
    while the Yahoo daily bar for this session moved, treat Barchart as stale and
    use that session's Yahoo close (never overnight live_last for a prior date).
    """
    # Prefer the Yahoo daily bar for settle_date — not overnight live_last.
    session_close = float(yahoo_close) if yahoo_close and yahoo_close > 0 else 0.0
    yh_vol = float((yahoo_bar or {}).get("volume") or 0)
    prefix = COL_TO_PREFIX.get(col, "")
    min_vol = MIN_SESSION_VOLUME.get(f"{prefix}_volume", 0)
    today_str = _now_et().strftime("%Y-%m-%d")
    same_session = bool(settle_date and settle_date == today_str)
    # Only blend live_last on the same settle day (after close), never for backfill.
    if same_session and live_last and live_last > 0 and yh_vol >= min_vol:
        if session_close <= 0 or abs(live_last - session_close) / session_close < 0.01:
            session_close = float(live_last)

    detail: Dict[str, Any] = {
        "barchart_settle": round(float(barchart_settle), 4) if barchart_settle else None,
        "session_close": round(session_close, 4) if session_close else None,
        "prior_settle": round(float(prior_settle), 4) if prior_settle else None,
    }

    bc = float(barchart_settle) if barchart_settle and barchart_settle > 0 else 0.0
    prior = float(prior_settle) if prior_settle and prior_settle > 0 else 0.0

    # Per-product stale: Barchart still equals prior while this session's Yahoo moved.
    # Threshold was 0.8% — Aug 20 RBOB/ULSD moved ~0.2–0.7% and kept yesterday's settle.
    bc_is_prior = prior > 0 and bc > 0 and abs(bc - prior) / prior < 0.0015
    yahoo_moved = (
        prior > 0
        and session_close > 0
        and abs(session_close - prior) / prior >= 0.002
    )
    if bc_is_prior and yahoo_moved:
        detail["reason"] = "stale_barchart_use_yahoo"
        return round(session_close, 4), "session_close", detail

    if bc > 0:
        detail["reason"] = "official_nymex_settle"
        return round(bc, 4), "nymex_settle", detail

    if session_close > 0:
        detail["reason"] = "session_close_fallback"
        return round(session_close, 4), "session_close", detail

    return 0.0, "missing", detail


def _prior_session_closes(settle_date: str) -> Dict[str, float]:
    """Most recent cached settles strictly before settle_date."""
    cache = _load_session_settle_cache()
    for date_key in sorted(cache.keys(), reverse=True):
        if date_key >= settle_date:
            continue
        row = (cache.get(date_key) or {}).get("closes") or {}
        out = {
            k: float(v)
            for k, v in row.items()
            if k in REQUIRED_SETTLE_COLS and float(v) > 0
        }
        if len(out) >= len(REQUIRED_SETTLE_COLS):
            return out
    try:
        hist = load_official_price_history()
        if hist is not None and not hist.empty:
            sub = hist[pd.to_datetime(hist["date"]) < pd.Timestamp(settle_date)]
            if not sub.empty:
                last = sub.iloc[-1]
                return {
                    c: float(last[c])
                    for c in REQUIRED_SETTLE_COLS
                    if c in last.index and pd.notna(last[c]) and float(last[c]) > 0
                }
    except Exception:
        pass
    return {}


def _closes_match_prior(closes: Dict[str, float], prior: Dict[str, float], tol: float = 0.0015) -> bool:
    if not closes or not prior:
        return False
    matched = 0
    for col in REQUIRED_SETTLE_COLS:
        a, b = closes.get(col), prior.get(col)
        if not a or not b or a <= 0 or b <= 0:
            return False
        if abs(float(a) - float(b)) / float(b) < tol:
            matched += 1
    return matched >= len(REQUIRED_SETTLE_COLS)


def _any_product_matches_prior(
    closes: Dict[str, float],
    prior: Dict[str, float],
    tol: float = 0.0015,
) -> bool:
    """True if any product still equals yesterday — common when Barchart lags overnight."""
    if not closes or not prior:
        return False
    for col in REQUIRED_SETTLE_COLS:
        a, b = closes.get(col), prior.get(col)
        if a and b and a > 0 and b > 0 and abs(float(a) - float(b)) / float(b) < tol:
            return True
    return False


def _reconcile_barchart_with_yahoo(
    barchart: Dict[str, float],
    settle_date: str,
    resolved_contracts: Optional[Dict[str, str]] = None,
    live_last: Optional[Dict[str, float]] = None,
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """
    Merge Barchart official settlement with Yahoo front-month session close.
    Uses front-month .NYM (not RB=F) as the session-close reference.
    """
    yahoo_closes, yahoo_bars, tickers_used = _fetch_yahoo_session_bars(
        settle_date, resolved_contracts
    )
    prior = _prior_session_closes(settle_date)
    if not yahoo_closes:
        out = {k: round(float(v), 4) for k, v in barchart.items() if v and float(v) > 0}
        # Don't accept an all-stale copy of yesterday with no Yahoo confirmation
        if prior and _closes_match_prior(out, prior):
            return {}, {"validated": False, "reason": "stale_barchart_no_yahoo"}
        return out, {"validated": bool(out), "reason": "barchart_only"}

    out: Dict[str, float] = {}
    picks: Dict[str, Any] = {}
    live_last = live_last or {}

    for col in REQUIRED_SETTLE_COLS:
        bc = barchart.get(col)
        yh = yahoo_closes.get(col)
        if bc is None and yh is None:
            continue
        prefix = COL_TO_PREFIX.get(col, "")
        picked, method, detail = _pick_official_close(
            col,
            float(bc) if bc is not None else 0.0,
            float(yh) if yh is not None else 0.0,
            live_last.get(col),
            prior_settle=prior.get(col),
            settle_date=settle_date,
            yahoo_bar=yahoo_bars.get(prefix),
        )
        out[col] = picked
        picks[col] = {
            **detail,
            "picked": picked,
            "method": method,
            "yahoo_ticker": tickers_used.get(col),
            "yahoo_low": (yahoo_bars.get(prefix) or {}).get("low"),
            "yahoo_high": (yahoo_bars.get(prefix) or {}).get("high"),
        }

    label_suffix = ""
    methods = {col: p.get("method") for col, p in picks.items()}
    if any(m == "session_close" for m in methods.values()):
        label_suffix = " (session close fallback where settle unavailable)"
    if any((p.get("reason") == "stale_barchart_use_yahoo") for p in picks.values()):
        label_suffix += " [stale Barchart overridden]"

    return out, {
        "validated": True,
        "yahoo_closes": yahoo_closes,
        "yahoo_tickers": tickers_used,
        "prior_closes": prior,
        "picks": picks,
        "label_suffix": label_suffix,
    }


def _past_session_complete(session_date, now_et: datetime) -> bool:
    """True when session_date is a weekday session that has finished."""
    if session_date.weekday() >= 5:
        return False
    if session_date < now_et.date():
        return True
    return _session_closed_for_date(session_date, now_et)


def _fetch_yahoo_history_session_close(
    settle_date,
    futures_path: str = "data/futures_ohlc.csv",
) -> Tuple[Dict[str, float], str, str, Dict[str, Any]]:
    """Fallback for missed sessions: Yahoo front-month OHLC for a specific date."""
    target_str = settle_date.strftime("%Y-%m-%d")
    resolved: Dict[str, str] = {}
    try:
        from scripts.fetch_barchart_settle import fetch_barchart_settlement_closes

        _, _, bc_meta = fetch_barchart_settlement_closes()
        resolved = (bc_meta or {}).get("resolved") or {}
    except Exception:
        pass

    yahoo_closes, yahoo_bars, tickers_used = _fetch_yahoo_session_bars(
        target_str, resolved_contracts=resolved
    )
    if len(yahoo_closes) < len(REQUIRED_SETTLE_COLS):
        return {}, "", "", {}

    # Prefer cached official Barchart settle when we already have it for this date
    cached, _ = _cached_settles_for_date(target_str)
    barchart = dict(cached) if cached else {}
    if not barchart:
        try:
            from scripts.fetch_barchart_settle import fetch_barchart_settlement_closes

            live_bc, _, bc_meta = fetch_barchart_settlement_closes()
            barchart = live_bc or {}
            resolved = (bc_meta or {}).get("resolved") or resolved
        except Exception:
            barchart = {}

    closes, reconcile_meta = _reconcile_barchart_with_yahoo(
        barchart,
        target_str,
        resolved_contracts=resolved,
        live_last=yahoo_closes,
    )
    if not closes:
        closes = yahoo_closes

    picks = reconcile_meta.get("picks") or {}
    settle_parts = []
    for col in REQUIRED_SETTLE_COLS:
        p = picks.get(col) or {}
        if p.get("method") == "nymex_settle":
            settle_parts.append(f"{col} settle")
        elif p.get("method") == "session_close":
            settle_parts.append(f"{col} close")
    label = f"NYMEX ({target_str})"
    if settle_parts:
        label += " — " + ", ".join(settle_parts)
    label += " (historical backfill)"

    meta = {
        "source": "yahoo_history_backfill",
        "label": label,
        "reconcile": reconcile_meta,
        "yahoo_tickers": tickers_used,
        "resolved": {
            col: (tickers_used.get(col) or "").replace(".NYM", "")
            for col in REQUIRED_SETTLE_COLS
            if tickers_used.get(col)
        },
    }
    _write_settle_to_futures_csv(closes, target_str, futures_path)
    _save_session_settle_cache(target_str, closes, meta)
    return closes, target_str, label, meta


def _fetch_barchart_session_close(
    futures_path: str,
    settle_date,
) -> Tuple[Dict[str, float], str, str, Dict[str, Any]]:
    """Official front-month settlement from Barchart — never Yahoo."""
    target_str = settle_date.strftime("%Y-%m-%d")
    try:
        from scripts.fetch_barchart_settle import fetch_barchart_settlement_closes
        from contract_roll import get_nearby_map, roll_status

        nearby_map = get_nearby_map()
        closes, _as_of, bc_meta = fetch_barchart_settlement_closes(nearby_map=nearby_map)
        roll_info = roll_status()
        if isinstance(bc_meta, dict):
            bc_meta["contract_roll"] = roll_info
        if len(closes) < len(REQUIRED_SETTLE_COLS):
            return {}, "", "", bc_meta if isinstance(bc_meta, dict) else {}
        if not all(k in closes for k in REQUIRED_SETTLE_COLS):
            return {}, "", "", bc_meta if isinstance(bc_meta, dict) else {}
        resolved = (bc_meta or {}).get("resolved") or {}
        live = (bc_meta or {}).get("live_last") or {}
        closes, reconcile_meta = _reconcile_barchart_with_yahoo(
            closes, target_str, resolved_contracts=resolved, live_last=live
        )
        picks = reconcile_meta.get("picks") or {}
        settle_parts = []
        for col in REQUIRED_SETTLE_COLS:
            p = picks.get(col) or {}
            if p.get("method") == "nymex_settle":
                settle_parts.append(f"{col} settle")
            elif p.get("method") == "session_close":
                settle_parts.append(f"{col} close")
        label = f"NYMEX ({target_str})"
        if settle_parts:
            label += " — " + ", ".join(settle_parts)
        if reconcile_meta.get("label_suffix"):
            label += reconcile_meta["label_suffix"]
        bc_meta = dict(bc_meta or {})
        bc_meta["label"] = label
        bc_meta["source"] = "nymex_official"
        bc_meta["reconcile"] = reconcile_meta
        bc_meta["trust_level"] = _settle_trust_level(bc_meta)
        issues = validate_session_closes(closes, as_of_date=target_str)
        if issues and _is_verified_settle(target_str):
            cached, cached_label = _cached_settles_for_date(target_str)
            if cached:
                return cached, target_str, cached_label
        if issues:
            bc_meta["validation_warnings"] = issues
        _write_settle_to_futures_csv(closes, target_str, futures_path)
        _save_session_settle_cache(target_str, closes, bc_meta)
        return closes, target_str, label, bc_meta
    except Exception:
        return {}, "", "", {}


def _finalize_named_month_closes(
    closes: Dict[str, float],
    settle_date: str,
    label: str = "",
    meta: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, float], str]:
    """Last-chance gate before any caller sees session closes."""
    if not closes or not settle_date:
        return closes or {}, label
    meta = dict(meta or {})
    src = str(meta.get("source") or "")
    # Never overwrite official / VWAP / Gill-verified with Yahoo daily last
    if (
        _settle_trust_level(meta) >= 2
        and src in PUBLISHABLE_SETTLE_SOURCES
    ) or src == "verified":
        return closes, label or str(meta.get("label") or "")
    tickers = meta.get("yahoo_tickers") or (meta.get("reconcile") or {}).get("yahoo_tickers")
    resolved = meta.get("resolved")
    # Prefer settle-window VWAP over daily last when rejecting continuous
    try:
        vwap_closes, _, vwap_label, vwap_meta = _fetch_yahoo_settle_vwap(
            settle_date, resolved_contracts=resolved
        )
        if vwap_closes and len(vwap_closes) >= len(REQUIRED_SETTLE_COLS):
            return vwap_closes, vwap_label or label
    except Exception:
        pass
    fixed, coerce_meta = _coerce_named_month_settles(
        closes, settle_date, tickers=tickers, resolved=resolved
    )
    if coerce_meta.get("coerced"):
        meta["named_month_coercion"] = coerce_meta.get("replacements")
        meta["yahoo_tickers"] = coerce_meta.get("yahoo_tickers") or tickers
        meta["resolved"] = coerce_meta.get("resolved") or resolved
        meta["source"] = "yahoo_named_month"
        meta["trust_level"] = 1
        label = f"NYMEX ({settle_date}) — Oct/named-month daily last (unverified)"
        meta["label"] = label
        _save_session_settle_cache(settle_date, fixed, meta)
        try:
            sync_prices_csv_from_futures(fixed, as_of_date=settle_date)
            _write_settle_to_futures_csv(fixed, settle_date)
        except Exception:
            pass
        return fixed, label
    return closes, label


def get_nymex_session_close(
    futures_path: str = "data/futures_ohlc.csv",
) -> Tuple[Dict[str, float], str, str]:
    """
    Last completed NYMEX afternoon settlement close.

    Always returns named-month RBOB/ULSD (never continuous RB=F / HO=F).
    """
    now_et = _now_et()
    target = _last_completed_settle_date(now_et)
    target_str = target.strftime("%Y-%m-%d")
    calendar_gap = (now_et.date() - target).days

    cached, cached_label = _cached_settles_for_date(target_str)
    cache_hit = cached and all(cached.get(c) for c in REQUIRED_SETTLE_COLS)
    prior = _prior_session_closes(target_str)
    stale_duplicate = bool(cache_hit and prior and _closes_match_prior(cached, prior))
    partial_stale = bool(cache_hit and prior and _any_product_matches_prior(cached, prior))

    roll_contract_stale = False
    try:
        from contract_roll import get_nearby_map

        if get_nearby_map(now_et).get("RBOB") == "RB*2":
            cache_row = (_load_session_settle_cache().get(target_str) or {})
            cached_rb = ((cache_row.get("meta") or {}).get("resolved") or {}).get("RBOB", "")
            if cached_rb and "U26" in cached_rb:
                roll_contract_stale = True
    except Exception:
        pass

    continuous_roll_artifact = False
    cache_row = (_load_session_settle_cache().get(target_str) or {}) if cache_hit else {}
    meta_cached = cache_row.get("meta") or {}
    # Yahoo daily-last (or other non-publishable) cache must refresh to Barchart/VWAP
    cache_unpublishable = bool(
        cache_hit and not is_publishable_settle(target_str, meta_cached)
    )
    if cache_hit and prior:
        try:
            rb0 = float(prior.get("RBOB") or 0)
            rb1 = float(cached.get("RBOB") or 0)
            c0 = float(prior.get("Crude") or 0)
            c1 = float(cached.get("Crude") or 0)
            if rb0 > 0 and rb1 > 0:
                rb_chg = abs(rb1 - rb0) / rb0
                crude_chg = abs(c1 - c0) / c0 if c0 > 0 else 0.0
                if rb_chg >= 0.035 and crude_chg < rb_chg * 0.50:
                    continuous_roll_artifact = True
            for col in ("RBOB", "ULSD"):
                yh = (meta_cached.get("yahoo_tickers") or {}).get(col, "")
                rec_yh = ((meta_cached.get("reconcile") or {}).get("yahoo_tickers") or {}).get(col, "")
                if _is_continuous_yahoo_ticker(yh) or _is_continuous_yahoo_ticker(rec_yh):
                    continuous_roll_artifact = True
                    break
            # Price labeled named-month but still equals continuous RB=F / HO=F
            if not continuous_roll_artifact:
                try:
                    from scripts.fetch_futures_ohlc import fetch_symbol_history
                    from config import FUTURES_SYMBOLS

                    for prefix, col in (("rbob", "RBOB"), ("diesel", "ULSD")):
                        px = float(cached.get(col) or 0)
                        if px <= 0:
                            continue
                        hist = fetch_symbol_history(FUTURES_SYMBOLS.get(prefix, ""), period="1mo")
                        if hist is None or hist.empty:
                            continue
                        day = hist[hist["date"].dt.date == target]
                        if day.empty:
                            continue
                        cont = float(day.iloc[-1]["Close"])
                        if cont > 0 and abs(px - cont) / cont <= CONTINUOUS_MATCH_PCT:
                            # Named front should diverge from continuous after early roll
                            named_closes, _, _ = _fetch_yahoo_session_bars(target_str)
                            named = float((named_closes or {}).get(col) or 0)
                            if named > 0 and abs(named - cont) / cont >= CONTINUOUS_MATCH_PCT:
                                continuous_roll_artifact = True
                                break
                except Exception:
                    pass
        except Exception:
            pass

    force_refresh = (
        calendar_gap >= 3
        or (now_et.weekday() == 0 and target.weekday() == 4)
        or stale_duplicate
        or partial_stale
        or roll_contract_stale
        or continuous_roll_artifact
        or cache_unpublishable
    )
    past_complete = _past_session_complete(target, now_et)

    same_day_resettle = (
        target == now_et.date()
        and _session_closed_for_date(target, now_et)
        and now_et.weekday() < 5
    )

    def _return(closes: Dict[str, float], date_str: str, label: str, meta: Optional[Dict] = None):
        fixed, lab = _finalize_named_month_closes(closes, date_str, label, meta)
        return fixed, date_str, lab

    if cache_hit and not force_refresh and (
        not same_day_resettle or _is_verified_settle(target_str)
    ):
        return _return(cached, target_str, cached_label, meta_cached)

    should_fetch = force_refresh or (
        past_complete and not cache_hit
    ) or (same_day_resettle and not _is_verified_settle(target_str))
    if should_fetch:
        bc_closes, bc_date, bc_label, bc_meta = _fetch_barchart_session_close(futures_path, target)
        if bc_closes and not (prior and _closes_match_prior(bc_closes, prior)):
            label = f"{bc_label} (post-weekend refresh)" if force_refresh else bc_label
            return _return(bc_closes, bc_date, label, bc_meta if isinstance(bc_meta, dict) else None)
        if bc_closes and prior and _closes_match_prior(bc_closes, prior):
            hist_closes, hist_date, hist_label, hist_meta = _fetch_yahoo_history_session_close(
                target, futures_path
            )
            if hist_closes and not _closes_match_prior(hist_closes, prior):
                return _return(
                    hist_closes, hist_date, hist_label,
                    hist_meta if isinstance(hist_meta, dict) else None,
                )
        # Barchart empty/stale → named-month Globex VWAP (official window), not Yahoo daily last
        if past_complete and (not cache_hit or stale_duplicate or partial_stale or continuous_roll_artifact or same_day_resettle or cache_unpublishable):
            vwap_closes, vwap_date, vwap_label, vwap_meta = _fetch_yahoo_settle_vwap(
                target_str, futures_path=futures_path
            )
            if vwap_closes and not (prior and _closes_match_prior(vwap_closes, prior)):
                lab = f"{vwap_label} (post-weekend refresh)" if force_refresh else vwap_label
                return _return(
                    vwap_closes,
                    vwap_date,
                    lab,
                    vwap_meta if isinstance(vwap_meta, dict) else None,
                )
        if past_complete and (not cache_hit or stale_duplicate or partial_stale or continuous_roll_artifact):
            hist_closes, hist_date, hist_label, hist_meta = _fetch_yahoo_history_session_close(
                target, futures_path
            )
            if hist_closes:
                return _return(
                    hist_closes, hist_date, hist_label,
                    hist_meta if isinstance(hist_meta, dict) else None,
                )

    cached, cached_label = _cached_settles_for_date(target_str)
    if cached:
        row = (_load_session_settle_cache().get(target_str) or {})
        return _return(cached, target_str, cached_label, row.get("meta"))

    cache = _load_session_settle_cache()
    for date_key in sorted(cache.keys(), reverse=True):
        if date_key >= target_str:
            continue
        cached, cached_label = _cached_settles_for_date(date_key)
        if cached:
            row = cache.get(date_key) or {}
            return _return(cached, date_key, cached_label, row.get("meta"))

    return {}, "", ""


def validate_session_closes(
    closes: Dict[str, float],
    *,
    as_of_date: Optional[str] = None,
) -> List[str]:
    """
    Sanity-check the three NYMEX closes before forecasting.
    Catches RB=F continuous contract (~10¢ low on RBOB) and stale scrapes.
    """
    issues: List[str] = []
    if not closes:
        return ["No session closes returned"]

    date_str = as_of_date or datetime.now().strftime("%Y-%m-%d")
    try:
        from scripts.fetch_barchart_settle import fetch_barchart_settlement_closes

        bc_closes, _, bc_meta = fetch_barchart_settlement_closes()
        resolved = (bc_meta or {}).get("resolved") or {}
        live_last = (bc_meta or {}).get("live_last") or {}
    except Exception:
        bc_closes = {}
        resolved = {}
        live_last = {}

    yahoo_fm, yahoo_bars, tickers = _fetch_yahoo_session_bars(date_str, resolved)
    vwap_closes: Dict[str, float] = {}
    try:
        vwap_closes, _, _, _ = _fetch_yahoo_settle_vwap(
            date_str, resolved_contracts=resolved
        )
    except Exception:
        vwap_closes = {}

    # If caller already has publishable VWAP/Barchart, do not flag vs Yahoo daily last
    cached_meta = (_load_session_settle_cache().get(date_str) or {}).get("meta") or {}
    if is_publishable_settle(date_str, cached_meta):
        # Only flag continuous-contract mismatches below
        yahoo_fm = {}

    for col, product_key in (
        ("RBOB", "RBOB_Gasoline"),
        ("Crude", "Crude_Oil"),
        ("ULSD", "ULSD_Diesel"),
    ):
        val = closes.get(col)
        if val is None or val <= 0:
            issues.append(f"{product_key}: missing close")
            continue
        yh = yahoo_fm.get(col)
        bc = bc_closes.get(col)
        vwap = vwap_closes.get(col)
        prefix = COL_TO_PREFIX.get(col, "")
        # Prefer Barchart, then settle-window VWAP, never Yahoo daily last as "expected"
        preferred = float(bc) if bc else (float(vwap) if vwap else 0.0)
        if preferred > 0 and abs(val - preferred) / preferred > 0.006:
            method = "barchart" if bc else "settle_vwap"
            issues.append(
                f"{product_key}: ${val:.4f} should be ${preferred:.4f} "
                f"({method}, {tickers.get(col, '')})"
            )
            continue
        if not preferred and yh:
            expected, method, detail = _pick_official_close(
                col,
                float(bc) if bc else 0.0,
                float(yh) if yh else 0.0,
                live_last.get(col),
                prior_settle=(_prior_session_closes(date_str) or {}).get(col),
                settle_date=date_str,
                yahoo_bar=yahoo_bars.get(prefix),
            )
            if expected > 0 and abs(val - expected) / expected > 0.006:
                issues.append(
                    f"{product_key}: ${val:.4f} should be ${expected:.4f} "
                    f"({method}, {tickers.get(col, '')})"
                )

    # Continuous RB=F / HO=F must never equal the stored settle when named front differs
    try:
        from scripts.fetch_futures_ohlc import fetch_symbol_history
        from config import FUTURES_SYMBOLS
        from contract_roll import infer_resolved_contracts

        inferred = infer_resolved_contracts(pd.Timestamp(date_str).to_pydatetime())
        target = pd.Timestamp(date_str).date()
        for prefix, col, product_key in (
            ("rbob", "RBOB", "RBOB_Gasoline"),
            ("diesel", "ULSD", "ULSD_Diesel"),
        ):
            px = closes.get(col)
            if not px or px <= 0:
                continue
            cont_hist = fetch_symbol_history(FUTURES_SYMBOLS.get(prefix, ""), period="1mo")
            if cont_hist is None or cont_hist.empty:
                continue
            day = cont_hist[cont_hist["date"].dt.date == target]
            if day.empty:
                continue
            cont = float(day.iloc[-1]["Close"])
            named_sym = inferred.get(col)
            named = None
            if named_sym:
                nh = fetch_symbol_history(f"{named_sym}.NYM", period="1mo")
                if nh is not None and not nh.empty:
                    nd = nh[nh["date"].dt.date == target]
                    if not nd.empty:
                        named = float(nd.iloc[-1]["Close"])
            if (
                cont > 0
                and named
                and named > 0
                and abs(named - cont) / cont >= CONTINUOUS_MATCH_PCT
                and abs(px - cont) / cont <= CONTINUOUS_MATCH_PCT
            ):
                issues.append(
                    f"{product_key}: ${px:.4f} matches continuous "
                    f"{FUTURES_SYMBOLS.get(prefix)} (${cont:.4f}) — "
                    f"use {named_sym}.NYM (${named:.4f})"
                )
            elif (
                not is_publishable_settle(date_str, cached_meta)
                and not (vwap_closes.get(col) and abs(px - float(vwap_closes[col])) / px < 0.002)
                and named
                and named > 0
                and abs(px - named) / named >= 0.008
            ):
                issues.append(
                    f"{product_key}: ${px:.4f} diverges from {named_sym}.NYM "
                    f"(${named:.4f})"
                )
    except Exception:
        pass

    return issues


def repair_recent_settles_from_named_month(
    lookback_sessions: int = 15,
    futures_path: str = "data/futures_ohlc.csv",
) -> int:
    """
    Force-repair recent RBOB/ULSD/Crude closes to named-month Yahoo.
    Call after every save_futures_ohlc so continuous RB=F cannot stick.
    """
    fixed = 0
    try:
        from contract_roll import infer_resolved_contracts
    except Exception:
        return 0

    # Prefer dates from futures_ohlc / prices
    dates: List[str] = []
    for path in (futures_path, "data/prices.csv"):
        if not os.path.exists(path):
            continue
        try:
            df = pd.read_csv(path)
            if "date" not in df.columns:
                continue
            ds = (
                pd.to_datetime(df["date"], errors="coerce")
                .dropna()
                .dt.strftime("%Y-%m-%d")
                .unique()
                .tolist()
            )
            dates.extend(ds)
        except Exception:
            pass
    cache = _load_session_settle_cache()
    dates.extend(cache.keys())
    dates = sorted(set(dates))[-lookback_sessions:]

    for date_str in dates:
        try:
            # Never overwrite Gill-verified or publishable official settles with Yahoo last
            row_meta = (cache.get(date_str) or {}).get("meta") or {}
            if is_publishable_settle(date_str, row_meta) or _settle_trust_level(row_meta) >= 3:
                continue
            inferred = infer_resolved_contracts(pd.Timestamp(date_str).to_pydatetime())
            named_closes, _, named_tickers = _fetch_yahoo_session_bars(
                date_str, resolved_contracts=inferred
            )
            # Require named RBOB on the front contract — never invent from lead/continuous
            if not named_closes or not named_closes.get("RBOB"):
                continue
            ticker = (named_tickers or {}).get("RBOB") or ""
            if _is_continuous_yahoo_ticker(ticker):
                continue
            expected_sym = (inferred.get("RBOB") or "").replace(".NYM", "")
            got_sym = ticker.replace(".NYM", "")
            if expected_sym and got_sym and expected_sym != got_sym:
                continue

            # Only repair when cached/current looks like continuous or is missing
            cached_closes = ((cache.get(date_str) or {}).get("closes") or {})
            needs_repair = not cached_closes.get("RBOB")
            if not needs_repair:
                try:
                    from scripts.fetch_futures_ohlc import fetch_symbol_history
                    from config import FUTURES_SYMBOLS

                    for prefix, col in (("rbob", "RBOB"), ("diesel", "ULSD")):
                        px = float(cached_closes.get(col) or 0)
                        if px <= 0:
                            needs_repair = True
                            break
                        hist = fetch_symbol_history(FUTURES_SYMBOLS.get(prefix, ""), period="1mo")
                        if hist is None or hist.empty:
                            continue
                        day = hist[hist["date"].dt.date == pd.Timestamp(date_str).date()]
                        if day.empty:
                            continue
                        cont = float(day.iloc[-1]["Close"])
                        if cont > 0 and abs(px - cont) / cont <= CONTINUOUS_MATCH_PCT:
                            needs_repair = True
                            break
                except Exception:
                    needs_repair = True
            if not needs_repair:
                continue

            meta = {
                "source": "yahoo_named_month",
                "label": f"NYMEX ({date_str}) — named-month repair",
                "yahoo_tickers": named_tickers,
                "resolved": {
                    col: (named_tickers.get(col) or "").replace(".NYM", "")
                    for col in REQUIRED_SETTLE_COLS
                    if named_tickers.get(col)
                },
                "trust_level": 1,
            }
            _save_session_settle_cache(date_str, named_closes, meta)
            _write_settle_to_futures_csv(named_closes, date_str, futures_path)
            sync_prices_csv_from_futures(named_closes, as_of_date=date_str)
            patch_final_data_session_closes(
                {
                    "RBOB_Gasoline": named_closes.get("RBOB"),
                    "ULSD_Diesel": named_closes.get("ULSD"),
                    "Crude_Oil": named_closes.get("Crude"),
                },
                date_str,
            )
            fixed += 1
            cache = _load_session_settle_cache()
        except Exception:
            continue
    return fixed


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
    cache_row = (_load_session_settle_cache().get(as_of) or {}) if as_of else {}
    bc_meta = dict(cache_row.get("meta") or {})
    try:
        from contract_roll import roll_status

        roll_info = roll_status()
    except Exception:
        roll_info = {}
    src = str(bc_meta.get("source") or "")
    if not src:
        low = (label or "").lower()
        if "vwap" in low:
            src = "yahoo_settle_vwap"
        elif low.startswith("barchart"):
            src = "barchart"
        elif "verified" in low:
            src = "verified"
        elif "named-month" in low or "daily last" in low:
            src = "yahoo_named_month"
        else:
            src = "unknown"
    meta = {
        "as_of_date": as_of,
        "label": label,
        "source": src,
        "session": "NYMEX afternoon settle",
        "closes": closes,
        "by_product": by_product,
        "resolved": bc_meta.get("resolved") or {},
        "contract_roll": roll_info,
        "trust_level": _settle_trust_level({**bc_meta, "source": src, "label": label}),
        "publishable": is_publishable_settle(
            as_of, {**bc_meta, "source": src, "label": label}
        ),
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
            nested = block.get(hkey)
            ret_pct = block.get(chg_key)
            if ret_pct is None and isinstance(nested, dict) and nested.get("change_percent") is not None:
                ret_pct = nested.get("change_percent")
            if ret_pct is None and old_current > 0:
                old_p = nested
                if isinstance(old_p, dict):
                    old_p = old_p.get("price")
                if old_p is None:
                    old_p = block.get(hkey.replace("day_", ""))
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
            if hkey == "day_1":
                cap *= float(block.get("_day1_cap_mult") or 1.0)
            ret_pct = max(-cap, min(cap, float(ret_pct)))
            new_p = spot * (1.0 + ret_pct / 100.0)
            direction = "UP" if ret_pct > 0.08 else "DOWN" if ret_pct < -0.08 else "FLAT"
            if isinstance(nested, dict):
                nested = dict(nested)
                nested["price"] = float(new_p)
                nested["change_percent"] = float(ret_pct)
                nested["direction"] = direction
                block[hkey] = nested
            else:
                block[hkey] = float(new_p)
            if hkey == "day_1":
                block["next_day"] = float(new_p)
            elif hkey == "day_4":
                block["next_week"] = float(new_p)
            elif hkey == "day_7":
                block["biweekly"] = float(new_p)
                block["monthly"] = float(new_p)
            block[chg_key] = float(ret_pct)
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
    # Prefer front-month NYMEX when contract is known from settle cache
    resolved: Dict[str, str] = {}
    try:
        cache = _load_session_settle_cache()
        for date_key in sorted(cache.keys(), reverse=True):
            resolved = ((cache.get(date_key) or {}).get("meta") or {}).get("resolved") or {}
            if resolved:
                break
    except Exception:
        resolved = {}

    out: Dict[str, float] = {}
    for prefix, col in prefix_map.items():
        ticker = _yahoo_ticker(prefix, resolved)
        if not ticker or _is_continuous_yahoo_ticker(ticker):
            try:
                from contract_roll import infer_resolved_contracts

                inferred = infer_resolved_contracts()
                sym = inferred.get(col)
                ticker = f"{sym}.NYM" if sym else ""
            except Exception:
                ticker = ""
        if not ticker or _is_continuous_yahoo_ticker(ticker):
            continue
        hist = fetch_symbol_history(ticker, period="5d")
        if hist is None or hist.empty or "Close" not in hist.columns:
            continue
        val = float(hist["Close"].iloc[-1])
        if val > 0:
            out[col] = val
    return out


def live_gap_by_product(
    settle_by_product: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """
    Live overnight/intraday price by product key (diagnostic / gap overlay).
    Returns {RBOB_Gasoline: live_price, ...} — never used as email spot.
    """
    live_cols = fetch_live_futures_closes()
    out: Dict[str, float] = {}
    for col, pk in PRODUCT_KEY_MAP.items():
        if col in live_cols and live_cols[col] > 0:
            out[pk] = float(live_cols[col])
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


def save_verified_session_settle(
    settle_date: str,
    closes: Dict[str, float],
    *,
    note: str = "user verified",
    futures_path: str = "data/futures_ohlc.csv",
    prices_path: str = "data/prices.csv",
) -> Dict[str, float]:
    """Persist manually verified NYMEX official settles for a session date."""
    clean = {
        k: round(float(v), 4)
        for k, v in closes.items()
        if k in REQUIRED_SETTLE_COLS and v and float(v) > 0
    }
    if len(clean) < len(REQUIRED_SETTLE_COLS):
        raise ValueError(f"Need RBOB, ULSD, Crude for {settle_date}")

    meta_out = {
        "source": "verified",
        "method": "manual",
        "label": f"NYMEX ({settle_date}) — verified official settle",
        "note": note,
        "trust_level": 3,
    }
    _save_session_settle_cache(settle_date, clean, meta_out)
    _write_settle_to_futures_csv(clean, settle_date, futures_path)
    sync_prices_csv_from_futures(clean, prices_path=prices_path, as_of_date=settle_date)
    return clean


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


def load_trusted_settle_history(
    min_trust: int = 2,
    prices_path: str = "data/prices.csv",
    settles_path: str = SESSION_SETTLES_PATH,
) -> pd.DataFrame:
    """
    Official NYMEX settles for scoring / calendar actuals.
    min_trust=2: Barchart official or Gill-verified only (default for eval).
    min_trust=1: include Yahoo session-close fallbacks for model features.
    Never uses futures_ohlc.csv closes.
    """
    by_date: Dict[str, Dict[str, float]] = {}
    cache = _load_session_settle_cache(settles_path)

    for date_key in sorted(cache.keys()):
        row = cache.get(date_key) or {}
        meta = row.get("meta") or {}
        if _settle_trust_level(meta) < min_trust:
            continue
        closes = row.get("closes") or {}
        if len(closes) < len(REQUIRED_SETTLE_COLS):
            continue
        by_date[date_key] = {
            k: float(v) for k, v in closes.items() if k in REQUIRED_SETTLE_COLS and float(v) > 0
        }

    # Legacy rows from prices.csv before session cache existed
    if os.path.exists(prices_path):
        try:
            spot = pd.read_csv(prices_path)
            spot["date"] = pd.to_datetime(spot["date"], errors="coerce")
            spot = spot.dropna(subset=["date"]).sort_values("date")
            for _, row in spot.iterrows():
                d = row["date"].strftime("%Y-%m-%d")
                if d in by_date:
                    continue
                rec: Dict[str, float] = {}
                for col in REQUIRED_SETTLE_COLS:
                    if col in row.index and pd.notna(row[col]) and float(row[col]) > 0:
                        rec[col] = float(row[col])
                if len(rec) >= len(REQUIRED_SETTLE_COLS):
                    by_date[d] = rec
        except Exception:
            pass

    if not by_date:
        return pd.DataFrame()

    records: List[Dict[str, Any]] = []
    for d in sorted(by_date.keys()):
        rec: Dict[str, Any] = {"date": pd.Timestamp(d)}
        for col in REQUIRED_SETTLE_COLS:
            if col in by_date[d]:
                rec[col] = by_date[d][col]
        records.append(rec)
    return pd.DataFrame(records).sort_values("date")


def load_official_price_history(
    prices_path: str = "data/prices.csv",
    settles_path: str = SESSION_SETTLES_PATH,
) -> pd.DataFrame:
    """Barchart / verified session settles for models and momentum (trust >= 1)."""
    return load_trusted_settle_history(
        min_trust=1, prices_path=prices_path, settles_path=settles_path
    )


def resolved_contract(col: str, date_str: str) -> Optional[str]:
    """Front-month symbol (e.g. RBV26) stored at settle time."""
    try:
        cache = _load_session_settle_cache()
        row = cache.get(str(date_str)[:10]) or {}
        sym = ((row.get("meta") or {}).get("resolved") or {}).get(col)
        return str(sym) if sym else None
    except Exception:
        return None


def contract_roll_between(col: str, date_from: Any, date_to: Any) -> bool:
    """
    True when NYMEX contract month changed between two session dates
    (e.g. RBU26 Sep -> RBV26 Oct). Prevents fake -12% 'selloff' in momentum.
    """
    d0 = pd.Timestamp(date_from).strftime("%Y-%m-%d")
    d1 = pd.Timestamp(date_to).strftime("%Y-%m-%d")
    if d0 == d1:
        return False
    a = resolved_contract(col, d0)
    b = resolved_contract(col, d1)
    if a and b:
        return a != b
    # Fallback: huge product gap without matching crude move = contract roll artifact
    # (Yahoo continuous RB=F can jump months outside the calendar roll window)
    if col not in ("RBOB", "ULSD"):
        return False
    try:
        hist = load_trusted_settle_history(min_trust=1)
        if hist.empty or col not in hist.columns:
            return False
        hist = hist.sort_values("date")
        r0 = hist[hist["date"].astype(str).str[:10] == d0]
        r1 = hist[hist["date"].astype(str).str[:10] == d1]
        if r0.empty or r1.empty:
            return False
        p0 = float(r0.iloc[-1][col])
        p1 = float(r1.iloc[-1][col])
        if p0 <= 0:
            return False
        prod_chg = abs((p1 - p0) / p0 * 100.0)
        if prod_chg < 5.5:
            return False
        if "Crude" in hist.columns:
            c0 = float(r0.iloc[-1]["Crude"])
            c1 = float(r1.iloc[-1]["Crude"])
            if c0 > 0:
                crude_chg = abs((c1 - c0) / c0 * 100.0)
                if crude_chg < prod_chg * 0.45:
                    return True
        return prod_chg >= 8.0
    except Exception:
        return False


def _window_crosses_contract_roll(col: str, dates: pd.Series) -> bool:
    norm = pd.to_datetime(dates, errors="coerce").dt.normalize()
    for i in range(1, len(norm)):
        if pd.isna(norm.iloc[i]) or pd.isna(norm.iloc[i - 1]):
            continue
        if contract_roll_between(col, norm.iloc[i - 1], norm.iloc[i]):
            return True
    return False


def recent_session_return_pct(
    product_key: str,
    days: int = 1,
    history: Optional[pd.DataFrame] = None,
) -> Optional[float]:
    """Latest N-session return % from official settle series."""
    col = PRODUCT_COL_MAP.get(product_key)
    if not col:
        return None
    hist = history if history is not None else load_official_price_history()
    if hist.empty or col not in hist.columns:
        return None
    sub = hist.dropna(subset=[col]).sort_values("date")
    if len(sub) < days + 1:
        return None
    window = sub.iloc[-(days + 1) :].copy()
    dates = pd.to_datetime(window["date"], errors="coerce").dt.normalize()
    if _window_crosses_contract_roll(col, dates):
        return None
    # Allow weekend/holiday gaps between consecutive sessions; reject only large holes
    max_gap = max(4, MAX_SESSION_GAP_DAYS)
    for i in range(1, len(dates)):
        if pd.isna(dates.iloc[i]) or pd.isna(dates.iloc[i - 1]):
            return None
        if int((dates.iloc[i] - dates.iloc[i - 1]).days) > max_gap:
            return None
    cur = float(window.iloc[-1][col])
    prev = float(window.iloc[0][col])
    if prev <= 0:
        return None
    return (cur - prev) / prev * 100.0


def prior_session_return_pct(
    product_key: str,
    history: Optional[pd.DataFrame] = None,
) -> Optional[float]:
    """Return % for the session before the most recent (e.g. day-before-yesterday move)."""
    col = PRODUCT_COL_MAP.get(product_key)
    if not col:
        return None
    hist = history if history is not None else load_official_price_history()
    if hist.empty or col not in hist.columns:
        return None
    sub = hist.dropna(subset=[col]).sort_values("date")
    if len(sub) < 3:
        return None
    d_mid = pd.Timestamp(sub.iloc[-2]["date"]).normalize()
    d_prev = pd.Timestamp(sub.iloc[-3]["date"]).normalize()
    if contract_roll_between(col, d_prev, d_mid):
        return None
    if (d_mid - d_prev).days > max(4, MAX_SESSION_GAP_DAYS):
        return None
    cur = float(sub.iloc[-2][col])
    prev = float(sub.iloc[-3][col])
    if prev <= 0:
        return None
    return (cur - prev) / prev * 100.0


def upgrade_recent_settles_to_vwap(days: int = 7) -> int:
    """Re-derive recent untrusted settles (trust < 2, e.g. Yahoo daily last) from the
    14:28-14:30 ET named-month VWAP. Yahoo keeps 1-minute bars ~7 days, so only
    recent sessions can be upgraded. Returns the number of sessions upgraded."""
    cache = _load_session_settle_cache()
    cutoff = (_now_et() - timedelta(days=days)).strftime("%Y-%m-%d")
    today = _now_et().strftime("%Y-%m-%d")
    upgraded = 0
    for date_str in sorted(cache):
        if date_str < cutoff or date_str > today:
            continue
        meta = (cache.get(date_str) or {}).get("meta") or {}
        if _settle_trust_level(meta) >= 2:
            continue
        if not _session_closed_for_date(pd.Timestamp(date_str).date(), _now_et()):
            continue
        closes, _, _, vmeta = _fetch_yahoo_settle_vwap(date_str)
        if closes and vmeta.get("trust_level", 0) >= 2:
            upgraded += 1
    return upgraded
