"""
Prediction Engine - Orchestrates data collection and predictions
Runs daily to update predictions for next day, week, and biweekly
"""
import os
import sys
from datetime import datetime
from scripts.fetch_prices import save_prices
from scripts.fetch_news import save_news
from scripts.fetch_inventory import fetch_inventory
from scripts.preprocessing import merge_data
from predictor import EnergyPricePredictor
from alerts import EmailAlertSystem
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

class PredictionEngine:
    """Main prediction engine that orchestrates data collection and predictions"""
    
    def __init__(self):
        self.predictor = EnergyPricePredictor()
    
    def collect_data(self):
        """Collect all required data"""
        print("=" * 60)
        print("Collecting Data for Predictions")
        print("=" * 60)
        
        # Ensure data directory exists
        os.makedirs("data", exist_ok=True)
        
        # Fetch prices
        print("\n1. Fetching prices...")
        try:
            save_prices()
        except Exception as e:
            print(f"Error fetching prices: {str(e)}")
        
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
    
    def generate_predictions(self):
        """Generate price predictions"""
        print("\n" + "=" * 60)
        print("Generating AI Predictions")
        print("=" * 60)
        
        predictions = self.predictor.generate_predictions()
        
        if predictions:
            print("\n" + self.predictor.format_predictions(predictions))
            
            # Save predictions to file
            import json
            predictions_json = {}
            for product, pred in predictions.items():
                if pred:
                    predictions_json[product] = {
                        'current_price': float(pred['current_price']),
                        'next_day': {
                            'price': float(pred['next_day']),
                            'change_percent': float(pred['next_day_change']),
                            'direction': pred['next_day_direction']
                        },
                        'next_week': {
                            'price': float(pred['next_week']),
                            'change_percent': float(pred['next_week_change']),
                            'direction': pred['next_week_direction']
                        },
                        'biweekly': {
                            'price': float(pred['biweekly']),
                            'change_percent': float(pred['biweekly_change']),
                            'direction': pred['biweekly_direction']
                        },
                        'monthly': {
                            'price': float(pred.get('monthly', pred['biweekly'])),
                            'change_percent': float(pred.get('monthly_change', pred['biweekly_change'])),
                            'direction': pred.get('monthly_direction', pred['biweekly_direction'])
                        },
                        'confidence_range': {
                            'lower': float(pred['confidence_lower']),
                            'upper': float(pred['confidence_upper'])
                        },
                        'timestamp': datetime.now().isoformat()
                    }
            
            os.makedirs("data", exist_ok=True)
            with open("data/predictions.json", "w") as f:
                json.dump(predictions_json, f, indent=2)
            
            print("\nPredictions saved to data/predictions.json")
            
            # Send prediction email if configured
            self.send_prediction_email(predictions_json)
            
            return predictions_json
        else:
            print("\nNo predictions generated")
            return None
    
    def send_prediction_email(self, predictions):
        """Send prediction results via email"""
        if not predictions:
            return
        
        alert_system = EmailAlertSystem()
        
        if not alert_system.is_configured():
            print("\nEmail not configured. Predictions saved but not emailed.")
            return
        
        try:
            # Create email message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"Energy Market Predictions - {datetime.now().strftime('%Y-%m-%d')}"
            msg['From'] = alert_system.sender_email
            msg['To'] = ', '.join(alert_system.recipient_emails)
            
            # Build HTML email with predictions
            html = """
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body { font-family: Arial, sans-serif; margin: 20px; }
                    .header { background-color: #1976d2; color: white; padding: 15px; border-radius: 5px; }
                    .prediction-box { background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin: 10px 0; }
                    .data-table { width: 100%; border-collapse: collapse; margin: 10px 0; }
                    .data-table th { background-color: #1976d2; color: white; padding: 10px; text-align: left; }
                    .data-table td { padding: 8px; border-bottom: 1px solid #ddd; }
                    .up { color: #d32f2f; font-weight: bold; }
                    .down { color: #388e3c; font-weight: bold; }
                    .footer { color: #666; font-size: 12px; margin-top: 20px; }
                </style>
            </head>
            <body>
                <div class="header">
                    <h2>🤖 AI Energy Market Predictions</h2>
                    <p>Generated: """ + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + """</p>
                </div>
            """
            
            # Add predictions for each product
            for product, pred in predictions.items():
                if not pred:
                    continue
                
                product_name = product.replace('_', ' ')
                current_price = pred.get('current_price', 0)
                
                html += f"""
                <div class="prediction-box">
                    <h3>{product_name}</h3>
                    <p><strong>Current Price:</strong> ${current_price:.4f}</p>
                    <table class="data-table">
                        <tr>
                            <th>Time Horizon</th>
                            <th>Predicted Price</th>
                            <th>Change</th>
                            <th>Direction</th>
                        </tr>
                """
                
                # Tomorrow
                tomorrow = pred.get('next_day', {})
                tomorrow_price = tomorrow.get('price', 0)
                tomorrow_pct = tomorrow.get('change_percent', 0)
                tomorrow_dir = tomorrow.get('direction', 'UP')
                dir_class = 'up' if tomorrow_dir == 'UP' else 'down'
                arrow = '+' if tomorrow_dir == 'UP' else '-'
                html += f"""
                        <tr>
                            <td>Daily (Tomorrow)</td>
                            <td>${tomorrow_price:.4f}</td>
                            <td class="{dir_class}">{arrow}{abs(tomorrow_pct):.2f}%</td>
                            <td class="{dir_class}">{tomorrow_dir}</td>
                        </tr>
                """
                
                # One Week
                week = pred.get('next_week', {})
                week_price = week.get('price', 0)
                week_pct = week.get('change_percent', 0)
                week_dir = week.get('direction', 'UP')
                dir_class = 'up' if week_dir == 'UP' else 'down'
                arrow = '+' if week_dir == 'UP' else '-'
                html += f"""
                        <tr>
                            <td>One Week</td>
                            <td>${week_price:.4f}</td>
                            <td class="{dir_class}">{arrow}{abs(week_pct):.2f}%</td>
                            <td class="{dir_class}">{week_dir}</td>
                        </tr>
                """
                
                # Two Weeks
                biweekly = pred.get('biweekly', {})
                if not biweekly:
                    biweekly = pred.get('next_week', {})
                biweekly_price = biweekly.get('price', 0)
                biweekly_pct = biweekly.get('change_percent', 0)
                biweekly_dir = biweekly.get('direction', 'UP')
                dir_class = 'up' if biweekly_dir == 'UP' else 'down'
                arrow = '+' if biweekly_dir == 'UP' else '-'
                html += f"""
                        <tr>
                            <td>Two Weeks</td>
                            <td>${biweekly_price:.4f}</td>
                            <td class="{dir_class}">{arrow}{abs(biweekly_pct):.2f}%</td>
                            <td class="{dir_class}">{biweekly_dir}</td>
                        </tr>
                """
                
                # One Month
                monthly = pred.get('monthly', {})
                if not monthly:
                    monthly = pred.get('biweekly', {})
                month_price = monthly.get('price', 0)
                month_pct = monthly.get('change_percent', 0)
                month_dir = monthly.get('direction', 'UP')
                dir_class = 'up' if month_dir == 'UP' else 'down'
                arrow = '+' if month_dir == 'UP' else '-'
                html += f"""
                        <tr>
                            <td>Monthly</td>
                            <td>${month_price:.4f}</td>
                            <td class="{dir_class}">{arrow}{abs(month_pct):.2f}%</td>
                            <td class="{dir_class}">{month_dir}</td>
                        </tr>
                """
                
                # Confidence range
                conf = pred.get('confidence_range', {})
                html += f"""
                    </table>
                    <p><small>Confidence Range: ${conf.get('lower', 0):.4f} - ${conf.get('upper', 0):.4f}</small></p>
                </div>
                """
            
            html += """
                <div class="footer">
                    <p><strong>Note:</strong> These predictions are based on historical price data, inventory levels, and world news sentiment analysis.</p>
                    <p>Predictions are generated using AI/ML models and should be used for informational purposes only.</p>
                    <p>This is an automated email from the Energy AI Agent system.</p>
                </div>
            </body>
            </html>
            """
            
            html_part = MIMEText(html, 'html')
            msg.attach(html_part)
            
            # Send email
            with smtplib.SMTP(alert_system.smtp_server, alert_system.smtp_port) as server:
                server.starttls()
                server.login(alert_system.sender_email, alert_system.sender_password)
                server.send_message(msg)
            
            print(f"\n[OK] Prediction email sent to: {', '.join(alert_system.recipient_emails)}")
            
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
        
        # Step 1: Collect data
        self.collect_data()
        
        # Step 2: Generate predictions
        predictions = self.generate_predictions()
        
        print("\n" + "=" * 60)
        print("Pipeline Complete")
        print("=" * 60)
        
        return predictions

if __name__ == "__main__":
    engine = PredictionEngine()
    engine.run_full_pipeline()
