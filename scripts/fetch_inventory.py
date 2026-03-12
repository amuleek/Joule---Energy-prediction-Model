"""
Fetch Inventory Data for Prediction Model
Fetches weekly inventory reports from EIA
"""
import requests
import pandas as pd
from datetime import datetime
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import API_CONFIG, EIA_INVENTORY_SERIES

EIA_API_KEY = API_CONFIG.get('eia_api_key', '')

def fetch_inventory():
    """Fetch inventory data from EIA"""
    print("Fetching inventory data...")
    
    inventory_data = []
    
    try:
        # Get gasoline inventory
        url = "https://api.eia.gov/v2/petroleum/stoc/wstk/data/"
        params = {
            'api_key': EIA_API_KEY,
            'frequency': 'weekly',
            'data[0]': 'value',
            'facets[series][]': EIA_INVENTORY_SERIES['GASOLINE']['series_id'],
            'sort[0][column]': 'period',
            'sort[0][direction]': 'desc',
            'length': 1
        }
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        
        if 'response' in data and 'data' in data['response']:
            if data['response']['data']:
                item = data['response']['data'][0]
                inventory_data.append({
                    'date': item.get('period', ''),
                    'gasoline_inventory': float(item.get('value', 0)),
                    'diesel_inventory': None  # Will fetch separately
                })
        
        # Get diesel inventory
        params['facets[series][]'] = EIA_INVENTORY_SERIES['DIESEL']['series_id']
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        
        if 'response' in data and 'data' in data['response']:
            if data['response']['data']:
                item = data['response']['data'][0]
                if inventory_data:
                    inventory_data[0]['diesel_inventory'] = float(item.get('value', 0))
                else:
                    inventory_data.append({
                        'date': item.get('period', ''),
                        'gasoline_inventory': None,
                        'diesel_inventory': float(item.get('value', 0))
                    })
        
    except Exception as e:
        print(f"Error fetching inventory: {str(e)}")
    
    if inventory_data:
        df = pd.DataFrame(inventory_data)
        csv_path = "data/inventory.csv"
        
        if os.path.exists(csv_path):
            existing_df = pd.read_csv(csv_path)
            df = pd.concat([existing_df, df], ignore_index=True)
            df = df.drop_duplicates(subset=['date'], keep='last')
        
        df.to_csv(csv_path, index=False)
        print(f"Inventory saved: {len(df)} records")
        return df
    else:
        print("No inventory data fetched")
        return pd.DataFrame(columns=['date', 'gasoline_inventory', 'diesel_inventory'])

if __name__ == "__main__":
    fetch_inventory()
