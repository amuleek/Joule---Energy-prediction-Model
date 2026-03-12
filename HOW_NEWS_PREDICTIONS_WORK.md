# How World News Drives Fuel Price Predictions

## ✅ YES - The Project Uses World News for Predictions!

### How It Works:

1. **News Collection** 📰
   - Fetches news from NewsAPI and World News API
   - Searches for: "oil OR gasoline OR diesel OR OPEC OR crude OR energy"
   - Collects 50+ articles daily

2. **Sentiment Analysis** 🧠
   - Uses TextBlob to analyze each news article
   - Calculates sentiment score: -1.0 (very negative) to +1.0 (very positive)
   - Example:
     - "OPEC cuts production" → Negative sentiment → Prices may rise
     - "Refinery explosion disrupts supply" → Negative sentiment → Prices may rise
     - "New oil discovery" → Positive sentiment → Prices may fall

3. **Data Integration** 🔗
   - Merges news sentiment with price data
   - Creates daily sentiment scores
   - Includes in prediction model as a feature

4. **AI Prediction Model** 🤖
   - **Prophet Model** uses sentiment as a regressor
   - Formula: `Price = f(Time, Sentiment, Historical Trends)`
   - Sentiment influences the forecast:
     - **Positive news** → May predict lower prices (more supply, less demand)
     - **Negative news** → May predict higher prices (supply disruptions, conflicts)

### Current Status:

✅ **News APIs Configured:**
- NewsAPI: `8886b39275f645a79cf2fb3d66d6d7b1` (Active)
- World News API: `e1a4d874e47646dfb3a8afe4691ba540` (Backup)

✅ **Sentiment Analysis:**
- Processing news articles daily
- Latest sentiment: 0.089 (slightly positive)
- Integrated into prediction model

✅ **Predictions Include News:**
- Prophet model uses sentiment as regressor
- Future predictions use latest sentiment value
- News sentiment influences tomorrow, week, and monthly forecasts

### Example Flow:

```
1. News: "OPEC announces production cuts"
   ↓
2. Sentiment Analysis: -0.65 (negative)
   ↓
3. Model Interpretation: Supply reduction expected
   ↓
4. Prediction: Prices ↑ (increase forecasted)
```

### Verification:

Check if sentiment is being used:
```bash
python -c "import pandas as pd; df = pd.read_csv('data/final_data.csv'); print('Sentiment column:', 'sentiment' in df.columns); print('Latest sentiment:', df['sentiment'].iloc[-1])"
```

### What News Affects Predictions:

- **OPEC Announcements**: Production decisions
- **Geopolitical Events**: Wars, sanctions (Russia, Middle East)
- **Natural Disasters**: Hurricanes, refinery fires
- **Economic News**: Demand forecasts, recession fears
- **Supply Disruptions**: Pipeline issues, export bans
- **Policy Changes**: US energy policy, environmental regulations

### How to See It Working:

1. **Check News Data:**
   ```bash
   python scripts/fetch_news.py
   cat data/news.csv
   ```

2. **Check Sentiment:**
   ```bash
   cat data/news_processed.csv
   ```

3. **See Sentiment in Predictions:**
   ```bash
   python -c "import pandas as pd; df = pd.read_csv('data/final_data.csv'); print(df[['date', 'RBOB', 'sentiment']].tail())"
   ```

### Summary:

**YES** - Your prediction system:
- ✅ Fetches world news daily
- ✅ Analyzes sentiment from news
- ✅ Uses sentiment in AI predictions
- ✅ Adjusts forecasts based on market news

The Prophet model includes sentiment as a regressor, meaning news sentiment directly influences the price predictions for tomorrow, one week, and one month!
