"""
Simple Energy Agent - Basic Alert Monitoring
Monitors oil prices and sends alerts when significant changes occur
"""
import time
from data_collector import EnergyDataCollector
from datetime import datetime

# Global variables to track previous prices
previous_prices = {
    'CRUDE_OIL': None,
    'RBOB_GASOLINE': None,
    'DIESEL': None
}

def check_alert(product_key: str, current_price: float, threshold: float = 2.0):
    """
    Check if price change exceeds threshold and alert
    Args:
        product_key: Product identifier
        current_price: Current price
        threshold: Percentage change threshold (default 2.0%)
    Returns:
        True if alert triggered, False otherwise
    """
    global previous_prices
    
    if previous_prices[product_key] is None:
        previous_prices[product_key] = current_price
        print(f"  Initial price recorded: ${current_price:.2f}")
        return False
    
    change = (current_price - previous_prices[product_key]) / previous_prices[product_key] * 100
    
    if abs(change) > threshold:
        direction = "jumped" if change > 0 else "dropped"
        arrow = "↑" if change > 0 else "↓"
        print(f"🚨 ALERT: {product_key.replace('_', ' ')} price {direction} {arrow} {abs(change):.2f}%")
        print(f"   Previous: ${previous_prices[product_key]:.2f} → Current: ${current_price:.2f}")
        previous_prices[product_key] = current_price
        return True
    
    previous_prices[product_key] = current_price
    return False

def get_price(product_key: str):
    """
    Get current price for a product
    Args:
        product_key: Product identifier
    Returns:
        Current price or None if error
    """
    collector = EnergyDataCollector()
    
    if product_key == 'CRUDE_OIL':
        price_data = collector.get_crude_oil_price()
    elif product_key == 'RBOB_GASOLINE':
        price_data = collector.get_rbob_gasoline_price()
    elif product_key == 'DIESEL':
        price_data = collector.get_diesel_price()
    else:
        return None
    
    if price_data:
        return price_data.get('price')
    return None

def monitor_energy_markets(interval_seconds: int = 300, threshold: float = 2.0):
    """
    Main monitoring loop
    Args:
        interval_seconds: Time between checks (default 300 = 5 minutes)
        threshold: Price change threshold percentage (default 2.0%)
    """
    products = {
        'CRUDE_OIL': 'Crude Oil',
        'RBOB_GASOLINE': 'RBOB Gasoline',
        'DIESEL': 'Diesel'
    }
    
    print("=" * 60)
    print("Energy AI Agent - Price Monitoring Started")
    print("=" * 60)
    print(f"Monitoring interval: {interval_seconds // 60} minutes")
    print(f"Alert threshold: {threshold}% price change")
    print(f"Products monitored: {', '.join(products.values())}")
    print("=" * 60)
    print("\nStarting monitoring... (Press Ctrl+C to stop)\n")
    
    try:
        while True:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n[{timestamp}] Checking prices...")
            
            alerts_triggered = 0
            
            for product_key, product_name in products.items():
                price = get_price(product_key)
                
                if price:
                    print(f"Current {product_name} Price: ${price:.2f}")
                    
                    if check_alert(product_key, price, threshold):
                        alerts_triggered += 1
                else:
                    print(f"⚠️  Failed to fetch {product_name} price")
            
            if alerts_triggered > 0:
                print(f"\n⚠️  {alerts_triggered} alert(s) triggered this cycle")
            
            print(f"\nNext check in {interval_seconds // 60} minutes...")
            time.sleep(interval_seconds)
            
    except KeyboardInterrupt:
        print("\n\n" + "=" * 60)
        print("Monitoring stopped by user")
        print("=" * 60)
        print("\nFinal recorded prices:")
        for product_key, price in previous_prices.items():
            if price:
                print(f"  {product_key.replace('_', ' ')}: ${price:.2f}")

if __name__ == '__main__':
    # Run monitoring loop
    # Checks every 5 minutes (300 seconds)
    # Alerts on 2% price change
    monitor_energy_markets(interval_seconds=300, threshold=2.0)
