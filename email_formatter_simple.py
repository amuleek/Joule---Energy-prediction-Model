"""
Luxury-styled prediction email — crisp inline reasoning, email-client safe.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from html import escape
from typing import Dict, Optional, Tuple

# Luxury palette (inline-only for email clients)
C = {
    "bg_outer": "#0f0f12",
    "bg_card": "#faf9f7",
    "bg_panel": "#ffffff",
    "gold": "#b8956a",
    "gold_light": "#d4bc94",
    "ink": "#1c1c1e",
    "ink_soft": "#5c5c62",
    "ink_muted": "#8e8e93",
    "rule": "#e8e4df",
    "up": "#1f7a4d",
    "down": "#6b3a3a",
    "flat": "#6b6b70",
    "header_bg": "#141418",
}

CALL_STRIP = (
    ("RBOB_Gasoline", "Gasoline", "Gas", 4),
    ("ULSD_Diesel", "Diesel", "Diesel", 4),
    ("Crude_Oil", "Crude", "Crude", 2),
)


class SimpleEmailFormatter:
    """Premium forecast email: header + NYMEX price calendar."""

    def _next_session_dt(self, preds: Dict) -> datetime:
        for pk, *_ in CALL_STRIP:
            d1 = (preds.get(pk) or {}).get("day_1") or {}
            td = d1.get("target_date") if isinstance(d1, dict) else None
            if td:
                try:
                    return datetime.strptime(str(td)[:10], "%Y-%m-%d")
                except ValueError:
                    pass
        as_of = str(((preds.get("_meta") or {}).get("spot_reference") or {}).get("as_of_date") or "")
        if as_of:
            try:
                d = datetime.strptime(as_of[:10], "%Y-%m-%d") + timedelta(days=1)
                while d.weekday() >= 5:
                    d += timedelta(days=1)
                return d
            except ValueError:
                pass
        d = datetime.now() + timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d

    def _session_labels(self, preds: Dict) -> Tuple[datetime, str, str, str]:
        dt = self._next_session_dt(preds)
        word = dt.strftime("%A")
        title = dt.strftime("%A, %B %d")
        short = dt.strftime("%a %b %d")
        return dt, word, title, short

    def _settle_line(self, preds: Dict) -> str:
        as_of = str(((preds.get("_meta") or {}).get("spot_reference") or {}).get("as_of_date") or "")
        roll = ((preds.get("_meta") or {}).get("spot_reference") or {}).get("contract_roll") or {}
        resolved = ((preds.get("_meta") or {}).get("spot_reference") or {}).get("resolved") or {}
        rb = resolved.get("RBOB") or ""
        contract_note = f" · {rb}" if rb else ""
        if roll.get("in_roll_window") and rb:
            contract_note = f" · {rb} (lead month)"
        if not as_of:
            return "Last NYMEX settle" + contract_note
        try:
            d = datetime.strptime(as_of[:10], "%Y-%m-%d")
            return f"vs {d.strftime('%A, %b %d')} settle{contract_note}"
        except ValueError:
            return f"vs {as_of} settle{contract_note}"

    def format_email_subject(self, preds: Dict) -> str:
        meta = preds.get("_meta") or {}
        _, _, _, short = self._session_labels(preds)
        if meta.get("correction_email"):
            reason = (meta.get("correction_detail") or {}).get("reason", "overnight_gap")
            if reason == "intraday_tape":
                return f"NYMEX CORRECTED | {short} | intraday tape"
            return f"NYMEX CORRECTED | {short} | overnight gap"
        return f"NYMEX price calendar | {short}"

    def format_email_html(
        self,
        current_predictions: Dict,
        previous_predictions: Optional[Dict] = None,
    ) -> str:
        _, _session_word, session_title, _session_short = self._session_labels(current_predictions)
        sent_at = datetime.now().strftime("%a, %b %d · %I:%M %p ET")
        settle_note = self._settle_line(current_predictions)
        meta = current_predictions.get("_meta") or {}
        correction_banner = ""
        if meta.get("correction_email"):
            detail = meta.get("correction_detail") or {}
            flips = detail.get("flips") or []
            flip_lines = []
            for f in flips:
                pk = f.get("product", "")
                short = pk.replace("_Gasoline", "").replace("_Diesel", "").replace("_Oil", "")
                gap = f.get("gap_pct")
                if gap is not None:
                    flip_lines.append(f"{short}: {f.get('was')} → {f.get('now')} ({float(gap):+.1f}% live)")
                else:
                    flip_lines.append(f"{short}: {f.get('was')} → {f.get('now')}")
            reason = detail.get("reason", "overnight_gap")
            if reason == "intraday_tape":
                headline = "Day-1 updated — live NYMEX tape reversed the morning call."
            else:
                headline = "Day-1 updated after Asia/overnight gap."
            flip_text = " · ".join(flip_lines) if flip_lines else headline
            correction_banner = f"""
<tr><td style="padding:14px 20px 0;">
<p style="margin:0;padding:12px 14px;background:#3d2a2a;border:1px solid {C['down']};font-size:12px;color:#f5f3ef;line-height:1.5;">
<strong style="color:{C['gold_light']};letter-spacing:1px;">CORRECTED</strong> — {escape(headline)}<br>
<span style="color:#e8dcd8;">{escape(flip_text)}</span>
</p>
</td></tr>
"""

        html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:{C['bg_outer']};font-family:Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{C['bg_outer']};padding:28px 12px;">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:580px;background:{C['bg_card']};border:1px solid #2a2a30;">

<tr><td style="background:{C['header_bg']};padding:28px 28px 22px;text-align:center;border-bottom:2px solid {C['gold']};">
<p style="margin:0 0 8px;font-size:10px;letter-spacing:4px;text-transform:uppercase;color:{C['gold']};font-family:Georgia,'Times New Roman',serif;">Gill Energy</p>
<h1 style="margin:0;font-size:24px;font-weight:400;color:#f5f3ef;font-family:Georgia,'Times New Roman',serif;letter-spacing:0.3px;">{escape(session_title)}</h1>
<p style="margin:10px 0 0;font-size:11px;color:{C['gold_light']};letter-spacing:0.3px;">NYMEX price calendar</p>
<p style="margin:6px 0 0;font-size:11px;color:{C['ink_muted']};">{escape(settle_note)} · {escape(sent_at)}</p>
</td></tr>
{correction_banner}
"""
        html += self._render_prediction_calendar()

        html += f"""
<tr><td style="padding:24px 28px;text-align:center;border-top:1px solid {C['rule']};">
<p style="margin:0 0 4px;font-size:9px;letter-spacing:2px;text-transform:uppercase;color:{C['gold']};">Gill Energy Intelligence</p>
<p style="margin:0;font-size:10px;color:{C['ink_muted']};line-height:1.5;">For operational planning only · Not financial advice</p>
</td></tr>

</table>
</td></tr></table>
</body></html>
"""
        return html

    def _render_prediction_calendar(self) -> str:
        try:
            from prediction_calendar import build_prediction_calendar
            cal = build_prediction_calendar(n_past=4, n_forward=10)
        except Exception:
            return ""
        past = cal.get("past") or []
        future = cal.get("future") or []
        if not past and not future:
            return ""

        def cell(prods: Dict, pk: str, dec: int, future_row: bool) -> str:
            row = prods.get(pk) or {}
            pred = row.get("predicted")
            act = row.get("actual")
            pred_px = f"{float(pred):.{dec}f}" if pred is not None else "—"
            if future_row or row.get("pending") or act is None:
                band = row.get("range_80") or {}
                if band.get("low") is not None and band.get("high") is not None:
                    return (
                        f'<span style="color:{C["ink"]};">${pred_px}</span>'
                        f'<br><span style="color:{C["ink_muted"]};font-size:9px;">'
                        f'{float(band["low"]):.{dec}f}–{float(band["high"]):.{dec}f}</span>'
                    )
                return f'<span style="color:{C["ink"]};">${pred_px}</span>'
            act_px = f"{float(act):.{dec}f}"
            return (
                f'<span style="color:{C["ink"]};">${pred_px}</span>'
                f'<br><span style="color:{C["up"]};font-weight:600;">${act_px}</span>'
            )

        vline = f"border-left:1px solid {C['rule']};"
        hline = f"border-top:1px solid {C['rule']};"

        def table_html(days: list, future_row: bool) -> str:
            if not days:
                return ""
            body = ""
            for day in days:
                prods = day.get("products") or {}
                date_s = day.get("label") or day.get("date") or ""
                ink = C["ink"] if not future_row else C["ink_soft"]
                body += f"""<tr>
<td style="padding:7px 8px 7px 6px;{hline}font-size:11px;color:{ink};white-space:nowrap;">{escape(date_s)}</td>
<td align="right" style="padding:7px 8px;{hline}{vline}font-size:11px;font-variant-numeric:tabular-nums;">{cell(prods, "RBOB_Gasoline", 4, future_row)}</td>
<td align="right" style="padding:7px 8px;{hline}{vline}font-size:11px;font-variant-numeric:tabular-nums;">{cell(prods, "ULSD_Diesel", 4, future_row)}</td>
<td align="right" style="padding:7px 8px;{hline}{vline}font-size:11px;font-variant-numeric:tabular-nums;">{cell(prods, "Crude_Oil", 2, future_row)}</td>
</tr>
"""
            return f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{C['bg_panel']};border:1px solid {C['rule']};border-collapse:collapse;">
<tr>
<td style="padding:6px 8px;border-bottom:1px solid {C['rule']};font-size:9px;letter-spacing:1px;text-transform:uppercase;color:{C['ink_muted']};">Session</td>
<td align="right" style="padding:6px 8px;border-bottom:1px solid {C['rule']};border-left:1px solid {C['rule']};font-size:9px;letter-spacing:1px;text-transform:uppercase;color:{C['ink_muted']};">Gas</td>
<td align="right" style="padding:6px 8px;border-bottom:1px solid {C['rule']};border-left:1px solid {C['rule']};font-size:9px;letter-spacing:1px;text-transform:uppercase;color:{C['ink_muted']};">Diesel</td>
<td align="right" style="padding:6px 8px;border-bottom:1px solid {C['rule']};border-left:1px solid {C['rule']};font-size:9px;letter-spacing:1px;text-transform:uppercase;color:{C['ink_muted']};">Crude</td>
</tr>
{body}
</table>
"""

        tables = table_html(past, False)
        if past and future:
            tables += '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td style="height:12px;font-size:0;line-height:0;">&nbsp;</td></tr></table>'
        tables += table_html(future, True)

        return f"""
<tr><td style="padding:16px 20px 8px;">
<p style="margin:0 0 10px;font-size:9px;letter-spacing:2px;text-transform:uppercase;color:{C['gold']};">Price calendar</p>
{tables}
<p style="margin:10px 0 0;font-size:9px;color:{C['ink_muted']};">Dark number is the prediction (last settle) · small grey range is 80% likely · <span style="color:{C['up']};">green is the actual settle</span></p>
</td></tr>
"""

