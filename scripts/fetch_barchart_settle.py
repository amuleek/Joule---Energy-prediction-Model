"""
Fetch NYMEX official settlement closes from Barchart (front-month / nearby contracts).

Uses the exchange settlement (prior close reference on Barchart), NOT the live
lastPrice tick — which can differ by several cents (RBOB) or dollars (crude)
after the session or in extended hours.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Dict, Optional, Tuple

import requests

# Barchart nearby notation → resolves to active front month (e.g. RBN26)
BARCHART_NEARBY = {
    "RBOB": "RB*1",
    "Crude": "CL*1",
    "ULSD": "HO*1",
}

BARCHART_TO_PRODUCT = {
    "RBOB": "RBOB_Gasoline",
    "ULSD": "ULSD_Diesel",
    "Crude": "Crude_Oil",
}

_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
)

# currentSymbol block on overview page (field order varies)
_CURRENT_SYMBOL_BLOCK = re.compile(
    r'"currentSymbol"\s*:\s*\{(?P<body>[^}]+)\}',
    re.DOTALL,
)

# nearby page: first contract quote block
_NEARBY_SYMBOL_RE = re.compile(
    r'"symbol"\s*:\s*"(?P<sym>[A-Z0-9]+)"[^}]*?'
    r'"lastPrice"\s*:\s*"(?P<last>[^"]+)"[^}]*?'
    r'"priceChange"\s*:\s*"(?P<chg>[+-]?[0-9.]+)"',
    re.DOTALL,
)

# Fallback front-month roots when nearby page scrape fails
_CONTRACT_ROOT_FALLBACK = {
    "RB*1": "RB",
    "CL*1": "CL",
    "HO*1": "HO",
}


def _parse_price_token(raw: str) -> Tuple[Optional[float], bool]:
    """Return (price, is_settlement). Barchart marks settle with trailing 's'."""
    token = str(raw or "").strip().lower()
    if not token:
        return None, False
    is_settle = token.endswith("s")
    if is_settle:
        token = token[:-1]
    try:
        val = float(token)
    except ValueError:
        return None, False
    return val, is_settle


def _parse_signed_change(raw: str) -> float:
    return float(str(raw).replace("+", ""))


def _settlement_from_quote(last_price: float, price_change: float) -> float:
    """
    Barchart settlement for the completed session.

    On Barchart, priceChange is vs the official settle; lastPrice can be an
    after-hours / next-tick print.  settle = lastPrice - priceChange matches
    the exchange close shown on Barchart (e.g. RBN26 2.9472 not 2.9664 live).
    """
    return round(last_price - price_change, 4)


def _parse_current_symbol_body(body: str) -> Tuple[Optional[float], Optional[float], Optional[str], str]:
    """Parse currentSymbol JSON body → (settle, live_last, symbol, field)."""
    sym_m = re.search(r'"symbol"\s*:\s*"(?P<sym>[A-Z0-9]+)"', body)
    last_m = re.search(r'"lastPrice"\s*:\s*"(?P<last>[^"]+)"', body)
    chg_m = re.search(r'"priceChange"\s*:\s*"(?P<chg>[+-]?[0-9.]+)"', body)
    if not sym_m or not last_m:
        return None, None, None, ""

    sym = sym_m.group("sym")
    last_val, is_settle = _parse_price_token(last_m.group("last"))
    if last_val is None:
        return None, None, sym, ""

    if is_settle:
        return round(last_val, 4), last_val, sym, "settle_flag"

    chg = _parse_signed_change(chg_m.group("chg")) if chg_m else 0.0
    return _settlement_from_quote(last_val, chg), last_val, sym, "last_minus_change"


def _scrape_contract_overview(contract: str) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """Return (settlement, last_price, contract) from a contract overview page."""
    url = f"https://www.barchart.com/futures/quotes/{contract}/overview"
    try:
        html = _SESSION.get(url, timeout=30).text
    except Exception:
        return None, None, contract

    block = _CURRENT_SYMBOL_BLOCK.search(html)
    if block:
        settle, last, sym, _field = _parse_current_symbol_body(block.group("body"))
        if settle and settle > 0:
            return settle, last, sym or contract

    if contract:
        for nearby_block in _NEARBY_SYMBOL_RE.finditer(html):
            if nearby_block.group("sym") != contract:
                continue
            last_val, is_settle = _parse_price_token(nearby_block.group("last"))
            if last_val is None:
                continue
            if is_settle:
                return round(last_val, 4), last_val, contract
            chg = _parse_signed_change(nearby_block.group("chg"))
            return _settlement_from_quote(last_val, chg), last_val, contract

    return None, None, contract


def _resolve_nearby_contract(nearby: str) -> Optional[str]:
    """Resolve RB*1 → RBN26 from Barchart nearby or overview pages."""
    url = f"https://www.barchart.com/futures/quotes/{nearby}/futures-prices"
    try:
        html = _SESSION.get(url, timeout=30).text
        m = _NEARBY_SYMBOL_RE.search(html)
        if m:
            return m.group("sym")
    except Exception:
        pass

    try:
        html = _SESSION.get(
            f"https://www.barchart.com/futures/quotes/{nearby}/overview",
            timeout=30,
        ).text
        block = _CURRENT_SYMBOL_BLOCK.search(html)
        if block:
            sym_m = re.search(r'"symbol"\s*:\s*"(?P<sym>[A-Z0-9]+)"', block.group("body"))
            if sym_m:
                return sym_m.group("sym")
    except Exception:
        pass

    root = _CONTRACT_ROOT_FALLBACK.get(nearby)
    if not root:
        return None
    month_codes = "FGHJKMNQUVXZ"
    now = datetime.now()
    # Try current + next two month codes on same year letter
    year_code = str(now.year)[-1]
    for offset in (0, 1, 2):
        mi = (now.month - 1 + offset) % 12
        y_off = (now.month - 1 + offset) // 12
        code = f"{root}{month_codes[mi]}{int(year_code) + y_off}"
        settle, _, sym = _scrape_contract_overview(code)
        if settle and settle > 0:
            return sym or code
    return None


def _fetch_ondemand_settles(api_key: str, symbols: str) -> Dict[str, Tuple[float, str]]:
    """Return {symbol: (settle_price, field_used)} from Barchart ondemand API."""
    url = "https://ondemand.websol.barchart.com/getQuote.json"
    params = {
        "apikey": api_key,
        "symbols": symbols,
        "fields": "symbol,settle,close,lastPrice,priceChange",
        "mode": "D",
    }
    out: Dict[str, Tuple[float, str]] = {}
    try:
        r = _SESSION.get(url, params=params, timeout=20)
        r.raise_for_status()
        for row in r.json().get("results") or []:
            sym = str(row.get("symbol", "")).upper()
            settle = row.get("settle")
            if settle not in (None, ""):
                out[sym] = (float(settle), "settle")
                continue
            close = row.get("close")
            if close not in (None, ""):
                out[sym] = (float(close), "close")
                continue
            last = row.get("lastPrice")
            chg = row.get("priceChange")
            if last not in (None, "") and chg not in (None, ""):
                out[sym] = (
                    _settlement_from_quote(float(last), _parse_signed_change(str(chg))),
                    "last-chg",
                )
    except Exception:
        pass
    return out


def fetch_barchart_settlement_closes(
    nearby_map: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, float], str, Dict[str, str]]:
    """
    Return official NYMEX settlement closes from Barchart front-month contracts.

    Returns:
        closes: {RBOB, ULSD, Crude}
        as_of_date: YYYY-MM-DD
        meta: source details
    """
    nearby_map = nearby_map or BARCHART_NEARBY
    meta: Dict[str, str] = {"source": "barchart", "method": "overview_settle"}
    closes: Dict[str, float] = {}
    resolved: Dict[str, str] = {}
    live: Dict[str, float] = {}

    api_key = os.getenv("BARCHART_API_KEY", "").strip()
    api_settles: Dict[str, Tuple[float, str]] = {}
    if api_key:
        contracts = []
        for nearby in nearby_map.values():
            sym = _resolve_nearby_contract(nearby)
            if sym:
                contracts.append(sym)
        if contracts:
            api_settles = _fetch_ondemand_settles(api_key, ",".join(contracts))
            if api_settles:
                meta["method"] = "ondemand_settle"

    for col, nearby in nearby_map.items():
        contract = _resolve_nearby_contract(nearby)
        if not contract:
            meta[f"{col}_error"] = "contract_unresolved"
            continue
        resolved[col] = contract

        if contract in api_settles:
            closes[col] = api_settles[contract][0]
            meta[f"{col}_field"] = api_settles[contract][1]
            continue

        settle, last, sym = _scrape_contract_overview(contract)
        if sym:
            resolved[col] = sym
        if last is not None:
            live[col] = last
        if settle and settle > 0:
            closes[col] = settle
            meta[f"{col}_field"] = meta.get(f"{col}_field") or "overview"

    meta["symbols"] = ",".join(resolved.values()) or ",".join(nearby_map.values())
    meta["nearby"] = ",".join(nearby_map.values())
    meta["resolved"] = resolved
    meta["live_last"] = live
    as_of = datetime.now().strftime("%Y-%m-%d")
    return closes, as_of, meta


def fetch_barchart_by_product(
    nearby_map: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, float], Dict[str, str]]:
    closes, as_of, meta = fetch_barchart_settlement_closes(nearby_map)
    by_product = {
        BARCHART_TO_PRODUCT[col]: price
        for col, price in closes.items()
        if col in BARCHART_TO_PRODUCT
    }
    meta["as_of_date"] = as_of
    meta["label"] = f"Barchart settle ({as_of})"
    meta["session"] = "NYMEX afternoon settle (Barchart)"
    meta["closes"] = closes
    meta["by_product"] = by_product
    return by_product, meta


if __name__ == "__main__":
    bp, m = fetch_barchart_by_product()
    print(m.get("label"), m.get("resolved"))
    for k, v in bp.items():
        live = (m.get("live_last") or {}).get(
            {"RBOB_Gasoline": "RBOB", "ULSD_Diesel": "ULSD", "Crude_Oil": "Crude"}.get(k, ""),
            None,
        )
        suffix = f"  (live last ${live:.4f})" if live else ""
        print(f"  {k}: ${v:.4f}{suffix}")
