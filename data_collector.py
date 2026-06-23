"""
Data Collector for Energy Prices and Inventories
Fetches RBOB Gasoline, Diesel, Crude Oil prices from Alpha Vantage
and inventory data from EIA
"""
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime
from typing import Dict, Optional, List
import json
import os
import time
from config import PRODUCTS, API_CONFIG, EIA_INVENTORY_SERIES


class EnergyDataCollector:
    """Collects energy price data from Alpha Vantage and inventory data from EIA"""
    
    def __init__(self):
        self.use_yahoo = API_CONFIG.get('use_yahoo_finance', False)
        self.api_key = API_CONFIG.get('alpha_vantage_api_key', '')
        self.eia_api_key = API_CONFIG.get('eia_api_key', '')
        self.primary_source = API_CONFIG.get('primary_source', 'alpha_vantage')
    
    def get_price_from_alpha_vantage(self, symbol: str) -> Optional[Dict]:
        """
        Fetch current price from Alpha Vantage API
        Args:
            symbol: Futures symbol (e.g., 'CL=F', 'RB=F', 'HO=F')
        Returns:
            Dictionary with price information or None if error
        """
        if not self.api_key:
            print(f"Warning: Alpha Vantage API key not set")
            return None
        
        try:
            url = "https://www.alphavantage.co/query"
            params = {
                'function': 'GLOBAL_QUOTE',
                'symbol': symbol,
                'apikey': self.api_key
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Check for API rate limit message
            if 'Note' in data:
                print(f"API Rate Limit: {data['Note']}")
                time.sleep(12)  # Wait 12 seconds (free tier: 5 calls/min)
                return None
            
            if 'Global Quote' in data and data['Global Quote']:
                quote = data['Global Quote']
                price_str = quote.get('05. price', '0')
                
                # Handle empty or invalid price
                if not price_str or price_str == 'None':
                    return None
                
                return {
                    'price': float(price_str),
                    'open': float(quote.get('02. open', 0) or 0),
                    'high': float(quote.get('03. high', 0) or 0),
                    'low': float(quote.get('04. low', 0) or 0),
                    'volume': int(quote.get('06. volume', 0) or 0),
                    'previous_close': float(quote.get('08. previous close', 0) or 0),
                    'change': float(quote.get('09. change', 0) or 0),
                    'change_percent': quote.get('10. change percent', '0%').replace('%', ''),
                    'timestamp': datetime.now().isoformat(),
                    'currency': 'USD',
                    'source': 'Alpha Vantage'
                }
            else:
                print(f"No data in Global Quote for {symbol}")
                return None
                
        except Exception as e:
            print(f"Error fetching from Alpha Vantage for {symbol}: {str(e)}")
            return None
    
    def get_price_from_yahoo(self, symbol: str) -> Optional[Dict]:
        """
        Fetch current price from Yahoo Finance (fallback)
        Args:
            symbol: Yahoo Finance symbol (e.g., 'RB=F' for RBOB Gasoline)
        Returns:
            Dictionary with price information or None if error
        """
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period='1d', interval='1m')
            
            if data.empty:
                data = ticker.history(period='5d')
            
            if not data.empty:
                latest = data.iloc[-1]
                info = ticker.info
                
                return {
                    'price': float(latest['Close']),
                    'open': float(latest['Open']),
                    'high': float(latest['High']),
                    'low': float(latest['Low']),
                    'volume': int(latest['Volume']) if pd.notna(latest['Volume']) else 0,
                    'timestamp': datetime.now().isoformat(),
                    'currency': info.get('currency', 'USD'),
                    'source': 'Yahoo Finance'
                }
        except Exception as e:
            print(f"Error fetching from Yahoo Finance for {symbol}: {str(e)}")
            return None
    
    def get_crude_oil_price(self) -> Optional[Dict]:
        """Get Crude Oil price"""
        product = PRODUCTS['CRUDE_OIL']
        
        # Try Alpha Vantage first if configured
        if self.primary_source == 'alpha_vantage' and self.api_key:
            price_data = self.get_price_from_alpha_vantage(product['ticker'])
            # Fallback to Yahoo if Alpha Vantage fails
            if not price_data:
                price_data = self.get_price_from_yahoo(product['symbol'])
        else:
            price_data = self.get_price_from_yahoo(product['symbol'])
        
        if price_data:
            price_data['product'] = product['name']
            price_data['product_key'] = 'CRUDE_OIL'
        
        return price_data
    
    def get_rbob_gasoline_price(self) -> Optional[Dict]:
        """Get RBOB Gasoline price"""
        product = PRODUCTS['RBOB_GASOLINE']
        
        # Try Alpha Vantage first if configured
        if self.primary_source == 'alpha_vantage' and self.api_key:
            price_data = self.get_price_from_alpha_vantage(product['ticker'])
            # Fallback to Yahoo if Alpha Vantage fails
            if not price_data:
                price_data = self.get_price_from_yahoo(product['symbol'])
        else:
            price_data = self.get_price_from_yahoo(product['symbol'])
        
        if price_data:
            price_data['product'] = product['name']
            price_data['product_key'] = 'RBOB_GASOLINE'
        
        return price_data
    
    def get_diesel_price(self) -> Optional[Dict]:
        """Get Ultra-Low Sulfur Diesel price"""
        product = PRODUCTS['DIESEL']
        
        # Try Alpha Vantage first if configured
        if self.primary_source == 'alpha_vantage' and self.api_key:
            price_data = self.get_price_from_alpha_vantage(product['ticker'])
            # Fallback to Yahoo if Alpha Vantage fails
            if not price_data:
                price_data = self.get_price_from_yahoo(product['symbol'])
        else:
            price_data = self.get_price_from_yahoo(product['symbol'])
        
        if price_data:
            price_data['product'] = product['name']
            price_data['product_key'] = 'DIESEL'
        
        return price_data
    
    def get_eia_inventory(self, series_id: str, name: str) -> Optional[Dict]:
        """
        Fetch inventory data from EIA API v2
        Args:
            series_id: EIA series ID
            name: Name of the inventory type
        Returns:
            Dictionary with inventory information or None if error
        """
        if not self.eia_api_key:
            return None
        
        try:
            # EIA API v2 format for petroleum stock data
            url = "https://api.eia.gov/v2/petroleum/stoc/wstk/data/"
            params = {
                'api_key': self.eia_api_key,
                'frequency': 'weekly',
                'data[0]': 'value',  # Only 'value' is allowed in data parameter
                'sort[0][column]': 'period',
                'sort[0][direction]': 'desc',
                'length': 1
            }
            
            # Add series filter using facets
            if series_id:
                params['facets[series][]'] = series_id
            
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            # Debug: print response structure if needed
            if 'response' not in data:
                print(f"EIA API response structure: {list(data.keys())}")
                if 'error' in data:
                    print(f"EIA API error: {data.get('error')}")
                return None
            
            if 'response' in data and 'data' in data['response']:
                data_list = data['response']['data']
                if data_list and len(data_list) > 0:
                    latest = data_list[0]
                    value_str = latest.get('value', '0')
                    # EIA API v2 returns values as strings
                    try:
                        value = float(value_str) if value_str else 0
                    except (ValueError, TypeError):
                        value = 0
                    
                    return {
                        'value': value,
                        'period': latest.get('period', ''),
                        'units': latest.get('units', 'thousand barrels'),
                        'name': name,
                        'timestamp': datetime.now().isoformat(),
                        'source': 'EIA'
                    }
            else:
                print(f"EIA API: No data in response for {name}")
                if 'response' in data:
                    print(f"Response keys: {list(data['response'].keys())}")
        except requests.exceptions.RequestException as e:
            print(f"EIA API request error for {name}: {str(e)}")
            return None
        except Exception as e:
            print(f"Error fetching EIA inventory data for {name}: {str(e)}")
            import traceback
            traceback.print_exc()
            return None

    def get_eia_weekly_retail_pump_prices(self) -> Optional[Dict]:
        """
        Latest EIA weekly retail pump prices for a configured region (default PADD 1B, includes NJ).
        Uses petroleum/pri/gnd — not futures; complements NYMEX RBOB/HO in reports.
        """
        if not self.eia_api_key:
            return None
        duo = API_CONFIG.get('eia_retail_duoarea', 'R1Y')
        label = API_CONFIG.get('eia_retail_duoarea_label', duo)
        url = "https://api.eia.gov/v2/petroleum/pri/gnd/data/"
        products = {
            "EPMR": "regular_gasoline",
            "EPD2DXL0": "ulsd_diesel",
        }
        out: Dict = {
            "region_code": duo,
            "region_label": label,
            "period": None,
            "units": "$/gal",
            "source": "EIA Weekly Retail (G&D)",
        }
        try:
            for facet_product, key in products.items():
                params = {
                    "api_key": self.eia_api_key,
                    "frequency": "weekly",
                    "data[0]": "value",
                    "facets[duoarea][]": duo,
                    "facets[product][]": facet_product,
                    "length": 1,
                    "sort[0][column]": "period",
                    "sort[0][direction]": "desc",
                }
                response = requests.get(url, params=params, timeout=15)
                response.raise_for_status()
                data = response.json()
                rows = data.get("response", {}).get("data") or []
                if not rows:
                    continue
                row = rows[0]
                val = row.get("value")
                if val is None or val == "":
                    continue
                out[key] = float(val)
                p = row.get("period")
                if p and (out["period"] is None or p > out["period"]):
                    out["period"] = p
            if out.get("regular_gasoline") is None and out.get("ulsd_diesel") is None:
                return None
            out["timestamp"] = datetime.now().isoformat()
            return out
        except Exception as e:
            print(f"Error fetching EIA retail pump prices: {str(e)}")
            return None
    
    def get_gasoline_inventory(self) -> Optional[Dict]:
        """Get Gasoline inventory data from EIA"""
        series = EIA_INVENTORY_SERIES['GASOLINE']
        inventory_data = self.get_eia_inventory(series['series_id'], series['name'])
        if inventory_data:
            inventory_data['product_key'] = 'GASOLINE_INVENTORY'
        return inventory_data
    
    def get_diesel_inventory(self) -> Optional[Dict]:
        """Get Diesel inventory data from EIA"""
        series = EIA_INVENTORY_SERIES['DIESEL']
        inventory_data = self.get_eia_inventory(series['series_id'], series['name'])
        if inventory_data:
            inventory_data['product_key'] = 'DIESEL_INVENTORY'
        return inventory_data

    def get_crude_inventory(self) -> Optional[Dict]:
        """Get U.S. commercial crude oil stocks from EIA"""
        series = EIA_INVENTORY_SERIES['CRUDE']
        inventory_data = self.get_eia_inventory(series['series_id'], series['name'])
        if inventory_data:
            inventory_data['product_key'] = 'CRUDE_INVENTORY'
        return inventory_data
    
    def get_all_prices(self) -> Dict[str, Optional[Dict]]:
        """Get prices for all tracked products"""
        prices = {}
        
        # Add small delay between API calls to respect rate limits
        prices['CRUDE_OIL'] = self.get_crude_oil_price()
        time.sleep(1)  # Rate limit protection
        
        prices['RBOB_GASOLINE'] = self.get_rbob_gasoline_price()
        time.sleep(1)
        
        prices['DIESEL'] = self.get_diesel_price()
        
        return prices
    
    def get_all_inventories(self) -> Dict[str, Optional[Dict]]:
        """Get inventory data for all tracked products"""
        return {
            'GASOLINE_INVENTORY': self.get_gasoline_inventory(),
            'DIESEL_INVENTORY': self.get_diesel_inventory(),
            'CRUDE_INVENTORY': self.get_crude_inventory(),
        }
    
    def get_all_data(self) -> Dict:
        """Get all price and inventory data"""
        return {
            'prices': self.get_all_prices(),
            'inventories': self.get_all_inventories(),
            'retail_pump_weekly': self.get_eia_weekly_retail_pump_prices(),
        }


if __name__ == '__main__':
    # Test the data collector
    collector = EnergyDataCollector()
    print("Fetching energy prices from Alpha Vantage...")
    print("=" * 60)
    
    prices = collector.get_all_prices()
    for product_key, price_data in prices.items():
        if price_data:
            print(f"\n{price_data['product']}:")
            print(f"  Current Price: ${price_data['price']:.4f}")
            print(f"  Open: ${price_data['open']:.4f}")
            print(f"  High: ${price_data['high']:.4f}")
            print(f"  Low: ${price_data['low']:.4f}")
            if 'change_percent' in price_data:
                print(f"  Change: {price_data['change_percent']}%")
            print(f"  Volume: {price_data['volume']:,}")
            print(f"  Source: {price_data.get('source', 'Unknown')}")
        else:
            print(f"\n{product_key}: Failed to fetch price data")
    
    # Test inventory data if EIA API key is set
    if collector.eia_api_key:
        print("\n" + "=" * 60)
        print("Fetching inventory data from EIA...")
        inventories = collector.get_all_inventories()
        for inv_key, inv_data in inventories.items():
            if inv_data:
                print(f"\n{inv_data['name']}:")
                print(f"  Value: {inv_data['value']:,.0f} {inv_data['units']}")
                print(f"  Period: {inv_data['period']}")
            else:
                print(f"\n{inv_key}: Failed to fetch inventory data")
    else:
        print("\n" + "=" * 60)
        print("EIA API key not set. Skipping inventory data.")
