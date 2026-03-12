# Quick Start: AI Predictions

## 🚀 Get Started in 3 Steps

### Step 1: Install Dependencies

```bash
pip install prophet textblob scikit-learn
```

### Step 2: Collect Initial Data

```bash
# Collect some historical data (run multiple times to build history)
python scripts/fetch_prices.py
python scripts/fetch_inventory.py
python scripts/preprocessing.py
```

### Step 3: Generate Predictions

```bash
python prediction_engine.py
```

This will:
- ✅ Collect latest data
- ✅ Generate AI predictions
- ✅ Save to `data/predictions.json`

## View Predictions

Predictions automatically appear in:
- **Console**: When running `python main.py`
- **Email Alerts**: Included in email notifications

## What Gets Predicted?

**Products:**
- RBOB Gasoline (NY Harbor)
- ULSD Diesel (NY Harbor)
- Crude Oil (WTI)

**Time Horizons:**
- **Next Day**: Tomorrow's price forecast
- **Next Week**: 7-day forecast
- **Biweekly**: 14-day forecast

**Output:**
- Price prediction
- % change from current
- Direction (↑ increase / ↓ decrease)
- Confidence range

## Example Output

```
🤖 AI PRICE PREDICTIONS:

  RBOB Gasoline:
    Current: $2.8706
    Next Day: ↑ 0.25%
    Next Week: ↑ 1.50%
    Biweekly: ↑ 2.30%

  ULSD Diesel:
    Current: $3.6379
    Next Day: ↓ 0.15%
    Next Week: ↑ 0.80%
    Biweekly: ↑ 1.20%
```

## Automation

Run predictions daily:

```bash
# Add to Windows Task Scheduler or cron
python prediction_engine.py
```

Or integrate into main.py to run automatically!

## Need Help?

See `PREDICTION_SETUP.md` for detailed documentation.
