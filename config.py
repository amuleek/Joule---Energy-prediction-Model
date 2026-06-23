"""
Configuration file for Energy AI Agent
"""
import os
from typing import Dict

# Email Configuration
EMAIL_CONFIG = {
    'smtp_server': os.getenv('SMTP_SERVER', 'smtp.gmail.com'),
    'smtp_port': int(os.getenv('SMTP_PORT', '587')),
    'sender_email': os.getenv('SENDER_EMAIL', ''),
    'sender_password': os.getenv('SENDER_PASSWORD', ''),
    'recipient_emails': os.getenv(
        'RECIPIENT_EMAILS',
        'taransandhu@gillenergy.com,bikramgill@gillenergy.com,ravigill@gillenergy.com,kashmirgill@gillenergy.com'
    ).split(',')
}

# API Configuration
API_CONFIG = {
    # Alpha Vantage API (free tier available)
    'alpha_vantage_api_key': os.getenv('ALPHA_VANTAGE_API_KEY', ''),
    # EIA API for inventory data
    'eia_api_key': os.getenv('EIA_API_KEY', ''),
    # NewsAPI for news sentiment analysis (optional - get free key at newsapi.org)
    'news_api_key': os.getenv('NEWS_API_KEY', ''),
    # World News API (alternative news source)
    'world_news_api_key': os.getenv('WORLD_NEWS_API_KEY', ''),
    # Alternative: Yahoo Finance (no API key needed) - used as fallback
    'use_yahoo_finance': os.getenv('USE_YAHOO_FINANCE', 'true').lower() == 'true',
    # Primary data source: 'alpha_vantage' or 'yahoo_finance'
    # Note: Alpha Vantage may not support futures symbols, so Yahoo Finance is used as fallback
    'primary_source': os.getenv('PRIMARY_SOURCE', 'yahoo_finance'),
    # EIA "Weekly Retail Gasoline and Diesel" (PADD / metro). R1Y = PADD 1B Central Atlantic (includes NJ).
    # See duoarea facet on https://api.eia.gov/v2/petroleum/pri/gnd/ — override if you want NYC (Y35NY) etc.
    'eia_retail_duoarea': os.getenv('EIA_RETAIL_DUOAREA', 'R1Y'),
    'eia_retail_duoarea_label': os.getenv(
        'EIA_RETAIL_DUOAREA_LABEL',
        'PADD 1B Central Atlantic (includes NJ)',
    ),
    # EIA daily spot (product + duoarea) — v2 facet IDs
    'eia_spot_series': {
        'RBOB': {'product': 'EPMRR', 'duoarea': 'Y05LA'},  # Primary RBOB proxy (LA spot)
        'ULSD': {'product': 'EPD2DXL0', 'duoarea': 'RGC'},
        'Crude': {'product': 'EPCWTI', 'duoarea': 'YCUOK'},
        'spot_ny': {'product': 'EPMRR', 'duoarea': 'Y35NY'},  # NY Harbor — key for NJ / East Coast basis
        'spot_gulf': {'product': 'EPMRR', 'duoarea': 'RGC'},
        'Brent': {'product': 'EPCBRENT', 'duoarea': 'ZEU'},
    },
}

# Product Configuration
PRODUCTS = {
    'CRUDE_OIL': {
        'name': 'Crude Oil',
        'symbol': 'CL=F',  # Alpha Vantage symbol
        'cme_symbol': 'CL',
        'ticker': 'CL=F'
    },
    'RBOB_GASOLINE': {
        'name': 'RBOB Gasoline',
        'symbol': 'RB=F',  # Alpha Vantage symbol
        'cme_symbol': 'RB',
        'ticker': 'RB=F'
    },
    'DIESEL': {
        'name': 'Ultra-Low Sulfur Diesel',
        'symbol': 'HO=F',  # Alpha Vantage symbol for Heating Oil (ULSD proxy)
        'cme_symbol': 'HO',
        'ticker': 'HO=F'
    }
}

# EIA Inventory Series IDs
# Verified working series IDs from EIA API v2
EIA_INVENTORY_SERIES = {
    'GASOLINE': {
        'series_id': 'WGTSTUS1',  # Total Motor Gasoline Stocks (thousand barrels)
        'name': 'Gasoline Inventories'
    },
    'DIESEL': {
        'series_id': 'WDISTUS1',  # Total Distillate Fuel Oil Stocks (thousand barrels)
        'name': 'Diesel/Distillate Inventories'
    },
    'CRUDE': {
        'series_id': 'WCESTUS1',  # U.S. Ending Stocks of Crude Oil (thousand barrels)
        'name': 'Crude Oil Inventories'
    },
}

# EIA operational / trade series (weekly unless noted)
EIA_OPERATIONAL_SERIES = {
    'refinery_utilization_pct': {
        'series_id': 'WPULEUS3',
        'name': 'US Refinery Utilization %',
        'frequency': 'weekly',
    },
    'crude_imports_kbpd': {
        'series_id': 'WTTIMUS2',
        'name': 'US Crude Imports (kbpd)',
        'frequency': 'weekly',
    },
    'crude_exports_kbpd': {
        'series_id': 'WCRNTUS2',
        'name': 'US Crude Exports (kbpd)',
        'frequency': 'weekly',
    },
}

# Yahoo futures symbols (extended)
FUTURES_SYMBOLS = {
    'rbob': 'RB=F',
    'crude': 'CL=F',
    'diesel': 'HO=F',
    'brent': 'BZ=F',
    'natgas': 'NG=F',
}

# Ensemble model default weights (updated by learning loop)
DEFAULT_ENSEMBLE_WEIGHTS = {
    'RBOB_Gasoline': {'technical': 0.50, 'fundamental': 0.28, 'news': 0.22},
    'ULSD_Diesel': {'technical': 0.35, 'fundamental': 0.40, 'news': 0.25},
    'Crude_Oil': {'technical': 0.35, 'fundamental': 0.35, 'news': 0.30},
}

# Max absolute % move caps per product/horizon (applied after model output)
PRODUCT_HORIZON_CAPS = {
    'RBOB_Gasoline': {'day_1': 0.025, 'day_4': 0.06, 'day_7': 0.08},
    'ULSD_Diesel': {'day_1': 0.03, 'day_4': 0.07, 'day_7': 0.09},
    'Crude_Oil': {'day_1': 0.035, 'day_4': 0.08, 'day_7': 0.10},
}

MODEL_WEIGHTS_PATH = os.getenv('MODEL_WEIGHTS_PATH', 'data/model_weights.json')
ALERT_CONFIG = {
    'price_change_threshold_percent': float(os.getenv('PRICE_CHANGE_THRESHOLD', '2.0')),  # 2% change triggers alert (default)
    'inventory_change_threshold_percent': float(os.getenv('INVENTORY_CHANGE_THRESHOLD', '2.0')),  # 2% inventory change
    'check_interval_minutes': int(os.getenv('CHECK_INTERVAL_MINUTES', '5')),  # Check every 5 minutes
    'check_interval_seconds': int(os.getenv('CHECK_INTERVAL_SECONDS', '300')),  # 300 seconds = 5 minutes
    'data_storage_file': 'price_history.json',
    'inventory_storage_file': 'inventory_history.json',
    # Enable/disable price change alerts (predictions still work)
    'enable_price_alerts': os.getenv('ENABLE_PRICE_ALERTS', 'false').lower() == 'true'  # Disabled by default
}

# Prediction Email Schedule (EST Timezone)
PREDICTION_SCHEDULE = {
    'times': os.getenv('PREDICTION_TIMES', '06:00,09:00,12:00,18:00').split(','),  # 6 AM, 9 AM, 12 PM, 6 PM EST
    'timezone': os.getenv('PREDICTION_TIMEZONE', 'US/Eastern'),  # EST/EDT
    'enabled': os.getenv('PREDICTION_SCHEDULE_ENABLED', 'true').lower() == 'true',
    # Time horizons included in predictions
    'time_horizons': ['daily', 'one_week', 'two_weeks', 'monthly']
}
