"""
Prediction Engine - Orchestrates data collection and predictions
Runs daily to update predictions for next day, week, and biweekly
"""
import os
import sys

from pipeline_fast import apply_fast_defaults
apply_fast_defaults()

import json
import math
import pandas as pd
from datetime import datetime
from typing import Any, Dict
from intelligence_signals import (
    build_intelligence_layer,
    finalize_email_narratives,
    smart_alert_candidates,
    load_inventory_history,
    weekly_inventory_snapshot,
)
from scripts.fetch_prices import save_prices
from scripts.fetch_news import save_news
from scripts.fetch_inventory import fetch_inventory
from scripts.fetch_futures_ohlc import save_futures_ohlc
from scripts.fetch_dollar_index import save_dollar_index, latest_dollar_index_snapshot
from scripts.preprocessing import merge_data
from news_signals import latest_topic_snapshot
from forecast_horizons import PREDICTION_HORIZONS, max_frac_for
from post_mortem import apply_bias_to_predictions, archive_predictions, run_daily_post_mortem
from day1_precision import reconcile_day1_precision
from predictor import EnergyPricePredictor
from data_sync import sync_all_csv_to_db
from model_weights import ensure_default_weights
from alerts import EmailAlertSystem
from live_prices import (
    apply_session_close_baseline,
    patch_final_data_session_closes,
    session_close_by_product,
)
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

class PredictionEngine:
    """Main prediction engine that orchestrates data collection and predictions"""
    
    def __init__(self):
        self.predictor = EnergyPricePredictor()
        self._ensemble_meta = {}
        self._rag_context = {}

    @staticmethod
    def _hurricane_snapshot() -> dict:
        try:
            from scripts.fetch_hurricane_freight import latest_hurricane_snapshot
            return latest_hurricane_snapshot()
        except Exception:
            return {}

    @staticmethod
    def _latest_operational_snapshot() -> dict:
        path = "data/operational.csv"
        if not os.path.exists(path):
            return {}
        try:
            df = pd.read_csv(path)
            if df.empty:
                return {}
            row = df.iloc[-1].to_dict()
            return {k: row[k] for k in row if k != "date" and pd.notna(row[k])}
        except Exception:
            return {}

    @staticmethod
    def _latest_freight_snapshot() -> dict:
        path = "data/freight.csv"
        if not os.path.exists(path):
            return {}
        try:
            df = pd.read_csv(path)
            if df.empty:
                return {}
            row = df.iloc[-1].to_dict()
            return {k: row[k] for k in row if k != "date" and pd.notna(row[k])}
        except Exception:
            return {}

    @staticmethod
    def _latest_weather_snapshot() -> dict:
        path = "data/weather.csv"
        if not os.path.exists(path):
            return {}
        try:
            df = pd.read_csv(path)
            if df.empty:
                return {}
            row = df.iloc[-1].to_dict()
            return {k: row[k] for k in row if k != "date" and pd.notna(row[k])}
        except Exception:
            return {}

    @staticmethod
    def _print_pipeline_health() -> None:
        """Warn when critical inputs are missing or degraded."""
        issues = []
        if not os.getenv("EIA_API_KEY", "").strip():
            issues.append("EIA_API_KEY missing — inventory signals stale")
        if not os.getenv("NEWS_API_KEY", "").strip() and not os.getenv("WORLD_NEWS_API_KEY", "").strip():
            issues.append("No news API key — sentiment/geo headlines degraded")
        if not os.getenv("BARCHART_API_KEY", "").strip():
            issues.append("BARCHART_API_KEY missing — settle prices use HTML scrape (less reliable)")
        if os.getenv("FAST_ENSEMBLE", "true").lower() in ("1", "true", "yes"):
            issues.append("FAST_ENSEMBLE=true — technical layer is momentum-only (set false for production)")

        try:
            from prediction_attribution import load_factor_learning
            rules = (load_factor_learning() or {}).get("global_rules") or {}
            if rules.get("trust_ensemble_over_overlay"):
                print("  Learning: momentum overlays disabled (recent tape misses)")
            cap = rules.get("momentum_blend_cap")
            if cap is not None:
                print(f"  Learning: momentum blend cap {float(cap):.2f}")
        except Exception:
            pass

        if issues:
            print("\nPipeline health warnings:")
            for msg in issues:
                print(f"  [!] {msg}")
        else:
            print("\nPipeline health: all critical API keys present")
    
    def collect_data(self):
        """Collect all required data"""
        print("=" * 60)
        print("Collecting Data for Predictions")
        print("=" * 60)
        
        os.makedirs("data", exist_ok=True)

        print("\n0. EIA historical backfill (if history is short)…")
        try:
            from scripts.backfill_eia_history import run_backfill
            n_rows = 0
            if os.path.exists("data/prices.csv"):
                _p = pd.read_csv("data/prices.csv").dropna(subset=["date"])
                n_rows = len(_p)
            if n_rows < 90 or os.getenv("EIA_BACKFILL_FORCE", "").lower() in ("1", "true", "yes"):
                run_backfill(days=int(os.getenv("EIA_BACKFILL_DAYS", "730")))
            else:
                print(f"  Skipping backfill ({n_rows} price rows on file).")
        except Exception as e:
            print(f"  Backfill skipped: {e}")
        
        print("\n1. Fetching NYMEX futures OHLC (Yahoo)…")
        try:
            save_futures_ohlc(period="2y")
        except Exception as e:
            print(f"Error fetching futures OHLC: {e}")

        print("\n1a. Repairing named-month product closes (reject RB=F continuous)…")
        try:
            from live_prices import repair_recent_settles_from_named_month

            n_fix = repair_recent_settles_from_named_month(lookback_sessions=15)
            print(f"  Named-month settle repair: {n_fix} session(s) aligned")
        except Exception as e:
            print(f"  Named-month repair skipped: {e}")

        # Upgrade recent Yahoo-daily (trust 1) settles to the 14:28-14:30 ET VWAP while
        # 1-minute data is still available (~7 days), so those sessions can be scored.
        try:
            from live_prices import upgrade_recent_settles_to_vwap

            n_up = upgrade_recent_settles_to_vwap(days=7)
            print(f"  Settle VWAP upgrade: {n_up} session(s) upgraded to settlement-window VWAP")
        except Exception as e:
            print(f"  Settle VWAP upgrade skipped: {e}")

        print("\n1b. Syncing spot prices from live futures…")
        try:
            save_prices()
        except Exception as e:
            print(f"Error fetching prices: {str(e)}")

        print("\n1c. Fetching U.S. Dollar Index (DXY)…")
        try:
            save_dollar_index(period="2y")
        except Exception as e:
            print(f"Error fetching dollar index: {e}")

        print("\n1d. Fetching refinery utilization & trade flows…")
        try:
            from scripts.fetch_operational_data import fetch_operational
            fetch_operational()
        except Exception as e:
            print(f"Error fetching operational data: {e}")

        print("\n1e. Fetching Gulf Coast weather…")
        try:
            from scripts.fetch_weather import fetch_weather
            fetch_weather(days_back=14)
        except Exception as e:
            print(f"Error fetching weather: {e}")

        print("\n1f. Fetching hurricane tracks & freight rates…")
        try:
            from scripts.fetch_hurricane_freight import save_hurricane_and_freight
            save_hurricane_and_freight()
        except Exception as e:
            print(f"Error fetching hurricane/freight: {e}")
        
        # Fetch news
        print("\n2. Fetching news...")
        try:
            save_news()
        except Exception as e:
            print(f"Error fetching news: {str(e)}")
        
        # Fetch inventory
        print("\n3. Fetching inventory...")
        try:
            fetch_inventory()
        except Exception as e:
            print(f"Error fetching inventory: {str(e)}")

        print("\n3a. Building RBOB/ULSD catalyst calendar…")
        try:
            from economic_calendar import save_calendar_json
            cal = save_calendar_json()
            nxt = cal.get("next") or {}
            if nxt:
                print(
                    f"  Next: {nxt.get('report')} {nxt.get('date')} {nxt.get('time_et')} ET "
                    f"({float(nxt.get('hours_to') or 0):.0f}h)"
                )
        except Exception as e:
            print(f"  Catalyst calendar skipped: {e}")
        
        # Preprocess and merge
        print("\n4. Preprocessing data...")
        try:
            merge_data()
        except Exception as e:
            print(f"Error preprocessing: {str(e)}")
            import traceback
            traceback.print_exc()

        print("\n5. Syncing data to timestamped database…")
        try:
            sync_all_csv_to_db()
        except Exception as e:
            print(f"Database sync skipped: {e}")

        print("\n6. Indexing news for RAG retrieval…")
        try:
            from rag_store import RAGStore
            n = RAGStore().index_news_csv(max_rows=int(os.getenv("RAG_MAX_INDEX", "80")))
            if n:
                print(f"  Indexed {n} recent news articles")
        except Exception as e:
            print(f"RAG indexing skipped: {e}")
    
    def generate_predictions(self, *, send_email: bool = True, force_send_email: bool = False):
        """Generate price predictions"""
        print("\n" + "=" * 60)
        print("Generating AI Predictions")
        print("=" * 60)
        
        # Live NYMEX futures closes (matches email spot and model input)
        # NYMEX afternoon settlement close (not intraday live quote)
        print("Fetching NYMEX session settle prices...")
        current_prices, spot_ref = session_close_by_product()
        self._spot_reference = spot_ref
        if spot_ref.get("label"):
            print(f"  Reference: {spot_ref['label']}")
        try:
            from live_prices import calendar_gap_between_sessions, is_weekend_gap_session
            gap = calendar_gap_between_sessions()
            if is_weekend_gap_session():
                print(
                    f"  Weekend/holiday gap ({gap} calendar days since prior settle) — "
                    "tape momentum suppressed; run after 3:07 PM ET for today's official close."
                )
        except Exception:
            pass
        for product, price in current_prices.items():
            label = product.replace("_", " ")
            print(f"  {label}: ${price:.4f}")

        try:
            from live_prices import validate_session_closes, sync_prices_csv_from_futures

            settle_date = spot_ref.get("as_of_date") or ""
            col_closes = {
                "RBOB": current_prices.get("RBOB_Gasoline"),
                "ULSD": current_prices.get("ULSD_Diesel"),
                "Crude": current_prices.get("Crude_Oil"),
            }
            col_closes = {k: v for k, v in col_closes.items() if v}
            issues = validate_session_closes(col_closes, as_of_date=settle_date)
            if issues:
                print("  [!] Session close validation:")
                for msg in issues:
                    print(f"      - {msg}")
            else:
                print("  Session closes validated (front-month NYMEX)")
            if not spot_ref.get("publishable"):
                src = spot_ref.get("source") or "unknown"
                print(
                    f"  [!] Spot NOT publishable ({src}, trust={spot_ref.get('trust_level')}) — "
                    "email will be blocked until Barchart/VWAP/verified settle"
                )
            if col_closes and settle_date:
                sync_prices_csv_from_futures(col_closes, as_of_date=settle_date)
        except Exception as e:
            print(f"  Session close validation skipped: {e}")

        if not current_prices:
            from data_collector import EnergyDataCollector
            collector = EnergyDataCollector()
            price_data = collector.get_rbob_gasoline_price()
            if price_data and 'price' in price_data:
                current_prices['RBOB_Gasoline'] = float(price_data['price'])
            price_data = collector.get_diesel_price()
            if price_data and 'price' in price_data:
                current_prices['ULSD_Diesel'] = float(price_data['price'])
            price_data = collector.get_crude_oil_price()
            if price_data and 'price' in price_data:
                current_prices['Crude_Oil'] = float(price_data['price'])

        settle_date = spot_ref.get("as_of_date") or ""
        if current_prices and settle_date:
            patch_final_data_session_closes(current_prices, settle_date)
            print(f"  Model baseline: {spot_ref.get('label', 'NYMEX settle')} ({settle_date})")

        retail_weekly = None
        try:
            from data_collector import EnergyDataCollector
            retail_weekly = EnergyDataCollector().get_eia_weekly_retail_pump_prices()
        except Exception:
            pass
        if retail_weekly:
            print("  Retail pump (EIA weekly, configured region):")
            if retail_weekly.get("regular_gasoline") is not None:
                print(f"    Regular gasoline: ${retail_weekly['regular_gasoline']:.3f}/gal")
            if retail_weekly.get("ulsd_diesel") is not None:
                print(f"    ULSD diesel: ${retail_weekly['ulsd_diesel']:.3f}/gal")
            print(f"    ({retail_weekly.get('region_label', '')}, week {retail_weekly.get('period', '')})")
        
        predictions = self.predictor.generate_predictions(
            session_prices=current_prices or None,
            settle_date=settle_date or None,
        )
        ensemble_meta = {}
        rag_ctx = {}
        topic_snapshot = latest_topic_snapshot()
        pre_meta: Dict[str, Any] = {}
        if predictions:
            try:
                ensure_default_weights()
                fd_path = "data/final_data.csv"
                fd = pd.read_csv(fd_path) if os.path.exists(fd_path) else None
                pre_meta = {
                    "inventory_weekly": weekly_inventory_snapshot(load_inventory_history()),
                    "crack_spreads_current": getattr(self.predictor, "_last_crack_snapshot", None),
                    "operational": self._latest_operational_snapshot(),
                    "hurricane": self._hurricane_snapshot(),
                    "freight": self._latest_freight_snapshot(),
                    "weather": self._latest_weather_snapshot(),
                    "sentiment": None,
                    "dollar_index": latest_dollar_index_snapshot(),
                }
                try:
                    from economic_calendar import build_catalyst_snapshot
                    pre_meta["catalyst_calendar"] = build_catalyst_snapshot()
                except Exception:
                    pre_meta["catalyst_calendar"] = {}
                pre_meta["topic_snapshot"] = topic_snapshot
                pre_meta["geo_risk_score"] = topic_snapshot.get("geo_risk_score")
                if fd is not None and "sentiment" in fd.columns and len(fd):
                    pre_meta["sentiment"] = float(fd["sentiment"].iloc[-1])
                try:
                    from rag_store import build_rag_context
                    rag_ctx = build_rag_context(pre_meta)
                    pre_meta["rag_context"] = rag_ctx.get("RBOB_Gasoline", [])
                except Exception:
                    rag_ctx = {}
                from ensemble_models import EnsembleAgent
                agent = EnsembleAgent()
                predictions, ensemble_meta = agent.apply_to_predictions(predictions, fd, pre_meta)
            except Exception as e:
                print(f"Ensemble layer skipped: {e}")

            self._ensemble_meta = ensemble_meta
            self._rag_context = rag_ctx
            weather_snap = self._latest_weather_snapshot()
            live_by_product: Dict[str, float] = {}
            try:
                from live_prices import live_gap_by_product
                live_by_product = live_gap_by_product()
                if live_by_product:
                    print("  Overnight/live tape (gap overlay, not email spot):")
                    for pk, px in live_by_product.items():
                        spot = current_prices.get(pk)
                        if spot and spot > 0:
                            gap = (px - spot) / spot * 100.0
                            print(f"    {pk.replace('_', ' ')}: ${px:.4f} ({gap:+.2f}% vs settle)")
            except Exception as e:
                print(f"  Live gap overlay skipped: {e}")
            signal_context = {
                "inventory_weekly": pre_meta.get("inventory_weekly"),
                "topic_snapshot": topic_snapshot,
                "dollar_index": pre_meta.get("dollar_index"),
                "hurricane": pre_meta.get("hurricane"),
                "weather": weather_snap,
                "crack_spreads": pre_meta.get("crack_spreads_current"),
                "live_by_product": live_by_product,
                "news_csv": "data/news.csv",
                "catalyst_calendar": pre_meta.get("catalyst_calendar"),
            }
            predictions, day1_meta = reconcile_day1_precision(
                predictions,
                ensemble_meta=ensemble_meta,
                xgb_info=getattr(self.predictor, "_last_xgb_info", None),
                current_prices=current_prices,
                context_meta={
                    "geo_risk_score": topic_snapshot.get("geo_risk_score"),
                    "catalyst_calendar": pre_meta.get("catalyst_calendar"),
                },
                signal_context=signal_context,
            )
            predictions = apply_bias_to_predictions(predictions)
            self._day1_meta = day1_meta
            for pk, dm in (day1_meta or {}).items():
                mom = (dm or {}).get("momentum_continuation")
                if mom:
                    mode = mom.get("mode", "continuation")
                    if mode == "bounce_fade":
                        label = "Bounce fade"
                    elif mode == "post_spike_fade":
                        label = "Post-spike fade"
                    elif mode == "rbob_soft_fade":
                        label = "RBOB soft fade"
                    elif mode == "reversal_fade":
                        label = "Reversal fade"
                    elif mode == "selloff_after_spike":
                        label = "Selloff after spike"
                    else:
                        label = "Momentum"
                    print(
                        f"  {label} {pk.replace('_', ' ')}: "
                        f"prior session {mom['prior_session_pct']:+.2f}% — "
                        f"day-1 {mom['consensus_before']:+.2f}% -> {mom['consensus_after']:+.2f}%"
                    )
                spill = (dm or {}).get("crude_spillover")
                if spill:
                    print(
                        f"  Crude spillover {pk.replace('_', ' ')}: "
                        f"WTI {spill['crude_prior_session_pct']:+.2f}% — "
                        f"day-1 {spill['consensus_before']:+.2f}% -> {spill['consensus_after']:+.2f}%"
                    )
                learn = (dm or {}).get("signal_learning")
                if learn and learn.get("drivers"):
                    print(
                        f"  Learned signals {pk.replace('_', ' ')}: "
                        f"day-1 {learn['consensus_before']:+.2f}% -> {learn['consensus_after']:+.2f}% "
                        f"({', '.join(learn['drivers'])})"
                    )
                event_mom = (dm or {}).get("post_inventory_momentum")
                if event_mom:
                    print(
                        f"  Post-inventory momentum {pk.replace('_', ' ')}: "
                        f"z={event_mom['inventory_z']:+.2f}, "
                        f"prior {event_mom['prior_session_pct']:+.2f}% — "
                        f"day-1 {event_mom['consensus_before']:+.2f}% -> "
                        f"{event_mom['consensus_after']:+.2f}%"
                    )
                surprise = (dm or {}).get("inventory_surprise")
                if surprise:
                    print(
                        f"  Inventory surprise {pk.replace('_', ' ')}: "
                        f"z={surprise.get('inventory_z')} {surprise.get('lean')} — "
                        f"day-1 {surprise['consensus_before']:+.2f}% -> {surprise['consensus_after']:+.2f}%"
                    )
                headline = (dm or {}).get("headline_pullback")
                if headline:
                    print(
                        f"  Headline pullback {pk.replace('_', ' ')}: "
                        f"bearish supply {headline['bearish_supply_score']:.0%} — "
                        f"day-1 {headline['consensus_before']:+.2f}% -> {headline['consensus_after']:+.2f}%"
                    )
                thrust = (dm or {}).get("thrust_continuation")
                if thrust:
                    print(
                        f"  Multi-day thrust {pk.replace('_', ' ')}: "
                        f"3-session {thrust['three_session_pct']:+.2f}% — "
                        f"day-1 {thrust['consensus_before']:+.2f}% -> {thrust['consensus_after']:+.2f}%"
                    )
                cfade = (dm or {}).get("complex_spike_fade")
                if cfade:
                    print(
                        f"  Complex spike fade {pk.replace('_', ' ')}: "
                        f"crude prior {cfade['crude_prior_session_pct']:+.2f}% — "
                        f"day-1 {cfade['consensus_before']:+.2f}% -> {cfade['consensus_after']:+.2f}%"
                    )
                wash = (dm or {}).get("washout_bounce")
                if wash:
                    print(
                        f"  Washout bounce {pk.replace('_', ' ')}: "
                        f"{wash['washout_source']} {wash['washout_pct']:+.2f}% — "
                        f"day-1 {wash['consensus_before']:+.2f}% -> {wash['consensus_after']:+.2f}%"
                    )
                selloff = (dm or {}).get("selloff_continuation")
                if selloff:
                    print(
                        f"  Selloff continuation {pk.replace('_', ' ')}: "
                        f"{selloff.get('source')} prior {selloff['prior_session_pct']:+.2f}% — "
                        f"day-1 {selloff['consensus_before']:+.2f}% -> {selloff['consensus_after']:+.2f}%"
                    )
                overnight = (dm or {}).get("overnight_gap")
                if overnight:
                    print(
                        f"  Overnight gap {pk.replace('_', ' ')}: "
                        f"live {overnight['gap_pct']:+.2f}% — "
                        f"day-1 {overnight['consensus_before']:+.2f}% -> {overnight['consensus_after']:+.2f}%"
                    )
            for pk, dm in (day1_meta or {}).items():
                gap = (dm or {}).get("gap_risk") or {}
                if gap.get("active"):
                    reasons = ", ".join(gap.get("reasons") or []) or "elevated"
                    print(
                        f"  Gap risk ACTIVE (score {gap.get('score', 0):.2f}, "
                        f"cap x{gap.get('cap_mult', 1):.2f}): {reasons}"
                    )
                    break
            if current_prices:
                predictions = apply_session_close_baseline(predictions, current_prices)
        
        if predictions:
            print("\n" + self.predictor.format_predictions(predictions))
            
            # Save predictions to file with current prices
            predictions_json = {}
            spot_ref = getattr(self, "_spot_reference", {}) or {}
            anchor_date = pd.Timestamp(spot_ref.get("as_of_date") or datetime.now().date())
            session_hist = None
            horizon_targets: Dict[str, Any] = {}
            weekend_gap_flag = False
            try:
                from live_prices import is_weekend_gap_session, load_official_price_history, trading_session_offset
                session_hist = load_official_price_history()
                weekend_gap_flag = is_weekend_gap_session(session_hist)
                for hkey, days_ahead, _, _ in PREDICTION_HORIZONS:
                    t = trading_session_offset(anchor_date, days_ahead, session_hist)
                    if t is not None:
                        horizon_targets[hkey] = t
            except Exception:
                pass
            for product, pred in predictions.items():
                if pred:
                    # Always anchor to validated NYMEX session close (never stale pred cache)
                    current_price = current_prices.get(product) or pred.get('current_price', 0)
                    
                    # Handle NaN
                    if isinstance(current_price, float) and math.isnan(current_price):
                        current_price = current_prices.get(product, 0)
                    
                    if current_price == 0:
                        d1 = pred.get('day_1', pred.get('next_day', 0))
                        if d1 and d1 > 0:
                            current_price = float(d1) * 0.99

                    product_out = {
                        'current_price': float(current_price),
                        'confidence_range': {
                            'lower': float(pred.get('confidence_lower', 0)),
                            'upper': float(pred.get('confidence_upper', 0)),
                        },
                        'timestamp': datetime.now().isoformat(),
                    }
                    for hkey, _days, max_frac, label in PREDICTION_HORIZONS:
                        max_frac = max_frac_for(hkey, product)
                        raw_p = float(pred.get(hkey, pred.get(hkey.replace('day_', ''), current_price)))
                        if math.isnan(raw_p) or raw_p <= 0:
                            raw_p = current_price
                        else:
                            raw_p = max(
                                current_price * (1 - max_frac),
                                min(raw_p, current_price * (1 + max_frac)),
                            )
                        chg = ((raw_p - current_price) / current_price * 100) if current_price else 0
                        h_label = label
                        target_ts = horizon_targets.get(hkey)
                        if target_ts is not None:
                            if _days == 1 and (target_ts.normalize() - anchor_date.normalize()).days > 1:
                                h_label = f"Next session ({target_ts.strftime('%a %b %d')})"
                        product_out[hkey] = {
                            'price': raw_p,
                            'change_percent': float(chg),
                            'direction': 'UP' if chg > 0 else 'DOWN' if chg < 0 else 'FLAT',
                            'label': h_label,
                            'days_ahead': _days,
                        }
                        if target_ts is not None:
                            product_out[hkey]['target_date'] = target_ts.strftime('%Y-%m-%d')
                    # Legacy keys for older consumers
                    if 'day_1' in product_out:
                        product_out['next_day'] = product_out['day_1']
                    if 'day_4' in product_out:
                        product_out['next_week'] = product_out['day_4']
                    if 'day_7' in product_out:
                        product_out['biweekly'] = product_out['day_7']
                        product_out['monthly'] = product_out['day_7']
                    predictions_json[product] = product_out
            
            predictions_json['_meta'] = {
                'model': getattr(self.predictor, '_last_model_used', 'Prophet'),
                'model_stack': ['VAR/Prophet', 'XGBoost', 'Ensemble', 'BiasCorrection'],
                'weekend_gap': weekend_gap_flag,
                'crack_spreads_current': getattr(self.predictor, '_last_crack_snapshot', None),
                'crack_spreads_forecast_var': self.predictor.crack_spread_forecast_from_var(),
                'retail_pump_weekly': retail_weekly,
                'operational': self._latest_operational_snapshot(),
                'hurricane': self._hurricane_snapshot(),
                'freight': self._latest_freight_snapshot(),
                'xgb_rbob': getattr(self.predictor, '_last_xgb_info', None),
                'product_ml': getattr(self.predictor, '_last_product_ml', None),
                'catboost_medium_term': getattr(self.predictor, '_last_catboost_info', None),
                'dollar_index': latest_dollar_index_snapshot(),
                'catalyst_calendar': pre_meta.get('catalyst_calendar'),
                'ensemble': self._ensemble_meta,
                'day1_consensus': getattr(self, '_day1_meta', {}),
                'spot_reference': getattr(self, '_spot_reference', {}),
                'rag_context': self._rag_context,
                'forecast_horizons': [
                    {'key': k, 'days_ahead': d, 'label': lb} for k, d, _, lb in PREDICTION_HORIZONS
                ],
            }

            sentiment = None
            topic_snapshot = latest_topic_snapshot()
            try:
                fd_path = "data/final_data.csv"
                if os.path.exists(fd_path):
                    fd = pd.read_csv(fd_path)
                    if "sentiment" in fd.columns and len(fd):
                        sentiment = float(fd["sentiment"].iloc[-1])
                    if topic_snapshot.get("sentiment") is None and "geo_risk_score" in fd.columns:
                        topic_snapshot["geo_risk_score"] = float(fd["geo_risk_score"].iloc[-1])
            except Exception:
                sentiment = None

            intel = build_intelligence_layer(
                predictions_json, sentiment=sentiment, topic_snapshot=topic_snapshot
            )
            predictions_json["_meta"].update(intel)
            predictions_json["_meta"]["smart_alerts"] = smart_alert_candidates(
                predictions_json, intel
            )
            for pk, dv in (intel.get("directional_signals") or {}).items():
                if pk in predictions_json and isinstance(predictions_json[pk], dict):
                    predictions_json[pk]["directional"] = dv
            for pk, ts in (intel.get("trading_signals") or {}).items():
                if pk in predictions_json and isinstance(predictions_json[pk], dict):
                    predictions_json[pk]["trading_signal"] = ts

            finalize_email_narratives(predictions_json)

            try:
                from forecast_uncertainty import apply_forecast_uncertainty
                apply_forecast_uncertainty(
                    predictions_json,
                    day1_meta=getattr(self, "_day1_meta", {}),
                    ensemble_meta=self._ensemble_meta,
                )
            except Exception as e:
                print(f"Uncertainty layer skipped: {e}")

            try:
                from reasoning_engine import build_all_reasoning
                reasoning = build_all_reasoning(
                    predictions_json, self._ensemble_meta, self._rag_context
                )
                predictions_json["_meta"]["reasoning"] = reasoning
                for pk, text in reasoning.items():
                    if pk in predictions_json and isinstance(predictions_json[pk], dict):
                        predictions_json[pk]["reasoning"] = text
            except Exception as e:
                print(f"Reasoning skipped: {e}")

            # Calibrated baseline (see baseline_forecast.py / research/): centre = settle,
            # backtested price ranges. FORECAST_MODE=legacy keeps the old stack's numbers.
            try:
                from baseline_forecast import apply_baseline_forecast
                bl = apply_baseline_forecast(predictions_json)
                if bl.get("applied"):
                    print("Calibrated baseline applied (settle + EWMA ranges)")
            except Exception as e:
                print(f"Baseline forecast skipped: {e}")

            os.makedirs("data", exist_ok=True)
            with open("data/predictions.json", "w") as f:
                json.dump(predictions_json, f, indent=2)
            try:
                archive_path = archive_predictions(predictions_json)
                print(f"Predictions archived to {archive_path}")
            except Exception as e:
                print(f"Archive skipped: {e}")

            try:
                from database import init_db, log_prediction
                init_db()
                issued = datetime.now().isoformat()
                for pk, block in predictions_json.items():
                    if pk.startswith("_") or not isinstance(block, dict):
                        continue
                    for hkey in ("day_1", "day_4", "day_7"):
                        hd = block.get(hkey)
                        if not isinstance(hd, dict):
                            continue
                        log_prediction(
                            issued,
                            pk,
                            hkey,
                            float(hd.get("price", 0)),
                            float(block.get("current_price", 0)),
                            model_stack=predictions_json.get("_meta", {}).get("model", ""),
                            ensemble=(self._ensemble_meta or {}).get(pk),
                            reasoning=block.get("reasoning", ""),
                        )
            except Exception as e:
                print(f"DB prediction log skipped: {e}")
            
            print("\nPredictions saved to data/predictions.json")
            
            if not send_email:
                return predictions_json

            # Weekend day-1 email policy + correction on overnight flip
            try:
                from weekend_day1_email import (
                    should_defer_weekend_day1_email,
                    detect_day1_direction_flip,
                    enrich_email_meta,
                    save_last_sent_day1,
                    should_send_day1_email,
                    acquire_email_send_lock,
                    release_email_send_lock,
                )
                defer, defer_reason = should_defer_weekend_day1_email(predictions_json)
                if defer:
                    predictions_json.setdefault("_meta", {})["day1_email_deferred"] = True
                    predictions_json["_meta"]["day1_defer_reason"] = defer_reason
                    print(
                        f"\n[i] Weekend day-1 email deferred ({defer_reason}) — "
                        "predictions saved; email after Asia tape (~8:15 PM ET Sun)"
                    )
                else:
                    flip_info = detect_day1_direction_flip(predictions_json)
                    overnight_dom = bool(
                        flip_info and flip_info.get("overnight_dominates")
                    )
                    is_correction = bool(flip_info)
                    if flip_info:
                        flip_info.setdefault("reason", "overnight_gap")
                        enrich_email_meta(predictions_json, flip_info)
                        flips = flip_info.get("flips") or []
                        parts = [
                            f"{f['product'].replace('_', ' ')} {f['was']}->{f['now']}"
                            for f in flips
                        ]
                        print(
                            f"\n[i] Day-1 direction correction vs last email: {', '.join(parts)}"
                        )
                    send_ok, send_reason = should_send_day1_email(
                        predictions_json,
                        correction=is_correction,
                        force_send=force_send_email,
                        overnight_dominates=overnight_dom,
                    )
                    if send_ok:
                        if not acquire_email_send_lock():
                            predictions_json.setdefault("_meta", {})["day1_email_skipped"] = True
                            predictions_json["_meta"]["day1_skip_reason"] = "lock_busy"
                            print(
                                "\n[i] Day-1 email skipped (another send in progress) — "
                                "no duplicate send"
                            )
                        else:
                            try:
                                # Re-check after lock (scheduler + manual race)
                                send_ok2, send_reason2 = should_send_day1_email(
                                    predictions_json,
                                    correction=is_correction,
                                    force_send=force_send_email,
                                    overnight_dominates=overnight_dom,
                                )
                                if not send_ok2:
                                    predictions_json.setdefault("_meta", {})[
                                        "day1_email_skipped"
                                    ] = True
                                    predictions_json["_meta"][
                                        "day1_skip_reason"
                                    ] = send_reason2
                                    print(
                                        f"\n[i] Day-1 email skipped ({send_reason2}) — "
                                        "predictions updated; no duplicate send"
                                    )
                                else:
                                    sent = self.send_prediction_email(predictions_json)
                                    if sent:
                                        save_last_sent_day1(
                                            predictions_json, correction=is_correction
                                        )
                                    else:
                                        predictions_json.setdefault("_meta", {})[
                                            "day1_email_failed"
                                        ] = True
                                        print(
                                            "\n[!] Day-1 email not sent — "
                                            "check SMTP config / spam folder"
                                        )
                            finally:
                                release_email_send_lock()
                    else:
                        predictions_json.setdefault("_meta", {})["day1_email_skipped"] = True
                        predictions_json["_meta"]["day1_skip_reason"] = send_reason
                        print(
                            f"\n[i] Day-1 email skipped ({send_reason}) — "
                            "predictions updated; no duplicate send"
                        )
            except Exception as e:
                print(f"\nWeekend day-1 email policy skipped: {e}")
                import traceback
                traceback.print_exc()
            
            return predictions_json
        else:
            print("\nNo predictions generated")
            return None
    
    def send_prediction_email(self, predictions):
        """Send enhanced prediction email with comparisons and insights"""
        if not predictions:
            return False
        
        alert_system = EmailAlertSystem()
        
        if not alert_system.is_configured():
            print("\nEmail not configured. Predictions saved but not emailed.")
            return False
        
        try:
            # Use email-safe formatter (inline styles for email client compatibility)
            try:
                from email_formatter_simple import SimpleEmailFormatter
                formatter = SimpleEmailFormatter()
                html = formatter.format_email_html(predictions, None)
                subject = formatter.format_email_subject(predictions)
            except ImportError:
                # Fallback to original formatter
                from email_formatter import PredictionEmailFormatter
                formatter = PredictionEmailFormatter()
                previous_predictions = formatter.load_previous_predictions()
                html = formatter.format_email_html(predictions, previous_predictions)
                subject = f"Energy Market Predictions - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            
            # Create email message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = alert_system.sender_email
            # Unique recipients only (duplicate To entries → duplicate deliveries)
            recipients = list(dict.fromkeys(
                e.strip() for e in (alert_system.recipient_emails or []) if e and e.strip()
            ))
            if not recipients:
                print("\n[!] No recipient emails configured")
                return False
            msg['To'] = ', '.join(recipients)
            
            html_part = MIMEText(html, 'html', 'utf-8')
            msg.attach(html_part)
            
            # Send email once
            with smtplib.SMTP(alert_system.smtp_server, alert_system.smtp_port) as server:
                server.starttls()
                server.login(alert_system.sender_email, alert_system.sender_password)
                server.send_message(msg, to_addrs=recipients)
            
            print(f"\n[OK] Enhanced prediction email sent to: {', '.join(recipients)}")
            return True
            
        except Exception as e:
            print(f"\n[!] Error sending prediction email: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    def run_intraday_correction(self, *, force: bool = False) -> bool:
        """Refresh day-1 and email CORRECTED when live tape flips vs morning call."""
        try:
            from intraday_day1_correction import run_intraday_correction

            return run_intraday_correction(self, force=force)
        except Exception as e:
            print(f"\n[!] Intraday correction skipped: {e}")
            return False

    def run_full_pipeline(self, *, force_send_email: bool = False):
        """Run complete prediction pipeline"""
        print("\n" + "=" * 60)
        print("AI PREDICTION ENGINE - Full Pipeline")
        print("=" * 60)
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("Fast pipeline defaults active (TextBlob news, cached CatBoost, no FinBERT bulk scoring).")
        self._print_pipeline_health()
        
        # Step 1: Collect data
        self.collect_data()

        # Step 1b: Force named-month settles before scoring/forecast (reject RB=F)
        try:
            from live_prices import repair_recent_settles_from_named_month

            n_fix = repair_recent_settles_from_named_month(lookback_sessions=10)
            print(f"\nPre-forecast named-month settle repair: {n_fix} session(s)")
        except Exception as e:
            print(f"\nPre-forecast settle repair skipped: {e}")

        # Step 2: Post-mortem on matured forecasts (uses fresh prices)
        try:
            run_daily_post_mortem(verbose=True)
        except Exception as e:
            print(f"Post-mortem skipped: {e}")

        try:
            from auto_retrain import run_auto_retrain
            run_auto_retrain(verbose=True)
        except Exception as e:
            print(f"Auto-retrain skipped: {e}")
        
        # Step 3: Generate predictions (applies bias corrections from post-mortem)
        predictions = self.generate_predictions(force_send_email=force_send_email)
        
        print("\n" + "=" * 60)
        print("Pipeline Complete")
        print("=" * 60)
        
        return predictions

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run full prediction pipeline")
    parser.add_argument(
        "--force-email",
        action="store_true",
        help="Send email even if day-1 call is unchanged (still respects 90s hard gap)",
    )
    args = parser.parse_args()
    engine = PredictionEngine()
    engine.run_full_pipeline(force_send_email=args.force_email)
