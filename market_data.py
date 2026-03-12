"""
Market Data Fetcher using Alpha Vantage API
Simple script to get current prices for energy commodities
"""
import requests
from config import API_CONFIG

API_KEY = API_CONFIG['alpha_vantage_api_key']

def get_price(symbol):
    """
    Get current price from Alpha Vantage API
    Args:
        symbol: Futures symbol (e.g., 'CL=F', 'RB=F', 'HO=F')
    Returns:
        Current price as float, or None if error
    """
    try:
        url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={API_KEY}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        # Check for API rate limit or error messages
        if 'Note' in data:
            print(f"API Note for {symbol}: {data['Note']}")
            return None
        
        if 'Error Message' in data:
            print(f"API Error for {symbol}: {data['Error Message']}")
            return None
        
        if 'Global Quote' in data and data['Global Quote']:
            quote = data['Global Quote']
            price_str = quote.get('05. price', '0')
            
            if not price_str or price_str == 'None' or price_str == '0':
                print(f"Warning: Invalid price data for {symbol}")
                return None
            
            return float(price_str)
        else:
            print(f"Error: No Global Quote data for {symbol}")
            print(f"Response keys: {list(data.keys())}")
            return None
    except Exception as e:
        print(f"Error fetching price for {symbol}: {str(e)}")
        return None

if __name__ == '__main__':
    print("Fetching energy market prices from Alpha Vantage...")
    print("-" * 50)
    print("Note: Alpha Vantage free tier has rate limits (5 calls/min)")
    print("      If you see errors, wait 12 seconds between calls")
    print("-" * 50)
    
    import time
    
    crude_price = get_price("CL=F")
    time.sleep(12)  # Rate limit: 5 calls per minute
    
    gasoline_price = get_price("RB=F")
    time.sleep(12)
    
    diesel_price = get_price("HO=F")
    
    print("\nResults:")
    print("-" * 50)
    if crude_price:
        print(f"Crude Oil (CL=F):     ${crude_price:.2f}")
    else:
        print("Crude Oil (CL=F):     Error - Try using Yahoo Finance fallback")
    
    if gasoline_price:
        print(f"RBOB Gasoline (RB=F): ${gasoline_price:.2f}")
    else:
        print("RBOB Gasoline (RB=F): Error - Try using Yahoo Finance fallback")
    
    if diesel_price:
        print(f"Diesel (HO=F):        ${diesel_price:.2f}")
    else:
        print("Diesel (HO=F):        Error - Try using Yahoo Finance fallback")
    
    print("-" * 50)
    print(f"API Key: {API_KEY[:10]}...{API_KEY[-4:]}")
    print("\nTip: If Alpha Vantage doesn't support futures symbols,")
    print("     the system will automatically fall back to Yahoo Finance.")
