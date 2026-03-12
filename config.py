"""
Configuration file for Energy AI Agent
"""
import os
from typing import Dict

# Email Configuration
EMAIL_CONFIG = {
    'smtp_server': os.getenv('SMTP_SERVER', 'smtp.gmail.com'),
    'smtp_port': int(os.getenv('SMTP_PORT', '587')),
    'sender_email': os.getenv('SENDER_EMAIL', 'amuleeksidhu96@gmail.com'),
    'sender_password': os.getenv('SENDER_PASSWORD', 'aznj dfcj nrxw mluq'),
    'recipient_emails': os.getenv('RECIPIENT_EMAILS', 'amuleeksidhu96@gmail.com,rangi93@yahoo.com').split(',') if os.getenv('RECIPIENT_EMAILS', 'amuleeksidhu96@gmail.com,rangi93@yahoo.com') else ['amuleeksidhu96@gmail.com', 'rangi93@yahoo.com']
}

# API Configuration
API_CONFIG = {
    # Alpha Vantage API (free tier available)
    'alpha_vantage_api_key': os.getenv('ALPHA_VANTAGE_API_KEY', 'LS254MALFOC29HFY'),
    # EIA API for inventory data
    'eia_api_key': os.getenv('EIA_API_KEY', 'uBrIecJrka8gtd3bIDLkubzhL7Hc8G2NdIAnBYCj'),
    # NewsAPI for news sentiment analysis (optional - get free key at newsapi.org)
    'news_api_key': os.getenv('NEWS_API_KEY', '8886b39275f645a79cf2fb3d66d6d7b1'),
    # World News API (alternative news source)
    'world_news_api_key': os.getenv('WORLD_NEWS_API_KEY', 'e1a4d874e47646dfb3a8afe4691ba540'),
    # Alternative: Yahoo Finance (no API key needed) - used as fallback
    'use_yahoo_finance': os.getenv('USE_YAHOO_FINANCE', 'true').lower() == 'true',
    # Primary data source: 'alpha_vantage' or 'yahoo_finance'
    # Note: Alpha Vantage may not support futures symbols, so Yahoo Finance is used as fallback
    'primary_source': os.getenv('PRIMARY_SOURCE', 'yahoo_finance')
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
    }
}

# Alert Configuration
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
