"""
NYMEX contract month selection (front month vs lead month during roll).

Gasoline/diesel nearby *1 can still be the expiring month (e.g. RBU26 ~$3.44)
while the market you trade has rolled to *2 (RBV26 ~$3.11). We switch to *2
in the roll window so forecasts match the screen you watch.
"""
from __future__ import annotations

import calendar
from datetime import datetime
from typing import Any, Dict, Optional

try:
    from config import NYMEX_CONTRACT_CONFIG
except ImportError:
    NYMEX_CONTRACT_CONFIG = {
        "roll_days_before_month_end": 5,
        "auto_roll_rbob": True,
        "auto_roll_ulsd": True,
        "auto_roll_crude": False,
        "force_lead_month": False,
    }

DEFAULT_NEARBY = {
    "RBOB": "RB*1",
    "Crude": "CL*1",
    "ULSD": "HO*1",
}

MONTH_CODES = "FGHJKMNQUVXZ"


def _now_et() -> datetime:
    try:
        from live_prices import _now_et as lp_now

        return lp_now()
    except Exception:
        return datetime.now()


def _in_roll_window(now: Optional[datetime] = None) -> bool:
    """Last N calendar days of month — typical gasoline/diesel roll into next month."""
    now = now or _now_et()
    if NYMEX_CONTRACT_CONFIG.get("force_lead_month"):
        return True
    roll_days = int(NYMEX_CONTRACT_CONFIG.get("roll_days_before_month_end", 5))
    last_day = calendar.monthrange(now.year, now.month)[1]
    return now.day > max(1, last_day - roll_days)


def get_nearby_map(now: Optional[datetime] = None) -> Dict[str, str]:
    """
    Barchart nearby notation per product column.
    RB*2 / HO*2 during roll window when auto_roll enabled.
    """
    now = now or _now_et()
    nearby = dict(DEFAULT_NEARBY)
    rolling = _in_roll_window(now)

    if rolling and NYMEX_CONTRACT_CONFIG.get("auto_roll_rbob", True):
        nearby["RBOB"] = "RB*2"
    if rolling and NYMEX_CONTRACT_CONFIG.get("auto_roll_ulsd", True):
        nearby["ULSD"] = "HO*2"
    if rolling and NYMEX_CONTRACT_CONFIG.get("auto_roll_crude", False):
        nearby["Crude"] = "CL*2"
    return nearby


def _add_months(year: int, month: int, n: int) -> tuple[int, int]:
    month = month + n
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1
    return year, month


def nymex_symbol(root: str, year: int, month: int) -> str:
    """Build CME symbol e.g. RB + Oct 2026 → RBV26."""
    code = MONTH_CODES[month - 1]
    return f"{root}{code}{str(year)[-2:]}"


def wti_last_trade_day(year: int, month: int) -> datetime:
    """Last trading day of the WTI contract that *expires* in (year, month):
    3 business days before the 25th, or before the last business day preceding
    the 25th when the 25th is not a business day (weekends only; exchange holidays
    can move it one day earlier)."""
    d = datetime(year, month, 25)
    # anchor on the 25th or the business day before it (Dec 25 is always a holiday)
    while d.weekday() >= 5 or (d.month == 12 and d.day == 25):
        d = d.replace(day=d.day - 1)
    n = 0
    while n < 3:
        d = d.replace(day=d.day - 1)
        if d.weekday() < 5:
            n += 1
    return d


def infer_wti_front_month(as_of: Optional[datetime] = None) -> tuple[int, int]:
    """WTI delivery month M expires around the 20th of month M-1. Before that date the
    front is next month; after it, the month after next (e.g. Nov 21 -> CLF)."""
    as_of = as_of or _now_et()
    exp = wti_last_trade_day(as_of.year, as_of.month)
    offset = 1 if as_of.date() <= exp.date() else 2
    return _add_months(as_of.year, as_of.month, offset)


def infer_delivery_front_month(as_of: Optional[datetime] = None) -> tuple[int, int]:
    """
    RBOB/HO: delivery month M expires in the prior calendar month, so during
    calendar month C the liquid front is typically C+1 (Sep → Oct RBV).
    """
    as_of = as_of or _now_et()
    return _add_months(as_of.year, as_of.month, 1)


def infer_resolved_contracts(as_of: Optional[datetime] = None) -> Dict[str, str]:
    """
    Named-month contracts from nearby map — never continuous RB=F / HO=F.
    RB*1 → front delivery, RB*2 → lead (next) delivery.
    """
    as_of = as_of or _now_et()
    nearby = get_nearby_map(as_of)
    fy, fm = infer_delivery_front_month(as_of)
    ly, lm = _add_months(fy, fm, 1)
    out: Dict[str, str] = {}
    for col, nb in nearby.items():
        root = (nb or "")[:2]
        if root not in ("RB", "HO", "CL"):
            continue
        if root == "CL":
            # WTI expires ~20th of the prior month, not at month end like RB/HO.
            y, m = infer_wti_front_month(as_of)
            if str(nb).endswith("*2"):
                y, m = _add_months(y, m, 1)
        elif str(nb).endswith("*2"):
            y, m = ly, lm
        else:
            y, m = fy, fm
        out[col] = nymex_symbol(root, y, m)
    return out


def contract_label(resolved: Optional[Dict[str, str]]) -> str:
    """Human label e.g. 'RBV26 (Oct 2026)'."""
    if not resolved:
        return ""
    parts = []
    for col, sym in resolved.items():
        if not sym or len(sym) < 4:
            continue
        root = sym[:2]
        month_code = sym[2] if len(sym) > 2 else ""
        year_digit = sym[3] if len(sym) > 3 else ""
        month_idx = MONTH_CODES.find(month_code)
        month_name = (
            calendar.month_name[month_idx + 1][:3]
            if month_idx >= 0
            else month_code
        )
        year = f"202{year_digit}" if year_digit.isdigit() else ""
        parts.append(f"{sym} ({month_name} {year})".strip())
    return " · ".join(parts)


def roll_status(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Diagnostic for pipeline logs / email meta."""
    now = now or _now_et()
    nearby = get_nearby_map(now)
    return {
        "in_roll_window": _in_roll_window(now),
        "nearby_map": nearby,
        "note": (
            "Lead month (RB*2) active — forecasts use October RBOB, not expiring September."
            if nearby.get("RBOB") == "RB*2"
            else "Front month (RB*1) active."
        ),
    }
