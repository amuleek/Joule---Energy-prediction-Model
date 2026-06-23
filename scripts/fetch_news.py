"""
Fetch News Data for Sentiment Analysis
Fetches energy market news from various sources
"""
import requests
import pandas as pd
from datetime import datetime, timedelta
import os

# News API configuration (free tier available at newsapi.org)
# Get free API key at: https://newsapi.org/register
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import API_CONFIG

NEWS_API_KEY = os.getenv('NEWS_API_KEY', API_CONFIG.get('news_api_key', ''))
WORLD_NEWS_API_KEY = os.getenv('WORLD_NEWS_API_KEY', API_CONFIG.get('world_news_api_key', ''))

def fetch_news_newsapi():
    """Fetch news from NewsAPI"""
    if not NEWS_API_KEY:
        print("NewsAPI key not configured. Skipping news fetch.")
        return None
    
    try:
        # Get news from last 7 days
        from_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        url = f"https://newsapi.org/v2/everything"
        params = {
            'q': '(oil OR gasoline OR diesel OR OPEC OR crude OR refinery OR hurricane OR "Strait of Hormuz") AND (energy OR petroleum)',
            'from': from_date,
            'sortBy': 'publishedAt',
            'language': 'en',
            'apiKey': NEWS_API_KEY,
            'pageSize': 50
        }
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        
        if 'articles' in data:
            articles = data['articles']
            news_data = []
            for a in articles:
                news_data.append({
                    'date': a.get('publishedAt', ''),
                    'title': a.get('title', ''),
                    'description': a.get('description', ''),
                    'source': a.get('source', {}).get('name', '')
                })
            return pd.DataFrame(news_data)
    except Exception as e:
        print(f"Error fetching news from NewsAPI: {str(e)}")
    return None

def fetch_news_world_news_api():
    """Fetch news from World News API"""
    if not WORLD_NEWS_API_KEY:
        return None
    
    try:
        # World News API endpoint
        url = "https://api.worldnewsapi.com/search-news"
        params = {
            'api-key': WORLD_NEWS_API_KEY,
            'text': 'oil OR gasoline OR diesel OR OPEC OR crude OR energy',
            'number': 50,
            'sort': 'publish-time',
            'sort-direction': 'DESC'
        }
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        
        if 'news' in data:
            articles = data['news']
            news_data = []
            for a in articles:
                news_data.append({
                    'date': a.get('publish_date', ''),
                    'title': a.get('title', ''),
                    'description': a.get('text', '')[:500],  # Limit description length
                    'source': a.get('source', {}).get('name', '') if isinstance(a.get('source'), dict) else ''
                })
            return pd.DataFrame(news_data)
    except Exception as e:
        print(f"Error fetching news from World News API: {str(e)}")
    return None

def fetch_news_simple():
    """Simple news fetch using web scraping (fallback)"""
    # This is a placeholder - in production, you'd use RSS feeds or other sources
    # For now, create empty dataframe
    return pd.DataFrame(columns=['date', 'title', 'description', 'source'])

def save_news():
    """Fetch and save news data"""
    print("Fetching news data...")
    
    # Try NewsAPI first
    df = fetch_news_newsapi()
    
    # If NewsAPI fails or returns empty, try World News API
    if df is None or df.empty:
        print("Trying World News API...")
        df_world = fetch_news_world_news_api()
        if df_world is not None and not df_world.empty:
            df = df_world
        elif df is None:
            df = pd.DataFrame(columns=['date', 'title', 'description', 'source'])
    
    # If both fail, use empty dataset
    if df is None or df.empty:
        print("No news data available. Using empty dataset.")
        df = fetch_news_simple()
    
    csv_path = "data/news.csv"
    if os.path.exists(csv_path):
        existing_df = pd.read_csv(csv_path)
        # Merge and remove duplicates
        df = pd.concat([existing_df, df], ignore_index=True)
        df = df.drop_duplicates(subset=['title'], keep='last')
    
    df.to_csv(csv_path, index=False)
    print(f"News saved: {len(df)} articles")
    return df

if __name__ == "__main__":
    save_news()
