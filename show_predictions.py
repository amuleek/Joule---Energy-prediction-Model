"""
Display Current Market Predictions
Shows tomorrow, one week, and one month predictions
"""
import json
import os
from datetime import datetime
from data_collector import EnergyDataCollector

def get_current_prices():
    """Get current prices from data collector"""
    collector = EnergyDataCollector()
    prices = collector.get_all_prices()
    
    current = {}
    if prices.get('RBOB_GASOLINE'):
        current['RBOB'] = prices['RBOB_GASOLINE']['price']
    if prices.get('DIESEL'):
        current['ULSD'] = prices['DIESEL']['price']
    if prices.get('CRUDE_OIL'):
        current['Crude'] = prices['CRUDE_OIL']['price']
    
    return current

def display_predictions():
    """Display formatted predictions"""
    pred_file = 'data/predictions.json'
    
    print("=" * 70)
    print("ENERGY MARKET PRICE PREDICTIONS")
    print("=" * 70)
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()
    
    if not os.path.exists(pred_file):
        print("No predictions available. Run: python prediction_engine.py")
        return
    
    # Load predictions
    with open(pred_file, 'r') as f:
        predictions = json.load(f)
    
    # Get current prices
    current_prices = get_current_prices()
    
    # Product mapping
    products = {
        'RBOB_Gasoline': {'name': 'RBOB Gasoline', 'current_key': 'RBOB'},
        'ULSD_Diesel': {'name': 'ULSD Diesel', 'current_key': 'ULSD'},
        'Crude_Oil': {'name': 'Crude Oil', 'current_key': 'Crude'}
    }
    
    for key, info in products.items():
        if key in predictions and predictions[key]:
            pred = predictions[key]
            current = current_prices.get(info['current_key'], pred.get('current_price', 0))
            
            # Use current price from live data if available
            if current and current > 0:
                current_price = float(current)
            else:
                current_price = float(pred.get('current_price', 0))
            
            if current_price == 0:
                continue
            
            print(f"{info['name']}:")
            print(f"  Current Price: ${current_price:.4f}")
            print()
            print("  PREDICTIONS:")
            
            # Tomorrow - recalculate with actual current price
            tomorrow_price = float(pred['next_day']['price'])
            tomorrow_pct = ((tomorrow_price - current_price) / current_price) * 100
            tomorrow_dir = 'UP' if tomorrow_pct > 0 else 'DOWN'
            arrow = '+' if tomorrow_dir == 'UP' else '-'
            print(f"    Tomorrow:     ${tomorrow_price:.4f} ({arrow}{abs(tomorrow_pct):.2f}%)")
            
            # One Week - recalculate with actual current price
            week_price = float(pred['next_week']['price'])
            week_pct = ((week_price - current_price) / current_price) * 100
            week_dir = 'UP' if week_pct > 0 else 'DOWN'
            arrow = '+' if week_dir == 'UP' else '-'
            print(f"    One Week:     ${week_price:.4f} ({arrow}{abs(week_pct):.2f}%)")
            
            # One Month - recalculate with actual current price
            if 'monthly' in pred:
                month_price = float(pred['monthly']['price'])
            else:
                # Fallback to biweekly if monthly not available
                month_price = float(pred['biweekly']['price'])
            
            month_pct = ((month_price - current_price) / current_price) * 100
            month_dir = 'UP' if month_pct > 0 else 'DOWN'
            arrow = '+' if month_dir == 'UP' else '-'
            print(f"    One Month:    ${month_price:.4f} ({arrow}{abs(month_pct):.2f}%)")
            
            # Confidence
            conf_lower = float(pred['confidence_range']['lower'])
            conf_upper = float(pred['confidence_range']['upper'])
            print(f"    Confidence:   ${conf_lower:.4f} - ${conf_upper:.4f}")
            print()
            print("=" * 70)
            print()

if __name__ == "__main__":
    display_predictions()
