# News API Setup (Optional)

## Current Status

The news fetching is **optional** and currently **not configured**. The prediction system works fine without it, but news sentiment can improve prediction accuracy.

## What News Does

News sentiment analysis helps the AI model understand:
- Market sentiment (positive/negative news about oil/gas)
- OPEC announcements
- Geopolitical events
- Supply disruptions
- Economic indicators

## How to Set Up (Optional)

### Step 1: Get Free NewsAPI Key

1. Go to: https://newsapi.org/register
2. Sign up for free account
3. Copy your API key

### Step 2: Configure the Key

**Option A - Environment Variable (Recommended):**
```powershell
$env:NEWS_API_KEY="your-newsapi-key-here"
```

**Option B - Edit config.py:**
```python
'news_api_key': os.getenv('NEWS_API_KEY', 'your-newsapi-key-here'),
```

### Step 3: Test

```bash
python scripts/fetch_news.py
```

## Free Tier Limits

- **500 requests per day** (plenty for daily predictions)
- **News from last month**
- **No credit card required**

## Is It Required?

**NO** - The prediction system works without news data. News sentiment is just an additional feature that can improve accuracy.

## Current Behavior

Without NewsAPI:
- ✅ Predictions still work
- ✅ Uses price and inventory data
- ✅ Sentiment defaults to neutral (0.0)
- ⚠️ Missing market sentiment context

With NewsAPI:
- ✅ All above features
- ✅ News sentiment analysis
- ✅ Better prediction accuracy
- ✅ Market context awareness

## Alternative News Sources

If you don't want to use NewsAPI, you can:
1. Leave it unconfigured (system works fine)
2. Use RSS feeds (requires custom implementation)
3. Use other news APIs (requires code modification)

## Summary

**News API is OPTIONAL** - Your prediction system is fully functional without it. It's a nice-to-have feature that adds sentiment analysis to improve predictions.
