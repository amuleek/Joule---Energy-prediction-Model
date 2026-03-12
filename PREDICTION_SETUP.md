# AI Prediction System Setup

## Overview

The AI prediction system forecasts price movements for:
- **RBOB Gasoline** (NY Harbor)
- **ULSD Diesel** (NY Harbor)  
- **Crude Oil** (WTI)

**Time Horizons:**
- Next Day
- Next Week
- Biweekly (2 weeks)

## Installation

Install additional dependencies:

```bash
pip install prophet textblob scikit-learn
```

Or install all requirements:

```bash
pip install -r requirements.txt
```

## Setup Steps

### 1. Initial Data Collection

Run the data collection scripts to build historical data:

```bash
# Collect price data
python scripts/fetch_prices.py

# Collect news data (optional - requires NewsAPI key)
python scripts/fetch_news.py

# Collect inventory data
python scripts/fetch_inventory.py

# Preprocess and merge data
python scripts/preprocessing.py
```

### 2. Generate Predictions

Run the full prediction pipeline:

```bash
python prediction_engine.py
```

This will:
1. Collect latest data
2. Preprocess and merge
3. Generate predictions
4. Save to `data/predictions.json`

### 3. View Predictions

```bash
python predictor.py
```

## Integration with Main System

The predictions are automatically included in:
- Console output when running `main.py`
- Email alerts (if configured)

## Data Sources

### Prices
- **EIA API**: Spot prices for RBOB and ULSD
- **Yahoo Finance**: Crude Oil futures (fallback)

### News (Optional)
- **NewsAPI**: Energy market news (requires free API key)
- Set environment variable: `NEWS_API_KEY=your-key`

### Inventory
- **EIA API**: Weekly inventory reports (already configured)

## Prediction Models

### Primary: Facebook Prophet
- Time series forecasting
- Handles seasonality and trends
- Includes sentiment as regressor

### Fallback: Linear Regression
- Simple trend-based prediction
- Used if Prophet unavailable or insufficient data

## Output Format

Predictions include:
- **Current Price**: Latest market price
- **Next Day Prediction**: Price and % change
- **Next Week Prediction**: Price and % change  
- **Biweekly Prediction**: Price and % change
- **Confidence Range**: Upper and lower bounds
- **Direction**: ↑ (increase) or ↓ (decrease)

## Automation

To run predictions daily, add to your scheduler:

```python
# In main.py or separate scheduler
import schedule
from prediction_engine import PredictionEngine

def run_predictions():
    engine = PredictionEngine()
    engine.run_full_pipeline()

# Run predictions daily at 6 AM
schedule.every().day.at("06:00").do(run_predictions)
```

## Troubleshooting

**"No predictions available"**
- Ensure data files exist in `data/` folder
- Run `prediction_engine.py` to collect data first
- Need at least 7 days of historical data

**"Prophet not installed"**
- Install: `pip install prophet`
- System will fallback to linear regression

**"No news data"**
- News is optional but improves predictions
- Get free API key from newsapi.org
- Set `NEWS_API_KEY` environment variable

## Files Structure

```
energy-ai-agent/
├── data/
│   ├── prices.csv          # Historical prices
│   ├── news.csv            # News articles
│   ├── inventory.csv        # Inventory data
│   ├── news_processed.csv   # Sentiment scores
│   ├── final_data.csv       # Merged dataset
│   └── predictions.json    # Latest predictions
├── scripts/
│   ├── fetch_prices.py      # Price data collection
│   ├── fetch_news.py        # News collection
│   ├── fetch_inventory.py   # Inventory collection
│   └── preprocessing.py    # Data preprocessing
├── predictor.py             # Prediction model
└── prediction_engine.py     # Main orchestrator
```

## Next Steps

1. **Collect Historical Data**: Run data collection scripts daily
2. **Generate Predictions**: Run `prediction_engine.py` 
3. **Monitor**: Predictions appear in main system automatically
4. **Refine**: Adjust models based on prediction accuracy
