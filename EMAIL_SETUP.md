# Email Alert Setup Guide

## Current Status

✅ **Email Address**: `amuleeksidhu96@gmail.com` (configured)  
✅ **Recipient**: `amuleeksidhu96@gmail.com` (configured)  
❌ **Password**: NOT SET (needs Gmail App Password)

## Quick Setup (3 Steps)

### Step 1: Get Gmail App Password

1. Go to: https://myaccount.google.com/apppasswords
2. If prompted, enable 2-Step Verification first
3. Select "Mail" and your device
4. Click "Generate"
5. Copy the 16-character password (looks like: `abcd efgh ijkl mnop`)

### Step 2: Set the Password

**Option A - Environment Variable (Recommended):**

**PowerShell:**
```powershell
$env:SENDER_PASSWORD="your-16-char-app-password"
```

**CMD:**
```cmd
set SENDER_PASSWORD=your-16-char-app-password
```

**Option B - Edit config.py (Less Secure):**

Edit line 12 in `config.py`:
```python
'sender_password': 'your-16-char-app-password',
```

### Step 3: Test Email

Run the test script:
```bash
python test_email.py
```

If successful, you'll see:
```
✅ EMAIL CONFIGURED
✅ Test email sent successfully!
Check your inbox: amuleeksidhu96@gmail.com
```

## Which Script Sends Emails?

### ✅ `main.py` - Sends Email Alerts
- Full-featured agent
- Sends HTML email alerts automatically
- Includes price and inventory data
- Generates market signals

### ❌ `energy_agent.py` - Console Alerts Only
- Simple monitoring agent
- Shows alerts in console only
- Does NOT send emails
- Good for testing

## Running with Email Alerts

Once configured, run:
```bash
python main.py
```

The system will:
1. Monitor prices every 5 minutes
2. Detect significant changes (2% threshold)
3. **Automatically send email alerts** to your Gmail
4. Include detailed market data in HTML format

## Troubleshooting

**"Email not configured" message:**
- Make sure you set the `SENDER_PASSWORD` environment variable
- Or edit `config.py` directly

**"Failed to send email" error:**
- Verify your App Password is correct (16 characters, no spaces)
- Check internet connection
- Make sure 2-Step Verification is enabled on your Google account

**No emails received:**
- Check spam/junk folder
- Verify recipient email in config.py
- Check that alerts are actually triggered (price change > 2%)

## Security Note

⚠️ **Never commit your App Password to Git!**

If you edit `config.py` directly, make sure it's in `.gitignore` or use environment variables instead.
