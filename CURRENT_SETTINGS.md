# Current System Settings

## Email Configuration

### Recipients
- amuleeksidhu96@gmail.com
- rangi93@yahoo.com

## Alert Settings

### ✅ ENABLED: Prediction Emails
- **Schedule**: 
  - Morning: 8:00 AM daily
  - Evening: 8:00 PM daily
- **Content**: AI predictions (tomorrow, one week, one month)
- **Automatic**: Yes, sent automatically when scheduler runs

### ❌ DISABLED: Price Change Alerts
- Price increase/decrease alerts: **OFF**
- Market signal alerts: **OFF**
- Inventory change alerts: **OFF**

## What You'll Receive

### Daily Prediction Emails (2x per day)
✅ **Morning Email** (8:00 AM):
- Current prices
- Tomorrow's predictions
- One week predictions
- One month predictions
- News sentiment analysis

✅ **Evening Email** (8:00 PM):
- Same content as morning
- Updated predictions based on latest data

### What You WON'T Receive
❌ Price change alerts (2% threshold)
❌ Market signal alerts
❌ Real-time price change notifications

## Running the System

### Start Prediction Scheduler
```bash
python prediction_scheduler.py
```

This will:
- Send test email immediately
- Schedule morning predictions (8:00 AM)
- Schedule evening predictions (8:00 PM)
- Run continuously

### Send Test Email Now
```bash
python send_test_prediction.py
```

## Summary

**Current Mode**: Prediction-only emails
- ✅ Prediction emails: Active (2x daily)
- ❌ Price change alerts: Disabled
- ✅ System monitoring: Active (but not sending alerts)
