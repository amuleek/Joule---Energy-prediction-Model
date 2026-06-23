"""
Luxury-styled prediction email — crisp inline reasoning, email-client safe.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime
from html import escape
from typing import Any, Dict, List, Optional, Tuple

from reasoning_engine import build_crisp_product_reasoning

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
    "up": "#3d5c45",
    "down": "#6b3a3a",
    "flat": "#6b6b70",
    "header_bg": "#141418",
}


class SimpleEmailFormatter:
    """Premium forecast email with short intellectual reasoning."""

    PRODUCT_NAMES = {
        "RBOB_Gasoline": {"display": "RBOB Gasoline", "subtitle": "NYMEX · Reformulated Blendstock"},
        "ULSD_Diesel": {"display": "ULSD Diesel", "subtitle": "Heating Oil / Distillate"},
        "Crude_Oil": {"display": "WTI Crude", "subtitle": "West Texas Intermediate"},
    }

    EMAIL_HORIZONS = (
        ("day_1", "Tomorrow"),
        ("day_4", "Day 4"),
        ("day_7", "Day 7"),
    )

    def _horizon_price_change(
        self, pred: Dict[str, Any], hkey: str, current: float
    ) -> Tuple[float, float]:
        hd = pred.get(hkey) or pred.get("next_day" if hkey == "day_1" else hkey)
        if isinstance(hd, dict):
            price = float(hd.get("price", current))
            pct = float(hd.get("change_percent", 0))
            if math.isnan(pct):
                pct = ((price - current) / current * 100) if current else 0
            return price, pct
        return current, 0.0

    def _insight_line(
        self,
        product_key: str,
        pred: Dict[str, Any],
        meta: Dict[str, Any],
        all_preds: Dict[str, Any],
    ) -> str:
        text = pred.get("reasoning") or build_crisp_product_reasoning(
            product_key, pred, meta, all_preds
        )
        return str(text).strip()[:220]

    def _direction_badge(self, pct: float) -> Tuple[str, str]:
        if pct > 0.15:
            return "▲", C["up"]
        if pct < -0.15:
            return "▼", C["down"]
        return "—", C["flat"]

    def format_email_html(
        self,
        current_predictions: Dict,
        previous_predictions: Optional[Dict] = None,
    ) -> str:
        est_time = datetime.now().strftime("%A, %B %d · %I:%M %p EST")
        meta = current_predictions.get("_meta") or {}
        spot_ref = meta.get("spot_reference") or {}
        spot_as_of = spot_ref.get("as_of_date") or ""
        if spot_as_of:
            try:
                settle_note = datetime.strptime(spot_as_of, "%Y-%m-%d").strftime("%b %d settle")
            except ValueError:
                settle_note = f"{spot_as_of} settle"
        else:
            settle_note = "Afternoon close"

        html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:{C['bg_outer']};font-family:Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{C['bg_outer']};padding:28px 12px;">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:580px;background:{C['bg_card']};border:1px solid #2a2a30;">

<!-- Header -->
<tr><td style="background:{C['header_bg']};padding:32px 28px 28px;text-align:center;border-bottom:2px solid {C['gold']};">
<p style="margin:0 0 6px;font-size:10px;letter-spacing:4px;text-transform:uppercase;color:{C['gold']};font-family:Georgia,'Times New Roman',serif;">Gill Energy</p>
<h1 style="margin:0;font-size:22px;font-weight:400;color:#f5f3ef;font-family:Georgia,'Times New Roman',serif;letter-spacing:0.5px;">Market Outlook</h1>
<p style="margin:10px 0 0;font-size:11px;color:{C['ink_muted']};letter-spacing:0.5px;">{escape(est_time)}</p>
</td></tr>

<!-- Intro strip -->
<tr><td style="padding:20px 28px 8px;">
<p style="margin:0;font-size:12px;line-height:1.6;color:{C['ink_soft']};font-style:italic;font-family:Georgia,'Times New Roman',serif;">
Three-horizon price view with drivers from inventories, crude, macro, and headlines.
</p>
</td></tr>
"""

        for product_key in ("RBOB_Gasoline", "ULSD_Diesel", "Crude_Oil"):
            pred = current_predictions.get(product_key)
            if not isinstance(pred, dict):
                continue
            pinfo = self.PRODUCT_NAMES.get(product_key, {"display": product_key, "subtitle": ""})
            spot_by_product = spot_ref.get("by_product") or {}
            try:
                ref_price = spot_by_product.get(product_key)
                current_price = float(ref_price if ref_price else pred.get("current_price", 0) or 0)
                if current_price <= 0 or math.isnan(current_price):
                    nd = pred.get("day_1") or pred.get("next_day") or {}
                    if isinstance(nd, dict) and nd.get("price"):
                        current_price = float(nd["price"]) * 0.99
                    else:
                        continue
            except (TypeError, ValueError):
                continue

            _, d1_pct = self._horizon_price_change(pred, "day_1", current_price)
            badge, badge_color = self._direction_badge(d1_pct)
            insight = self._insight_line(product_key, pred, meta, current_predictions)
            unc = pred.get("forecast_uncertainty") or {}
            unc_html = ""
            if unc.get("level") in ("HIGH", "MEDIUM"):
                reasons = unc.get("reasons") or []
                reason_txt = reasons[0] if reasons else unc.get("headline", "")
                unc_html = f"""
<tr><td style="padding:0 20px 10px;">
<p style="margin:0;font-size:11px;line-height:1.5;color:#6b4e2a;background:#faf6ef;border:1px solid #e8dcc8;padding:10px 12px;">
<strong style="color:#5c4a32;">Uncertainty ({escape(unc.get('level', ''))}):</strong> {escape(unc.get('headline', ''))}
{f'<br><span style="color:#7a6548;">{escape(reason_txt)}</span>' if reason_txt else ''}
</p>
</td></tr>
"""

            html += f"""
<tr><td style="padding:12px 28px 0;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{C['bg_panel']};border:1px solid {C['rule']};">
<tr><td style="padding:16px 20px 12px;border-top:3px solid {C['gold']};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
<td>
<p style="margin:0;font-size:15px;font-weight:600;color:{C['ink']};font-family:Georgia,'Times New Roman',serif;">{escape(pinfo['display'])}</p>
<p style="margin:3px 0 0;font-size:10px;color:{C['ink_muted']};letter-spacing:1px;text-transform:uppercase;">{escape(pinfo.get('subtitle', ''))}</p>
</td>
<td align="right" style="vertical-align:top;">
<p style="margin:0;font-size:18px;color:{badge_color};font-weight:600;">{badge}</p>
<p style="margin:2px 0 0;font-size:11px;color:{C['ink_soft']};">Close <span style="color:{C['ink']};font-weight:600;">${current_price:.4f}</span><br><span style="font-size:9px;color:{C['ink_muted']};">{escape(settle_note)}</span></p>
</td>
</tr></table>
</td></tr>

<tr><td style="padding:0 20px 14px;">
<p style="margin:0;font-size:12px;line-height:1.55;color:{C['ink_soft']};border-left:2px solid {C['gold_light']};padding-left:12px;">
{escape(insight)}
</p>
</td></tr>
{unc_html}

<tr><td style="padding:0 20px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid {C['rule']};">
<tr>
<td style="padding:10px 0 4px;font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:{C['ink_muted']};">Horizon</td>
<td align="right" style="padding:10px 0 4px;font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:{C['ink_muted']};">Price</td>
<td align="right" style="padding:10px 0 4px;font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:{C['ink_muted']};">Change</td>
</tr>
"""
            for hkey, hlabel in self.EMAIL_HORIZONS:
                price, change_pct = self._horizon_price_change(pred, hkey, current_price)
                chg_color = C["up"] if change_pct > 0 else C["down"] if change_pct < 0 else C["flat"]
                chg_txt = f"{change_pct:+.1f}%"
                html += f"""<tr>
<td style="padding:8px 0;border-top:1px solid {C['rule']};font-size:13px;color:{C['ink']};">{escape(hlabel)}</td>
<td align="right" style="padding:8px 0;border-top:1px solid {C['rule']};font-size:13px;color:{C['ink']};font-variant-numeric:tabular-nums;">${price:.4f}</td>
<td align="right" style="padding:8px 0;border-top:1px solid {C['rule']};font-size:13px;font-weight:600;color:{chg_color};font-variant-numeric:tabular-nums;">{chg_txt}</td>
</tr>
"""
            html += "</table></td></tr></table></td></tr>"

        html += self._render_post_mortem_luxury()

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

    def _render_post_mortem_luxury(self) -> str:
        path = "data/post_mortem_report.json"
        if not os.path.exists(path):
            return ""
        try:
            with open(path, encoding="utf-8") as f:
                report = json.load(f)
        except Exception:
            return ""

        explanations = report.get("explanations") or []
        if not explanations:
            return ""

        acc = report.get("direction_accuracy")
        mae = report.get("mean_abs_error_pct")
        stats = ""
        if acc is not None and mae is not None:
            stats = f"Last review: {acc:.0%} direction accuracy · {mae:.1f}% avg error"

        # One crisp post-mortem line only
        first = explanations[0]
        if len(first) > 160:
            first = first[:157] + "…"

        html = f"""
<tr><td style="padding:8px 28px 20px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{C['header_bg']};border:1px solid #2a2a30;">
<tr><td style="padding:14px 18px;">
<p style="margin:0 0 6px;font-size:9px;letter-spacing:2px;text-transform:uppercase;color:{C['gold']};">Yesterday&apos;s Check</p>
"""
        if stats:
            html += f'<p style="margin:0 0 8px;font-size:10px;color:{C["ink_muted"]};">{escape(stats)}</p>'
        html += f"""<p style="margin:0;font-size:11px;line-height:1.5;color:#c8c8cc;">{escape(first)}</p>
</td></tr></table></td></tr>
"""
        return html
