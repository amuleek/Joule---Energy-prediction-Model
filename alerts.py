"""
Email Alert System for Energy Price Changes
Sends email notifications when prices change significantly
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Dict, List
from config import EMAIL_CONFIG
import json
import os


class EmailAlertSystem:
    """Handles email alerts for energy price changes"""
    
    def __init__(self):
        self.smtp_server = EMAIL_CONFIG['smtp_server']
        self.smtp_port = EMAIL_CONFIG['smtp_port']
        self.sender_email = EMAIL_CONFIG['sender_email']
        self.sender_password = EMAIL_CONFIG['sender_password']
        self.recipient_emails = EMAIL_CONFIG['recipient_emails']
    
    def is_configured(self) -> bool:
        """Check if email configuration is complete"""
        return bool(
            self.sender_email and 
            self.sender_password and 
            self.recipient_emails
        )
    
    def format_alert_message(self, analysis: Dict) -> str:
        """
        Format analysis data into a readable email message
        Args:
            analysis: Analysis dictionary from PriceAnalyzer (price or inventory)
        Returns:
            Formatted HTML email message
        """
        product = analysis['product']
        change_metrics = analysis['change_metrics']
        additional_data = analysis.get('additional_data', {})
        
        # Check if this is price or inventory data
        is_price = 'current_price' in analysis
        is_inventory = 'current_value' in analysis
        
        if is_price:
            current_value = analysis['current_price']
            value_label = "Price"
            value_format = "${:.4f}"
            currency = additional_data.get('currency', 'USD')
        elif is_inventory:
            current_value = analysis['current_value']
            value_label = "Inventory"
            value_format = "{:,.0f}"
            currency = additional_data.get('units', 'thousand barrels')
        else:
            return "<p>Invalid analysis data</p>"
        
        # Determine alert type and color
        if change_metrics['direction'] == 'INCREASE':
            if is_price:
                alert_type = "PRICE INCREASE"
            else:
                alert_type = "INVENTORY INCREASE"
            color = "#d32f2f"  # Red
            arrow = "↑"
        elif change_metrics['direction'] == 'DECREASE':
            if is_price:
                alert_type = "PRICE DECREASE"
            else:
                alert_type = "INVENTORY DECREASE"
            color = "#388e3c"  # Green
            arrow = "↓"
        else:
            alert_type = "MARKET UPDATE"
            color = "#1976d2"  # Blue
            arrow = "→"
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background-color: {color}; color: white; padding: 15px; border-radius: 5px; }}
                .content {{ margin: 20px 0; }}
                .price-box {{ background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                .change-box {{ background-color: #e3f2fd; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                .data-table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
                .data-table td {{ padding: 8px; border-bottom: 1px solid #ddd; }}
                .data-table td:first-child {{ font-weight: bold; width: 40%; }}
                .footer {{ color: #666; font-size: 12px; margin-top: 20px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h2>{alert_type} {arrow} {product}</h2>
            </div>
            
            <div class="content">
                <div class="price-box">
                    <h3>Current Price Information</h3>
                    <table class="data-table">
                        <tr>
                            <td>Product:</td>
                            <td>{product}</td>
                        </tr>
                        <tr>
                            <td>Current {value_label}:</td>
                            <td><strong>{value_format.format(current_value)}</strong> {currency}</td>
                        </tr>
        """
        
        prev_key = 'previous_price' if is_price else 'previous_value'
        if change_metrics.get(prev_key):
            prev_value = change_metrics[prev_key]
            html += f"""
                        <tr>
                            <td>Previous {value_label}:</td>
                            <td>{value_format.format(prev_value)}</td>
                        </tr>
                        <tr>
                            <td>Change Amount:</td>
                            <td><strong>{value_format.format(change_metrics['change_amount'])}</strong></td>
                        </tr>
                        <tr>
                            <td>Change Percentage:</td>
                            <td><strong>{change_metrics['change_percent']:.2f}%</strong></td>
                        </tr>
            """
        
        html += f"""
                    </table>
                </div>
                
        """
        
        # Add market data for prices
        if is_price:
            html += f"""
                <div class="change-box">
                    <h3>Market Data</h3>
                    <table class="data-table">
                        <tr>
                            <td>Open:</td>
                            <td>${additional_data.get('open', 0):.4f}</td>
                        </tr>
                        <tr>
                            <td>High:</td>
                            <td>${additional_data.get('high', 0):.4f}</td>
                        </tr>
                        <tr>
                            <td>Low:</td>
                            <td>${additional_data.get('low', 0):.4f}</td>
                        </tr>
                        <tr>
                            <td>Volume:</td>
                            <td>{additional_data.get('volume', 0):,}</td>
                        </tr>
                    </table>
                </div>
            """
        elif is_inventory:
            period = additional_data.get('period', 'N/A')
            html += f"""
                <div class="change-box">
                    <h3>Inventory Information</h3>
                    <table class="data-table">
                        <tr>
                            <td>Period:</td>
                            <td>{period}</td>
                        </tr>
                        <tr>
                            <td>Units:</td>
                            <td>{currency}</td>
                        </tr>
                    </table>
                </div>
            """
        
        html += """
                
                <div class="footer">
                    <p>Alert generated at: {analysis.get('timestamp', datetime.now().isoformat())}</p>
                    <p>This is an automated alert from the Energy AI Agent system.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return html
    
    def send_alert(self, analysis: Dict) -> bool:
        """
        Send email alert for a single analysis
        Args:
            analysis: Analysis dictionary from PriceAnalyzer (price or inventory)
        Returns:
            True if email sent successfully, False otherwise
        """
        if not self.is_configured():
            print("Email not configured. Please set EMAIL_CONFIG in config.py or environment variables.")
            return False
        
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            direction = analysis['change_metrics']['direction']
            product = analysis['product']
            alert_type = "Price" if 'current_price' in analysis else "Inventory"
            msg['Subject'] = f"Energy Alert: {product} - {alert_type} {direction}"
            msg['From'] = self.sender_email
            msg['To'] = ', '.join(self.recipient_emails)
            
            # Create HTML content
            html_content = self.format_alert_message(analysis)
            html_part = MIMEText(html_content, 'html')
            msg.attach(html_part)
            
            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.send_message(msg)
            
            print(f"Alert email sent successfully for {analysis['product']}")
            return True
            
        except Exception as e:
            print(f"Error sending email alert: {str(e)}")
            return False
    
    def send_batch_alerts(self, analyses: List[Dict], market_signals: Dict = None) -> int:
        """
        Send alerts for multiple analyses
        Args:
            analyses: List of analysis dictionaries
            market_signals: Optional market signals dictionary
        Returns:
            Number of successfully sent emails
        """
        sent_count = 0
        
        # Send individual alerts for significant changes
        for analysis in analyses:
            if analysis.get('should_alert', False) and not analysis.get('error'):
                if self.send_alert(analysis):
                    sent_count += 1
        
        # Send combined alert with market signals if available
        if market_signals and market_signals.get('signals'):
            if self.send_market_signal_alert(analyses, market_signals):
                sent_count += 1
        
        return sent_count
    
    def get_predictions(self):
        """Load latest predictions from file"""
        predictions_file = "data/predictions.json"
        if os.path.exists(predictions_file):
            try:
                with open(predictions_file, 'r') as f:
                    return json.load(f)
            except:
                return None
        return None
    
    def send_market_signal_alert(self, analyses: List[Dict], market_signals: Dict) -> bool:
        """
        Send a comprehensive alert with market signals
        Args:
            analyses: List of all analyses
            market_signals: Market signals dictionary
        Returns:
            True if email sent successfully
        """
        if not self.is_configured():
            return False
        
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = "Energy Market Signals Alert"
            msg['From'] = self.sender_email
            msg['To'] = ', '.join(self.recipient_emails)
            
            # Build comprehensive HTML
            html = """
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body { font-family: Arial, sans-serif; margin: 20px; }
                    .header { background-color: #1976d2; color: white; padding: 15px; border-radius: 5px; }
                    .signal-box { background-color: #fff3cd; padding: 15px; border-radius: 5px; margin: 10px 0; border-left: 4px solid #ffc107; }
                    .high-severity { border-left-color: #d32f2f; background-color: #ffebee; }
                    .data-table { width: 100%; border-collapse: collapse; margin: 10px 0; }
                    .data-table td { padding: 8px; border-bottom: 1px solid #ddd; }
                </style>
            </head>
            <body>
                <div class="header">
                    <h2>🚨 Energy Market Signals Alert</h2>
                </div>
            """
            
            # Add market signals
            if market_signals.get('signals'):
                html += "<h3>Market Signals Detected:</h3>"
                for signal in market_signals['signals']:
                    severity_class = 'high-severity' if signal['severity'] == 'HIGH' else ''
                    html += f"""
                    <div class="signal-box {severity_class}">
                        <strong>[{signal['severity']}] {signal['product']}</strong><br>
                        {signal['message']}
                    </div>
                    """
            
            # Add summary of all analyses
            html += "<h3>Current Market Status:</h3>"
            html += "<table class='data-table'><tr><th>Product</th><th>Type</th><th>Value</th><th>Change</th></tr>"
            
            for analysis in analyses:
                if analysis.get('error'):
                    continue
                
                product = analysis['product']
                is_price = 'current_price' in analysis
                value = analysis.get('current_price') or analysis.get('current_value', 0)
                change_metrics = analysis['change_metrics']
                
                if is_price:
                    value_str = f"${value:.4f}"
                    data_type = "Price"
                else:
                    value_str = f"{value:,.0f}"
                    data_type = "Inventory"
                
                change_str = f"{change_metrics['change_percent']:+.2f}%"
                direction = change_metrics['direction']
                
                html += f"<tr><td>{product}</td><td>{data_type}</td><td>{value_str}</td><td>{direction} {change_str}</td></tr>"
            
            html += "</table>"
            
            # Add AI Predictions section
            predictions = self.get_predictions()
            if predictions:
                html += "<h3>🤖 AI Price Predictions:</h3>"
                html += "<table class='data-table'>"
                html += "<tr><th>Product</th><th>Daily</th><th>One Week</th><th>Two Weeks</th><th>Monthly</th></tr>"
                
                for product, pred in predictions.items():
                    if str(product).startswith('_'):
                        continue
                    if pred:
                        product_name = product.replace('_', ' ')
                        next_day = f"{pred['next_day']['direction']} {abs(pred['next_day']['change_percent']):.2f}%"
                        next_week = f"{pred['next_week']['direction']} {abs(pred['next_week']['change_percent']):.2f}%"
                        biweekly = f"{pred['biweekly']['direction']} {abs(pred['biweekly']['change_percent']):.2f}%"
                        monthly = pred.get('monthly', {})
                        if monthly:
                            monthly_str = f"{monthly['direction']} {abs(monthly['change_percent']):.2f}%"
                        else:
                            monthly_str = "N/A"
                        
                        html += f"<tr>"
                        html += f"<td>{product_name}</td>"
                        html += f"<td>{next_day}</td>"
                        html += f"<td>{next_week}</td>"
                        html += f"<td>{biweekly}</td>"
                        html += f"<td>{monthly_str}</td>"
                        html += f"</tr>"
                
                html += "</table>"
            
            html += f"<p><small>Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small></p>"
            html += "</body></html>"
            
            html_part = MIMEText(html, 'html')
            msg.attach(html_part)
            
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.send_message(msg)
            
            print("Market signals alert email sent successfully")
            return True
            
        except Exception as e:
            print(f"Error sending market signals email: {str(e)}")
            return False


if __name__ == '__main__':
    # Test the alert system
    from data_collector import EnergyDataCollector
    from analyzer import PriceAnalyzer
    
    print("Testing alert system...")
    
    collector = EnergyDataCollector()
    analyzer = PriceAnalyzer()
    alert_system = EmailAlertSystem()
    
    if not alert_system.is_configured():
        print("\n⚠️  Email not configured. To test alerts:")
        print("1. Set environment variables:")
        print("   - SENDER_EMAIL")
        print("   - SENDER_PASSWORD")
        print("   - RECIPIENT_EMAILS (comma-separated)")
        print("2. Or edit config.py directly")
    else:
        print("Fetching prices and analyzing...")
        prices = collector.get_all_prices()
        analyses = analyzer.analyze_all_prices(prices)
        
        print(f"\nSending alerts for {len([a for a in analyses if a.get('should_alert')])} products...")
        sent = alert_system.send_batch_alerts(analyses)
        print(f"Successfully sent {sent} alert(s)")
