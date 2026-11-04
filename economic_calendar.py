"""
RBOB / ULSD catalyst calendar: EIA WPSR, API Tuesday, CPI/PPI/PCE, NFP, FOMC.

Used as model features (hours-to-print, inventory surprise z-score), not as a
literal "actual > forecast = bullish" rule. Inventory consensus is the trailing
8-week median kbbl change when a street survey is not on file.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore

OUT_PATH = "data/economic_calendar.json"
INVENTORY_PATH = "data/inventory.csv"

# Explicit window from the Gill Energy 30-day list + FOMC just after the cutoff.
NAMED_EVENTS: List[Dict[str, Any]] = [
    {"date": "2026-08-12", "time_et": "08:30", "event_id": "cpi", "report": "CPI — July", "importance": 8},
    {"date": "2026-08-12", "time_et": "10:30", "event_id": "eia", "report": "EIA Petroleum Inventories", "importance": 10},
    {"date": "2026-08-18", "time_et": "16:30", "event_id": "api", "report": "API Weekly Petroleum Stocks", "importance": 8},
    {"date": "2026-08-19", "time_et": "10:30", "event_id": "eia", "report": "EIA Petroleum Inventories", "importance": 10},
    {"date": "2026-08-19", "time_et": "14:00", "event_id": "fomc_minutes", "report": "FOMC Minutes", "importance": 6},
    {"date": "2026-08-20", "time_et": "08:30", "event_id": "claims", "report": "Initial Jobless Claims", "importance": 3},
    {"date": "2026-08-25", "time_et": "16:30", "event_id": "api", "report": "API Weekly Petroleum Stocks", "importance": 8},
    {"date": "2026-08-26", "time_et": "10:30", "event_id": "eia", "report": "EIA Petroleum Inventories", "importance": 10},
    {"date": "2026-08-27", "time_et": "08:30", "event_id": "claims", "report": "Initial Jobless Claims", "importance": 3},
    {"date": "2026-08-28", "time_et": "08:30", "event_id": "pce", "report": "PCE Price Index", "importance": 7},
    {"date": "2026-09-01", "time_et": "16:30", "event_id": "api", "report": "API Weekly Petroleum Stocks", "importance": 8},
    {"date": "2026-09-02", "time_et": "10:30", "event_id": "eia", "report": "EIA Petroleum Inventories", "importance": 10},
    {"date": "2026-09-03", "time_et": "08:30", "event_id": "claims", "report": "Initial Jobless Claims", "importance": 3},
    {"date": "2026-09-04", "time_et": "08:30", "event_id": "nfp", "report": "Employment Situation / NFP", "importance": 6},
    {"date": "2026-09-10", "time_et": "08:30", "event_id": "ppi", "report": "PPI — August", "importance": 7},
    {
        "date": "2026-09-10",
        "time_et": "12:00",
        "event_id": "eia",
        "report": "EIA Weekly Petroleum Inventories (Labor Day week)",
        "importance": 10,
        "note": "Week ending Sep 4 released Thursday 12:00 PM ET, not Wednesday 10:30.",
    },
    {"date": "2026-09-11", "time_et": "08:30", "event_id": "cpi", "report": "CPI — August", "importance": 8},
    {"date": "2026-09-16", "time_et": "14:00", "event_id": "fomc", "report": "FOMC statement / press conference", "importance": 8},
]

# Labor Day 2026: skip the usual Tue API / Wed EIA that week.
SKIP_RECURRING = {
    ("api", "2026-09-08"),
    ("eia", "2026-09-09"),
}

# Recurring generation window beyond the named 30-day list
RECUR_START = "2026-08-12"
RECUR_END = "2026-12-31"

# Product lean if inventory print is below the typical weekly change (draw surprise).
# Standardized surprise = (actual_kbbl_chg - 8w median) / historical vol.
# Negative z = more draw / less build than typical → bullish for that product.
SURPRISE_WEIGHT = {
    "RBOB_Gasoline": {"gasoline": 1.00, "distillate": 0.25, "crude": 0.55},
    "ULSD_Diesel": {"gasoline": 0.25, "distillate": 1.00, "crude": 0.55},
    "Crude_Oil": {"gasoline": 0.20, "distillate": 0.20, "crude": 1.00},
}

MACRO_IDS = {"cpi", "ppi", "pce", "nfp", "fomc", "fomc_minutes", "claims"}


def _now_et() -> datetime:
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo("US/Eastern"))
    return datetime.now()


def _event_dt(date_str: str, time_et: str) -> datetime:
    hh, mm = (time_et or "10:30").split(":")[:2]
    naive = datetime.strptime(f"{date_str} {int(hh):02d}:{int(mm):02d}", "%Y-%m-%d %H:%M")
    if ZoneInfo is not None:
        return naive.replace(tzinfo=ZoneInfo("US/Eastern"))
    return naive


def _recurring_events(start: str, end: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    d = datetime.strptime(start, "%Y-%m-%d").date()
    last = datetime.strptime(end, "%Y-%m-%d").date()
    while d <= last:
        ds = d.isoformat()
        wd = d.weekday()
        if wd == 1 and ("api", ds) not in SKIP_RECURRING:
            out.append({
                "date": ds,
                "time_et": "16:30",
                "event_id": "api",
                "report": "API Weekly Petroleum Stocks",
                "importance": 8,
            })
        if wd == 2 and ("eia", ds) not in SKIP_RECURRING:
            out.append({
                "date": ds,
                "time_et": "10:30",
                "event_id": "eia",
                "report": "EIA Petroleum Inventories",
                "importance": 10,
            })
        if wd == 3:
            out.append({
                "date": ds,
                "time_et": "08:30",
                "event_id": "claims",
                "report": "Initial Jobless Claims",
                "importance": 3,
            })
        d += timedelta(days=1)
    return out


def _event_key(ev: Dict[str, Any]) -> Tuple[str, str, str]:
    return (ev["date"], ev["time_et"], ev["event_id"])


def all_events() -> List[Dict[str, Any]]:
    """Named 30-day list plus recurring EIA/API/claims through year-end."""
    merged: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for ev in _recurring_events(RECUR_START, RECUR_END):
        merged[_event_key(ev)] = dict(ev)
    for ev in NAMED_EVENTS:
        merged[_event_key(ev)] = dict(ev)
    rows = list(merged.values())
    rows.sort(key=lambda e: (e["date"], e["time_et"], e["event_id"]))
    for ev in rows:
        ev.setdefault("rbob_weight", 10 if ev["event_id"] == "eia" else 8 if ev["event_id"] == "api" else 6 if ev["event_id"] in MACRO_IDS else 3)
        ev.setdefault("ulsd_weight", ev["rbob_weight"])
        ev["if_hotter_or_build"] = (
            "bearish via Fed/USD (macro can be overwhelmed by oil fundamentals)"
            if ev["event_id"] in MACRO_IDS
            else "gas/distillate/crude build vs typical week = bearish products"
        )
        ev["if_cooler_or_draw"] = (
            "generally bullish via USD/crude, unless inventory story dominates"
            if ev["event_id"] in MACRO_IDS
            else "draw vs typical week = bullish (gasoline for RBOB, distillate for ULSD)"
        )
    return rows


def _inventory_surprises(csv_path: str = INVENTORY_PATH) -> Dict[str, Any]:
    """
    Surprise = latest WoW kbbl change − 8-week median of prior changes.
    Standardized = surprise / std of prior 16 weekly changes.
    Negative z (more of a draw than typical) is bullish for that product.
    """
    empty = {"gasoline": None, "distillate": None, "crude": None, "as_of": None}
    if not os.path.exists(csv_path):
        return empty
    df = pd.read_csv(csv_path)
    if df.empty:
        return empty
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    cols = {
        "gasoline": "gasoline_inventory",
        "distillate": "diesel_inventory",
        "crude": "crude_inventory",
    }
    out: Dict[str, Any] = {"as_of": df["date"].iloc[-1].strftime("%Y-%m-%d")}
    for name, col in cols.items():
        if col not in df.columns or len(df) < 3:
            out[name] = None
            continue
        levels = df[col].astype(float)
        chg = levels.diff().dropna()
        if len(chg) < 3:
            out[name] = None
            continue
        actual = float(chg.iloc[-1])
        hist = chg.iloc[:-1]
        consensus = float(hist.tail(8).median())
        vol = float(hist.tail(16).std(ddof=1) or 0.0)
        surprise = actual - consensus
        z = surprise / vol if vol and vol > 1e-6 else 0.0
        actual_pct = None
        prev = float(levels.iloc[-2])
        if prev:
            actual_pct = actual / prev * 100.0
        out[name] = {
            "actual_kbbl": round(actual, 1),
            "consensus_kbbl": round(consensus, 1),
            "surprise_kbbl": round(surprise, 1),
            "z_score": round(z, 3),
            "wow_pct": round(actual_pct, 3) if actual_pct is not None else None,
            "rule": "z<0 (draw vs typical) bullish; z>0 (build vs typical) bearish",
        }
    return out


def _composite_z(surprises: Dict[str, Any], product_key: str) -> Optional[float]:
    wmap = SURPRISE_WEIGHT.get(product_key) or {}
    num = 0.0
    den = 0.0
    for series, w in wmap.items():
        row = surprises.get(series)
        if not row or row.get("z_score") is None:
            continue
        num += w * max(-3.0, min(3.0, float(row["z_score"])))
        den += w
    if den <= 0:
        return None
    return num / den


def _hours(now: datetime, ev: Dict[str, Any]) -> float:
    dt = _event_dt(ev["date"], ev["time_et"])
    if now.tzinfo is None and dt.tzinfo is not None:
        now = now.replace(tzinfo=dt.tzinfo)
    return (dt - now).total_seconds() / 3600.0


def _direction_from_z(z: float) -> str:
    if z <= -0.75:
        return "BULLISH"
    if z >= 0.75:
        return "BEARISH"
    return "WAIT"


def build_catalyst_snapshot(
    now: Optional[datetime] = None,
    inventory_csv: str = INVENTORY_PATH,
    upcoming_n: int = 8,
) -> Dict[str, Any]:
    """Feature pack for day-1 gap risk, ensemble, email, and attribution."""
    now = now or _now_et()
    events = all_events()
    upcoming = [e for e in events if _hours(now, e) >= -0.25]
    upcoming.sort(key=lambda e: _hours(now, e))
    next_ev = upcoming[0] if upcoming else None
    next_high = next((e for e in upcoming if int(e.get("importance") or 0) >= 7), None)

    last_past = [e for e in events if _hours(now, e) < -0.25]
    last_print = last_past[-1] if last_past else None

    hours_to = _hours(now, next_ev) if next_ev else None
    hours_since = -_hours(now, last_print) if last_print else None
    surprises = _inventory_surprises(inventory_csv)

    gap_bump = 0.0
    gap_reasons: List[str] = []
    focus = next_high or next_ev
    if focus and hours_to is not None:
        imp = int(focus.get("importance") or 0)
        label = focus.get("report")
        when = f"{focus['date']} {focus['time_et']} ET"
        if imp >= 8 and hours_to <= 20:
            gap_bump = max(gap_bump, 0.35)
            gap_reasons.append(f"{label} in {hours_to:.0f}h ({when})")
        elif imp >= 6 and hours_to <= 8:
            gap_bump = max(gap_bump, 0.22)
            gap_reasons.append(f"{label} in {hours_to:.0f}h")
    if last_print and hours_since is not None:
        imp = int(last_print.get("importance") or 0)
        if imp >= 8 and hours_since <= 8:
            gap_bump = max(gap_bump, 0.20)
            gap_reasons.append(f"just printed: {last_print.get('report')}")

    product_features: Dict[str, Any] = {}
    for pk in ("RBOB_Gasoline", "ULSD_Diesel", "Crude_Oil"):
        z = _composite_z(surprises, pk)
        fresh = False
        if last_print and last_print.get("event_id") == "eia" and hours_since is not None:
            fresh = hours_since <= 72
        elif surprises.get("as_of"):
            # Inventory week-ending date is typically last Friday; treat as usable for ~5 sessions.
            try:
                age = (now.date() - datetime.strptime(str(surprises["as_of"])[:10], "%Y-%m-%d").date()).days
                fresh = age <= 8
            except Exception:
                fresh = False
        lean = "WAIT"
        nudge = 0.0
        conf = 35
        if z is not None and fresh:
            lean = _direction_from_z(z)
            # Negative z (draw vs typical) → positive day-1 nudge
            if abs(z) >= 0.50:
                nudge = max(-0.45, min(0.45, -z * 0.18))
                conf = min(80, 40 + int(abs(z) * 18))
        product_features[pk] = {
            "inventory_z": round(z, 3) if z is not None else None,
            "lean": lean,
            "day1_nudge_pct": round(nudge, 4),
            "confidence": conf,
            "fresh_print": fresh,
        }

    upcoming_out = []
    for e in upcoming[:upcoming_n]:
        item = dict(e)
        item["hours_to"] = round(_hours(now, e), 2)
        upcoming_out.append(item)

    return {
        "as_of_et": now.strftime("%Y-%m-%d %H:%M"),
        "next": ({**next_ev, "hours_to": round(hours_to, 2)} if next_ev and hours_to is not None else None),
        "next_high_impact": (
            {**next_high, "hours_to": round(_hours(now, next_high), 2)} if next_high else None
        ),
        "upcoming": upcoming_out,
        "inventory_surprise": surprises,
        "product_features": product_features,
        "gap_bump": round(gap_bump, 3),
        "gap_reasons": gap_reasons,
        "modeling_rule": (
            "Do not map actual>forecast to direction. Use Surprise = actual − typical week, "
            "then z = surprise / historical vol. Inventory z<0 (draw vs typical) is bullish."
        ),
    }


def save_calendar_json(path: str = OUT_PATH) -> Dict[str, Any]:
    snap = build_catalyst_snapshot()
    snap["events"] = all_events()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=2)
    return snap


def event_intel_block(snap: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    snap = snap or build_catalyst_snapshot()
    nxt = snap.get("next_high_impact") or snap.get("next") or {}
    products = snap.get("product_features") or {}
    return {
        "status": "calendar",
        "note": snap.get("modeling_rule"),
        "next": nxt,
        "upcoming": snap.get("upcoming") or [],
        "inventory_surprise": snap.get("inventory_surprise") or {},
        "rbob": products.get("RBOB_Gasoline"),
        "ulsd": products.get("ULSD_Diesel"),
        "crude": products.get("Crude_Oil"),
        "gap_bump": snap.get("gap_bump"),
        "gap_reasons": snap.get("gap_reasons") or [],
    }


if __name__ == "__main__":
    s = save_calendar_json()
    nxt = s.get("next") or {}
    print(f"Saved {OUT_PATH}")
    print(f"Next: {nxt.get('report')} {nxt.get('date')} {nxt.get('time_et')} ET ({nxt.get('hours_to')}h)")
    print(f"Gap bump: {s.get('gap_bump')} {s.get('gap_reasons')}")
    for pk, feat in (s.get("product_features") or {}).items():
        print(f"  {pk}: z={feat.get('inventory_z')} {feat.get('lean')} nudge={feat.get('day1_nudge_pct')}")
