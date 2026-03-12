"""
Fetch Price Data for Prediction Model
Fetches RBOB Gasoline, ULSD Diesel, and Crude Oil prices
"""
import requests
import pandas as pd
from datetime import datetime
import os
import sys

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import API_CONFIG

EIA_API_KEY = API_CONFIG.get('eia_api_key', '')

def get_rbob_price():
    """Get RBOB Gasoline spot price from EIA"""
    try:
        url = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
        params = {
            'api_key': EIA_API_KEY,
            'frequency': 'daily',
            'data[0]': 'value',
            'facets[product][]': 'EPMRBRR',  # RBOB Regular Gasoline
            'sort[0][column]': 'period',
            'sort[0][direction]': 'desc',
            'length': 1
        }
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if 'response' in data and 'data' in data['response']:
            if data['response']['data']:
                return float(data['response']['data'][0].get('value', 0))
    except Exception as e:
        print(f"Error fetching RBOB: {str(e)}")
    return None

def get_ulsd_price():
    """Get ULSD Diesel spot price from EIA"""
    try:
        url = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
        params = {
            'api_key': EIA_API_KEY,
            'frequency': 'daily',
            'data[0]': 'value',
            'facets[product][]': 'EPMULRR',  # Ultra-Low Sulfur Diesel
            'sort[0][column]': 'period',
            'sort[0][direction]': 'desc',
            'length': 1
        }
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if 'response' in data and 'data' in data['response']:
            if data['response']['data']:
                return float(data['response']['data'][0].get('value', 0))
    except Exception as e:
        print(f"Error fetching ULSD: {str(e)}")
    return None

def get_crude_price():
    """Get Crude Oil price (using existing data collector)"""
    try:
        from data_collector import EnergyDataCollector
        collector = EnergyDataCollector()
        price_data = collector.get_crude_oil_price()
        if price_data:
            return price_data.get('price')
    except Exception as e:
        print(f"Error fetching Crude: {str(e)}")
    return None

def save_prices():
    """Fetch and save current prices"""
    print("Fetching price data...")
    
    rbob = get_rbob_price()
    ulsd = get_ulsd_price()
    crude = get_crude_price()
    
    # Use current prices from data collector if EIA fails
    if not rbob or not ulsd:
        from data_collector import EnergyDataCollector
        collector = EnergyDataCollector()
        all_prices = collector.get_all_prices()
        
        if not rbob and all_prices.get('RBOB_GASOLINE'):
            rbob = all_prices['RBOB_GASOLINE'].get('price')
        if not ulsd and all_prices.get('DIESEL'):
            ulsd = all_prices['DIESEL'].get('price')
    
    data = {
        "date": [datetime.now().strftime('%Y-%m-%d')],
        "RBOB": [rbob] if rbob else [None],
        "ULSD": [ulsd] if ulsd else [None],
        "Crude": [crude] if crude else [None]
    }
    
    df = pd.DataFrame(data)
    
    # Append to existing CSV or create new
    csv_path = "data/prices.csv"
    if os.path.exists(csv_path):
        try:
            existing_df = pd.read_csv(csv_path)
            # Only append if this is a new date or if we want to update today's data
            today = datetime.now().strftime('%Y-%m-%d')
            if today not in existing_df['date'].values:
                df = pd.concat([existing_df, df], ignore_index=True)
            else:
                # Update today's data
                existing_df.loc[existing_df['date'] == today] = df.iloc[0]
                df = existing_df
        except:
            pass  # If error reading, just use new df
    
    df.to_csv(csv_path, index=False)
    print(f"Prices saved: RBOB={rbob}, ULSD={ulsd}, Crude={crude}")
    return df

if __name__ == "__main__":
    save_prices()
