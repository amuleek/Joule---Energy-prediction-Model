"""
Daily post-mortem: compare archived forecasts to realized prices,
explain hits/misses, rank drivers, update feature importance, and
compute bias adjustments for future forecasts.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from forecast_horizons import PREDICTION_HORIZONS

try:
    from live_prices import _now_et, _row_is_full_session, _session_closed_for_date, trading_session_offset
except ImportError:
    def _row_is_full_session(row) -> bool:  # type: ignore[misc]
        return True

    def trading_session_offset(anchor, sessions_ahead, history=None):  # type: ignore[misc]
        return None

    def _now_et():  # type: ignore[misc]
        return datetime.now()

    def _session_closed_for_date(session_date, now_et):  # type: ignore[misc]
        return pd.Timestamp(session_date).date() < now_et.date()

ARCHIVE_DIR = "data/predictions_archive"
REPORT_PATH = "data/post_mortem_report.json"
FEATURE_IMPORTANCE_PATH = "data/feature_importance.json"
ERROR_ADJUSTMENTS_PATH = "data/error_adjustments.json"
EVAL_LOG_PATH = "data/prediction_eval_log.csv"
MISTAKE_LESSONS_PATH = "data/mistake_lessons.jsonl"
PRICES_PATH = "data/prices.csv"
FUTURES_PATH = "data/futures_ohlc.csv"

FUTURES_TO_PRICE_COL = {
    "rbob_close": "RBOB",
    "diesel_close": "ULSD",
    "crude_close": "Crude",
}

PRODUCT_COLUMNS = {
    "RBOB_Gasoline": "RBOB",
    "ULSD_Diesel": "ULSD",
    "Crude_Oil": "Crude",
}

DISPLAY = {
    "RBOB_Gasoline": "Gasoline (RBOB)",
    "ULSD_Diesel": "Diesel (ULSD)",
    "Crude_Oil": "WTI Crude",
}

EVAL_HORIZONS = [(k, d) for k, d, _, _ in PREDICTION_HORIZONS]


def archive_predictions(predictions_json: Dict[str, Any], issued_date: Optional[str] = None) -> str:
    """Save dated snapshot for later evaluation."""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    day = issued_date or datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(ARCHIVE_DIR, f"{day}.json")
    payload = {
        "issued_date": day,
        "issued_at": datetime.now().isoformat(),
        "predictions": predictions_json,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


def _load_prices() -> pd.DataFrame:
    """Trusted official settles only — never futures_ohlc intraday/continuous closes."""
    try:
        from live_prices import load_trusted_settle_history
        official = load_trusted_settle_history(min_trust=2)
        if not official.empty:
            return official.sort_values("date")
    except Exception:
        pass
    return pd.DataFrame()


def _named_month_actual(col: str, target: pd.Timestamp) -> Optional[float]:
    """Front-month Yahoo settle for eval — never continuous RB=F / HO=F."""
    try:
        from live_prices import _fetch_yahoo_session_bars
        from contract_roll import infer_resolved_contracts

        date_str = pd.Timestamp(target).strftime("%Y-%m-%d")
        inferred = infer_resolved_contracts(pd.Timestamp(target).to_pydatetime())
        closes, _, tickers = _fetch_yahoo_session_bars(date_str, resolved_contracts=inferred)
        px = closes.get(col)
        if not px or float(px) <= 0:
            return None
        ticker = (tickers or {}).get(col) or ""
        expected = (inferred.get(col) or "").replace(".NYM", "")
        got = str(ticker).replace(".NYM", "")
        if expected and got and expected != got:
            return None
        if str(ticker).endswith("=F"):
            return None
        return float(px)
    except Exception:
        return None


def _actual_near_date(
    prices: pd.DataFrame,
    col: str,
    target: pd.Timestamp,
    max_gap_days: int = 0,
) -> Optional[float]:
    """Settle on the target NYMEX session only. Reject continuous-contract prints."""
    if prices.empty or col not in prices.columns:
        named = _named_month_actual(col, target)
        return named
    work = prices.dropna(subset=[col]).copy()
    if work.empty:
        return _named_month_actual(col, target)
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    day = pd.Timestamp(target).normalize()
    exact = work[work["date"].dt.normalize() == day]
    cached = float(exact.iloc[-1][col]) if not exact.empty else None

    named = _named_month_actual(col, target)
    if named and named > 0:
        # Prefer named front when cached looks like continuous / wrong month
        if cached is None:
            return named
        if abs(cached - named) / named >= 0.008:
            try:
                from scripts.fetch_futures_ohlc import fetch_symbol_history
                from config import FUTURES_SYMBOLS

                prefix = {"RBOB": "rbob", "ULSD": "diesel", "Crude": "crude"}.get(col, "")
                hist = fetch_symbol_history(FUTURES_SYMBOLS.get(prefix, ""), period="1mo")
                if hist is not None and not hist.empty:
                    d = hist[hist["date"].dt.date == day.date()]
                    if not d.empty:
                        cont = float(d.iloc[-1]["Close"])
                        if cont > 0 and abs(cached - cont) / cont <= 0.015:
                            return named
            except Exception:
                pass
            # Large divergence from named front — trust named
            if abs(cached - named) / named >= 0.02:
                return named
        return cached if cached else named

    if cached is not None:
        return cached
    if max_gap_days <= 0:
        return None
    deltas = (work["date"].dt.normalize() - day).dt.days
    mask = deltas.abs() <= max_gap_days
    close = work.loc[mask].copy()
    if close.empty:
        return None
    close = close.assign(abs_delta=deltas.abs())
    row = close.sort_values("abs_delta").iloc[0]
    return float(row[col])


def scrub_continuous_eval_actuals(lookback_days: int = 21) -> int:
    """
    Rewrite recent eval-log actuals that still equal Yahoo continuous RB=F / HO=F
    while the named front (RBV26 etc.) differs — those fake dumps poison learning.
    """
    if not os.path.exists(EVAL_LOG_PATH):
        return 0
    df = pd.read_csv(EVAL_LOG_PATH)
    if df.empty or "actual" not in df.columns:
        return 0

    cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    named_cache: Dict[str, Dict[str, float]] = {}
    cont_cache: Dict[str, Dict[str, float]] = {}
    fixed = 0

    def _named_for(date_str: str, col: str) -> Optional[float]:
        if date_str not in named_cache:
            named_cache[date_str] = {}
            try:
                from live_prices import _fetch_yahoo_session_bars
                from contract_roll import infer_resolved_contracts

                inferred = infer_resolved_contracts(pd.Timestamp(date_str).to_pydatetime())
                closes, _, tickers = _fetch_yahoo_session_bars(
                    date_str, resolved_contracts=inferred
                )
                for c in ("RBOB", "ULSD", "Crude"):
                    px = closes.get(c)
                    t = (tickers or {}).get(c) or ""
                    exp = (inferred.get(c) or "").replace(".NYM", "")
                    got = str(t).replace(".NYM", "")
                    if px and float(px) > 0 and (not exp or exp == got) and not str(t).endswith("=F"):
                        named_cache[date_str][c] = float(px)
            except Exception:
                pass
        return named_cache.get(date_str, {}).get(col)

    def _cont_for(date_str: str, col: str) -> Optional[float]:
        if date_str not in cont_cache:
            cont_cache[date_str] = {}
            try:
                from scripts.fetch_futures_ohlc import fetch_symbol_history
                from config import FUTURES_SYMBOLS

                day = pd.Timestamp(date_str).date()
                for c, prefix in (("RBOB", "rbob"), ("ULSD", "diesel"), ("Crude", "crude")):
                    hist = fetch_symbol_history(FUTURES_SYMBOLS.get(prefix, ""), period="1mo")
                    if hist is None or hist.empty:
                        continue
                    d = hist[hist["date"].dt.date == day]
                    if not d.empty:
                        cont_cache[date_str][c] = float(d.iloc[-1]["Close"])
            except Exception:
                pass
        return cont_cache.get(date_str, {}).get(col)

    for i, row in df.iterrows():
        product = str(row.get("product") or "")
        col = PRODUCT_COLUMNS.get(product)
        target = str(row.get("target_date") or "")[:10]
        if not col or not target or target < cutoff:
            continue
        try:
            named = _named_for(target, col)
            if not named or named <= 0:
                continue
            actual = float(row["actual"])
            if abs(actual - named) / named < 0.005:
                continue
            cont = _cont_for(target, col)
            if cont and cont > 0 and abs(actual - cont) / cont <= 0.02:
                pass
            elif abs(actual - named) / named >= 0.02:
                pass
            else:
                continue
            pred = float(row.get("predicted") or 0)
            spot = float(row.get("spot_at_issue") or 0)
            err = pred - named
            df.at[i, "actual"] = named
            df.at[i, "error"] = err
            df.at[i, "error_pct"] = round((err / named) * 100, 3)
            df.at[i, "abs_error_pct"] = round(abs(err / named) * 100, 3)
            act_dir = "UP" if spot and named > spot else "DOWN" if spot and named < spot else "FLAT"
            df.at[i, "actual_direction"] = act_dir
            pred_dir = str(row.get("predicted_direction") or "FLAT")
            df.at[i, "direction_correct"] = pred_dir == act_dir or abs(err / named * 100) < 0.5
            fixed += 1
        except Exception:
            continue
    if fixed:
        df.to_csv(EVAL_LOG_PATH, index=False)
    return fixed


def _load_eval_log() -> pd.DataFrame:
    if not os.path.exists(EVAL_LOG_PATH):
        return pd.DataFrame()
    return pd.read_csv(EVAL_LOG_PATH)


def drop_premature_eval_rows() -> int:
    """Remove 'actuals' written before that NYMEX session had settled."""
    if not os.path.exists(EVAL_LOG_PATH):
        return 0
    df = pd.read_csv(EVAL_LOG_PATH)
    if df.empty or "target_date" not in df.columns:
        return 0
    now_et = _now_et()
    targets = pd.to_datetime(df["target_date"], errors="coerce")
    keep = []
    for td in targets:
        if pd.isna(td):
            keep.append(False)
            continue
        keep.append(bool(_session_closed_for_date(td.date(), now_et)))
    keep_s = pd.Series(keep, index=df.index)
    dropped = int((~keep_s).sum())
    if dropped:
        df.loc[keep_s].to_csv(EVAL_LOG_PATH, index=False)
    return dropped


def _eval_key(row: Dict[str, Any]) -> Tuple:
    return (row["issued_date"], row["product"], row["horizon"])


def bootstrap_archive_if_needed() -> None:
    """Seed archive from predictions.json when no history exists yet."""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    if any(f.endswith(".json") for f in os.listdir(ARCHIVE_DIR)):
        return
    path = "data/predictions.json"
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            preds = json.load(f)
        ts = None
        for pk in PRODUCT_COLUMNS:
            block = preds.get(pk) or {}
            ts = block.get("timestamp")
            if ts:
                break
        if ts:
            day = str(ts)[:10]
        else:
            day = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d")
        archive_predictions(preds, issued_date=day)
    except Exception:
        pass


def evaluate_mature_predictions(prices: Optional[pd.DataFrame] = None) -> List[Dict[str, Any]]:
    """Compare archived forecasts to realized prices when horizons have matured."""
    bootstrap_archive_if_needed()
    n_scrub = scrub_continuous_eval_actuals()
    if n_scrub:
        print(f"  Scrubbed {n_scrub} eval actual(s) that matched continuous RB=F/HO=F")
    prices = prices if prices is not None else _load_prices()
    if prices.empty:
        return []

    drop_premature_eval_rows()

    existing = _load_eval_log()
    seen = set()
    if not existing.empty:
        for _, r in existing.iterrows():
            seen.add((str(r["issued_date"]), r["product"], r["horizon"]))

    today = pd.Timestamp(datetime.now().date())
    results: List[Dict[str, Any]] = []

    if not os.path.isdir(ARCHIVE_DIR):
        return results

    for fname in sorted(os.listdir(ARCHIVE_DIR)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(ARCHIVE_DIR, fname)
        try:
            with open(path, encoding="utf-8") as f:
                archive = json.load(f)
        except Exception:
            continue

        issued_date = pd.Timestamp(archive.get("issued_date", fname.replace(".json", "")))
        # Prefer wrapped archive; tolerate flat dumps written by manual repairs
        preds = archive.get("predictions")
        if not isinstance(preds, dict) or not any(
            k in preds for k in PRODUCT_COLUMNS
        ):
            if any(k in archive for k in PRODUCT_COLUMNS):
                preds = {k: v for k, v in archive.items() if not str(k).startswith("issued")}
            else:
                preds = {}
        meta = preds.get("_meta") or archive.get("_meta") or {}
        spot_ref = meta.get("spot_reference") or {}
        spot_by_product = spot_ref.get("by_product") or {}

        for product, col in PRODUCT_COLUMNS.items():
            block = preds.get(product)
            if not isinstance(block, dict):
                continue
            ref_spot = spot_by_product.get(product)
            spot = float(ref_spot if ref_spot else block.get("current_price", 0) or 0)

            for hkey, days in EVAL_HORIZONS:
                key = (issued_date.strftime("%Y-%m-%d"), product, hkey)
                if key in seen:
                    continue

                target = trading_session_offset(issued_date, days, prices)
                if target is None:
                    target = issued_date + pd.Timedelta(days=days)
                if target.date() > today.date():
                    continue
                if not _session_closed_for_date(target.date(), _now_et()):
                    continue

                hd = block.get(hkey)
                if not isinstance(hd, dict):
                    continue
                pred_price = float(hd.get("price", 0))
                if pred_price <= 0:
                    continue

                actual = _actual_near_date(prices, col, target)
                if actual is None or actual <= 0:
                    continue
                try:
                    from live_prices import _is_trusted_settle
                    if not _is_trusted_settle(target.strftime("%Y-%m-%d"), min_trust=2):
                        continue
                except ImportError:
                    pass

                error = pred_price - actual
                error_pct = (error / actual) * 100
                pred_dir = hd.get("direction", "FLAT")
                actual_dir = "UP" if actual > spot else "DOWN" if actual < spot else "FLAT"
                direction_ok = pred_dir == actual_dir or abs(error_pct) < 0.5

                meta = preds.get("_meta") or {}
                drivers = _drivers_at_issue(block, meta, product)
                ensemble_block = (meta.get("ensemble") or {}).get(product) or {}
                ensemble_components = (ensemble_block.get("components") or {}) if ensemble_block else {}

                row = {
                    "issued_date": issued_date.strftime("%Y-%m-%d"),
                    "target_date": target.strftime("%Y-%m-%d"),
                    "product": product,
                    "display": DISPLAY.get(product, product),
                    "horizon": hkey,
                    "horizon_days": days,
                    "spot_at_issue": spot,
                    "predicted": pred_price,
                    "actual": actual,
                    "error": error,
                    "error_pct": round(error_pct, 3),
                    "abs_error_pct": round(abs(error_pct), 3),
                    "direction_correct": direction_ok,
                    "predicted_direction": pred_dir,
                    "actual_direction": actual_dir,
                    "drivers_at_issue": drivers,
                    "ensemble_components": ensemble_components,
                    "model": meta.get("model", ""),
                    # Range calibration + baseline comparison (see baseline_forecast.py)
                    "naive_abs_error_pct": round(abs(spot - actual) / actual * 100, 3) if spot else None,
                    "in_range_80": _in_range(hd.get("range_80"), actual),
                    "in_range_95": _in_range(hd.get("range_95"), actual),
                }
                results.append(row)
                seen.add(key)

    return results


def _in_range(band: Any, actual: float) -> Optional[bool]:
    """True/False if a forecast range exists, None for forecasts issued without one."""
    if not isinstance(band, dict) or band.get("low") is None or band.get("high") is None:
        return None
    return bool(float(band["low"]) <= actual <= float(band["high"]))


def _drivers_at_issue(block: Dict[str, Any], meta: Dict[str, Any], product: str) -> Dict[str, Any]:
    """Snapshot of signals available when the forecast was issued."""
    dv = block.get("directional") or {}
    drivers = dv.get("drivers") or {}
    inv = meta.get("inventory_weekly") or {}
    inv_key = {"RBOB_Gasoline": "gasoline", "ULSD_Diesel": "distillate", "Crude_Oil": "crude"}.get(product)
    inv_row = inv.get(inv_key or "", {}) or {}

    dxy = meta.get("dollar_index") or {}
    crack = meta.get("crack_spreads_current") or {}
    layers = meta.get("layer_scores") or {}
    hurricane = meta.get("hurricane") or {}
    day1_meta = (meta.get("day1_consensus") or {}).get(product) or {}
    mom = day1_meta.get("momentum_continuation") or {}
    div_meta = day1_meta.get("crude_rally_gasoline_divergence") or {}

    crude_1d_pct = None
    product_1d_pct = None
    try:
        from live_prices import recent_session_return_pct

        issued = str(meta.get("spot_reference", {}).get("as_of_date") or "")[:10]
        if issued:
            hist = None
            try:
                from live_prices import load_official_price_history
                import pandas as pd

                full = load_official_price_history()
                if full is not None and not full.empty:
                    hist = full[pd.to_datetime(full["date"]) <= pd.Timestamp(issued)].copy()
            except Exception:
                hist = None
            crude_1d_pct = recent_session_return_pct("Crude_Oil", days=1, history=hist)
            product_1d_pct = recent_session_return_pct(product, days=1, history=hist)
    except Exception:
        pass

    cross_divergence_pp = None
    if crude_1d_pct is not None and product_1d_pct is not None:
        cross_divergence_pp = float(crude_1d_pct) - float(product_1d_pct)
    elif div_meta.get("divergence_pp") is not None:
        cross_divergence_pp = float(div_meta["divergence_pp"])

    return {
        "inventory_wow_pct": inv_row.get("wow_change_pct"),
        "sentiment": drivers.get("sentiment"),
        "geo_risk_score": drivers.get("geo_risk_score"),
        "dxy_change_pct": dxy.get("change_pct_1d") or dxy.get("change_1d_pct"),
        "gasoline_crack": crack.get("gasoline_crack_usd_per_bbl"),
        "diesel_crack": crack.get("diesel_crack_usd_per_bbl"),
        "layer_composite": (layers.get("composite") or {}).get("score"),
        "model_next_day_pct": drivers.get("model_next_day_pct"),
        "model_next_week_pct": drivers.get("model_next_week_pct"),
        "hurricane_risk_score": hurricane.get("risk_score"),
        "momentum_overlay_mode": mom.get("mode"),
        "crude_1d_pct": round(crude_1d_pct, 3) if crude_1d_pct is not None else None,
        "product_1d_pct": round(product_1d_pct, 3) if product_1d_pct is not None else None,
        "cross_divergence_pp": round(cross_divergence_pp, 3) if cross_divergence_pp is not None else None,
        "divergence_overlay_applied": bool(div_meta),
        "predicted_day1_pct": block.get("day_1", {}).get("change_percent")
        if isinstance(block.get("day_1"), dict)
        else block.get("day_1_change"),
    }


def _explain_row(row: Dict[str, Any]) -> str:
    """Plain-language explanation for one evaluated forecast."""
    ok = row["direction_correct"]
    verdict = "correct direction" if ok else "wrong direction"
    err = row["error_pct"]
    drivers = row.get("drivers_at_issue") or {}

    parts = [
        f"{row['display']} {row['horizon']} ({row['issued_date']} to {row['target_date']}): "
        f"predicted ${row['predicted']:.4f}, actual ${row['actual']:.4f} "
        f"({err:+.1f}% error, {verdict})."
    ]

    reasons: List[str] = []
    wow = drivers.get("inventory_wow_pct")
    if wow is not None:
        w = float(wow)
        if w < -0.3:
            reasons.append(f"gasoline/distillate/crude stocks drew {abs(w):.1f}% WoW (supportive)")
        elif w > 0.3:
            reasons.append(f"stocks built {w:.1f}% WoW (bearish supply cushion)")

    dxy = drivers.get("dxy_change_pct")
    if dxy is not None and abs(float(dxy)) >= 0.05:
        reasons.append(f"USD index moved {float(dxy):+.2f}% (macro headwind/tailwind)")

    sent = drivers.get("sentiment")
    if sent is not None and abs(float(sent)) > 0.05:
        reasons.append(f"news sentiment was {float(sent):+.2f}")

    gc = drivers.get("gasoline_crack")
    if gc is not None and row["product"] == "RBOB_Gasoline":
        reasons.append(f"gasoline crack ~${float(gc):.0f}/bbl")

    crude_1d = drivers.get("crude_1d_pct")
    prod_1d = drivers.get("product_1d_pct")
    div_pp = drivers.get("cross_divergence_pp")
    divergence_setup = (
        row["product"] == "RBOB_Gasoline"
        and crude_1d is not None
        and prod_1d is not None
        and float(crude_1d) >= 1.0
        and float(prod_1d) <= 0.35
        and float(div_pp or (float(crude_1d) - float(prod_1d))) >= 1.0
    )
    if divergence_setup:
        reasons.append(
            f"crude bid +{float(crude_1d):.1f}% but gasoline only {float(prod_1d):+.1f}% "
            f"(divergence {float(div_pp or (float(crude_1d) - float(prod_1d))):.1f}pp)"
        )

    if not ok:
        if divergence_setup and row.get("predicted_direction") == "UP":
            parts.append(
                "Missed crack compression — crude rallied but gasoline lagged/sold off; "
                "inventory/crack support was overweighted vs live product tape."
            )
        elif err > 0:
            parts.append("Model overshot — likely overweighted bullish drivers or underweighted supply builds / stronger dollar.")
        else:
            parts.append("Model undershot — likely missed supportive inventory draws, crude strength, or headline risk.")
    else:
        parts.append("Forecast aligned with the dominant driver mix at issue time.")

    if reasons:
        parts.append("Key factors at issue: " + "; ".join(reasons) + ".")
    return " ".join(parts)


def learn_from_prediction_mistakes(new_evals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    After each scored session, record what we got wrong and what to adjust next time.
    Appends to mistake_lessons.jsonl and returns lessons for the daily report.
    """
    if not new_evals:
        return []

    lessons: List[Dict[str, Any]] = []
    by_target: Dict[str, List[Dict[str, Any]]] = {}
    for row in new_evals:
        if row.get("horizon") != "day_1":
            continue
        by_target.setdefault(str(row["target_date"]), []).append(row)

    for target_date, rows in by_target.items():
        crude_row = next((r for r in rows if r["product"] == "Crude_Oil"), None)
        gas_row = next((r for r in rows if r["product"] == "RBOB_Gasoline"), None)
        if not gas_row or gas_row.get("direction_correct"):
            continue

        drivers = gas_row.get("drivers_at_issue") or {}
        if isinstance(drivers, str):
            try:
                drivers = json.loads(drivers)
            except Exception:
                drivers = {}

        crude_1d = drivers.get("crude_1d_pct")
        prod_1d = drivers.get("product_1d_pct")
        div_pp = drivers.get("cross_divergence_pp")
        crude_actual_up = crude_row and crude_row.get("actual_direction") == "UP"
        gas_pred_up = gas_row.get("predicted_direction") == "UP"
        gas_actual_down = gas_row.get("actual_direction") == "DOWN"

        pattern = None
        lesson_text = None
        action = None

        if (
            gas_pred_up
            and gas_actual_down
            and crude_1d is not None
            and prod_1d is not None
            and float(crude_1d) >= 1.0
            and float(prod_1d) <= 0.35
        ):
            pattern = "crude_up_gas_down"
            gap = float(div_pp or (float(crude_1d) - float(prod_1d)))
            lesson_text = (
                f"Called RBOB UP but gasoline sold off while crude was bid "
                f"(crude {float(crude_1d):+.1f}%, gas {float(prod_1d):+.1f}%, gap {gap:.1f}pp)."
            )
            action = "boost crude_gas_divergence overlay; reduce crude spillover into RBOB"
        elif gas_pred_up and gas_actual_down and crude_actual_up:
            pattern = "crude_up_gas_down_session"
            lesson_text = (
                "Session divergence: crude finished UP but RBOB finished DOWN — "
                "products do not always follow crude on geo/distillate-led days."
            )
            action = "tag crude_gas_divergence regime; learn blend_boost from this miss"

        if not pattern:
            continue

        entry = {
            "logged_at": datetime.now().isoformat(),
            "target_date": target_date,
            "issued_date": gas_row.get("issued_date"),
            "pattern": pattern,
            "product": "RBOB_Gasoline",
            "predicted_direction": gas_row.get("predicted_direction"),
            "actual_direction": gas_row.get("actual_direction"),
            "error_pct": gas_row.get("error_pct"),
            "crude_1d_pct": crude_1d,
            "product_1d_pct": prod_1d,
            "cross_divergence_pp": div_pp,
            "lesson": lesson_text,
            "action": action,
        }
        lessons.append(entry)

    if lessons:
        os.makedirs(os.path.dirname(MISTAKE_LESSONS_PATH) or "data", exist_ok=True)
        with open(MISTAKE_LESSONS_PATH, "a", encoding="utf-8") as f:
            for entry in lessons:
                f.write(json.dumps(entry, default=str) + "\n")

    return lessons


def _rank_variables(
    new_evals: List[Dict[str, Any]],
    df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Rank influential variables from model importance + error correlation."""
    ranked: Dict[str, Any] = {"updated_at": datetime.now().isoformat(), "products": {}}

    # XGB feature importance (optional — trains a model, can be slow)
    if os.getenv("SKIP_XGB_IMPORTANCE", "true").lower() not in ("1", "true", "yes"):
        try:
            from rbob_xgb_model import get_feature_importance_scores
            xgb_imp = get_feature_importance_scores(df)
            if xgb_imp:
                ranked["rbob_xgb"] = xgb_imp
        except Exception:
            pass
    elif os.path.exists(FEATURE_IMPORTANCE_PATH):
        try:
            with open(FEATURE_IMPORTANCE_PATH, encoding="utf-8") as f:
                prior = json.load(f)
            if prior.get("rbob_xgb"):
                ranked["rbob_xgb"] = prior["rbob_xgb"]
        except Exception:
            pass

    # Error-correlation ranking per product from evaluation history
    log = _load_eval_log()
    if new_evals:
        new_df = pd.DataFrame(new_evals)
        log = pd.concat([log, new_df], ignore_index=True) if not log.empty else new_df

    driver_keys = [
        "inventory_wow_pct",
        "sentiment",
        "geo_risk_score",
        "dxy_change_pct",
        "gasoline_crack",
        "diesel_crack",
        "layer_composite",
        "model_next_day_pct",
    ]

    for product in PRODUCT_COLUMNS:
        if log.empty:
            continue
        sub = log[log["product"] == product].tail(30)
        if len(sub) < 2:
            continue

        scores: List[Tuple[str, float]] = []
        for dk in driver_keys:
            vals, errs = [], []
            for _, r in sub.iterrows():
                drivers = r.get("drivers_at_issue")
                if isinstance(drivers, str):
                    try:
                        drivers = json.loads(drivers.replace("'", '"'))
                    except Exception:
                        drivers = {}
                if not isinstance(drivers, dict):
                    continue
                v = drivers.get(dk)
                if v is None or (isinstance(v, float) and np.isnan(v)):
                    continue
                vals.append(float(v))
                errs.append(float(r["error_pct"]))
            if len(vals) >= 3:
                corr = float(np.corrcoef(vals, errs)[0, 1])
                if not np.isnan(corr):
                    scores.append((dk, abs(corr)))

        scores.sort(key=lambda x: x[1], reverse=True)
        ranked["products"][product] = {
            "error_correlation_rank": [{"variable": k, "score": round(s, 4)} for k, s in scores[:8]],
        }

    # Merge with prior scores (EMA)
    if os.path.exists(FEATURE_IMPORTANCE_PATH):
        try:
            with open(FEATURE_IMPORTANCE_PATH, encoding="utf-8") as f:
                prior = json.load(f)
            alpha = 0.35
            if "rbob_xgb" in prior and "rbob_xgb" in ranked:
                merged = {}
                all_keys = set(prior["rbob_xgb"]) | set(ranked["rbob_xgb"])
                for k in all_keys:
                    old = float(prior["rbob_xgb"].get(k, 0))
                    new = float(ranked["rbob_xgb"].get(k, old))
                    merged[k] = round(alpha * new + (1 - alpha) * old, 4)
                ranked["rbob_xgb"] = dict(sorted(merged.items(), key=lambda x: x[1], reverse=True))
        except Exception:
            pass

    return ranked


def compute_error_adjustments(evaluations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Rolling mean signed error (%): positive = model overshot actual.
    Future forecasts subtract this bias.
    """
    log = _load_eval_log()
    if evaluations:
        rows = []
        for e in evaluations:
            row = dict(e)
            row["drivers_at_issue"] = json.dumps(e.get("drivers_at_issue") or {})
            rows.append(row)
        new_df = pd.DataFrame(rows)
        log = pd.concat([log, new_df], ignore_index=True) if not log.empty else new_df
        log.to_csv(EVAL_LOG_PATH, index=False)

    adjustments: Dict[str, Any] = {
        "updated_at": datetime.now().isoformat(),
        "products": {},
        "note": "bias_pct = mean(pred-actual)/actual*100; subtracted from future % change",
    }

    if log.empty:
        return adjustments

    for product in PRODUCT_COLUMNS:
        adjustments["products"][product] = {}
        sub = log[log["product"] == product]
        for hkey, days in EVAL_HORIZONS:
            hsub = sub[sub["horizon"] == hkey].tail(14)
            if len(hsub) < 1:
                continue
            bias = float(hsub["error_pct"].mean())
            mae = float(hsub["abs_error_pct"].mean())
            hit_rate = float(hsub["direction_correct"].mean()) if "direction_correct" in hsub.columns else None
            adjustments["products"][product][hkey] = {
                "bias_pct": round(bias, 3),
                "mae_pct": round(mae, 3),
                "direction_hit_rate": round(hit_rate, 3) if hit_rate is not None else None,
                "n_samples": len(hsub),
            }

    with open(ERROR_ADJUSTMENTS_PATH, "w", encoding="utf-8") as f:
        json.dump(adjustments, f, indent=2)
    return adjustments


SCORECARD_PATH = "data/forecast_scorecard.json"


def compute_forecast_scorecard() -> Dict[str, Any]:
    """Honest live scorecard from the eval log, per product x horizon:
      mae_pct / naive_mae_pct  model error vs "price stays at the settle" (skill > 0 = better)
      cover80 / cover95        share of actuals inside the issued 80% / 95% ranges
                               (should be ~0.80 / ~0.95; only rows issued with ranges)
    """
    out: Dict[str, Any] = {"updated_at": datetime.now().isoformat(), "products": {}}
    if not os.path.exists(EVAL_LOG_PATH):
        return out
    log = pd.read_csv(EVAL_LOG_PATH)
    for product in PRODUCT_COLUMNS:
        out["products"][product] = {}
        for hkey, _ in EVAL_HORIZONS:
            sub = log[(log["product"] == product) & (log["horizon"] == hkey)].tail(60)
            if sub.empty:
                continue
            mae = float(sub["abs_error_pct"].mean())
            spot = pd.to_numeric(sub["spot_at_issue"], errors="coerce")
            act = pd.to_numeric(sub["actual"], errors="coerce")
            naive_rows = (spot - act).abs() / act * 100  # derivable for older rows too
            if "naive_abs_error_pct" in sub:
                naive_rows = pd.to_numeric(sub["naive_abs_error_pct"], errors="coerce").fillna(naive_rows)
            naive = float(naive_rows.mean())
            stats: Dict[str, Any] = {"n": int(len(sub)), "mae_pct": round(mae, 3)}
            if pd.notna(naive) and naive > 0:
                stats["naive_mae_pct"] = round(float(naive), 3)
                stats["skill_vs_naive"] = round(1 - mae / float(naive), 3)
            for lvl in ("80", "95"):
                col = f"in_range_{lvl}"
                if col in sub:
                    v = sub[col].map({True: 1.0, False: 0.0, "True": 1.0, "False": 0.0}).dropna()
                    if len(v):
                        stats[f"cover{lvl}"] = round(float(v.mean()), 3)
                        stats[f"n_ranged_{lvl}"] = int(len(v))
            out["products"][product][hkey] = stats
    with open(SCORECARD_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    return out


def build_post_mortem_report(new_evals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Assemble daily post-mortem report JSON."""
    try:
        compute_forecast_scorecard()
    except Exception as e:  # never block the post-mortem
        print(f"  Scorecard skipped: {e}")
    from model_weights import compute_model_metrics, update_weights_from_evaluations

    explanations = [_explain_row(r) for r in new_evals]
    mistake_lessons = learn_from_prediction_mistakes(new_evals)
    importance = _rank_variables(new_evals)
    adjustments = compute_error_adjustments(new_evals)
    model_metrics = compute_model_metrics()
    updated_weights = update_weights_from_evaluations(new_evals)

    attribution_summary = {}
    try:
        from prediction_attribution import run_daily_attribution
        attribution_summary = run_daily_attribution(new_evals)
        for att in attribution_summary.get("latest_attributions") or []:
            if att.get("narrative") and att["narrative"] not in explanations:
                explanations.append(att["narrative"])
    except Exception as exc:
        attribution_summary = {"error": str(exc)}

    summary = {
        "generated_at": datetime.now().isoformat(),
        "evaluations_count": len(new_evals),
        "evaluations": new_evals,
        "explanations": explanations,
        "feature_importance": importance,
        "error_adjustments": adjustments,
        "model_metrics": model_metrics,
        "ensemble_weights": updated_weights,
        "attribution": attribution_summary,
        "mistake_lessons": mistake_lessons,
    }

    if new_evals:
        hits = sum(1 for e in new_evals if e["direction_correct"])
        summary["direction_accuracy"] = round(hits / len(new_evals), 3)
        summary["mean_abs_error_pct"] = round(
            float(np.mean([e["abs_error_pct"] for e in new_evals])), 3
        )
    else:
        summary["direction_accuracy"] = None
        summary["mean_abs_error_pct"] = None
        summary["message"] = "No mature forecasts to evaluate yet (need archived predictions + elapsed horizons)."

    with open(FEATURE_IMPORTANCE_PATH, "w", encoding="utf-8") as f:
        json.dump(importance, f, indent=2)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    try:
        from database import init_db, log_outcome, upsert_model_performance
        init_db()
        for ev in new_evals:
            log_outcome(
                ev["issued_date"],
                ev["target_date"],
                ev["product"],
                ev["horizon"],
                float(ev["predicted"]),
                float(ev["actual"]),
                bool(ev["direction_correct"]),
            )
        for product, horizons in (model_metrics.get("products") or {}).items():
            for hkey, stats in horizons.items():
                upsert_model_performance(
                    "ensemble_stack",
                    product,
                    hkey,
                    float(stats.get("mae", 0)),
                    float(stats.get("rmse", 0)),
                    float(stats.get("direction_accuracy", 0)),
                    float(stats.get("bias_pct", 0)),
                    int(stats.get("n_samples", 0)),
                )
    except Exception:
        pass

    return summary


def run_daily_post_mortem(verbose: bool = True) -> Dict[str, Any]:
    """Main entry: evaluate, report, rank variables, update adjustments."""
    new_evals = evaluate_mature_predictions()
    report = build_post_mortem_report(new_evals)

    if verbose:
        print("\n" + "=" * 60)
        print("DAILY POST-MORTEM")
        print("=" * 60)
        if not new_evals:
            print(report.get("message", "Nothing to evaluate."))
            att = report.get("attribution") or {}
            if att.get("latest_attributions"):
                print(f"Attribution refreshed ({len(att.get('latest_attributions') or [])} recent forecasts)")
                for item in (att.get("latest_attributions") or [])[-3:]:
                    if item.get("narrative"):
                        print(f"  - {item['narrative'][:140]}")
            top_miss = att.get("top_missed_factors_day1") or []
            if top_miss:
                print("Top missed factors (day 1):", ", ".join(
                    f"{m['label']} ({m['count']})" for m in top_miss[:4]
                ))
            acc = att.get("accuracy_by_product") or {}
            if acc:
                for pk, stats in acc.items():
                    print(
                        f"  Track {stats['label']}: day-1 direction {stats['day1_direction_pct']}% "
                        f"(MAE {stats['day1_mae_pct']}%, n={stats['samples']})"
                    )
        else:
            print(f"Evaluated {len(new_evals)} forecast(s)")
            print(f"Direction accuracy: {report.get('direction_accuracy', 0):.0%}")
            print(f"Mean abs error: {report.get('mean_abs_error_pct', 0):.2f}%")
            for line in report.get("explanations", [])[:8]:
                print(f"  - {line}")
            for lesson in (report.get("mistake_lessons") or [])[:3]:
                print(f"  [learn] {lesson.get('lesson')} → {lesson.get('action')}")
            att = report.get("attribution") or {}
            top_miss = att.get("top_missed_factors_day1") or []
            if top_miss:
                print("Top missed factors (day 1):", ", ".join(
                    f"{m['label']} ({m['count']})" for m in top_miss[:4]
                ))
            acc = att.get("accuracy_by_product") or {}
            if acc:
                for pk, stats in acc.items():
                    print(
                        f"  Track {stats['label']}: day-1 direction {stats['day1_direction_pct']}% "
                        f"(MAE {stats['day1_mae_pct']}%, n={stats['samples']})"
                    )
            top = (report.get("feature_importance") or {}).get("rbob_xgb") or {}
            if top:
                items = list(top.items())[:5]
                print("Top RBOB model features:", ", ".join(f"{k} ({v:.2f})" for k, v in items))
        print(f"Report saved: {REPORT_PATH}")

    return report


def load_error_adjustments() -> Dict[str, Any]:
    if not os.path.exists(ERROR_ADJUSTMENTS_PATH):
        return {}
    try:
        with open(ERROR_ADJUSTMENTS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def apply_bias_to_predictions(results: Dict[str, Any]) -> Dict[str, Any]:
    """Subtract rolling bias from raw horizon prices before JSON export."""
    from forecast_horizons import LEGACY_ALIASES, max_frac_for

    adj = load_error_adjustments()
    products = adj.get("products") or {}
    if not products:
        return results

    day1_bias_factor = float(os.getenv("DAY1_BIAS_FACTOR", "0.40"))
    day1_retain_floor = float(os.getenv("DAY1_BIAS_RETAIN_FLOOR", "0.70"))

    for product, block in results.items():
        if product.startswith("_") or not isinstance(block, dict):
            continue
        padj = products.get(product) or {}
        current = float(block.get("current_price", 0) or 0)
        if current <= 0:
            continue
        for hkey, _days, max_frac, _label in PREDICTION_HORIZONS:
            if hkey not in padj or hkey not in block:
                continue
            max_frac = max_frac_for(hkey, product)
            try:
                price = float(block[hkey])
            except (TypeError, ValueError):
                continue
            bias_pct = float(padj[hkey].get("bias_pct", 0))
            if hkey == "day_1":
                raw_chg = (price - current) / current * 100.0
                # Gap/shock days: barely shrink the signal
                local_factor = day1_bias_factor
                if float(block.get("_day1_cap_mult") or 1.0) >= 1.5:
                    local_factor *= 0.45
                bias_adj = bias_pct * local_factor
                new_chg = raw_chg - bias_adj
                if abs(raw_chg) >= 0.55 and raw_chg * bias_adj > 0:
                    min_mag = abs(raw_chg) * day1_retain_floor
                    if abs(new_chg) < min_mag:
                        new_chg = min_mag * (1.0 if raw_chg > 0 else -1.0)
                # Don't let historical bias flip day-1 direction on a clear signal
                if abs(raw_chg) >= 0.25 and raw_chg * new_chg < 0:
                    new_chg = abs(raw_chg) * day1_retain_floor * (1.0 if raw_chg > 0 else -1.0)
                cap_pct = max_frac * 100.0 * float(block.get("_day1_cap_mult") or 1.0)
                new_chg = max(-cap_pct, min(new_chg, cap_pct))
                block[hkey] = current * (1.0 + new_chg / 100.0)
            else:
                adjusted = price * (1 - bias_pct / 100.0)
                lo = current * (1 - max_frac)
                hi = current * (1 + max_frac)
                block[hkey] = max(lo, min(adjusted, hi))
            chg = ((block[hkey] - current) / current * 100) if current else 0
            block[f"{hkey}_change"] = float(chg)
            block[f"{hkey}_direction"] = "UP" if chg > 0 else "DOWN" if chg < 0 else "FLAT"
            for old_key, new_key in LEGACY_ALIASES.items():
                if new_key == hkey:
                    block[old_key] = block[hkey]
                    block[f"{old_key}_change"] = block[f"{hkey}_change"]
                    block[f"{old_key}_direction"] = block[f"{hkey}_direction"]

    return results
