"""
Fetch Price Data for Prediction Model
Fetches RBOB Gasoline, ULSD Diesel, and Crude Oil prices
"""
import requests
import pandas as pd
from datetime import datetime
import os
import sys
from typing import Optional

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import API_CONFIG

EIA_API_KEY = API_CONFIG.get('eia_api_key', '')
SPOT_SERIES = API_CONFIG.get('eia_spot_series', {})


def _eia_spot_latest(column: str) -> Optional[float]:
    """Latest EIA daily spot for configured product/duoarea."""
    spec = SPOT_SERIES.get(column, {})
    product = spec.get('product')
    duoarea = spec.get('duoarea')
    if not product or not EIA_API_KEY:
        return None
    try:
        url = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
        params = {
            'api_key': EIA_API_KEY,
            'frequency': 'daily',
            'data[0]': 'value',
            'facets[product][]': product,
            'sort[0][column]': 'period',
            'sort[0][direction]': 'desc',
            'length': 1,
        }
        if duoarea:
            params['facets[duoarea][]'] = duoarea
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        rows = data.get('response', {}).get('data') or []
        if rows:
            return float(rows[0].get('value', 0))
    except Exception as e:
        print(f"Error fetching EIA spot {column}: {e}")
    return None


def get_rbob_price():
    """Get RBOB Gasoline spot price from EIA (NYC reformulated regular proxy)."""
    val = _eia_spot_latest('RBOB')
    if val:
        return val
    try:
        url = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
        params = {
            'api_key': EIA_API_KEY,
            'frequency': 'daily',
            'data[0]': 'value',
            'facets[product][]': 'EPMRR',
            'facets[duoarea][]': 'Y05LA',
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
    """Get ULSD Diesel spot price from EIA (US Gulf Coast)."""
    val = _eia_spot_latest('ULSD')
    if val:
        return val
    try:
        url = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
        params = {
            'api_key': EIA_API_KEY,
            'frequency': 'daily',
            'data[0]': 'value',
            'facets[product][]': 'EPD2DXL0',
            'facets[duoarea][]': 'RGC',
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
    """Get WTI crude spot from EIA, else futures via data collector."""
    val = _eia_spot_latest('Crude')
    if val:
        return val
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
    """Fetch and save current prices — NYMEX futures closes preferred over lagging EIA spot."""
    print("Fetching price data...")

    from live_prices import latest_futures_closes, sync_prices_csv_from_futures, get_nymex_session_close

    closes, as_of, label = get_nymex_session_close()
    if closes and all(closes.get(k) for k in ("RBOB", "ULSD", "Crude")):
        df = sync_prices_csv_from_futures(closes, as_of_date=as_of)
        rbob = closes.get("RBOB")
        ulsd = closes.get("ULSD")
        crude = closes.get("Crude")
        print(f"Prices saved ({label}): RBOB={rbob}, ULSD={ulsd}, Crude={crude}")
        return df

    print(
        "Warning: Barchart settlement unavailable for all three products — "
        "skipping Yahoo/EIA fallback for session close. Re-run after 3:07 PM ET."
    )
    if os.path.exists("data/prices.csv"):
        return pd.read_csv("data/prices.csv")

    # Legacy fallback only when no prices file exists (not used for session close display)
    rbob = get_rbob_price()
    ulsd = get_ulsd_price()
    crude = get_crude_price()

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
        "Crude": [crude] if crude else [None],
        "Brent": [_eia_spot_latest('Brent')],
        "spot_ny": [_eia_spot_latest('spot_ny')],
        "spot_gulf": [_eia_spot_latest('spot_gulf')],
    }

    df = pd.DataFrame(data)

    csv_path = "data/prices.csv"
    if os.path.exists(csv_path):
        try:
            existing_df = pd.read_csv(csv_path)
            existing_df = existing_df.dropna(subset=["date"], how="any")
            today = datetime.now().strftime('%Y-%m-%d')
            if today not in existing_df['date'].values:
                df = pd.concat([existing_df, df], ignore_index=True)
            else:
                existing_df.loc[existing_df['date'] == today] = df.iloc[0]
                df = existing_df
        except Exception:
            pass

    df = df.dropna(subset=["date"], how="any")
    df = df.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    df.to_csv(csv_path, index=False)
    print(f"Prices saved (fallback): RBOB={rbob}, ULSD={ulsd}, Crude={crude}")
    return df

if __name__ == "__main__":
    save_prices()
