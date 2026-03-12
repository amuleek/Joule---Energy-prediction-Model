# Updated Prediction Schedule

## New Schedule (EST Timezone)

Prediction emails are now sent **5 times daily** in Eastern Time:

1. **6:00 AM EST** - Morning Report
2. **9:00 AM EST** - Mid-Morning Update
3. **12:00 PM EST** - Noon Update
4. **6:00 PM EST** - Evening Report

## Prediction Report Contents

Each email includes predictions for **4 time horizons**:

1. **Daily (Tomorrow)** - Next day price prediction
2. **One Week** - 7-day forecast
3. **Two Weeks** - 14-day forecast
4. **Monthly** - 30-day forecast

## Email Format

Each prediction email shows:
- Current price for each product (RBOB Gasoline, ULSD Diesel, Crude Oil)
- Predicted price for each time horizon
- Percentage change from current price
- Direction (UP/DOWN)
- Confidence ranges

## Timezone

All times are in **EST (Eastern Standard Time)** / **EDT (Eastern Daylight Time)**
- Automatically adjusts for daylight saving time
- Uses US/Eastern timezone

## Running the Scheduler

```bash
python prediction_scheduler.py
```

This will:
1. Send a test email immediately
2. Schedule 4 daily emails at the specified times
3. Run continuously in the background

## Customize Schedule

Edit `prediction_scheduler.py`:
```python
scheduler.start_scheduler(
    times=["06:00", "09:00", "12:00", "18:00"]  # Customize times
)
```

Or set environment variable:
```powershell
$env:PREDICTION_TIMES="06:00,09:00,12:00,18:00"
```

## Recipients

Emails sent to:
- amuleeksidhu96@gmail.com
- rangi93@yahoo.com

## Summary

✅ **Schedule**: 5 times daily (6 AM, 9 AM, 12 PM, 6 PM EST)
✅ **Time Horizons**: Daily, One Week, Two Weeks, Monthly
✅ **Timezone**: EST/EDT (automatic DST adjustment)
✅ **Status**: Ready to run
