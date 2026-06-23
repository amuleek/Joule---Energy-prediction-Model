# Prediction Email Scheduler Status

## ⚠️ Important: Scheduler Must Be Running

The prediction emails are **only sent automatically** if the scheduler is running.

## Current Schedule Configuration

**Times (EST Timezone):**
- 6:00 AM EST
- 9:00 AM EST  
- 12:00 PM EST
- 6:00 PM EST

**Timezone:** US/Eastern (automatically adjusts for DST)

**Status:** Configured ✅, but needs to be **running** to send emails

## How to Start the Scheduler

### Option 1: Run in Terminal (Temporary)

```powershell
python prediction_scheduler.py
```

This will:
- Send a test email immediately
- Schedule emails at the 4 times above
- Run continuously until you press Ctrl+C

**Note:** This stops when you close the terminal.

### Option 2: Run in Background (Persistent)

```powershell
# Run in background (Windows)
Start-Process pythonw -ArgumentList "prediction_scheduler.py" -WindowStyle Hidden
```

### Option 3: Use Windows Task Scheduler (Recommended for 24/7)

1. Open **Task Scheduler** (search in Windows)
2. Create **Basic Task**
3. Name: "Energy AI Prediction Emails"
4. Trigger: **Daily** at 6:00 AM, 9:00 AM, 12:00 PM, 6:00 PM
5. Action: **Start a program**
6. Program: `python`
7. Arguments: `C:\energy ai-agent\prediction_engine.py`
8. Start in: `C:\energy ai-agent`

### Option 4: Docker (If using Docker)

The Docker container runs the scheduler automatically:

```powershell
docker-compose up -d
```

## Check if Scheduler is Running

### Check Python Processes:

```powershell
Get-Process python -ErrorAction SilentlyContinue
```

### Check if Emails Were Sent:

Look for log messages or check your email inbox for:
- Timestamps matching scheduled times
- Subject: "🔮 Energy Market AI Predictions"

## Manual Test (Send Email Now)

To test if emails work without waiting for schedule:

```powershell
python send_test_prediction.py
```

## Troubleshooting

### Emails Not Being Sent?

1. **Is scheduler running?**
   - Check if `prediction_scheduler.py` is running
   - Check Python processes

2. **Is email configured?**
   - Check `config.py` for email settings
   - Verify Gmail App Password is correct

3. **Check logs:**
   - Look for error messages in terminal
   - Check if predictions are being generated

4. **Timezone issues:**
   - Scheduler uses EST/EDT
   - Make sure your system timezone is correct

## Summary

✅ **Schedule Configured**: 4 times daily (6 AM, 9 AM, 12 PM, 6 PM EST)
⚠️ **Action Required**: Start `prediction_scheduler.py` to enable automatic emails
📧 **Recipients**: amuleeksidhu96@gmail.com, rangi93@yahoo.com
