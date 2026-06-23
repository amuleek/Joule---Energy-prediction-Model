# Data Sources and Prediction Methodology

## Current Data Sources

### 1. **Price Data Sources**

#### **Diesel (ULSD) - HO=F**
- **Primary Source**: Yahoo Finance (NYMEX Heating Oil Futures)
- **Symbol**: `HO=F` (Heating Oil futures, used as proxy for ULSD)
- **Type**: Futures contract price
- **Fallback**: Alpha Vantage API (if Yahoo fails)
- **Alternative**: EIA API spot prices (`EPMULRR`)

#### **RBOB Gasoline - RB=F**
- **Primary Source**: Yahoo Finance (NYMEX RBOB Gasoline Futures)
- **Symbol**: `RB=F`
- **Type**: Futures contract price
- **Fallback**: Alpha Vantage API
- **Alternative**: EIA API spot prices (`EPMRBRR`)

#### **Crude Oil - CL=F**
- **Primary Source**: Yahoo Finance (NYMEX WTI Crude Oil Futures)
- **Symbol**: `CL=F`
- **Type**: WTI Crude Oil Futures
- **Fallback**: Alpha Vantage API

### 2. **Inventory Data**
- **Source**: EIA (U.S. Energy Information Administration) API
- **Gasoline Inventory**: Series ID `WGTSTUS1`
- **Diesel Inventory**: Series ID `WDISTUS1`
- **Frequency**: Weekly reports

### 3. **News/Sentiment Data**
- **Primary**: NewsAPI
- **Backup**: World News API
- **Keywords**: Oil, gasoline, diesel, OPEC, energy markets

## Prediction Model

### **Primary Model: Facebook Prophet**
- Time series forecasting
- Handles seasonality and trends
- Includes sentiment as regressor
- **Issue**: Requires sufficient historical data (ideally 30+ days)

### **Fallback Model: Linear Regression**
- Simple trend-based prediction
- Used when Prophet unavailable or insufficient data
- **Issue**: Can over-extrapolate with limited data

## Current Issue: Unrealistic Diesel Predictions

### **Problem Identified:**
- **Current Price**: $3.37/gallon
- **Predicted Tomorrow**: $3.73 (+10.68%) ⚠️
- **Predicted One Week**: $3.80 (+12.75%) ⚠️
- **Predicted Monthly**: $4.02 (+19.28%) ⚠️

### **Likely Causes:**

1. **Limited Historical Data**
   - Only a few days of data in `prices.csv`
   - Prophet/Linear models need more data for accurate predictions
   - With limited data, models can over-extrapolate trends

2. **Data Quality Issues**
   - Missing or incomplete historical data
   - Gaps in time series
   - Inconsistent data sources

3. **Model Overfitting**
   - Model may be fitting to noise rather than real trends
   - Small sample size leads to unreliable predictions

4. **Futures vs Spot Price Confusion**
   - HO=F (Heating Oil futures) may not perfectly track ULSD spot prices
   - Futures prices can be more volatile

## Recommendations

### **Immediate Fixes:**

1. **Collect More Historical Data**
   ```bash
   # Run data collection multiple times to build history
   python scripts/fetch_prices.py
   ```

2. **Add Data Validation**
   - Check if predictions are within reasonable bounds (±5% for daily, ±15% for monthly)
   - Flag unrealistic predictions

3. **Use Multiple Data Sources**
   - Cross-reference EIA spot prices with futures prices
   - Validate predictions against multiple sources

4. **Improve Model Training**
   - Require minimum 30 days of data before making predictions
   - Use more conservative predictions with limited data

### **Long-term Improvements:**

1. **Better Data Collection**
   - Collect historical data going back 3-6 months
   - Use EIA historical data API

2. **Model Improvements**
   - Add confidence intervals
   - Implement prediction bounds (max ±10% daily change)
   - Use ensemble methods

3. **Data Validation**
   - Check for outliers
   - Validate against market norms
   - Flag suspicious predictions

## Current Status

⚠️ **Warning**: Predictions may be unreliable due to limited historical data.

**Action Required**: Collect more historical data before relying on predictions.
