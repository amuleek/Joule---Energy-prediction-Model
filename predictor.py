"""
AI Price Prediction Model
Predicts price movements for RBOB Gasoline, ULSD Diesel, and Crude Oil
Time horizons: Next day, Next week, Biweekly (2 weeks)
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import warnings
from typing import Optional
warnings.filterwarnings('ignore')

try:
    from prophet import Prophet
    PROPHET_AVAILABLE = True
except ImportError:
    PROPHET_AVAILABLE = False
    print("Warning: Prophet not installed. Using simple linear regression.")

from sklearn.linear_model import LinearRegression

try:
    from statsmodels.tsa.api import VAR
    VAR_AVAILABLE = True
except ImportError:
    VAR_AVAILABLE = False

GAL_PER_BBL = 42.0

from forecast_horizons import (
    LEGACY_ALIASES,
    MAX_FORECAST_PERIODS,
    PREDICTION_HORIZONS,
    max_frac_for,
    step_index,
)

try:
    from product_ml import apply_product_ml_overlay
    from rbob_xgb_model import apply_xgboost_rbob_overlay
    XGB_OVERLAY_AVAILABLE = True
except ImportError:
    try:
        from rbob_xgb_model import apply_xgboost_rbob_overlay
        apply_product_ml_overlay = None
        XGB_OVERLAY_AVAILABLE = True
    except ImportError:
        apply_product_ml_overlay = None
        XGB_OVERLAY_AVAILABLE = False

try:
    from medium_term_model import apply_medium_term_overlay
    MEDIUM_TERM_AVAILABLE = True
except ImportError:
    MEDIUM_TERM_AVAILABLE = False


class EnergyPricePredictor:
    """Predicts energy price movements using time series and sentiment analysis"""
    
    def __init__(self):
        self.models = {}
        self.scalers = {}
        self.data_path = "data/final_data.csv"
        self._last_var_forecast = None  # steps x 3: Crude, RBOB, ULSD
        self._last_crack_snapshot = None
        self._last_model_used = 'Prophet'
        self._last_xgb_info: Optional[dict] = None
        self._last_product_ml: Optional[dict] = None
        self._last_catboost_info: Optional[dict] = None

    def enrich_features(self, df):
        """Add barrel-equivalent crack spreads and lags if missing."""
        df = df.copy()
        for c in ('RBOB', 'ULSD', 'Crude'):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')
        if not all(c in df.columns for c in ('RBOB', 'ULSD', 'Crude')):
            return df
        if 'crack_gasoline' not in df.columns:
            df['crack_gasoline'] = df['RBOB'] * GAL_PER_BBL - df['Crude']
        if 'crack_diesel' not in df.columns:
            df['crack_diesel'] = df['ULSD'] * GAL_PER_BBL - df['Crude']
        for col in ('Crude', 'RBOB', 'ULSD'):
            if f'{col}_lag1' not in df.columns:
                df[f'{col}_lag1'] = df[col].shift(1)
            if f'{col}_lag7' not in df.columns:
                df[f'{col}_lag7'] = df[col].shift(7)
        if 'crack_gasoline_lag1' not in df.columns:
            df['crack_gasoline_lag1'] = df['crack_gasoline'].shift(1)
        if 'crack_diesel_lag1' not in df.columns:
            df['crack_diesel_lag1'] = df['crack_diesel'].shift(1)
        return df

    def load_data(self):
        """Load preprocessed data"""
        if not os.path.exists(self.data_path):
            print(f"Data file not found: {self.data_path}")
            print("Run preprocessing first: python scripts/preprocessing.py")
            return None
        
        df = pd.read_csv(self.data_path)
        if df.empty:
            print("No data available for prediction")
            return None
        
        # Convert date to datetime
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
        
        return self.enrich_features(df)

    def _apply_legacy_aliases(self, predictions: dict) -> dict:
        for old_key, new_key in LEGACY_ALIASES.items():
            if new_key in predictions:
                predictions[old_key] = predictions[new_key]
                pct_key = f"{new_key}_change"
                dir_key = f"{new_key}_direction"
                if pct_key in predictions:
                    predictions[f"{old_key}_change"] = predictions[pct_key]
                if dir_key in predictions:
                    predictions[f"{old_key}_direction"] = predictions[dir_key]
        return predictions

    def _finalize_product_prediction(self, current_price, predictions, product_key=None):
        """Clamp horizons (day 1 / 4 / 7), add change % and directions."""
        import math
        current_price = float(current_price)
        for key, _days, max_frac, _label in PREDICTION_HORIZONS:
            if product_key:
                max_frac = max_frac_for(key, product_key)
            if key not in predictions:
                continue
            val = predictions[key]
            if math.isnan(val) or val <= 0 or val > current_price * 10 or val < current_price * 0.1:
                predictions[key] = current_price
            else:
                lo = current_price * (1 - max_frac)
                hi = current_price * (1 + max_frac)
                predictions[key] = max(lo, min(float(val), hi))
            chg = ((predictions[key] - current_price) / current_price) * 100 if current_price else 0.0
            predictions[f"{key}_change"] = float(chg)
            predictions[f"{key}_direction"] = "UP" if chg > 0 else "DOWN" if chg < 0 else "FLAT"
        predictions["current_price"] = current_price
        return self._apply_legacy_aliases(predictions)

    def _raw_horizons_from_steps(self, step_values, last_step_for_confidence: int = None):
        """Build raw price dict from a sequence indexed by step_index(days_ahead)."""
        raw = {}
        for key, days, _, _ in PREDICTION_HORIZONS:
            step = min(step_index(days), len(step_values) - 1)
            raw[key] = float(step_values[step])
        conf_step = last_step_for_confidence
        if conf_step is None:
            conf_step = step_index(PREDICTION_HORIZONS[-1][1])
        conf_step = min(conf_step, len(step_values) - 1)
        raw["confidence_lower"] = float(step_values[conf_step]) * 0.95
        raw["confidence_upper"] = float(step_values[conf_step]) * 1.05
        return raw

    def predict_joint_var(self, df):
        """
        Joint VAR on Crude, RBOB, ULSD — captures cross-impacts in one model.
        Crack spreads are implied by forecasts: product*42 - crude ($/bbl).
        """
        self._last_var_forecast = None
        if not VAR_AVAILABLE:
            return None
        cols = ['Crude', 'RBOB', 'ULSD']
        if not all(c in df.columns for c in cols):
            return None
        data = df[cols].dropna()
        if len(data) < 10:
            print(f"VAR skipped: need at least 10 complete rows (have {len(data)})")
            return None
        # Conservative maxlags for 3-equation VAR on short samples
        maxlags = min(5, max(1, len(data) // 10))
        try:
            model = VAR(data)
            results = model.fit(maxlags=maxlags, ic='aic')
            lag = results.k_ar
            y = data.values[-lag:]
            fc = results.forecast(y, steps=max(30, MAX_FORECAST_PERIODS))
            self._last_var_forecast = fc
        except Exception as e:
            print(f"VAR fit failed: {e}")
            return None

        idx = {'Crude': 0, 'RBOB': 1, 'ULSD': 2}
        product_map = [
            ('Crude_Oil', 'Crude'),
            ('RBOB_Gasoline', 'RBOB'),
            ('ULSD_Diesel', 'ULSD'),
        ]
        results_out = {}
        for key, col in product_map:
            cidx = idx[col]
            current_price = float(data[col].iloc[-1])
            series = [float(fc[s, cidx]) for s in range(fc.shape[0])]
            raw = self._raw_horizons_from_steps(series)
            results_out[key] = self._finalize_product_prediction(current_price, raw, product_key=key)
        return results_out

    def _extra_regressors(self, df):
        """Optional columns for multivariate Prophet."""
        cols = []
        if 'sentiment' in df.columns:
            cols.append('sentiment')
        if 'geo_risk_score' in df.columns:
            cols.append('geo_risk_score')
        if 'retail_gasoline' in df.columns and df['retail_gasoline'].notna().any():
            cols.append('retail_gasoline')
        return cols

    def predict_with_prophet_multivariate(self, df, product_col):
        """Prophet with crack spreads, sentiment, geo risk, and retail pump as regressors."""
        if not PROPHET_AVAILABLE:
            return None
        need = ['date', product_col, 'crack_gasoline', 'crack_diesel']
        if not all(c in df.columns for c in need):
            return None
        try:
            extra = self._extra_regressors(df)
            use_cols = ['date', product_col, 'crack_gasoline', 'crack_diesel'] + extra
            p = df[use_cols].copy()
            p['date'] = pd.to_datetime(p['date'], errors='coerce')
            p = p.dropna(subset=['date', product_col, 'crack_gasoline', 'crack_diesel'])
            p = p[p[product_col] > 0]
            if len(p) < 5:
                return None
            for col in extra:
                p[col] = pd.to_numeric(p[col], errors='coerce').fillna(0.0)
            p = p.rename(columns={'date': 'ds', product_col: 'y'})
            model = Prophet(
                yearly_seasonality=False,
                weekly_seasonality=True,
                daily_seasonality=False,
                seasonality_mode='additive',
            )
            model.add_regressor('crack_gasoline')
            model.add_regressor('crack_diesel')
            for col in extra:
                model.add_regressor(col)
            model.fit(p)
            future = model.make_future_dataframe(periods=MAX_FORECAST_PERIODS)
            last = p.iloc[-1]
            future['crack_gasoline'] = float(last['crack_gasoline'])
            future['crack_diesel'] = float(last['crack_diesel'])
            for col in extra:
                future[col] = float(last[col])
            forecast = model.predict(future)
            hist_len = len(p)
            yhat_series = forecast.iloc[hist_len:]['yhat'].astype(float).values
            conf_i = min(hist_len + step_index(PREDICTION_HORIZONS[-1][1]), len(forecast) - 1)
            predictions = self._raw_horizons_from_steps(yhat_series)
            predictions['confidence_lower'] = float(forecast.iloc[conf_i]['yhat_lower'])
            predictions['confidence_upper'] = float(forecast.iloc[conf_i]['yhat_upper'])
            for key, _, _, _ in PREDICTION_HORIZONS:
                if predictions[key] <= 0 or np.isnan(predictions[key]):
                    return None
            return predictions
        except Exception as e:
            print(f"Multivariate Prophet error ({product_col}): {e}")
            return None

    def predict_with_prophet(self, df, product_col, periods=14):
        """Predict using Facebook Prophet"""
        if not PROPHET_AVAILABLE:
            return None
        
        try:
            # Step 1: Clean data - remove rows with missing dates or prices
            clean_df = df[['date', product_col]].copy()
            
            # Convert date to datetime and drop invalid dates
            clean_df['date'] = pd.to_datetime(clean_df['date'], errors='coerce')
            clean_df = clean_df.dropna(subset=['date', product_col])  # Drop rows where date or price is NaN
            
            # Ensure price values are positive
            clean_df = clean_df[clean_df[product_col] > 0]
            
            if len(clean_df) < 3:  # Need at least 3 days of data for Prophet
                print(f"Warning: Only {len(clean_df)} valid days of data. Need at least 3 days for Prophet.")
                return None
            
            # Step 2: Prepare data for Prophet (exact column names required: ds, y)
            prophet_df = clean_df.copy()
            prophet_df.columns = ['ds', 'y']
            prophet_df = prophet_df.sort_values('ds')  # Ensure chronological order
            
            # Step 3: Add sentiment as regressor if available (must align with cleaned data)
            has_sentiment = False
            if 'sentiment' in df.columns:
                # Re-merge sentiment with cleaned data
                sentiment_df = df[['date', 'sentiment']].copy()
                sentiment_df['date'] = pd.to_datetime(sentiment_df['date'], errors='coerce')
                sentiment_df = sentiment_df.dropna(subset=['date'])
                
                # Rename 'date' to 'ds' to match prophet_df column name
                sentiment_df = sentiment_df.rename(columns={'date': 'ds'})
                
                # Merge sentiment with prophet_df
                prophet_df = prophet_df.merge(sentiment_df, on='ds', how='left')
                prophet_df['sentiment'] = prophet_df['sentiment'].fillna(0.0)  # Fill missing with 0
                has_sentiment = True
            
            # Step 4: Create and fit model with proper seasonality
            model = Prophet(
                yearly_seasonality=False,  # Disable for short data
                weekly_seasonality=True,   # Enable weekly patterns
                daily_seasonality=False,   # Disable daily (not needed for daily data)
                seasonality_mode='additive'
            )
            
            # Add sentiment regressor if available
            if has_sentiment:
                model.add_regressor('sentiment')
            
            model.fit(prophet_df)
            
            # Step 5: Make future dataframe (30 days for monthly predictions)
            future = model.make_future_dataframe(periods=MAX_FORECAST_PERIODS)

            if has_sentiment:
                last_sentiment = float(prophet_df['sentiment'].iloc[-1]) if len(prophet_df) > 0 else 0.0
                future['sentiment'] = last_sentiment

            forecast = model.predict(future)
            hist_len = len(prophet_df)
            yhat_series = forecast.iloc[hist_len:]['yhat'].astype(float).values
            conf_i = min(hist_len + step_index(PREDICTION_HORIZONS[-1][1]), len(forecast) - 1)
            predictions = self._raw_horizons_from_steps(yhat_series)
            predictions['confidence_lower'] = float(forecast.iloc[conf_i]['yhat_lower'])
            predictions['confidence_upper'] = float(forecast.iloc[conf_i]['yhat_upper'])

            import math
            for key, _, _, _ in PREDICTION_HORIZONS:
                if math.isnan(predictions[key]) or predictions[key] <= 0:
                    print(f"Warning: Prophet returned invalid {key} prediction: {predictions[key]}")
                    return None

            return predictions
            
        except Exception as e:
            print(f"Prophet prediction error: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    def predict_with_linear(self, df, product_col, periods=14):
        """Simple linear regression prediction (fallback)"""
        try:
            # Prepare features
            df_clean = df[['date', product_col]].copy().dropna()
            
            if len(df_clean) < 3:
                return None
            
            # Create time-based features
            df_clean['days'] = (df_clean['date'] - df_clean['date'].min()).dt.days
            
            X = df_clean[['days']].values
            y = df_clean[product_col].values
            
            # Fit model
            model = LinearRegression()
            model.fit(X, y)
            
            # Predict future (30 days for monthly)
            last_day = df_clean['days'].max()
            n_future = max(31, MAX_FORECAST_PERIODS + 1)
            future_days = np.array([[last_day + i] for i in range(1, n_future)])
            predictions_array = model.predict(future_days).flatten()
            predictions = self._raw_horizons_from_steps(predictions_array)
            return predictions
            
        except Exception as e:
            print(f"Linear prediction error: {str(e)}")
            return None
    
    def predict_product(self, df, product_col, product_name):
        """Predict price for a specific product"""
        if product_col not in df.columns:
            print(f"Column {product_col} not found in data")
            return None
        
        current_price = df[product_col].iloc[-1] if not df[product_col].isna().all() else None
        
        if current_price is None:
            print(f"No current price data for {product_name}")
            return None
        
        # Multivariate Prophet (crack spreads + sentiment), then univariate Prophet, then linear
        predictions = self.predict_with_prophet_multivariate(df, product_col)
        if predictions is None:
            predictions = self.predict_with_prophet(df, product_col)
        if predictions is None:
            predictions = self.predict_with_linear(df, product_col)
        
        if predictions is None:
            # If both models fail, use simple trend-based prediction
            # With limited data, just predict small change based on recent trend
            recent_prices = df[product_col].dropna().tail(3)
            if len(recent_prices) >= 2:
                trend = (recent_prices.iloc[-1] - recent_prices.iloc[0]) / len(recent_prices)
                predictions = {
                    key: float(current_price + trend * days)
                    for key, days, _, _ in PREDICTION_HORIZONS
                }
                predictions['confidence_lower'] = float(current_price * 0.95)
                predictions['confidence_upper'] = float(current_price * 1.05)
            else:
                predictions = {
                    key: float(current_price)
                    for key, _, _, _ in PREDICTION_HORIZONS
                }
                predictions['confidence_lower'] = float(current_price * 0.95)
                predictions['confidence_upper'] = float(current_price * 1.05)
        
        product_key_map = {
            "RBOB": "RBOB_Gasoline",
            "ULSD": "ULSD_Diesel",
            "Crude": "Crude_Oil",
        }
        return self._finalize_product_prediction(
            current_price, predictions, product_key=product_key_map.get(product_col)
        )
    
    def _apply_session_baseline(
        self,
        df: pd.DataFrame,
        session_prices: Optional[dict],
        settle_date: Optional[str],
    ) -> pd.DataFrame:
        """Use last completed NYMEX settlement as the model's starting point."""
        if df is None or df.empty or not session_prices or not settle_date:
            return df
        if "date" not in df.columns:
            return df

        out = df.copy()
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        settle = pd.to_datetime(settle_date).normalize()
        out = out[out["date"].dt.normalize() <= settle].sort_values("date").reset_index(drop=True)
        if out.empty:
            return df

        col_map = {
            "RBOB_Gasoline": "RBOB",
            "ULSD_Diesel": "ULSD",
            "Crude_Oil": "Crude",
        }
        fut_map = {
            "RBOB_Gasoline": "rbob_close",
            "ULSD_Diesel": "diesel_close",
            "Crude_Oil": "crude_close",
        }
        last = out.index[-1]
        for product_key, col in col_map.items():
            price = session_prices.get(product_key)
            if price and col in out.columns:
                out.at[last, col] = float(price)
            fut_col = fut_map.get(product_key)
            if price and fut_col in out.columns:
                out.at[last, fut_col] = float(price)
        return out

    def generate_predictions(
        self,
        df: Optional[pd.DataFrame] = None,
        session_prices: Optional[dict] = None,
        settle_date: Optional[str] = None,
    ):
        """Generate predictions — joint VAR when enough data, else per-product chain.

        If ``df`` is provided (walk-forward / backtests), it must include at least
        ``date`` and price columns; it is enriched the same way as ``load_data()``."""
        if df is None:
            df = self.load_data()
        else:
            df = self.enrich_features(df.copy())
            if df.empty:
                return None
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'], errors='coerce')
                df = df.sort_values('date').reset_index(drop=True)
        if df is None:
            return None

        df = self._apply_session_baseline(df, session_prices, settle_date)

        self._last_crack_snapshot = self.crack_spread_snapshot(df)
        self._last_model_used = 'Prophet'
        self._last_xgb_info = None

        joint = self.predict_joint_var(df)
        if joint:
            self._last_model_used = 'VAR'
            print("Using joint VAR model (Crude, RBOB, ULSD) with implied crack spreads.")
            joint = self._apply_xgb_overlay(df, joint)
            joint = self._apply_medium_term_overlay(df, joint)
            return joint

        results = {}
        if 'RBOB' in df.columns:
            results['RBOB_Gasoline'] = self.predict_product(df, 'RBOB', 'RBOB Gasoline')
        if 'ULSD' in df.columns:
            results['ULSD_Diesel'] = self.predict_product(df, 'ULSD', 'ULSD Diesel')
        if 'Crude' in df.columns:
            results['Crude_Oil'] = self.predict_product(df, 'Crude', 'Crude Oil')
        results = self._apply_xgb_overlay(df, results)
        return self._apply_medium_term_overlay(df, results)

    def _apply_xgb_overlay(self, df, results):
        if not results or not XGB_OVERLAY_AVAILABLE:
            return results
        try:
            if apply_product_ml_overlay is not None:
                results, infos = apply_product_ml_overlay(
                    df, results, finalize_fn=self._finalize_product_prediction
                )
                self._last_product_ml = infos
                self._last_xgb_info = infos.get("RBOB_Gasoline") or {}
                used = [pk for pk, inf in infos.items() if inf.get("used")]
                if used:
                    self._last_model_used = f"{self._last_model_used}+ML"
                for pk, info in infos.items():
                    if not info.get("used"):
                        continue
                    wf = info.get("walk_forward") or {}
                    label = pk.replace("_", " ")
                    print(
                        f"{label} next session: ML {info.get('predicted_return_pct', 0):+.2f}% "
                        f"({info.get('direction')}, conf {info.get('confidence_pct')}%) "
                        f"walk-forward dir {wf.get('dir_acc') or '?'} "
                        f"MAE {wf.get('mae') or '?'}."
                    )
                return results
            results, info = apply_xgboost_rbob_overlay(
                df, results, finalize_fn=self._finalize_product_prediction
            )
            self._last_xgb_info = info
            if info.get("used"):
                self._last_model_used = f"{self._last_model_used}+XGB"
                print(
                    f"RBOB tomorrow: XGB ${info.get('next_day_price', 0):.4f} "
                    f"(holdout MAPE ~{info.get('holdout_mape_pct', '?')}%), "
                    f"blended with {self._last_model_used.split('+')[0]}."
                )
        except Exception as e:
            print(f"XGBoost overlay skipped: {e}")
        return results

    def _apply_medium_term_overlay(self, df, results):
        if not results or not MEDIUM_TERM_AVAILABLE:
            return results
        try:
            results, info = apply_medium_term_overlay(
                df, results, finalize_fn=self._finalize_product_prediction
            )
            self._last_catboost_info = info
            if info.get("products"):
                used = sum(
                    1 for pk in info["products"]
                    for hk in info["products"][pk]
                    if info["products"][pk][hk].get("used")
                )
                if used:
                    self._last_model_used = f"{self._last_model_used}+CatBoost"
                    print(f"Medium-term CatBoost overlay applied ({used} product-horizon models).")
        except Exception as e:
            print(f"CatBoost medium-term overlay skipped: {e}")
        return results

    def crack_spread_snapshot(self, df):
        """Current barrel-equivalent crack spreads ($/bbl) from last row."""
        if df is None or not all(c in df.columns for c in ('RBOB', 'ULSD', 'Crude')):
            return None
        last = df.dropna(subset=['RBOB', 'ULSD', 'Crude']).iloc[-1]
        rbob = float(last['RBOB'])
        ulsd = float(last['ULSD'])
        crude = float(last['Crude'])
        return {
            'gasoline_crack_usd_per_bbl': rbob * GAL_PER_BBL - crude,
            'diesel_crack_usd_per_bbl': ulsd * GAL_PER_BBL - crude,
            'units': 'Approx. product value 42 gal/bbl minus WTI; refinery margin proxy',
        }

    def crack_spread_forecast_from_var(self):
        """Implied crack spreads from last VAR forecast (if any)."""
        fc = self._last_var_forecast
        if fc is None or fc.shape[0] < 1:
            return None
        out = {}
        for key, days, _, _ in PREDICTION_HORIZONS:
            step = min(step_index(days), fc.shape[0] - 1)
            c, r, u = float(fc[step, 0]), float(fc[step, 1]), float(fc[step, 2])
            out[key] = {
                'gasoline_crack_usd_per_bbl': r * GAL_PER_BBL - c,
                'diesel_crack_usd_per_bbl': u * GAL_PER_BBL - c,
            }
        return out
    
    def format_predictions(self, predictions):
        """Format predictions for display/email"""
        if not predictions:
            return "No predictions available"
        
        output = []
        output.append("=" * 60)
        output.append("AI PRICE PREDICTIONS")
        output.append("=" * 60)
        output.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        output.append("")
        snap = getattr(self, '_last_crack_snapshot', None)
        if snap:
            output.append("Crack spreads (proxy, $/bbl):")
            output.append(f"  Gasoline: {snap['gasoline_crack_usd_per_bbl']:.2f}  |  Diesel: {snap['diesel_crack_usd_per_bbl']:.2f}")
            output.append("")
        fc_crack = self.crack_spread_forecast_from_var()
        if fc_crack:
            nd = fc_crack.get('next_day', {})
            output.append("VAR-implied crack (next day, $/bbl):")
            output.append(f"  Gasoline: {nd.get('gasoline_crack_usd_per_bbl', 0):.2f}  |  Diesel: {nd.get('diesel_crack_usd_per_bbl', 0):.2f}")
            output.append("")
        
        for product, pred in predictions.items():
            if pred is None:
                continue
            
            output.append(f"{product.replace('_', ' ')}:")
            output.append(f"  Current Price: ${pred['current_price']:.4f}")
            output.append("")
            output.append("  Predictions:")
            for key, days, _, label in PREDICTION_HORIZONS:
                if key not in pred:
                    continue
                dr = pred.get(f"{key}_direction", "FLAT")
                arrow = "+" if dr == "UP" else "-" if dr == "DOWN" else " "
                chg = abs(pred.get(f"{key}_change", 0))
                output.append(f"    {label:16} ${pred[key]:.4f} ({arrow}{chg:.2f}%)")
            output.append(f"    Confidence:    ${pred['confidence_lower']:.4f} - ${pred['confidence_upper']:.4f}")
            output.append("")
        
        output.append("=" * 60)
        return "\n".join(output)

if __name__ == "__main__":
    predictor = EnergyPricePredictor()
    predictions = predictor.generate_predictions()
    
    if predictions:
        print(predictor.format_predictions(predictions))
    else:
        print("No predictions generated. Ensure data files exist in data/ folder.")
