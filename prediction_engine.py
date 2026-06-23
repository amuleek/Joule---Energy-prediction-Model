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

        print("\n1a. Syncing spot prices from live futures…")
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
    
    def generate_predictions(self):
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
        for product, price in current_prices.items():
            label = product.replace("_", " ")
            print(f"  {label}: ${price:.4f}")

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
                    "sentiment": None,
                    "dollar_index": latest_dollar_index_snapshot(),
                }
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
            predictions = apply_bias_to_predictions(predictions)
            predictions, day1_meta = reconcile_day1_precision(
                predictions,
                ensemble_meta=ensemble_meta,
                xgb_info=getattr(self.predictor, "_last_xgb_info", None),
                current_prices=current_prices,
                context_meta={"geo_risk_score": topic_snapshot.get("geo_risk_score")},
            )
            self._day1_meta = day1_meta
            if current_prices:
                predictions = apply_session_close_baseline(predictions, current_prices)
        
        if predictions:
            print("\n" + self.predictor.format_predictions(predictions))
            
            # Save predictions to file with current prices
            predictions_json = {}
            for product, pred in predictions.items():
                if pred:
                    # Use fetched current price if available, otherwise use from prediction
                    current_price = current_prices.get(product, pred.get('current_price', 0))
                    
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
                        product_out[hkey] = {
                            'price': raw_p,
                            'change_percent': float(chg),
                            'direction': 'UP' if chg > 0 else 'DOWN' if chg < 0 else 'FLAT',
                            'label': label,
                            'days_ahead': _days,
                        }
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
                'crack_spreads_current': getattr(self.predictor, '_last_crack_snapshot', None),
                'crack_spreads_forecast_var': self.predictor.crack_spread_forecast_from_var(),
                'retail_pump_weekly': retail_weekly,
                'operational': self._latest_operational_snapshot(),
                'hurricane': self._hurricane_snapshot(),
                'freight': self._latest_freight_snapshot(),
                'xgb_rbob': getattr(self.predictor, '_last_xgb_info', None),
                'catboost_medium_term': getattr(self.predictor, '_last_catboost_info', None),
                'dollar_index': latest_dollar_index_snapshot(),
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
            
            # Send prediction email if configured
            self.send_prediction_email(predictions_json)
            
            return predictions_json
        else:
            print("\nNo predictions generated")
            return None
    
    def send_prediction_email(self, predictions):
        """Send enhanced prediction email with comparisons and insights"""
        if not predictions:
            return
        
        alert_system = EmailAlertSystem()
        
        if not alert_system.is_configured():
            print("\nEmail not configured. Predictions saved but not emailed.")
            return
        
        try:
            # Use email-safe formatter (inline styles for email client compatibility)
            try:
                from email_formatter_simple import SimpleEmailFormatter
                formatter = SimpleEmailFormatter()
                html = formatter.format_email_html(predictions, None)
            except ImportError:
                # Fallback to original formatter
                from email_formatter import PredictionEmailFormatter
                formatter = PredictionEmailFormatter()
                previous_predictions = formatter.load_previous_predictions()
                html = formatter.format_email_html(predictions, previous_predictions)
            
            # Create email message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"🔮 Energy Market AI Predictions - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            msg['From'] = alert_system.sender_email
            msg['To'] = ', '.join(alert_system.recipient_emails)
            
            html_part = MIMEText(html, 'html')
            msg.attach(html_part)
            
            # Send email
            with smtplib.SMTP(alert_system.smtp_server, alert_system.smtp_port) as server:
                server.starttls()
                server.login(alert_system.sender_email, alert_system.sender_password)
                server.send_message(msg)
            
            print(f"\n[OK] Enhanced prediction email sent to: {', '.join(alert_system.recipient_emails)}")
            
        except Exception as e:
            print(f"\n[!] Error sending prediction email: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def run_full_pipeline(self):
        """Run complete prediction pipeline"""
        print("\n" + "=" * 60)
        print("AI PREDICTION ENGINE - Full Pipeline")
        print("=" * 60)
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("Fast pipeline defaults active (TextBlob news, cached CatBoost, no FinBERT bulk scoring).")
        
        # Step 1: Collect data
        self.collect_data()

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
        predictions = self.generate_predictions()
        
        print("\n" + "=" * 60)
        print("Pipeline Complete")
        print("=" * 60)
        
        return predictions

if __name__ == "__main__":
    engine = PredictionEngine()
    engine.run_full_pipeline()
