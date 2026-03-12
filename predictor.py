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
warnings.filterwarnings('ignore')

try:
    from prophet import Prophet
    PROPHET_AVAILABLE = True
except ImportError:
    PROPHET_AVAILABLE = False
    print("Warning: Prophet not installed. Using simple linear regression.")

from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler

class EnergyPricePredictor:
    """Predicts energy price movements using time series and sentiment analysis"""
    
    def __init__(self):
        self.models = {}
        self.scalers = {}
        self.data_path = "data/final_data.csv"
    
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
        
        return df
    
    def predict_with_prophet(self, df, product_col, periods=14):
        """Predict using Facebook Prophet"""
        if not PROPHET_AVAILABLE:
            return None
        
        try:
            # Prepare data for Prophet
            prophet_df = df[['date', product_col]].copy()
            prophet_df.columns = ['ds', 'y']
            prophet_df = prophet_df.dropna()
            
            if len(prophet_df) < 3:  # Need at least 3 days of data for Prophet
                print(f"Warning: Only {len(prophet_df)} days of data. Need at least 3 days for Prophet. Using linear regression.")
                return None
            
            # Create and fit model
            model = Prophet(yearly_seasonality=False, daily_seasonality=False)
            
            # Add sentiment as regressor if available
            if 'sentiment' in df.columns:
                prophet_df['sentiment'] = df['sentiment'].values[:len(prophet_df)]
                model.add_regressor('sentiment')
            
            model.fit(prophet_df)
            
            # Make future predictions (14 days for biweekly, 30 for monthly)
            future = model.make_future_dataframe(periods=30)  # Extended to 30 days for monthly
            if 'sentiment' in df.columns:
                # Use last known sentiment for future periods
                last_sentiment = df['sentiment'].iloc[-1] if not df['sentiment'].isna().all() else 0.0
                future['sentiment'] = last_sentiment
            
            forecast = model.predict(future)
            
            # Get predictions for next day, week, biweekly (2 weeks), and monthly (30 days)
            predictions = {
                'next_day': float(forecast.iloc[-30]['yhat']) if len(forecast) > 30 else float(forecast.iloc[-1]['yhat']),
                'next_week': float(forecast.iloc[-23]['yhat']) if len(forecast) >= 23 else float(forecast.iloc[-1]['yhat']),
                'biweekly': float(forecast.iloc[-16]['yhat']) if len(forecast) >= 16 else float(forecast.iloc[-1]['yhat']),
                'monthly': float(forecast.iloc[-1]['yhat']),  # 30 days out
                'confidence_lower': float(forecast.iloc[-1]['yhat_lower']),
                'confidence_upper': float(forecast.iloc[-1]['yhat_upper'])
            }
            
            return predictions
            
        except Exception as e:
            print(f"Prophet prediction error: {str(e)}")
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
            future_days = np.array([[last_day + i] for i in range(1, 31)])  # 30 days
            predictions_array = model.predict(future_days)
            
            predictions = {
                'next_day': float(predictions_array[0]),
                'next_week': float(predictions_array[6]) if len(predictions_array) > 6 else float(predictions_array[-1]),
                'biweekly': float(predictions_array[13]) if len(predictions_array) > 13 else float(predictions_array[-1]),
                'monthly': float(predictions_array[-1]),  # 30 days
                'confidence_lower': float(predictions_array[-1] * 0.95),  # Simple 5% lower bound
                'confidence_upper': float(predictions_array[-1] * 1.05)   # Simple 5% upper bound
            }
            
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
        
        # Try Prophet first, fallback to linear
        predictions = self.predict_with_prophet(df, product_col)
        if predictions is None:
            predictions = self.predict_with_linear(df, product_col)
        
        if predictions is None:
            return None
        
        # Calculate percentage changes
        predictions['current_price'] = float(current_price)
        predictions['next_day_change'] = ((predictions['next_day'] - current_price) / current_price) * 100
        predictions['next_week_change'] = ((predictions['next_week'] - current_price) / current_price) * 100
        predictions['biweekly_change'] = ((predictions['biweekly'] - current_price) / current_price) * 100
        
        # Add monthly prediction if available, otherwise use biweekly
        if 'monthly' not in predictions:
            predictions['monthly'] = predictions['biweekly']
        predictions['monthly_change'] = ((predictions['monthly'] - current_price) / current_price) * 100
        
        # Determine direction (using ASCII-safe characters)
        predictions['next_day_direction'] = 'UP' if predictions['next_day_change'] > 0 else 'DOWN'
        predictions['next_week_direction'] = 'UP' if predictions['next_week_change'] > 0 else 'DOWN'
        predictions['biweekly_direction'] = 'UP' if predictions['biweekly_change'] > 0 else 'DOWN'
        predictions['monthly_direction'] = 'UP' if predictions['monthly_change'] > 0 else 'DOWN'
        
        return predictions
    
    def generate_predictions(self):
        """Generate predictions for all products"""
        df = self.load_data()
        if df is None:
            return None
        
        results = {}
        
        # Predict RBOB Gasoline
        if 'RBOB' in df.columns:
            results['RBOB_Gasoline'] = self.predict_product(df, 'RBOB', 'RBOB Gasoline')
        
        # Predict ULSD Diesel
        if 'ULSD' in df.columns:
            results['ULSD_Diesel'] = self.predict_product(df, 'ULSD', 'ULSD Diesel')
        
        # Predict Crude Oil
        if 'Crude' in df.columns:
            results['Crude_Oil'] = self.predict_product(df, 'Crude', 'Crude Oil')
        
        return results
    
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
        
        for product, pred in predictions.items():
            if pred is None:
                continue
            
            output.append(f"{product.replace('_', ' ')}:")
            output.append(f"  Current Price: ${pred['current_price']:.4f}")
            output.append("")
            output.append("  Predictions:")
            arrow_day = '+' if pred['next_day_direction'] == 'UP' else '-'
            arrow_week = '+' if pred['next_week_direction'] == 'UP' else '-'
            arrow_bi = '+' if pred['biweekly_direction'] == 'UP' else '-'
            arrow_month = '+' if pred.get('monthly_direction', 'UP') == 'UP' else '-'
            output.append(f"    Tomorrow:     ${pred['next_day']:.4f} ({arrow_day}{abs(pred['next_day_change']):.2f}%)")
            output.append(f"    One Week:      ${pred['next_week']:.4f} ({arrow_week}{abs(pred['next_week_change']):.2f}%)")
            output.append(f"    Two Weeks:     ${pred['biweekly']:.4f} ({arrow_bi}{abs(pred['biweekly_change']):.2f}%)")
            if 'monthly' in pred:
                output.append(f"    One Month:     ${pred['monthly']:.4f} ({arrow_month}{abs(pred['monthly_change']):.2f}%)")
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
