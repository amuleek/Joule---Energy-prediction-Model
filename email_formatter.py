"""
Enhanced Email Formatter for Energy Market Predictions
Creates user-friendly, detailed prediction emails with comparisons
"""
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional

class PredictionEmailFormatter:
    """Formats prediction emails with enhanced visuals and comparisons"""
    
    def __init__(self):
        self.predictions_file = "data/predictions.json"
        self.product_names = {
            'RBOB_Gasoline': {
                'display': 'RBOB Gasoline',
                'description': 'Reformulated Blendstock for Oxygenate Blending (Gasoline Futures)',
                'unit': 'per gallon',
                'symbol': 'RB=F'
            },
            'ULSD_Diesel': {
                'display': 'Ultra-Low Sulfur Diesel',
                'description': 'NY Harbor ULSD (Diesel Futures)',
                'unit': 'per gallon',
                'symbol': 'HO=F'
            },
            'Crude_Oil': {
                'display': 'Crude Oil (WTI)',
                'description': 'West Texas Intermediate Crude Oil',
                'unit': 'per barrel',
                'symbol': 'CL=F'
            }
        }
    
    def load_previous_predictions(self) -> Optional[Dict]:
        """Load previous predictions for comparison"""
        if not os.path.exists(self.predictions_file):
            return None
        
        try:
            with open(self.predictions_file, 'r') as f:
                data = json.load(f)
                # Get timestamp from first product
                if data and len(data) > 0:
                    first_key = list(data.keys())[0]
                    if 'timestamp' in data[first_key]:
                        return data
        except:
            pass
        return None
    
    def get_change_from_previous(self, current_pred: Dict, previous_pred: Dict, horizon: str) -> Optional[Dict]:
        """Compare current prediction with previous prediction"""
        if not previous_pred or horizon not in previous_pred:
            return None
        
        current_price = current_pred.get(horizon, {}).get('price', 0)
        previous_price = previous_pred.get(horizon, {}).get('price', 0)
        
        if previous_price == 0 or current_price == 0:
            return None
        
        change = current_price - previous_price
        change_pct = (change / previous_price) * 100
        
        return {
            'previous_price': previous_price,
            'change': change,
            'change_percent': change_pct,
            'direction': 'UP' if change > 0 else 'DOWN'
        }
    
    def get_risk_level(self, change_percent: float) -> Dict:
        """Determine risk level based on price change"""
        abs_change = abs(change_percent)
        if abs_change >= 5:
            return {'level': 'HIGH', 'color': '#d32f2f', 'icon': '⚠️'}
        elif abs_change >= 2:
            return {'level': 'MEDIUM', 'color': '#f57c00', 'icon': '⚡'}
        else:
            return {'level': 'LOW', 'color': '#388e3c', 'icon': '✓'}
    
    def get_trend_icon(self, direction: str) -> str:
        """Get trend icon based on direction"""
        if direction == 'UP':
            return '📈'
        elif direction == 'DOWN':
            return '📉'
        else:
            return '➡️'
    
    def format_price_change(self, change_pct: float, direction: str) -> str:
        """Format price change with color and arrow"""
        arrow = '↑' if direction == 'UP' else '↓' if direction == 'DOWN' else '→'
        sign = '+' if change_pct > 0 else ''
        return f"{sign}{change_pct:.2f}% {arrow}"
    
    def generate_insights(self, pred: Dict, product_key: str) -> str:
        """Generate market insights based on predictions"""
        insights = []
        
        # Check all horizons
        horizons = ['next_day', 'next_week', 'biweekly', 'monthly']
        directions = [pred.get(h, {}).get('direction', '') for h in horizons]
        
        # Overall trend
        up_count = directions.count('UP')
        down_count = directions.count('DOWN')
        
        if up_count > down_count:
            insights.append("📊 <strong>Overall Trend: BULLISH</strong> - Prices expected to rise across all timeframes")
        elif down_count > up_count:
            insights.append("📊 <strong>Overall Trend: BEARISH</strong> - Prices expected to decline across all timeframes")
        else:
            insights.append("📊 <strong>Overall Trend: MIXED</strong> - Mixed signals across timeframes")
        
        # Volatility check
        changes = [abs(pred.get(h, {}).get('change_percent', 0)) for h in horizons]
        max_change = max(changes) if changes else 0
        
        if max_change > 5:
            insights.append(f"⚡ <strong>High Volatility Expected</strong> - Significant price movements predicted ({max_change:.1f}%)")
        elif max_change > 2:
            insights.append(f"📈 <strong>Moderate Movement</strong> - Expected price change of {max_change:.1f}%")
        
        # Short vs long term
        daily_change = pred.get('next_day', {}).get('change_percent', 0)
        monthly_change = pred.get('monthly', {}).get('change_percent', 0)
        
        if abs(monthly_change) > abs(daily_change) * 2:
            insights.append("⏱️ <strong>Long-term Trend Stronger</strong> - Monthly forecast shows more significant movement")
        
        return '<br>'.join(insights) if insights else "📊 Market analysis in progress..."
    
    def format_email_html(self, current_predictions: Dict, previous_predictions: Optional[Dict] = None) -> str:
        """Generate enhanced HTML email with comparisons"""
        
        est_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S EST')
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
            color: #333;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
            background-color: white;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #1976d2 0%, #1565c0 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }}
        .header h1 {{
            margin: 0;
            font-size: 28px;
            font-weight: 600;
        }}
        .header p {{
            margin: 10px 0 0 0;
            opacity: 0.9;
            font-size: 14px;
        }}
        .summary-box {{
            background-color: #e3f2fd;
            padding: 20px;
            margin: 20px;
            border-radius: 8px;
            border-left: 4px solid #1976d2;
        }}
        .product-card {{
            margin: 20px;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            overflow: hidden;
            background-color: white;
        }}
        .product-header {{
            background: linear-gradient(135deg, #424242 0%, #212121 100%);
            color: white;
            padding: 20px;
        }}
        .product-header h2 {{
            margin: 0;
            font-size: 22px;
        }}
        .product-header .description {{
            margin: 5px 0 0 0;
            font-size: 13px;
            opacity: 0.9;
        }}
        .current-price {{
            background-color: #fafafa;
            padding: 15px 20px;
            border-bottom: 2px solid #e0e0e0;
        }}
        .current-price strong {{
            font-size: 24px;
            color: #1976d2;
        }}
        .predictions-table {{
            width: 100%;
            border-collapse: collapse;
        }}
        .predictions-table th {{
            background-color: #f5f5f5;
            padding: 12px;
            text-align: left;
            font-weight: 600;
            border-bottom: 2px solid #e0e0e0;
        }}
        .predictions-table td {{
            padding: 12px;
            border-bottom: 1px solid #f0f0f0;
        }}
        .predictions-table tr:hover {{
            background-color: #fafafa;
        }}
        .price-up {{
            color: #d32f2f;
            font-weight: bold;
        }}
        .price-down {{
            color: #388e3c;
            font-weight: bold;
        }}
        .comparison {{
            font-size: 12px;
            color: #666;
            margin-top: 5px;
        }}
        .risk-badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: bold;
            margin-left: 8px;
        }}
        .risk-high {{
            background-color: #ffebee;
            color: #c62828;
        }}
        .risk-medium {{
            background-color: #fff3e0;
            color: #e65100;
        }}
        .risk-low {{
            background-color: #e8f5e9;
            color: #2e7d32;
        }}
        .insights-box {{
            background-color: #fff9e6;
            padding: 15px;
            margin: 20px;
            border-radius: 8px;
            border-left: 4px solid #fbc02d;
        }}
        .insights-box h3 {{
            margin: 0 0 10px 0;
            color: #f57f17;
        }}
        .footer {{
            background-color: #fafafa;
            padding: 20px;
            text-align: center;
            color: #666;
            font-size: 12px;
            border-top: 1px solid #e0e0e0;
        }}
        .confidence-range {{
            background-color: #f5f5f5;
            padding: 10px 15px;
            margin: 10px 20px;
            border-radius: 5px;
            font-size: 13px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔮 Energy Market AI Predictions</h1>
            <p>Comprehensive Forecast Report • Generated: {est_time}</p>
        </div>
        
        <div class="summary-box">
            <h3 style="margin-top: 0;">📊 Executive Summary</h3>
            <p>This report provides AI-powered price predictions for key energy commodities based on historical data, 
            inventory levels, and market sentiment analysis. Predictions are generated using advanced machine learning 
            models (Facebook Prophet) and include confidence intervals.</p>
        </div>
"""
        
        # Add predictions for each product
        for product_key, pred in current_predictions.items():
            if product_key.startswith('_'):
                continue
            if not pred:
                continue
            
            product_info = self.product_names.get(product_key, {
                'display': product_key.replace('_', ' '),
                'description': '',
                'unit': '',
                'symbol': ''
            })
            
            # Get current price - handle NaN values
            import math
            current_price = pred.get('current_price', 0)
            
            # Check if current_price is valid
            try:
                if current_price is None:
                    current_price = None
                elif isinstance(current_price, float) and math.isnan(current_price):
                    current_price = None
                elif current_price == 0:
                    current_price = None
                else:
                    current_price = float(current_price)
            except (ValueError, TypeError):
                current_price = None
            
            # If no current price, try to estimate from next_day prediction
            if current_price is None:
                next_day = pred.get('next_day', {})
                if next_day and 'price' in next_day:
                    # Use next_day as approximate current (we'll note this in display)
                    estimated_price = float(next_day.get('price', 0))
                    if estimated_price > 0:
                        current_price = estimated_price
                    else:
                        continue
                else:
                    continue
            
            previous_pred = previous_predictions.get(product_key, {}) if previous_predictions else {}
            
            html += f"""
        <div class="product-card">
            <div class="product-header">
                <h2>{product_info['display']}</h2>
                <p class="description">{product_info['description']} ({product_info['symbol']})</p>
            </div>
            
            <div class="current-price">
                <strong>Current Market Price: ${current_price:.4f}</strong> {product_info['unit']}
                {'' if pred.get('current_price', 0) and not (isinstance(pred.get('current_price', 0), float) and math.isnan(pred.get('current_price', 0))) else '<br><small style="color: #666;">(Estimated from latest prediction data)</small>'}
            </div>
            
            <table class="predictions-table">
                <thead>
                    <tr>
                        <th>Time Horizon</th>
                        <th>Predicted Price</th>
                        <th>Expected Change</th>
                        <th>Risk Level</th>
                    </tr>
                </thead>
                <tbody>
"""
            
            # Add each time horizon
            horizons = [
                ('next_day', 'Daily (Tomorrow)'),
                ('next_week', 'One Week'),
                ('biweekly', 'Two Weeks'),
                ('monthly', 'Monthly (30 Days)')
            ]
            
            for horizon_key, horizon_name in horizons:
                horizon_data = pred.get(horizon_key, {})
                if not horizon_data:
                    continue
                
                price = horizon_data.get('price', 0)
                change_pct = horizon_data.get('change_percent', 0)
                direction = horizon_data.get('direction', 'UP')
                
                # If change_percent is NaN, calculate it from current_price
                import math
                if current_price and (math.isnan(change_pct) or change_pct == 0):
                    try:
                        change_pct = ((price - current_price) / current_price) * 100
                        direction = 'UP' if change_pct > 0 else 'DOWN'
                    except:
                        change_pct = 0
                
                # Get comparison with previous
                comparison = self.get_change_from_previous(pred, previous_pred, horizon_key) if previous_pred else None
                
                # Get risk level
                risk = self.get_risk_level(change_pct)
                trend_icon = self.get_trend_icon(direction)
                
                change_str = self.format_price_change(change_pct, direction)
                change_class = 'price-up' if direction == 'UP' else 'price-down'
                
                comparison_html = ""
                if comparison:
                    comp_icon = '📊' if comparison['change'] > 0 else '📉'
                    comparison_html = f"""
                        <div class="comparison">
                            {comp_icon} Previous prediction: ${comparison['previous_price']:.4f} 
                            ({comparison['change_percent']:+.2f}% change from last forecast)
                        </div>
                    """
                
                html += f"""
                    <tr>
                        <td><strong>{horizon_name}</strong></td>
                        <td><strong>${price:.4f}</strong> {product_info['unit']}</td>
                        <td class="{change_class}">
                            {trend_icon} {change_str}
                            {comparison_html}
                        </td>
                        <td>
                            <span class="risk-badge risk-{risk['level'].lower()}">
                                {risk['icon']} {risk['level']} RISK
                            </span>
                        </td>
                    </tr>
                """
            
            # Confidence range
            conf = pred.get('confidence_range', {})
            if conf:
                html += f"""
                </tbody>
            </table>
            <div class="confidence-range">
                <strong>📊 Confidence Range:</strong> ${conf.get('lower', 0):.4f} - ${conf.get('upper', 0):.4f} {product_info['unit']}
                <br><small>This range represents the 80% confidence interval for price predictions.</small>
            </div>
"""
            
            # Market insights
            insights = self.generate_insights(pred, product_key)
            html += f"""
            <div class="insights-box">
                <h3>💡 Market Insights</h3>
                <div>{insights}</div>
            </div>
        </div>
"""
        
        html += f"""
        <div class="footer">
            <p><strong>📌 Important Notes:</strong></p>
            <p>• Predictions are based on AI/ML models (Facebook Prophet) analyzing historical prices, inventory data, and news sentiment</p>
            <p>• These forecasts are for informational purposes only and should not be considered as financial advice</p>
            <p>• Market conditions can change rapidly; actual prices may differ from predictions</p>
            <p>• Confidence intervals represent statistical uncertainty in the model</p>
            <p style="margin-top: 15px; padding-top: 15px; border-top: 1px solid #e0e0e0;">
                <strong>Energy AI Agent</strong> • Automated Prediction System<br>
                Next report: {self._get_next_report_time()}
            </p>
        </div>
    </div>
</body>
</html>
"""
        
        return html
    
    def _get_next_report_time(self) -> str:
        """Get next scheduled report time"""
        now = datetime.now()
        times = [6, 9, 12, 18]  # 6 AM, 9 AM, 12 PM, 6 PM
        
        current_hour = now.hour
        for time in times:
            if current_hour < time:
                return f"Today at {time}:00 {'AM' if time < 12 else 'PM'} EST"
        
        return "Tomorrow at 6:00 AM EST"
