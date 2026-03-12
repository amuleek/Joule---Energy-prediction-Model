# Email Recipients Configuration

## Current Setup

### Sender Email
- **Email**: `amuleeksidhu96@gmail.com`
- **Password**: Configured (Gmail App Password)

### Recipients (Prediction & Alert Emails)
1. **amuleeksidhu96@gmail.com** ✅
2. **rangi93@yahoo.com** ✅ (NEW)

## What Gets Emailed

### 1. Price Change Alerts
- Sent when prices increase/decrease by > 2%
- Includes: Current price, change amount, market data
- **Recipients**: Both emails

### 2. AI Predictions
- Sent when predictions are generated
- Includes: Tomorrow, One Week, One Month forecasts
- **Recipients**: Both emails

### 3. Market Signals
- Sent when price-inventory correlations detected
- Includes: Strong demand/weak demand signals
- **Recipients**: Both emails

## How to Test

```bash
# Test email configuration
python test_email.py

# Test prediction email
python test_prediction_email.py

# Generate and send predictions
python prediction_engine.py
```

## Automatic Email Sending

When you run:
- `python main.py` - Sends alerts on price changes
- `python prediction_engine.py` - Sends prediction emails automatically

## Update Recipients

To add/remove recipients, edit `config.py` line 13:

```python
'recipient_emails': os.getenv('RECIPIENT_EMAILS', 'email1@gmail.com,email2@yahoo.com').split(',')
```

Or set environment variable:
```powershell
$env:RECIPIENT_EMAILS="email1@gmail.com,email2@yahoo.com,email3@outlook.com"
```

## Status

✅ **Both emails configured and receiving:**
- amuleeksidhu96@gmail.com
- rangi93@yahoo.com

✅ **Test email sent successfully!**
