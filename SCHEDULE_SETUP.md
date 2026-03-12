# Prediction Email Schedule Setup

## Automatic Email Schedule

The system is configured to send prediction emails **twice daily**:

### Schedule Times

- **Morning**: 8:00 AM (08:00)
- **Evening**: 8:00 PM (20:00)

### What Gets Sent

Each email includes:
- Current prices (RBOB Gasoline, ULSD Diesel, Crude Oil)
- Tomorrow's predictions
- One week predictions
- One month predictions
- Confidence ranges
- News sentiment analysis

### Recipients

Emails are sent to:
- amuleeksidhu96@gmail.com
- rangi93@yahoo.com

## How to Run

### Option 1: Start Scheduler (Recommended)

```bash
python prediction_scheduler.py
```

This will:
1. Send a test email immediately
2. Schedule morning predictions (8:00 AM daily)
3. Schedule evening predictions (8:00 PM daily)
4. Run continuously

### Option 2: Custom Times

Edit `prediction_scheduler.py` or set environment variables:

```powershell
$env:PREDICTION_MORNING_TIME="07:00"
$env:PREDICTION_EVENING_TIME="19:00"
python prediction_scheduler.py
```

### Option 3: Manual Test

Send test email now:
```bash
python test_prediction_email.py
```

## Running 24/7

### Windows

**Option A - Task Scheduler:**
1. Open Task Scheduler
2. Create Basic Task
3. Trigger: Daily at 8:00 AM and 8:00 PM
4. Action: Start program
5. Program: `pythonw`
6. Arguments: `C:\energy ai-agent\prediction_engine.py`

**Option B - Background Service:**
```powershell
# Run in background
Start-Process pythonw -ArgumentList "prediction_scheduler.py" -WindowStyle Hidden
```

### Linux/Mac

**Using cron:**
```bash
# Edit crontab
crontab -e

# Add these lines:
0 8 * * * cd /path/to/energy-ai-agent && python prediction_engine.py
0 20 * * * cd /path/to/energy-ai-agent && python prediction_engine.py
```

## Customize Schedule

Edit `config.py`:
```python
PREDICTION_SCHEDULE = {
    'morning_time': '07:30',  # 7:30 AM
    'evening_time': '21:00',  # 9:00 PM
}
```

Or edit `prediction_scheduler.py`:
```python
scheduler.start_scheduler(
    morning_time="07:30",
    evening_time="21:00"
)
```

## Test Email (Send Now)

Run this to send a test email immediately:
```bash
python test_prediction_email.py
```

Or:
```bash
python prediction_engine.py
```

## Status

✅ **Schedule configured**: Morning 8:00 AM, Evening 8:00 PM
✅ **Recipients**: 2 emails configured
✅ **Test email**: Ready to send
