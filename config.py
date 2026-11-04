"""
Configuration file for Energy AI Agent
"""
import os
from typing import Dict

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Email Configuration
_raw_recipients = [
    e.strip()
    for e in os.getenv(
        'RECIPIENT_EMAILS',
        'taransandhu@gillenergy.com,bikramgill@gillenergy.com,ravigill@gillenergy.com,kashmirgill@gillenergy.com',
    ).split(',')
    if e.strip()
]
# Preserve order, drop duplicates (duplicate To: caused double inbox copies)
_seen_recipients = set()
_recipient_emails = []
for _e in _raw_recipients:
    _key = _e.lower()
    if _key in _seen_recipients:
        continue
    _seen_recipients.add(_key)
    _recipient_emails.append(_e)

EMAIL_CONFIG = {
    'smtp_server': os.getenv('SMTP_SERVER', 'smtp.gmail.com'),
    'smtp_port': int(os.getenv('SMTP_PORT', '587')),
    'sender_email': os.getenv('SENDER_EMAIL', 'amuleeksidhu96@gmail.com'),
    'sender_password': os.getenv('SENDER_PASSWORD', '').replace(' ', ''),
    'recipient_emails': _recipient_emails,
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
# Day-1 raised so strong geo/tape sessions can print ~3–5% instead of always ~0.5%
PRODUCT_HORIZON_CAPS = {
    'RBOB_Gasoline': {'day_1': 0.045, 'day_4': 0.06, 'day_7': 0.08},
    'ULSD_Diesel': {'day_1': 0.05, 'day_4': 0.07, 'day_7': 0.09},
    'Crude_Oil': {'day_1': 0.055, 'day_4': 0.08, 'day_7': 0.10},
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

# Weekend day-1: wait for Asia/Globex tape before emailing Monday call
WEEKEND_DAY1_CONFIG = {
    'asia_ready_hour_et': int(os.getenv('ASIA_TAPE_READY_HOUR_ET', '20')),
    'asia_ready_minute_et': int(os.getenv('ASIA_TAPE_READY_MINUTE_ET', '15')),
    'defer_until_asia': os.getenv('DEFER_WEEKEND_DAY1_UNTIL_ASIA', 'true').lower() == 'true',
    'tape_gap_ready_pct': float(os.getenv('ASIA_TAPE_GAP_READY_PCT', '1.0')),
    # Skip repeat emails when day-1 call unchanged (direction + price move)
    'dedupe_emails': os.getenv('DEDUPE_DAY1_EMAILS', 'true').lower() == 'true',
    'dedupe_price_pct': float(os.getenv('DEDUPE_DAY1_PRICE_PCT', '0.20')),
    # Block a second email within N minutes (scheduler + manual run overlap)
    'email_cooldown_minutes': float(os.getenv('DAY1_EMAIL_COOLDOWN_MINUTES', '45')),
}

# Scheduler: run pipeline on startup without emailing (avoids duplicate on restart)
SCHEDULER_CONFIG = {
    'send_on_startup': os.getenv('SCHEDULER_SEND_ON_STARTUP', 'false').lower() == 'true',
}

# NYMEX contract month: auto-roll RBOB/ULSD to *2 in last days of month (Oct vs Sep)
NYMEX_CONTRACT_CONFIG = {
    'roll_days_before_month_end': int(os.getenv('NYMEX_ROLL_DAYS_BEFORE_MONTH_END', '5')),
    'auto_roll_rbob': os.getenv('NYMEX_AUTO_ROLL_RBOB', 'true').lower() == 'true',
    'auto_roll_ulsd': os.getenv('NYMEX_AUTO_ROLL_ULSD', 'true').lower() == 'true',
    'auto_roll_crude': os.getenv('NYMEX_AUTO_ROLL_CRUDE', 'false').lower() == 'true',
    'force_lead_month': os.getenv('NYMEX_FORCE_LEAD_MONTH', 'false').lower() == 'true',
}

# Intraday: correct morning day-1 when live tape gaps opposite (e.g. +2% vs DOWN call)
INTRADAY_DAY1_CONFIG = {
    'enabled': os.getenv('INTRADAY_CORRECTION_ENABLED', 'true').lower() == 'true',
    'tape_flip_pct': float(os.getenv('INTRADAY_TAPE_FLIP_PCT', '2.0')),
    'window_start_hour_et': int(os.getenv('INTRADAY_WINDOW_START_HOUR_ET', '8')),
    'window_end_hour_et': int(os.getenv('INTRADAY_WINDOW_END_HOUR_ET', '14')),
    'window_end_minute_et': int(os.getenv('INTRADAY_WINDOW_END_MINUTE_ET', '30')),
    'check_times': [
        t.strip()
        for t in os.getenv('INTRADAY_CHECK_TIMES', '10:30,13:30').split(',')
        if t.strip()
    ],
}
