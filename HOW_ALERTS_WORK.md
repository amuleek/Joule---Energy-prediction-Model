# How Alerts Work - Current System

## ✅ YES - Alerts ARE Sent on Both Rises AND Falls!

### Current Alert Behavior:

**The system sends email alerts when:**

1. **Price INCREASES** by more than 2% (default threshold)
   - Example: Gasoline goes from $2.80 → $2.86 (2.1% increase) = **ALERT SENT** ✅

2. **Price DECREASES** by more than 2% (default threshold)
   - Example: Gasoline goes from $2.80 → $2.74 (2.1% decrease) = **ALERT SENT** ✅

3. **First Recording** (establishes baseline)
   - First time a price is recorded = **ALERT SENT** ✅

### Current Settings:

- **Price Change Threshold**: 2.0% (configurable)
- **Inventory Change Threshold**: 2.0% (configurable)
- **Check Interval**: Every 5 minutes
- **Direction**: Alerts on BOTH increases AND decreases

### How It Works:

The system uses `abs(change_percent)` which means it checks the **absolute value** of the change:

```python
is_significant = abs(change_percent) >= threshold
```

This means:
- **+2.5% change** = Alert ✅ (increase)
- **-2.5% change** = Alert ✅ (decrease)
- **+1.5% change** = No alert (below threshold)
- **-1.5% change** = No alert (below threshold)

### Email Alert Content:

When an alert is triggered, the email shows:
- **Direction**: "PRICE INCREASE ↑" or "PRICE DECREASE ↓"
- **Change Amount**: $0.06
- **Change Percentage**: +2.1% or -2.1%
- **Previous Price**: $2.80
- **Current Price**: $2.86
- **Market Data**: Open, High, Low, Volume

### Summary:

✅ **Rises**: Alerts sent when price increases > 2%
✅ **Falls**: Alerts sent when price decreases > 2%
✅ **Both Directions**: System tracks and alerts on both

The 2% threshold prevents spam from tiny fluctuations while catching significant market movements in either direction!
