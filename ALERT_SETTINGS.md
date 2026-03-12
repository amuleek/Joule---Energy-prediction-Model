# Alert Settings Configuration

## Current Configuration

### ✅ ENABLED: Prediction Emails
- **Schedule**: Morning (8:00 AM) and Evening (8:00 PM)
- **Content**: AI predictions for tomorrow, one week, one month
- **Recipients**: 
  - amuleeksidhu96@gmail.com
  - rangi93@yahoo.com

### ❌ DISABLED: Price Change Alerts
- Price increase/decrease alerts are **turned off**
- No emails sent for 2% price changes
- System still monitors prices but doesn't send alerts

## What You'll Receive

### Daily Prediction Emails (2x per day)
- Morning email at 8:00 AM
- Evening email at 8:00 PM
- Includes:
  - Current prices
  - Tomorrow's predictions
  - One week predictions
  - One month predictions
  - News sentiment analysis

### What You WON'T Receive
- ❌ Price change alerts (when prices go up/down 2%)
- ❌ Market signal alerts
- ❌ Inventory change alerts

## Re-enable Price Alerts (If Needed)

To turn price change alerts back on:

**Option 1 - Edit config.py:**
```python
'enable_price_alerts': True  # Change to True
```

**Option 2 - Environment Variable:**
```powershell
$env:ENABLE_PRICE_ALERTS="true"
```

Then restart `main.py`

## Summary

- **Prediction Emails**: ✅ Active (2x daily)
- **Price Change Alerts**: ❌ Disabled
- **System Status**: Monitoring prices but only sending prediction emails
