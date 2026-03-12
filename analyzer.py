"""
Price and Inventory Analyzer for Energy Markets
Analyzes price changes and inventory data to determine if alerts should be triggered
"""
import json
import os
from datetime import datetime
from typing import Dict, Optional, List
from config import ALERT_CONFIG, PRODUCTS


class PriceAnalyzer:
    """Analyzes price changes and inventory data, generates alerts"""
    
    def __init__(self):
        self.storage_file = ALERT_CONFIG['data_storage_file']
        self.inventory_storage_file = ALERT_CONFIG.get('inventory_storage_file', 'inventory_history.json')
        self.price_threshold = ALERT_CONFIG['price_change_threshold_percent']
        self.inventory_threshold = ALERT_CONFIG.get('inventory_change_threshold_percent', 2.0)
        self.price_history = self.load_history()
        self.inventory_history = self.load_inventory_history()
    
    def load_history(self) -> Dict:
        """Load price history from storage file"""
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading price history: {str(e)}")
                return {}
        return {}
    
    def load_inventory_history(self) -> Dict:
        """Load inventory history from storage file"""
        if os.path.exists(self.inventory_storage_file):
            try:
                with open(self.inventory_storage_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading inventory history: {str(e)}")
                return {}
        return {}
    
    def save_history(self):
        """Save price history to storage file"""
        try:
            with open(self.storage_file, 'w') as f:
                json.dump(self.price_history, f, indent=2)
        except Exception as e:
            print(f"Error saving price history: {str(e)}")
    
    def save_inventory_history(self):
        """Save inventory history to storage file"""
        try:
            with open(self.inventory_storage_file, 'w') as f:
                json.dump(self.inventory_history, f, indent=2)
        except Exception as e:
            print(f"Error saving inventory history: {str(e)}")
    
    def get_previous_price(self, product_key: str) -> Optional[float]:
        """Get the previous recorded price for a product"""
        if product_key in self.price_history:
            history = self.price_history[product_key]
            if history and len(history) > 0:
                return history[-1].get('price')
        return None
    
    def calculate_change(self, current_price: float, previous_price: float) -> Dict:
        """
        Calculate price change metrics
        Returns:
            Dictionary with change amount, percentage, and direction
        """
        if previous_price is None or previous_price == 0:
            return {
                'change_amount': 0,
                'change_percent': 0,
                'direction': 'NEW',
                'is_significant': False
            }
        
        change_amount = current_price - previous_price
        change_percent = (change_amount / previous_price) * 100
        
        direction = 'INCREASE' if change_amount > 0 else 'DECREASE' if change_amount < 0 else 'NO_CHANGE'
        is_significant = abs(change_percent) >= self.price_threshold
        
        return {
            'change_amount': round(change_amount, 4),
            'change_percent': round(change_percent, 2),
            'direction': direction,
            'is_significant': is_significant,
            'previous_price': previous_price,
            'current_price': current_price
        }
    
    def analyze_price(self, price_data: Dict) -> Dict:
        """
        Analyze a single price data point
        Args:
            price_data: Dictionary containing price information
        Returns:
            Dictionary with analysis results including alerts
        """
        if not price_data:
            return {'error': 'No price data provided'}
        
        product_key = price_data.get('product_key')
        current_price = price_data.get('price')
        
        if not product_key or current_price is None:
            return {'error': 'Invalid price data'}
        
        previous_price = self.get_previous_price(product_key)
        change_metrics = self.calculate_change(current_price, previous_price)
        
        # Update history
        if product_key not in self.price_history:
            self.price_history[product_key] = []
        
        self.price_history[product_key].append({
            'price': current_price,
            'timestamp': price_data.get('timestamp', datetime.now().isoformat()),
            'open': price_data.get('open'),
            'high': price_data.get('high'),
            'low': price_data.get('low'),
            'volume': price_data.get('volume')
        })
        
        # Keep only last 100 entries per product
        if len(self.price_history[product_key]) > 100:
            self.price_history[product_key] = self.price_history[product_key][-100:]
        
        self.save_history()
        
        # Determine if alert should be sent
        # Alert on first recording OR when change exceeds threshold
        # The system alerts on BOTH increases and decreases
        should_alert = change_metrics['is_significant'] or previous_price is None
        
        analysis = {
            'product': price_data.get('product', product_key),
            'product_key': product_key,
            'current_price': current_price,
            'previous_price': previous_price,
            'change_metrics': change_metrics,
            'should_alert': should_alert,
            'timestamp': price_data.get('timestamp', datetime.now().isoformat()),
            'additional_data': {
                'open': price_data.get('open'),
                'high': price_data.get('high'),
                'low': price_data.get('low'),
                'volume': price_data.get('volume'),
                'currency': price_data.get('currency', 'USD')
            }
        }
        
        return analysis
    
    def analyze_all_prices(self, prices: Dict[str, Optional[Dict]]) -> List[Dict]:
        """
        Analyze all price data points
        Args:
            prices: Dictionary of product_key -> price_data
        Returns:
            List of analysis results
        """
        analyses = []
        
        for product_key, price_data in prices.items():
            if price_data:
                analysis = self.analyze_price(price_data)
                analyses.append(analysis)
            else:
                print(f"Warning: No price data for {product_key}")
        
        return analyses
    
    def analyze_inventory(self, inventory_data: Dict) -> Dict:
        """
        Analyze inventory data
        Args:
            inventory_data: Dictionary containing inventory information
        Returns:
            Dictionary with analysis results
        """
        if not inventory_data:
            return {'error': 'No inventory data provided'}
        
        product_key = inventory_data.get('product_key')
        current_value = inventory_data.get('value')
        
        if not product_key or current_value is None:
            return {'error': 'Invalid inventory data'}
        
        previous_value = self.get_previous_inventory(product_key)
        change_metrics = self.calculate_inventory_change(current_value, previous_value)
        
        # Update history
        if product_key not in self.inventory_history:
            self.inventory_history[product_key] = []
        
        self.inventory_history[product_key].append({
            'value': current_value,
            'timestamp': inventory_data.get('timestamp', datetime.now().isoformat()),
            'period': inventory_data.get('period', ''),
            'units': inventory_data.get('units', 'thousand barrels')
        })
        
        # Keep only last 50 entries per inventory type
        if len(self.inventory_history[product_key]) > 50:
            self.inventory_history[product_key] = self.inventory_history[product_key][-50:]
        
        self.save_inventory_history()
        
        # Determine if alert should be sent
        should_alert = change_metrics['is_significant'] or previous_value is None
        
        analysis = {
            'product': inventory_data.get('name', product_key),
            'product_key': product_key,
            'current_value': current_value,
            'previous_value': previous_value,
            'change_metrics': change_metrics,
            'should_alert': should_alert,
            'timestamp': inventory_data.get('timestamp', datetime.now().isoformat()),
            'additional_data': {
                'period': inventory_data.get('period', ''),
                'units': inventory_data.get('units', 'thousand barrels')
            }
        }
        
        return analysis
    
    def get_previous_inventory(self, product_key: str) -> Optional[float]:
        """Get the previous recorded inventory value for a product"""
        if product_key in self.inventory_history:
            history = self.inventory_history[product_key]
            if history and len(history) > 0:
                return history[-1].get('value')
        return None
    
    def calculate_inventory_change(self, current_value: float, previous_value: float) -> Dict:
        """
        Calculate inventory change metrics
        Returns:
            Dictionary with change amount, percentage, and direction
        """
        if previous_value is None or previous_value == 0:
            return {
                'change_amount': 0,
                'change_percent': 0,
                'direction': 'NEW',
                'is_significant': False
            }
        
        change_amount = current_value - previous_value
        change_percent = (change_amount / previous_value) * 100
        
        direction = 'INCREASE' if change_amount > 0 else 'DECREASE' if change_amount < 0 else 'NO_CHANGE'
        is_significant = abs(change_percent) >= self.inventory_threshold
        
        return {
            'change_amount': round(change_amount, 2),
            'change_percent': round(change_percent, 2),
            'direction': direction,
            'is_significant': is_significant,
            'previous_value': previous_value,
            'current_value': current_value
        }
    
    def analyze_all_inventories(self, inventories: Dict[str, Optional[Dict]]) -> List[Dict]:
        """
        Analyze all inventory data points
        Args:
            inventories: Dictionary of product_key -> inventory_data
        Returns:
            List of analysis results
        """
        analyses = []
        
        for product_key, inventory_data in inventories.items():
            if inventory_data:
                analysis = self.analyze_inventory(inventory_data)
                analyses.append(analysis)
            else:
                print(f"Warning: No inventory data for {product_key}")
        
        return analyses
    
    def generate_market_signal(self, price_analyses: List[Dict], inventory_analyses: List[Dict]) -> Dict:
        """
        Generate market signals based on price and inventory correlation
        Example: Gasoline inventory ↓ + RBOB price ↑ = Strong demand alert
        """
        signals = []
        
        # Find RBOB Gasoline price and inventory
        rbob_price = next((a for a in price_analyses if a.get('product_key') == 'RBOB_GASOLINE'), None)
        gas_inventory = next((a for a in inventory_analyses if a.get('product_key') == 'GASOLINE_INVENTORY'), None)
        
        # Find Diesel price and inventory
        diesel_price = next((a for a in price_analyses if a.get('product_key') == 'DIESEL'), None)
        diesel_inventory = next((a for a in inventory_analyses if a.get('product_key') == 'DIESEL_INVENTORY'), None)
        
        # Analyze RBOB Gasoline signals
        if rbob_price and gas_inventory:
            price_dir = rbob_price['change_metrics']['direction']
            inv_dir = gas_inventory['change_metrics']['direction']
            
            if price_dir == 'INCREASE' and inv_dir == 'DECREASE':
                signals.append({
                    'type': 'STRONG_DEMAND',
                    'product': 'RBOB Gasoline',
                    'message': 'Price ↑ + Inventory ↓ = Strong demand signal',
                    'severity': 'HIGH'
                })
            elif price_dir == 'DECREASE' and inv_dir == 'INCREASE':
                signals.append({
                    'type': 'WEAK_DEMAND',
                    'product': 'RBOB Gasoline',
                    'message': 'Price ↓ + Inventory ↑ = Weak demand signal',
                    'severity': 'MEDIUM'
                })
        
        # Analyze Diesel signals
        if diesel_price and diesel_inventory:
            price_dir = diesel_price['change_metrics']['direction']
            inv_dir = diesel_inventory['change_metrics']['direction']
            
            if price_dir == 'INCREASE' and inv_dir == 'DECREASE':
                signals.append({
                    'type': 'STRONG_DEMAND',
                    'product': 'Diesel',
                    'message': 'Price ↑ + Inventory ↓ = Strong demand signal',
                    'severity': 'HIGH'
                })
            elif price_dir == 'DECREASE' and inv_dir == 'INCREASE':
                signals.append({
                    'type': 'WEAK_DEMAND',
                    'product': 'Diesel',
                    'message': 'Price ↓ + Inventory ↑ = Weak demand signal',
                    'severity': 'MEDIUM'
                })
        
        return {
            'signals': signals,
            'timestamp': datetime.now().isoformat()
        }
    
    def get_price_trend(self, product_key: str, periods: int = 5) -> Optional[Dict]:
        """
        Get price trend over recent periods
        Args:
            product_key: Product identifier
            periods: Number of recent periods to analyze
        Returns:
            Dictionary with trend information
        """
        if product_key not in self.price_history:
            return None
        
        history = self.price_history[product_key][-periods:]
        
        if len(history) < 2:
            return None
        
        prices = [entry['price'] for entry in history]
        first_price = prices[0]
        last_price = prices[-1]
        
        total_change = last_price - first_price
        total_change_percent = (total_change / first_price) * 100 if first_price > 0 else 0
        
        # Calculate volatility (standard deviation of price changes)
        price_changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        volatility = sum(abs(change) for change in price_changes) / len(price_changes) if price_changes else 0
        
        return {
            'periods_analyzed': len(history),
            'first_price': first_price,
            'last_price': last_price,
            'total_change': round(total_change, 4),
            'total_change_percent': round(total_change_percent, 2),
            'volatility': round(volatility, 4),
            'trend': 'UPWARD' if total_change > 0 else 'DOWNWARD' if total_change < 0 else 'STABLE'
        }


if __name__ == '__main__':
    # Test the analyzer
    from data_collector import EnergyDataCollector
    
    analyzer = PriceAnalyzer()
    collector = EnergyDataCollector()
    
    print("Testing price analysis...")
    prices = collector.get_all_prices()
    analyses = analyzer.analyze_all_prices(prices)
    
    for analysis in analyses:
        print(f"\n{analysis['product']} Analysis:")
        print(f"  Current Price: ${analysis['current_price']:.4f}")
        if analysis['previous_price']:
            print(f"  Previous Price: ${analysis['previous_price']:.4f}")
            print(f"  Change: ${analysis['change_metrics']['change_amount']:.4f} ({analysis['change_metrics']['change_percent']:.2f}%)")
            print(f"  Direction: {analysis['change_metrics']['direction']}")
            print(f"  Significant Change: {analysis['change_metrics']['is_significant']}")
        else:
            print("  First recording - no previous price")
        print(f"  Should Alert: {analysis['should_alert']}")
