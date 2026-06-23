"""
Main entry point for Energy AI Agent
Runs the monitoring system on a schedule
"""
import schedule
import time
from datetime import datetime
from data_collector import EnergyDataCollector
from analyzer import PriceAnalyzer
from alerts import EmailAlertSystem
from config import ALERT_CONFIG
from predictor import EnergyPricePredictor
import json
import os


class EnergyAIAgent:
    """Main agent class that orchestrates data collection, analysis, and alerts"""
    
    def __init__(self):
        self.collector = EnergyDataCollector()
        self.analyzer = PriceAnalyzer()
        self.alert_system = EmailAlertSystem()
        self.predictor = EnergyPricePredictor()
    
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
    
    def run_check(self):
        """Execute one complete check cycle"""
        print(f"\n{'='*60}")
        print(f"Energy Market Check - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")
        
        try:
            # Collect all data
            print("\n📊 Collecting market data...")
            all_data = self.collector.get_all_data()
            prices = all_data.get('prices', {})
            inventories = all_data.get('inventories', {})
            retail_weekly = all_data.get('retail_pump_weekly')
            
            # Analyze prices
            print("🔍 Analyzing price changes...")
            price_analyses = self.analyzer.analyze_all_prices(prices)
            
            # Analyze inventories
            inventory_analyses = []
            if inventories:
                print("📦 Analyzing inventory changes...")
                inventory_analyses = self.analyzer.analyze_all_inventories(inventories)
            
            # Generate market signals
            market_signals = self.analyzer.generate_market_signal(price_analyses, inventory_analyses)
            
            # Display price results
            print("\n💰 PRICE DATA:")
            for analysis in price_analyses:
                product = analysis['product']
                current_price = analysis['current_price']
                change_metrics = analysis['change_metrics']
                
                print(f"\n  {product}:")
                print(f"    Current: ${current_price:.4f}")
                
                if change_metrics.get('previous_price'):
                    direction = change_metrics['direction']
                    change_pct = change_metrics['change_percent']
                    arrow = "↑" if direction == "INCREASE" else "↓" if direction == "DECREASE" else "→"
                    print(f"    Change: {arrow} {change_pct:+.2f}% ({direction})")
                    print(f"    Alert: {'YES' if change_metrics['is_significant'] else 'NO'}")
                else:
                    print("    Status: First recording")

            if retail_weekly:
                rg = retail_weekly.get("regular_gasoline")
                rd = retail_weekly.get("ulsd_diesel")
                print("\n⛽ RETAIL PUMP (EIA weekly, NJ area / Central Atlantic PADD 1B):")
                print(f"  Region: {retail_weekly.get('region_label', '')} ({retail_weekly.get('region_code', '')})")
                print(f"  Survey week: {retail_weekly.get('period', '—')}")
                if rg is not None:
                    print(f"  Regular gasoline: ${rg:.3f}/gal")
                if rd is not None:
                    print(f"  ULSD diesel: ${rd:.3f}/gal")
            
            # Display inventory results
            if inventory_analyses:
                print("\n📦 INVENTORY DATA:")
                for analysis in inventory_analyses:
                    product = analysis['product']
                    current_value = analysis['current_value']
                    change_metrics = analysis['change_metrics']
                    units = analysis['additional_data'].get('units', 'thousand barrels')
                    
                    print(f"\n  {product}:")
                    print(f"    Current: {current_value:,.0f} {units}")
                    
                    if change_metrics.get('previous_value'):
                        direction = change_metrics['direction']
                        change_pct = change_metrics['change_percent']
                        arrow = "↑" if direction == "INCREASE" else "↓" if direction == "DECREASE" else "→"
                        print(f"    Change: {arrow} {change_pct:+.2f}% ({direction})")
                        print(f"    Alert: {'YES' if change_metrics['is_significant'] else 'NO'}")
                    else:
                        print("    Status: First recording")
            
            # Display market signals
            if market_signals['signals']:
                print("\n🚨 MARKET SIGNALS:")
                for signal in market_signals['signals']:
                    print(f"  [{signal['severity']}] {signal['product']}: {signal['message']}")
            
            # Display AI Predictions
            print("\n🤖 AI PRICE PREDICTIONS:")
            predictions = self.get_predictions()
            if predictions:
                for product, pred in predictions.items():
                    if str(product).startswith('_'):
                        continue
                    if pred:
                        print(f"\n  {product.replace('_', ' ')}:")
                        print(f"    Current: ${pred['current_price']:.4f}")
                        print(f"    Next Day: {pred['next_day']['direction']} {abs(pred['next_day']['change_percent']):.2f}%")
                        print(f"    Next Week: {pred['next_week']['direction']} {abs(pred['next_week']['change_percent']):.2f}%")
                        print(f"    Biweekly: {pred['biweekly']['direction']} {abs(pred['biweekly']['change_percent']):.2f}%")
            else:
                print("  No predictions available (run prediction_engine.py first)")
            
            # Send alerts (only if enabled)
            if ALERT_CONFIG.get('enable_price_alerts', False):
                print("\n📧 Checking for price change alerts...")
                if self.alert_system.is_configured():
                    all_analyses = price_analyses + inventory_analyses
                    sent_count = self.alert_system.send_batch_alerts(all_analyses, market_signals)
                    if sent_count > 0:
                        print(f"✅ Sent {sent_count} alert email(s)")
                    else:
                        print("ℹ️  No alerts to send (no significant changes or first run)")
                else:
                    print("⚠️  Email alerts not configured")
            else:
                print("\n📧 Price change alerts: DISABLED (only prediction emails enabled)")
            
            print(f"\n{'='*60}\n")
            
        except Exception as e:
            print(f"❌ Error during check: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def start(self):
        """Start the monitoring agent"""
        interval_minutes = ALERT_CONFIG['check_interval_minutes']
        
        print("="*60)
        print("Energy AI Agent - Starting Monitoring System")
        print("="*60)
        print(f"Products monitored:")
        print(f"  - Crude Oil (CL=F)")
        print(f"  - RBOB Gasoline (RB=F)")
        print(f"  - Ultra-Low Sulfur Diesel (HO=F)")
        print(f"\nData Sources:")
        print(f"  - Prices: Yahoo Finance / Alpha Vantage (see config)")
        print(f"  - Inventories: EIA API (if configured)")
        print(f"  - Retail pump (NJ area): EIA weekly PADD 1B (override with EIA_RETAIL_DUOAREA)")
        print(f"\nCheck interval: Every {interval_minutes} minute(s)")
        print(f"Price change alerts: {'ENABLED' if ALERT_CONFIG.get('enable_price_alerts', False) else 'DISABLED'}")
        if ALERT_CONFIG.get('enable_price_alerts', False):
            print(f"Price change threshold: {ALERT_CONFIG['price_change_threshold_percent']}%")
            print(f"Inventory change threshold: {ALERT_CONFIG.get('inventory_change_threshold_percent', 2.0)}%")
        print(f"Prediction emails: ENABLED (morning & evening)")
        print("="*60)
        
        # Run initial check
        self.run_check()
        
        # Schedule periodic checks
        schedule.every(interval_minutes).minutes.do(self.run_check)
        
        print(f"\n🔄 Monitoring started. Press Ctrl+C to stop.\n")
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(30)  # Check every 30 seconds for scheduled tasks (more responsive for 5-min intervals)
        except KeyboardInterrupt:
            print("\n\n⏹️  Monitoring stopped by user")
            print("Thank you for using Energy AI Agent!")


if __name__ == '__main__':
    agent = EnergyAIAgent()
    agent.start()
