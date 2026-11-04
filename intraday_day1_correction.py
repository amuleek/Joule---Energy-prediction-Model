"""
Intraday day-1 correction: when live NYMEX tape gaps >=2% opposite the
morning email, refresh predictions and send a CORRECTED email.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from config import INTRADAY_DAY1_CONFIG
except ImportError:
    INTRADAY_DAY1_CONFIG = {
        "enabled": True,
        "tape_flip_pct": 2.0,
        "window_start_hour_et": 8,
        "window_end_hour_et": 14,
        "window_end_minute_et": 30,
    }

from weekend_day1_email import (
    PRODUCTS,
    enrich_email_meta,
    extract_day1_snapshot,
    load_last_sent_day1,
    save_last_sent_day1,
    detect_day1_direction_flip,
)

INTRADAY_STATE_PATH = "data/last_intraday_correction.json"


def _sign_dir(pct: float, eps: float = 0.08) -> str:
    if pct > eps:
        return "UP"
    if pct < -eps:
        return "DOWN"
    return "FLAT"


def compute_live_gaps_by_product() -> Dict[str, float]:
    """Live % move vs last official NYMEX settle, keyed by product."""
    try:
        from live_prices import fetch_live_futures_closes, get_nymex_session_close

        live_cols = fetch_live_futures_closes()
        settles, _, _ = get_nymex_session_close()
        col_map = {
            "RBOB": "RBOB_Gasoline",
            "ULSD": "ULSD_Diesel",
            "Crude": "Crude_Oil",
        }
        out: Dict[str, float] = {}
        for col, pk in col_map.items():
            settle = settles.get(col)
            live = live_cols.get(col)
            if settle and live and float(settle) > 0:
                out[pk] = (float(live) / float(settle) - 1.0) * 100.0
        return out
    except Exception:
        return {}


def in_intraday_window() -> bool:
    """After morning email, before NYMEX pit close (~2:30 PM ET)."""
    try:
        from live_prices import _now_et

        now = _now_et()
        if now.weekday() >= 5:
            return False
        start_h = int(INTRADAY_DAY1_CONFIG.get("window_start_hour_et", 8))
        end_h = int(INTRADAY_DAY1_CONFIG.get("window_end_hour_et", 14))
        end_m = int(INTRADAY_DAY1_CONFIG.get("window_end_minute_et", 30))
        if now.hour < start_h:
            return False
        if now.hour > end_h or (now.hour == end_h and now.minute >= end_m):
            return False
        return True
    except Exception:
        return False


def load_intraday_correction_state() -> Optional[Dict[str, Any]]:
    if not os.path.exists(INTRADAY_STATE_PATH):
        return None
    try:
        with open(INTRADAY_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def mark_intraday_correction_sent(flip_info: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(INTRADAY_STATE_PATH) or "data", exist_ok=True)
    payload = {
        "sent_at": datetime.now().isoformat(),
        "target_date": flip_info.get("target_date"),
        "reason": "intraday_tape",
        "flips": flip_info.get("flips") or [],
        "tape_flips": flip_info.get("tape_flips") or [],
    }
    with open(INTRADAY_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def already_sent_intraday_correction(target_date: Optional[str]) -> bool:
    if not target_date:
        return False
    state = load_intraday_correction_state()
    return bool(state and state.get("target_date") == target_date)


def detect_intraday_tape_flip(
    last_sent: Optional[Dict[str, Any]] = None,
    *,
    threshold_pct: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """
    Live tape moved >=threshold opposite the last emailed day-1 direction.
    """
    last_sent = last_sent if last_sent is not None else load_last_sent_day1()
    if not last_sent:
        return None

    threshold = float(
        threshold_pct if threshold_pct is not None else INTRADAY_DAY1_CONFIG.get("tape_flip_pct", 2.0)
    )
    gaps = compute_live_gaps_by_product()
    if not gaps:
        return None

    prev_dirs = last_sent.get("directions") or {}
    tape_flips: List[Dict[str, Any]] = []
    for pk in PRODUCTS:
        emailed = prev_dirs.get(pk)
        gap = gaps.get(pk)
        if not emailed or gap is None or emailed == "FLAT":
            continue
        if emailed == "DOWN" and gap >= threshold:
            tape_flips.append(
                {
                    "product": pk,
                    "was": "DOWN",
                    "now": "UP",
                    "gap_pct": round(gap, 3),
                }
            )
        elif emailed == "UP" and gap <= -threshold:
            tape_flips.append(
                {
                    "product": pk,
                    "was": "UP",
                    "now": "DOWN",
                    "gap_pct": round(gap, 3),
                }
            )

    if not tape_flips:
        return None

    return {
        "reason": "intraday_tape",
        "target_date": last_sent.get("target_date"),
        "previous_sent_at": last_sent.get("sent_at"),
        "tape_flips": tape_flips,
        "flips": tape_flips,
        "live_gaps": {k: round(v, 3) for k, v in gaps.items()},
    }


def patch_day1_from_live_tape(
    predictions_json: Dict[str, Any],
    tape_flips: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Force day-1 direction/price to match live tape when models did not flip."""
    for flip in tape_flips:
        pk = flip.get("product")
        gap = float(flip.get("gap_pct") or 0)
        if not pk or pk not in predictions_json:
            continue
        block = predictions_json[pk]
        settle = float(block.get("current_price") or 0)
        if settle <= 0:
            continue
        keep = 0.92
        chg = gap * keep
        price = settle * (1.0 + chg / 100.0)
        direction = _sign_dir(chg)
        d1 = block.setdefault("day_1", {})
        d1["price"] = price
        d1["change_percent"] = chg
        d1["direction"] = direction
        if "next_day" in block:
            block["next_day"] = d1
    meta = predictions_json.setdefault("_meta", {})
    meta["intraday_tape_patch"] = True
    return predictions_json


def run_intraday_correction(engine, *, force: bool = False) -> bool:
    """
    If live tape flipped vs morning email, regenerate predictions and send CORRECTED email.
    Returns True when a correction email was sent.
    """
    if not INTRADAY_DAY1_CONFIG.get("enabled", True):
        return False
    if not force and not in_intraday_window():
        return False

    last_sent = load_last_sent_day1()
    tape_info = detect_intraday_tape_flip(last_sent)
    if not tape_info:
        return False

    target_date = tape_info.get("target_date")
    if already_sent_intraday_correction(target_date):
        print(f"\n[i] Intraday correction already sent for {target_date}")
        return False

    flips = tape_info.get("tape_flips") or []
    parts = [f"{f['product'].replace('_', ' ')} {f['was']}→{f['now']} ({f['gap_pct']:+.1f}%)" for f in flips]
    print("\n" + "=" * 60)
    print("INTRADAY TAPE CORRECTION")
    print("=" * 60)
    print(f"Live tape opposite morning email: {', '.join(parts)}")

    predictions = engine.generate_predictions(send_email=False)
    if not predictions:
        print("[!] Intraday correction: no predictions generated")
        return False

    flip_info = detect_day1_direction_flip(predictions, last_sent)
    if flip_info:
        flip_info["reason"] = "intraday_tape"
        flip_info["tape_flips"] = tape_info.get("tape_flips")
        flip_info["live_gaps"] = tape_info.get("live_gaps")
    else:
        predictions = patch_day1_from_live_tape(predictions, flips)
        flip_info = {
            "reason": "intraday_tape",
            "target_date": target_date,
            "previous_sent_at": last_sent.get("sent_at") if last_sent else None,
            "tape_flips": flips,
            "flips": flips,
            "live_gaps": tape_info.get("live_gaps"),
            "patched_from_live": True,
        }

    enrich_email_meta(predictions, flip_info)
    from weekend_day1_email import acquire_email_send_lock, release_email_send_lock

    if not acquire_email_send_lock():
        print("\n[i] Intraday correction skipped — another email send in progress")
        return False
    try:
        engine.send_prediction_email(predictions)
        save_last_sent_day1(predictions, correction=True)
        mark_intraday_correction_sent(flip_info)
    finally:
        release_email_send_lock()

    print(f"\n[OK] Intraday correction email sent for {target_date}")
    return True
