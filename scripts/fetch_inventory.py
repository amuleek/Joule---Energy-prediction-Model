"""
Fetch Inventory Data for Prediction Model
Fetches weekly inventory reports from EIA
"""
import requests
import pandas as pd
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import API_CONFIG, EIA_INVENTORY_SERIES

EIA_API_KEY = API_CONFIG.get('eia_api_key', '')


def _fetch_one_series(series_id: str):
    url = "https://api.eia.gov/v2/petroleum/stoc/wstk/data/"
    params = {
        'api_key': EIA_API_KEY,
        'frequency': 'weekly',
        'data[0]': 'value',
        'facets[series][]': series_id,
        'sort[0][column]': 'period',
        'sort[0][direction]': 'desc',
        'length': 1,
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if 'response' in data and data['response'].get('data'):
        item = data['response']['data'][0]
        return item.get('period', ''), float(item.get('value', 0))
    return None, None


def fetch_inventory():
    """Fetch weekly gasoline, distillate, and crude inventories from EIA."""
    print("Fetching inventory data...")
    
    inventory_data = []
    
    try:
        gas_date, gas_val = _fetch_one_series(EIA_INVENTORY_SERIES['GASOLINE']['series_id'])
        die_date, die_val = _fetch_one_series(EIA_INVENTORY_SERIES['DIESEL']['series_id'])
        cru_date, cru_val = _fetch_one_series(EIA_INVENTORY_SERIES['CRUDE']['series_id'])

        # Align on latest common reporting week when dates differ (use max period string)
        period = max(filter(None, [gas_date, die_date, cru_date]), default=gas_date or die_date or cru_date)
        row = {
            'date': period or '',
            'gasoline_inventory': gas_val,
            'diesel_inventory': die_val,
            'crude_inventory': cru_val,
        }
        if row['date']:
            inventory_data.append(row)
        
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
        return pd.DataFrame(columns=['date', 'gasoline_inventory', 'diesel_inventory', 'crude_inventory'])

if __name__ == "__main__":
    fetch_inventory()
