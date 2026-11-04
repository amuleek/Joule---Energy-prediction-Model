"""
Weekend day-1 email policy: defer until Asia/Globex tape is readable,
and auto-send a correction when overnight gap flips direction vs last email.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    from config import WEEKEND_DAY1_CONFIG
except ImportError:
    WEEKEND_DAY1_CONFIG = {
        "asia_ready_hour_et": 20,
        "asia_ready_minute_et": 15,
        "defer_until_asia": True,
        "tape_gap_ready_pct": 1.0,
        "email_cooldown_minutes": 45,
        "dedupe_emails": True,
        "dedupe_price_pct": 0.20,
    }

LAST_SENT_PATH = "data/last_sent_day1.json"
EMAIL_LOCK_PATH = "data/day1_email.lock"
PRODUCTS = ("RBOB_Gasoline", "ULSD_Diesel", "Crude_Oil")
# Hard floor so scheduler + manual never double-fire in the same minute
MIN_SEND_GAP_SECONDS = 90
PRODUCT_TO_COL = {
    "RBOB_Gasoline": "RBOB",
    "ULSD_Diesel": "ULSD",
    "Crude_Oil": "Crude",
}


def _infer_target_date(predictions_json: Dict[str, Any]) -> Optional[str]:
    for pk in PRODUCTS:
        d1 = (predictions_json.get(pk) or {}).get("day_1") or {}
        if isinstance(d1, dict) and d1.get("target_date"):
            return str(d1["target_date"])[:10]
    as_of = str(
        ((predictions_json.get("_meta") or {}).get("spot_reference") or {}).get("as_of_date")
        or ""
    )
    if as_of:
        try:
            import pandas as pd

            t = pd.Timestamp(as_of) + pd.offsets.BDay(1)
            return t.strftime("%Y-%m-%d")
        except Exception:
            pass
    return None


def extract_day1_snapshot(predictions_json: Dict[str, Any]) -> Dict[str, Any]:
    """Day-1 directions/prices keyed by product."""
    directions: Dict[str, str] = {}
    prices: Dict[str, float] = {}
    change_pct: Dict[str, float] = {}
    target_date = _infer_target_date(predictions_json)
    for pk in PRODUCTS:
        d1 = (predictions_json.get(pk) or {}).get("day_1") or {}
        if not isinstance(d1, dict):
            continue
        directions[pk] = str(d1.get("direction") or "FLAT")
        if d1.get("price") is not None:
            prices[pk] = float(d1["price"])
        if d1.get("change_percent") is not None:
            change_pct[pk] = float(d1["change_percent"])
    return {
        "target_date": target_date,
        "directions": directions,
        "prices": prices,
        "change_pct": change_pct,
    }


def load_last_sent_day1() -> Optional[Dict[str, Any]]:
    if not os.path.exists(LAST_SENT_PATH):
        return None
    try:
        with open(LAST_SENT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_last_sent_day1(
    predictions_json: Dict[str, Any],
    *,
    correction: bool = False,
) -> None:
    snap = extract_day1_snapshot(predictions_json)
    os.makedirs(os.path.dirname(LAST_SENT_PATH) or "data", exist_ok=True)
    payload = {
        "sent_at": datetime.now().isoformat(),
        "target_date": snap.get("target_date"),
        "directions": snap.get("directions") or {},
        "prices": snap.get("prices") or {},
        "change_pct": snap.get("change_pct") or {},
        "correction": bool(correction),
    }
    with open(LAST_SENT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _overnight_dominates(predictions_json: Dict[str, Any]) -> bool:
    meta = predictions_json.get("_meta") or {}
    consensus = meta.get("day1_consensus") or {}
    for dm in consensus.values():
        og = (dm or {}).get("overnight_gap") or {}
        if og.get("dominates"):
            return True
    return False


def _max_live_gap_pct() -> float:
    try:
        from live_prices import fetch_live_futures_closes, get_nymex_session_close

        live_cols = fetch_live_futures_closes()
        settles, _, _ = get_nymex_session_close()
        gaps: List[float] = []
        for col, settle in settles.items():
            live = live_cols.get(col)
            if live and settle and float(settle) > 0:
                gaps.append(abs(float(live) / float(settle) - 1.0) * 100.0)
        return max(gaps) if gaps else 0.0
    except Exception:
        return 0.0


def should_defer_weekend_day1_email(predictions_json: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Hold day-1 email until Asia/Globex tape is usable for Monday session.
    Returns (defer, reason).
    """
    if not WEEKEND_DAY1_CONFIG.get("defer_until_asia", True):
        return False, "disabled"

    try:
        from day1_precision import _is_forecasting_weekend_gap
        from live_prices import _now_et
    except Exception:
        return False, "imports_unavailable"

    if not _is_forecasting_weekend_gap():
        return False, "not_weekend_gap"

    now = _now_et()
    asia_h = int(WEEKEND_DAY1_CONFIG.get("asia_ready_hour_et", 20))
    asia_m = int(WEEKEND_DAY1_CONFIG.get("asia_ready_minute_et", 15))
    tape_ready_pct = float(WEEKEND_DAY1_CONFIG.get("tape_gap_ready_pct", 1.0))

    if _overnight_dominates(predictions_json):
        return False, "overnight_gap_dominates"

    if now.weekday() == 0 and (now.hour > 5 or (now.hour == 5 and now.minute >= 30)):
        return False, "monday_session"

    if _max_live_gap_pct() >= tape_ready_pct:
        return False, "tape_gap_ready"

    if now.weekday() == 6:
        past_asia = now.hour > asia_h or (now.hour == asia_h and now.minute >= asia_m)
        if past_asia:
            return False, "sunday_asia_window"

    if now.weekday() in (4, 5, 6):
        return True, "waiting_for_asia_tape"

    return False, ""


def detect_day1_direction_flip(
    predictions_json: Dict[str, Any],
    last_sent: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """True when day-1 direction changed vs the last emailed forecast."""
    last_sent = last_sent if last_sent is not None else load_last_sent_day1()
    if not last_sent:
        return None

    cur = extract_day1_snapshot(predictions_json)
    if not cur.get("target_date") or cur["target_date"] != last_sent.get("target_date"):
        return None

    prev_dirs = last_sent.get("directions") or {}
    flips: List[Dict[str, str]] = []
    for pk in PRODUCTS:
        old = prev_dirs.get(pk)
        new = (cur.get("directions") or {}).get(pk)
        if not old or not new or old == new:
            continue
        if old == "FLAT" or new == "FLAT":
            continue
        flips.append({"product": pk, "was": old, "now": new})

    if not flips:
        return None

    overnight = _overnight_dominates(predictions_json)
    return {
        "flips": flips,
        "previous_sent_at": last_sent.get("sent_at"),
        "overnight_dominates": overnight,
    }


def enrich_email_meta(
    predictions_json: Dict[str, Any],
    flip_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Tag correction emails for subject line + banner."""
    meta = predictions_json.setdefault("_meta", {})
    if flip_info:
        meta["correction_email"] = True
        meta["correction_detail"] = flip_info
    return predictions_json


def _seconds_since_last_send(last_sent: Optional[Dict[str, Any]]) -> Optional[float]:
    if not last_sent or not last_sent.get("sent_at"):
        return None
    try:
        sent_at = datetime.fromisoformat(str(last_sent["sent_at"]))
        return (datetime.now() - sent_at).total_seconds()
    except Exception:
        return None


def _material_day1_change(
    cur: Dict[str, Any],
    last_sent: Optional[Dict[str, Any]],
) -> bool:
    if not last_sent:
        return True
    if cur.get("target_date") != last_sent.get("target_date"):
        return True
    prev_dirs = last_sent.get("directions") or {}
    cur_dirs = cur.get("directions") or {}
    for pk in PRODUCTS:
        if prev_dirs.get(pk) != cur_dirs.get(pk):
            return True
    threshold = float(WEEKEND_DAY1_CONFIG.get("dedupe_price_pct", 0.20))
    prev_pct = last_sent.get("change_pct") or {}
    cur_pct = cur.get("change_pct") or {}
    for pk in PRODUCTS:
        old = prev_pct.get(pk)
        new = cur_pct.get(pk)
        if old is None or new is None:
            continue
        if abs(float(new) - float(old)) >= threshold:
            return True
    return False


def acquire_email_send_lock(timeout_sec: float = 8.0) -> bool:
    """
    Cross-process lock so scheduler + manual prediction_engine cannot both send.
    Stale locks (>3 min) are broken automatically.
    """
    os.makedirs(os.path.dirname(EMAIL_LOCK_PATH) or "data", exist_ok=True)
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            fd = os.open(EMAIL_LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(f"{os.getpid()}\n{datetime.now().isoformat()}\n")
            return True
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(EMAIL_LOCK_PATH)
                if age > 180:
                    os.remove(EMAIL_LOCK_PATH)
                    continue
            except OSError:
                pass
            time.sleep(0.15)
        except OSError:
            time.sleep(0.15)
    return False


def release_email_send_lock() -> None:
    try:
        if os.path.exists(EMAIL_LOCK_PATH):
            os.remove(EMAIL_LOCK_PATH)
    except OSError:
        pass


def should_send_day1_email(
    predictions_json: Dict[str, Any],
    *,
    last_sent: Optional[Dict[str, Any]] = None,
    correction: bool = False,
    force_send: bool = False,
    overnight_dominates: bool = False,
) -> Tuple[bool, str]:
    """
    Avoid spamming identical day-1 calls on every scheduler tick / manual re-run.
    Cooldown always applies (including correction/force) unless overnight tape
    dominates — that alone may bypass cooldown after the hard MIN_SEND_GAP.

    Hard gate: never email on unverified Yahoo daily last (last ≠ NYMEX settle).
    """
    spot_ref = (predictions_json.get("_meta") or {}).get("spot_reference") or {}
    try:
        from live_prices import is_publishable_settle

        as_of = str(spot_ref.get("as_of_date") or "")[:10]
        if not is_publishable_settle(as_of, spot_ref):
            src = str(spot_ref.get("source") or "unknown")
            return False, f"unverified_settle:{src}"
    except Exception:
        # Fail closed — do not email without a settle check
        return False, "unverified_settle:check_failed"

    last_sent = last_sent if last_sent is not None else load_last_sent_day1()
    cur = extract_day1_snapshot(predictions_json)
    secs = _seconds_since_last_send(last_sent)
    cooldown_min = float(WEEKEND_DAY1_CONFIG.get("email_cooldown_minutes", 45))
    same_target = bool(
        last_sent
        and cur.get("target_date")
        and cur.get("target_date") == last_sent.get("target_date")
    )

    # Hard gap: blocks double-send when scheduler + manual race
    if secs is not None and secs < MIN_SEND_GAP_SECONDS and same_target:
        return False, f"send_lockout_{int(MIN_SEND_GAP_SECONDS - secs)}s"

    material = _material_day1_change(cur, last_sent) if last_sent else True
    in_cooldown = bool(
        secs is not None and same_target and secs < cooldown_min * 60.0
    )

    # Soft cooldown only blocks *unchanged* day-1 calls. Material flips and
    # --force-email may send after the hard gap (prevents spam, not corrections).
    if in_cooldown and not material and not force_send:
        left = max(1, int(cooldown_min - secs / 60.0))
        return False, f"email_cooldown_{left}min"

    if overnight_dominates and correction and material:
        return True, "overnight_correction"

    if correction and material:
        return True, "direction_correction"

    if force_send:
        return True, "manual_send"

    if not WEEKEND_DAY1_CONFIG.get("dedupe_emails", True):
        return True, "dedupe_disabled"

    if not last_sent:
        return True, "first_send"

    if _material_day1_change(cur, last_sent):
        if cur.get("target_date") != last_sent.get("target_date"):
            return True, "new_target_date"
        prev_dirs = last_sent.get("directions") or {}
        cur_dirs = cur.get("directions") or {}
        for pk in PRODUCTS:
            if prev_dirs.get(pk) != cur_dirs.get(pk):
                return True, f"direction_changed:{pk}"
        return True, "price_move_changed"

    return False, "unchanged_day1_call"
