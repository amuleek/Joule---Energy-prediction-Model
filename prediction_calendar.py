"""
NYMEX session calendar: recent scored day-1 vs settle, plus a 10-session path ahead.

Past rows come from the eval log (predicted close vs actual settle).
Forward rows are interpolated from the published day-1 / day-4 / day-7 calls
onto the next 10 NYMEX sessions.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

EVAL_LOG = "data/prediction_eval_log.csv"
PREDICTIONS_PATH = "data/predictions.json"

PRODUCTS = (
    ("RBOB_Gasoline", "Gas", 4),
    ("ULSD_Diesel", "Diesel", 4),
    ("Crude_Oil", "Crude", 2),
)

DISPLAY = {
    "RBOB_Gasoline": "Gas",
    "ULSD_Diesel": "Diesel",
    "Crude_Oil": "Crude",
}


def _fmt_date(s: str) -> str:
    try:
        return pd.Timestamp(s).strftime("%a %b %d")
    except Exception:
        return str(s)


def _load_preds() -> Dict[str, Any]:
    if not os.path.exists(PREDICTIONS_PATH):
        return {}
    try:
        with open(PREDICTIONS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_day1_scored(n_days: int = 12) -> pd.DataFrame:
    if not os.path.exists(EVAL_LOG):
        return pd.DataFrame()
    df = pd.read_csv(EVAL_LOG)
    if df.empty:
        return pd.DataFrame()
    d1 = df[df["horizon"].astype(str) == "day_1"].copy()
    if d1.empty:
        return pd.DataFrame()
    d1["target_date"] = pd.to_datetime(d1["target_date"], errors="coerce")
    d1["issued_date"] = pd.to_datetime(d1["issued_date"], errors="coerce")
    d1 = d1.dropna(subset=["target_date", "product", "predicted", "actual"])
    d1 = d1[d1["target_date"].dt.weekday < 5]
    try:
        from live_prices import _now_et, _session_closed_for_date
        now_et = _now_et()
        closed = d1["target_date"].dt.date.map(lambda d: _session_closed_for_date(d, now_et))
        d1 = d1[closed]
    except Exception:
        # If session-clock is unavailable, never treat today as settled.
        today = pd.Timestamp.now().normalize()
        d1 = d1[d1["target_date"] < today]
    d1 = d1.sort_values(["target_date", "issued_date"])
    d1 = d1.drop_duplicates(subset=["target_date", "product"], keep="last")
    dates = sorted(d1["target_date"].unique())[-n_days:]
    return d1[d1["target_date"].isin(dates)]


def _next_session(preds: Optional[Dict[str, Any]] = None) -> pd.Timestamp:
    preds = preds if preds is not None else _load_preds()
    for pk, _, _ in PRODUCTS:
        d1 = (preds.get(pk) or {}).get("day_1") or {}
        if isinstance(d1, dict) and d1.get("target_date"):
            t = pd.Timestamp(d1["target_date"])
            if pd.notna(t):
                return t.normalize()
    as_of = str(((preds.get("_meta") or {}).get("spot_reference") or {}).get("as_of_date") or "")
    if as_of:
        return (pd.Timestamp(as_of) + pd.offsets.BDay(1)).normalize()
    t = pd.Timestamp.now().normalize() + pd.Timedelta(days=1)
    while t.weekday() >= 5:
        t += pd.Timedelta(days=1)
    return t


def _forward_session_dates(n: int, start: Optional[pd.Timestamp] = None) -> List[str]:
    t = start if start is not None else _next_session()
    out: List[str] = []
    while len(out) < n:
        if t.weekday() < 5:
            out.append(t.strftime("%Y-%m-%d"))
        t += pd.Timedelta(days=1)
    return out


def _interp_price(session_n: int, anchors: List[Tuple[int, float]]) -> Optional[float]:
    if not anchors:
        return None
    anchors = sorted((int(i), float(p)) for i, p in anchors if p is not None)
    if not anchors:
        return None
    if session_n <= anchors[0][0]:
        return anchors[0][1]
    if session_n >= anchors[-1][0]:
        if len(anchors) >= 2:
            x0, y0 = anchors[-2]
            x1, y1 = anchors[-1]
            if x1 != x0:
                return y1 + (y1 - y0) / (x1 - x0) * (session_n - x1)
        return anchors[-1][1]
    for i in range(len(anchors) - 1):
        x0, y0 = anchors[i]
        x1, y1 = anchors[i + 1]
        if x0 <= session_n <= x1:
            if x1 == x0:
                return y1
            t = (session_n - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return anchors[-1][1]


def _horizon_price(block: Dict[str, Any], key: str) -> Optional[float]:
    hd = block.get(key) or {}
    if isinstance(hd, dict) and hd.get("price") is not None:
        try:
            return float(hd["price"])
        except (TypeError, ValueError):
            return None
    return None


def _product_anchors(block: Dict[str, Any]) -> List[Tuple[int, float]]:
    out: List[Tuple[int, float]] = []
    for key, n in (("day_1", 1), ("day_4", 4), ("day_7", 7)):
        px = _horizon_price(block, key)
        if px is not None and px > 0:
            out.append((n, px))
    return out


def _scored_days(n_past: int) -> List[Dict[str, Any]]:
    scored = _load_day1_scored(n_days=n_past)
    rows: List[Dict[str, Any]] = []
    for _, r in scored.iterrows():
        pk = str(r["product"])
        dec = 2 if pk == "Crude_Oil" else 4
        pred = float(r["predicted"])
        actual = float(r["actual"])
        spot = float(r["spot_at_issue"]) if "spot_at_issue" in r and pd.notna(r.get("spot_at_issue")) else None
        pred_pct = ((pred / spot) - 1.0) * 100.0 if spot else None
        act_pct = ((actual / spot) - 1.0) * 100.0 if spot else None
        rows.append({
            "target_date": pd.Timestamp(r["target_date"]).strftime("%Y-%m-%d"),
            "product": pk,
            "display": DISPLAY.get(pk, pk),
            "predicted": round(pred, dec),
            "actual": round(actual, dec),
            "predicted_pct": round(pred_pct, 2) if pred_pct is not None else None,
            "actual_pct": round(act_pct, 2) if act_pct is not None else None,
            "direction_correct": bool(r.get("direction_correct")),
            "pending": False,
            "section": "past",
        })
    dates = sorted({r["target_date"] for r in rows})[-n_past:]
    by_date: List[Dict[str, Any]] = []
    for d in dates:
        cell: Dict[str, Any] = {"date": d, "label": _fmt_date(d), "section": "past", "products": {}}
        for r in rows:
            if r["target_date"] == d:
                cell["products"][r["product"]] = r
        if cell["products"]:
            by_date.append(cell)
    return by_date


def _future_days(n_forward: int, preds: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    preds = preds if preds is not None else _load_preds()
    dates = _forward_session_dates(n_forward, _next_session(preds))
    spot = ((preds.get("_meta") or {}).get("spot_reference") or {}).get("by_product") or {}
    by_date: List[Dict[str, Any]] = []
    for i, d in enumerate(dates, start=1):
        cell: Dict[str, Any] = {
            "date": d,
            "label": _fmt_date(d),
            "section": "future",
            "session_n": i,
            "products": {},
        }
        for pk, short, dec in PRODUCTS:
            block = preds.get(pk) or {}
            if not isinstance(block, dict):
                continue
            try:
                current = float(spot.get(pk) or block.get("current_price") or 0)
            except (TypeError, ValueError):
                current = 0.0
            px = _interp_price(i, _product_anchors(block))
            if px is None or px <= 0:
                continue
            pct = ((px / current) - 1.0) * 100.0 if current else None
            band = None
            params = block.get("baseline_params")
            if params and current:
                try:
                    from baseline_forecast import price_range
                    band = price_range(px, params, 80, sessions=i)  # centred on forecast
                except Exception:
                    band = None
            cell["products"][pk] = {
                "range_80": {k: round(v, dec) for k, v in band.items()} if band else None,
                "target_date": d,
                "product": pk,
                "display": short,
                "predicted": round(px, dec),
                "actual": None,
                "predicted_pct": round(pct, 2) if pct is not None else None,
                "actual_pct": None,
                "direction_correct": None,
                "pending": True,
                "section": "future",
            }
        if cell["products"]:
            by_date.append(cell)
    return by_date


def build_prediction_calendar(
    n_days: int = 4,
    n_past: Optional[int] = None,
    n_forward: int = 10,
) -> Dict[str, Any]:
    past_n = n_past if n_past is not None else n_days
    preds = _load_preds()
    past = _scored_days(past_n)
    future = _future_days(n_forward, preds)
    rows_for_stats = [
        r
        for day in past
        for r in (day.get("products") or {}).values()
        if not r.get("pending")
    ]
    hits = sum(1 for r in rows_for_stats if r.get("direction_correct"))
    n = len(rows_for_stats)
    by_product: Dict[str, Dict[str, Any]] = {}
    for pk, short, _dec in PRODUCTS:
        hits_p = sum(
            1 for r in rows_for_stats
            if r["product"] == pk and r.get("direction_correct")
        )
        n_p = sum(1 for r in rows_for_stats if r["product"] == pk)
        by_product[pk] = {
            "display": short,
            "n_scored": n_p,
            "direction_hit_rate": round(hits_p / n_p, 3) if n_p else None,
        }
    return {
        "past": past,
        "future": future,
        "days": past + future,
        "direction_hit_rate": round(hits / n, 3) if n else None,
        "n_scored": n,
        "by_product": by_product,
        "horizon": "path",
        "note": f"Last {past_n} settled sessions, then {n_forward} predicted NYMEX sessions.",
    }


if __name__ == "__main__":
    cal = build_prediction_calendar(n_past=4, n_forward=10)
    print(f"Past {len(cal['past'])} · ahead {len(cal['future'])} · dir hit {cal['direction_hit_rate']}")
    for day in cal["days"]:
        bits = []
        for pk, _, _ in PRODUCTS:
            p = (day["products"] or {}).get(pk)
            if not p:
                continue
            if p.get("pending"):
                bits.append(f"{p['display']} {p['predicted']}")
            else:
                mark = "✓" if p.get("direction_correct") else "✗"
                bits.append(f"{p['display']} {p['predicted']}/{p['actual']} {mark}")
        print(day["section"], day["label"], " · ".join(bits))
