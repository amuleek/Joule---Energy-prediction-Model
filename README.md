# Energy AI Agent

An automated monitoring and alerting system for energy market prices and inventories. Tracks Crude Oil, RBOB Gasoline, and Ultra-Low Sulfur Diesel prices, plus inventory data from EIA.

## Features

- **Real-time Price Monitoring**: Tracks Crude Oil (CL=F), RBOB Gasoline (RB=F), and Diesel (HO=F) prices
- **Inventory Tracking**: Monitors gasoline and diesel inventory levels from EIA
- **Intelligent Analysis**: Detects significant price and inventory changes based on configurable thresholds
- **Market Signals**: Generates trading signals based on price-inventory correlations (e.g., Price ↑ + Inventory ↓ = Strong Demand)
- **Email Alerts**: Sends detailed HTML email notifications when prices/inventories change significantly
- **Automated Scheduling**: Runs continuously every 5 minutes (configurable)
- **Price History**: Maintains historical price and inventory data for trend analysis
- **Multiple Data Sources**: Uses Alpha Vantage API (with Yahoo Finance fallback) and EIA API

## Installation

1. Install required packages:
```bash
pip install -r requirements.txt
```

## Configuration

### API Keys

The system is pre-configured with an Alpha Vantage API key. For EIA inventory data, register at [EIA Open Data](https://www.eia.gov/opendata/) and set:

```bash
export EIA_API_KEY="your-eia-api-key"
```

### Email Setup

Set the following environment variables or edit `config.py`:

```bash
# For Gmail
export SENDER_EMAIL="your-email@gmail.com"
export SENDER_PASSWORD="your-app-password"  # Use App Password, not regular password
export RECIPIENT_EMails="recipient1@email.com,recipient2@email.com"
export SMTP_SERVER="smtp.gmail.com"
export SMTP_PORT="587"
```

**Note for Gmail**: You'll need to use an [App Password](https://support.google.com/accounts/answer/185833) instead of your regular password.

### Alert Configuration

```bash
export PRICE_CHANGE_THRESHOLD="2.0"           # Alert on 2% price change (default)
export INVENTORY_CHANGE_THRESHOLD="2.0"       # Alert on 2% inventory change
export CHECK_INTERVAL_MINUTES="5"              # Check every 5 minutes
export CHECK_INTERVAL_SECONDS="300"            # 300 seconds = 5 minutes
```

**Alert Logic:**
The system compares current prices with previous prices and triggers alerts when:
- Price change exceeds the threshold percentage (default: 2%)
- First run (establishes baseline)
- Inventory changes significantly (if EIA API configured)

## Usage

### Option 1: Simple Alert Agent (Recommended for Beginners)

Run the simple monitoring agent with basic alert logic:

```bash
python energy_agent.py
```

This agent:
- Monitors Crude Oil, RBOB Gasoline, and Diesel prices
- Checks every 5 minutes (300 seconds)
- Alerts when price changes exceed 2% threshold
- Displays alerts in console: `🚨 ALERT: Oil price jumped 2.1%`
- Runs continuously until stopped (Ctrl+C)

**Example Output:**
```
[2024-01-15 14:30:00] Checking prices...
Current Crude Oil Price: $93.17
Current RBOB Gasoline Price: $2.86
Current Diesel Price: $3.64

[2024-01-15 14:35:00] Checking prices...
Current Crude Oil Price: $95.12
🚨 ALERT: CRUDE_OIL price jumped ↑ 2.09%
   Previous: $93.17 → Current: $95.12
```

### Option 2: Full-Featured Agent (Advanced)

Run the comprehensive monitoring system with email alerts:

```bash
python main.py
```

This agent will:
1. Collect current prices for Crude Oil, RBOB Gasoline, and Diesel
2. Collect inventory data from EIA (if configured)
3. Analyze price and inventory changes compared to previous values
4. Generate market signals based on price-inventory correlations
5. Send email alerts if significant changes are detected
6. Continue monitoring at the configured interval (default: every 5 minutes)

### Test Individual Components

**Test Market Data Fetching:**
```bash
python market_data.py
```

**Test Data Collection:**
```bash
python data_collector.py
```

**Test Price Analysis:**
```bash
python analyzer.py
```

**Test Email Alerts:**
```bash
python alerts.py
```

## Project Structure

```
energy-ai-agent/
│
├── energy_agent.py     # Simple alert monitoring agent (basic version)
├── market_data.py      # Simple script to fetch prices from Alpha Vantage
├── data_collector.py   # Fetches price data from Alpha Vantage/Yahoo Finance and EIA
├── analyzer.py         # Analyzes price/inventory changes and generates market signals
├── alerts.py           # Sends email notifications with market data
├── config.py           # Configuration settings (API keys, thresholds, etc.)
├── main.py             # Full-featured agent with email alerts and market signals
├── requirements.txt    # Python dependencies
└── README.md          # This file
```

## Products Tracked

### Prices (from Alpha Vantage/Yahoo Finance)
- **Crude Oil (CL=F)**: West Texas Intermediate (WTI) crude oil futures
- **RBOB Gasoline (RB=F)**: Reformulated Blendstock for Oxygenate Blending
- **Ultra-Low Sulfur Diesel (HO=F)**: Heating Oil futures (proxy for ULSD)

### Inventories (from EIA)
- **Gasoline Inventories**: Weekly gasoline stock levels
- **Diesel/Distillate Inventories**: Weekly distillate stock levels

## Market Signals

The system generates intelligent market signals based on price-inventory correlations:

- **Strong Demand Signal**: Price ↑ + Inventory ↓ = High demand, potential price increase
- **Weak Demand Signal**: Price ↓ + Inventory ↑ = Low demand, potential price decrease

## Data Sources

1. **Alpha Vantage API**: Primary source for price data (API key: LS254MALFOC29HFY)
   - Free tier: 5 calls per minute
   - Automatically falls back to Yahoo Finance if Alpha Vantage fails

2. **Yahoo Finance**: Fallback source for price data (no API key required)
   - More reliable for futures symbols
   - Used automatically when Alpha Vantage doesn't support a symbol

3. **EIA API**: U.S. Energy Information Administration (requires free API key)
   - Weekly inventory data
   - Register at: https://www.eia.gov/opendata/

## Rate Limits

- **Alpha Vantage Free Tier**: 5 API calls per minute
- The system includes automatic rate limiting and fallback mechanisms

## Example Output

### Simple Agent (`energy_agent.py`)
```
[2024-01-15 14:30:00] Checking prices...
Current Crude Oil Price: $93.17
  Initial price recorded: $93.17
Current RBOB Gasoline Price: $2.86
  Initial price recorded: $2.86
Current Diesel Price: $3.64
  Initial price recorded: $3.64

[2024-01-15 14:35:00] Checking prices...
Current Crude Oil Price: $95.12
🚨 ALERT: CRUDE_OIL price jumped ↑ 2.09%
   Previous: $93.17 → Current: $95.12
```

### Full Agent (`main.py`)
```
Energy Market Check - 2024-01-15 14:30:00
============================================================

📊 Collecting market data...
🔍 Analyzing price changes...
📦 Analyzing inventory changes...

💰 PRICE DATA:

  Crude Oil:
    Current: $93.5600
    Change: ↑ +0.25% (INCREASE)
    Alert: YES

  RBOB Gasoline:
    Current: $2.8642
    Change: ↓ -0.15% (DECREASE)
    Alert: NO

🚨 MARKET SIGNALS:
  [HIGH] RBOB Gasoline: Price ↑ + Inventory ↓ = Strong demand signal
```

## Running 24/7

To run the agent continuously:

**Windows:**
```bash
# Run in background
pythonw energy_agent.py

# Or use Task Scheduler to run at startup
```

**Linux/Mac:**
```bash
# Run in background with nohup
nohup python energy_agent.py > energy_agent.log 2>&1 &

# Or use cron
# Add to crontab: */5 * * * * cd /path/to/energy-ai-agent && python energy_agent.py
```

## Next Steps (Future Enhancements)

After basic alerts work, you can enhance the system to monitor:
- **Refinery Outages**: Track refinery capacity and outages
- **OPEC News**: Monitor OPEC announcements and decisions
- **Weather Events**: Track hurricanes and weather impacts on Gulf Coast refineries
- **Economic Indicators**: Monitor GDP, employment data affecting demand
- **Trading Signals**: Generate buy/sell signals based on multiple factors

## License

This project is provided as-is for monitoring energy market prices.
