# Email Recipients Configuration

## Current Setup

### Sender Email
- **Email**: `amuleeksidhu96@gmail.com`
- **Password**: Configured (Gmail App Password)

### Recipients (Prediction & Alert Emails)
1. **taransandhu@gillenergy.com**
2. **bikramgill@gillenergy.com**
3. **ravigill@gillenergy.com**
4. **kashmirgill@gillenergy.com**

## What Gets Emailed

### 1. Price Change Alerts
- Sent when prices increase/decrease by > 2%
- Includes: Current price, change amount, market data
- **Recipients**: All configured emails above

### 2. AI Predictions
- Sent when predictions are generated
- Includes: Tomorrow, One Week, One Month forecasts
- **Recipients**: All configured emails above

### 3. Market Signals
- Sent when price-inventory correlations detected
- Includes: Strong demand/weak demand signals
- **Recipients**: All configured emails above

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

To add/remove recipients, edit `config.py` or set environment variable:

```powershell
$env:RECIPIENT_EMAILS="email1@gillenergy.com,email2@gillenergy.com"
```

Or in `.env`:

```
RECIPIENT_EMAILS=email1@gillenergy.com,email2@gillenergy.com
```

## Status

Active recipients:
- taransandhu@gillenergy.com
- bikramgill@gillenergy.com
- ravigill@gillenergy.com
- kashmirgill@gillenergy.com

Removed:
- amuleeksidhu96@gmail.com
- rangi93@yahoo.com
