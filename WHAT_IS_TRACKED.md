# What Fuel Prices Are Being Tracked?

## ✅ YES - The System IS Tracking Fuel Prices!

### Current Tracking Status:

**1. RBOB Gasoline (RB=F)**
- **Current Price**: ~$2.87 per gallon
- **Type**: Wholesale/Futures Price
- **What it is**: Reformulated Blendstock for Oxygenate Blending
- **Source**: NYMEX Futures via Yahoo Finance
- **Why it matters**: This is the wholesale price that affects retail gasoline prices

**2. Ultra-Low Sulfur Diesel (HO=F)**
- **Current Price**: ~$3.64 per gallon  
- **Type**: Wholesale/Futures Price (Heating Oil proxy)
- **What it is**: Heating Oil futures used as proxy for diesel
- **Source**: NYMEX Futures via Yahoo Finance
- **Why it matters**: This tracks diesel wholesale prices

**3. Crude Oil (CL=F)**
- **Current Price**: ~$93.47 per barrel
- **Type**: WTI Crude Oil Futures
- **Source**: NYMEX Futures via Yahoo Finance
- **Why it matters**: Base commodity that affects all fuel prices

## Important Distinction:

### ⚠️ Wholesale vs Retail Prices

**What We're Tracking:**
- **Wholesale/Futures Prices**: The price at which fuel is traded on commodity markets
- These are the prices that refineries and distributors use
- They directly influence retail prices but are NOT the same

**What We're NOT Tracking:**
- **Retail Pump Prices**: What you pay at gas stations
- Retail prices = Wholesale price + taxes + distribution + retail markup
- Typically $0.50-$1.00+ higher than wholesale

### Example:
- **Wholesale Gasoline (tracked)**: $2.87/gallon
- **Retail Gasoline (not tracked)**: ~$3.50-$4.00/gallon (varies by location)

## Why Track Wholesale Prices?

1. **Leading Indicator**: Wholesale prices change BEFORE retail prices
2. **Market Signals**: Futures prices predict future retail price movements
3. **Trading Value**: These are the prices traders and investors use
4. **Inventory Correlation**: Wholesale prices + inventory data = strong market signals

## Current System Status:

✅ **RBOB Gasoline**: Tracking and updating every 5 minutes
✅ **Diesel**: Tracking and updating every 5 minutes  
✅ **Crude Oil**: Tracking and updating every 5 minutes
✅ **Gasoline Inventories**: Tracking from EIA (249,476 thousand barrels)
✅ **Diesel Inventories**: Tracking from EIA (119,431 thousand barrels)

## Want to Track Retail Prices?

If you want to track actual retail pump prices, we would need to:
1. Use a different API (like GasBuddy API or AAA Fuel Gauge Report)
2. Track by location/region
3. Different data source entirely

**Current system is designed for:**
- Energy traders
- Market analysts
- Investors
- Anyone tracking commodity futures markets

The wholesale prices you're tracking are the **most important** prices for understanding fuel market dynamics!
