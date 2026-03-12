"""
Preprocess Data for Prediction Model
Merges prices, inventory, and news sentiment
"""
import pandas as pd
import os
from textblob import TextBlob
import numpy as np

def process_news_sentiment():
    """Calculate sentiment scores from news"""
    csv_path = "data/news.csv"
    if not os.path.exists(csv_path):
        print("No news data found. Creating empty sentiment data.")
        return pd.DataFrame(columns=['date', 'sentiment'])
    
    df = pd.read_csv(csv_path)
    
    if df.empty:
        return pd.DataFrame(columns=['date', 'sentiment'])
    
    # Calculate sentiment for each article
    def get_sentiment(text):
        if pd.isna(text) or text == '':
            return 0.0
        try:
            return TextBlob(str(text)).sentiment.polarity
        except:
            return 0.0
    
    df['sentiment'] = df['description'].apply(get_sentiment)
    
    # Aggregate by date (average sentiment per day)
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date']).dt.date
        daily_sentiment = df.groupby('date')['sentiment'].mean().reset_index()
        daily_sentiment['date'] = daily_sentiment['date'].astype(str)
    else:
        # If no date column, use overall average
        avg_sentiment = df['sentiment'].mean()
        daily_sentiment = pd.DataFrame({
            'date': [pd.Timestamp.now().strftime('%Y-%m-%d')],
            'sentiment': [avg_sentiment]
        })
    
    output_path = "data/news_processed.csv"
    daily_sentiment.to_csv(output_path, index=False)
    print(f"Processed news sentiment: {len(daily_sentiment)} days")
    return daily_sentiment

def merge_data():
    """Merge prices, inventory, and news sentiment"""
    print("Merging data for prediction model...")
    
    # Load data
    prices_df = pd.read_csv("data/prices.csv") if os.path.exists("data/prices.csv") else pd.DataFrame()
    inventory_df = pd.read_csv("data/inventory.csv") if os.path.exists("data/inventory.csv") else pd.DataFrame()
    news_df = process_news_sentiment()
    
    if prices_df.empty:
        print("Warning: No price data available")
        return pd.DataFrame()
    
    # Merge on date
    merged = prices_df.copy()
    
    if not inventory_df.empty and 'date' in inventory_df.columns:
        merged = merged.merge(inventory_df, on='date', how='left')
    
    if not news_df.empty and 'date' in news_df.columns:
        merged = merged.merge(news_df, on='date', how='left')
        # Fill missing sentiment with 0 (neutral)
        merged['sentiment'] = merged['sentiment'].fillna(0.0)
    else:
        merged['sentiment'] = 0.0
    
    # Fill missing inventory values with forward fill
    if 'gasoline_inventory' in merged.columns:
        merged['gasoline_inventory'] = merged['gasoline_inventory'].ffill()
    if 'diesel_inventory' in merged.columns:
        merged['diesel_inventory'] = merged['diesel_inventory'].ffill()
    
    output_path = "data/final_data.csv"
    merged.to_csv(output_path, index=False)
    print(f"Merged data saved: {len(merged)} records")
    return merged

if __name__ == "__main__":
    process_news_sentiment()
    merge_data()
