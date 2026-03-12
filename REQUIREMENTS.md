# Project Requirements & Setup Guide

## System Requirements

### Minimum System Specs
- **OS**: Windows 10/11, Linux, or macOS
- **Python**: 3.8 or higher
- **RAM**: 2GB minimum (4GB recommended)
- **Storage**: 500MB free space
- **Internet**: Stable broadband connection (required for API calls)

### Python Dependencies
All packages are listed in `requirements.txt`. Install with:
```bash
pip install -r requirements.txt
```

## Required API Keys & Services

### 1. **Alpha Vantage API** (Price Data)
- **Key**: `LS254MALFOC29HFY` (already configured)
- **Purpose**: Fetch RBOB Gasoline, Diesel, Crude Oil prices
- **Free Tier**: 5 API calls/minute, 500 calls/day
- **Status**: ✅ Configured

### 2. **EIA API** (Inventory Data)
- **Key**: `uBrIecJrka8gtd3bIDLkubzhL7Hc8G2NdIAnBYCj` (already configured)
- **Purpose**: Weekly fuel inventory reports
- **Free Tier**: Unlimited requests
- **Status**: ✅ Configured

### 3. **NewsAPI** (World News)
- **Key**: `8886b39275f645a79cf2fb3d66d6d7b1` (already configured)
- **Purpose**: Energy market news for sentiment analysis
- **Free Tier**: 100 requests/day
- **Status**: ✅ Configured

### 4. **World News API** (Backup News Source)
- **Key**: `e1a4d874e47646dfb3a8afe4691ba540` (already configured)
- **Purpose**: Backup news source if NewsAPI fails
- **Status**: ✅ Configured

### 5. **Gmail App Password** (Email Alerts)
- **Email**: `amuleeksidhu96@gmail.com`
- **Password**: `aznj dfcj nrxw mluq` (already configured)
- **Purpose**: Send prediction emails
- **Setup**: Requires 2-factor authentication enabled
- **Status**: ✅ Configured

## Installation Steps

### Step 1: Install Python
Download from: https://www.python.org/downloads/
- Check "Add Python to PATH" during installation

### Step 2: Install Dependencies
```bash
cd "C:\energy ai-agent"
pip install -r requirements.txt
```

### Step 3: Verify Installation
```bash
python -c "import pandas, prophet, schedule, requests; print('All packages installed!')"
```

### Step 4: Test Email Configuration
```bash
python test_email.py
```

### Step 5: Run Test Prediction
```bash
python send_test_prediction.py
```

## Running the Project

### Option 1: Prediction Scheduler (Recommended)
```bash
python prediction_scheduler.py
```
- Sends emails at 8:00 AM and 8:00 PM daily
- Runs continuously in background

### Option 2: Manual Prediction
```bash
python prediction_engine.py
```
- Generates predictions and sends email once
- Good for testing

### Option 3: Full Monitoring (Price Alerts + Predictions)
```bash
python main.py
```
- Monitors prices every 5 minutes
- Currently: Price alerts DISABLED, Predictions ENABLED

## Disadvantages of Running Locally

### 1. **Computer Must Stay On 24/7**
- ❌ Your computer must be running continuously
- ❌ Can't shut down or sleep
- ❌ Power consumption (~50-200W depending on computer)
- ❌ Electricity costs (~$5-20/month)

### 2. **Internet Dependency**
- ❌ Requires stable internet connection
- ❌ If internet goes down, predictions stop
- ❌ No offline functionality

### 3. **System Maintenance**
- ❌ Windows updates can interrupt service
- ❌ System crashes/restarts stop the scheduler
- ❌ Need to manually restart after power outages
- ❌ Background processes can be killed

### 4. **Resource Usage**
- ❌ Uses CPU/RAM while running
- ❌ May slow down your computer
- ❌ Python process runs in background

### 5. **Security Concerns**
- ❌ API keys stored locally (in config.py)
- ❌ Email password in plain text
- ❌ Risk if computer is compromised

### 6. **Limited Scalability**
- ❌ Can't run multiple instances easily
- ❌ Hard to monitor remotely
- ❌ No automatic failover

### 7. **No Built-in Monitoring**
- ❌ No dashboard to see if it's running
- ❌ No alerts if service stops
- ❌ Must manually check logs

## Better Alternatives (Cloud Deployment)

### Option 1: **AWS EC2 / Lightsail**
- ✅ Runs 24/7 without your computer
- ✅ $5-10/month
- ✅ Automatic restarts
- ✅ Can monitor remotely
- ❌ Requires AWS account setup

### Option 2: **Google Cloud Run / Functions**
- ✅ Pay per use (very cheap)
- ✅ Automatic scaling
- ✅ No server management
- ❌ More complex setup

### Option 3: **PythonAnywhere / Heroku**
- ✅ Free tier available
- ✅ Easy deployment
- ✅ Built-in scheduler
- ❌ Limited free resources

### Option 4: **Raspberry Pi** (Local but Dedicated)
- ✅ Low power (~5W)
- ✅ Can run 24/7 cheaply
- ✅ Dedicated device
- ❌ Still requires internet
- ❌ Initial cost (~$50)

## Recommendations

### For Testing/Development
✅ **Use Local Machine** - Perfect for testing and development

### For Production (24/7 Operation)
✅ **Use Cloud Service** - AWS, Google Cloud, or PythonAnywhere
- More reliable
- No need to keep computer on
- Better monitoring
- Automatic restarts

### Hybrid Approach
✅ **Develop locally, deploy to cloud**
- Test on your machine
- Deploy to cloud for production

## Cost Comparison

| Option | Monthly Cost | Reliability | Setup Difficulty |
|--------|-------------|-------------|------------------|
| Local Machine | $5-20 (electricity) | ⭐⭐ | ⭐ Easy |
| AWS EC2 | $5-10 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ Medium |
| PythonAnywhere | $0-5 | ⭐⭐⭐⭐ | ⭐⭐ Easy |
| Raspberry Pi | $1-2 (electricity) | ⭐⭐⭐ | ⭐⭐ Medium |

## Next Steps

1. **For Now**: Run locally for testing
2. **For Production**: Consider cloud deployment
3. **Quick Cloud Option**: PythonAnywhere (easiest setup)

Would you like help setting up cloud deployment?
