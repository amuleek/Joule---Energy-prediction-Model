"""
Geopolitical / market topic buckets for energy news.
Scores articles by keyword themes + TextBlob sentiment; daily aggregates for the model.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

try:
    from textblob import TextBlob
except ImportError:
    TextBlob = None  # type: ignore

# (bucket_key, display_name, keywords, bullish_when_high_sentiment)
# High negative sentiment on supply-disruption topics → bullish oil/gas
TOPIC_BUCKETS: List[Tuple[str, str, List[str], bool]] = [
    ("refinery", "Refinery / outage", ["refinery", "outage", "shutdown", "fire", "explosion", "force majeure", "maintenance"], False),
    ("hurricane", "Hurricane / storm", ["hurricane", "storm", "gulf coast", "gulf of mexico", "cyclone", "flooding"], False),
    ("opec", "OPEC / supply policy", ["opec", "opec+", "production cut", "output cut", "quota", "saudi"], False),
    ("geopolitical", "Geopolitical risk", ["iran", "israel", "sanctions", "middle east", "strait of hormuz", "hormuz", "red sea", "war", "missile", "attack"], False),
    ("shipping", "Shipping / logistics", ["tanker", "shipping", "port", "pipeline", "suez", "embargo", "blockade"], False),
    ("crude_markets", "Crude markets", ["wti", "brent", "crude oil", "crude prices", "oil prices"], True),
]

BUCKET_KEYS = [b[0] for b in TOPIC_BUCKETS]


def _text_blob(article: Dict[str, Any]) -> str:
    parts = [str(article.get("title") or ""), str(article.get("description") or "")]
    return " ".join(parts).lower()


def article_sentiment(text: str) -> float:
    """Fast TextBlob-only scoring (never loads FinBERT)."""
    if not text or TextBlob is None:
        return 0.0
    try:
        return float(TextBlob(text[:2000]).sentiment.polarity)
    except Exception:
        return 0.0


def score_article(article: Dict[str, Any], precomputed_sentiment: Optional[float] = None) -> Dict[str, Any]:
    """Per-article bucket hits and sentiment (FinBERT when available)."""
    blob = _text_blob(article)
    if precomputed_sentiment is not None:
        sent = float(precomputed_sentiment)
        engine = article.get("sentiment_engine", "textblob")
    else:
        try:
            from sentiment_engine import score_article_text
            sent_info = score_article_text(
                str(article.get("title") or ""),
                str(article.get("description") or ""),
                prefer_finbert=False,
            )
            sent = float(sent_info.get("sentiment", 0))
            engine = sent_info.get("sentiment_engine", "textblob")
        except Exception:
            sent = article_sentiment(blob)
            engine = "textblob"
    hits: Dict[str, int] = {}
    for key, _name, kws, _bull in TOPIC_BUCKETS:
        hits[key] = 1 if any(kw in blob for kw in kws) else 0
    return {
        "sentiment": sent,
        "sentiment_engine": engine,
        **{f"hit_{k}": hits[k] for k in BUCKET_KEYS},
    }


def process_news_csv(csv_path: str = "data/news.csv") -> pd.DataFrame:
    """Daily sentiment + topic intensity scores."""
    import os
    from datetime import datetime, timedelta

    empty_cols = ["date", "sentiment"] + [f"topic_{k}" for k in BUCKET_KEYS] + ["geo_risk_score"]
    if not os.path.exists(csv_path):
        return pd.DataFrame(columns=empty_cols)

    df = pd.read_csv(csv_path)
    if df.empty:
        return pd.DataFrame(columns=empty_cols)

    lookback_days = int(os.getenv("NEWS_SENTIMENT_DAYS", "7"))
    max_articles = int(os.getenv("NEWS_MAX_ARTICLES", "150"))
    cutoff = datetime.now() - timedelta(days=lookback_days)
    df["_dt"] = pd.to_datetime(df["date"], errors="coerce", utc=True)
    try:
        df["_dt"] = df["_dt"].dt.tz_localize(None)
    except Exception:
        pass
    df = df.dropna(subset=["_dt"]).sort_values("_dt")
    recent = df[df["_dt"] >= cutoff].tail(max_articles).copy()
    older_count = len(df) - len(recent)

    print(f"  News sentiment: scoring {len(recent)} articles (last {lookback_days}d, cap {max_articles}); skipping {older_count} archived rows")

    # Reuse prior daily aggregates for older dates
    prior_path = os.getenv("NEWS_PROCESSED_PATH", "data/news_processed.csv")
    prior_daily = pd.DataFrame()
    if older_count > 0 and os.path.exists(prior_path):
        try:
            prior_daily = pd.read_csv(prior_path)
            prior_daily["date"] = pd.to_datetime(prior_daily["date"], errors="coerce")
            prior_daily = prior_daily[prior_daily["date"] < cutoff].copy()
            if not prior_daily.empty:
                print(f"  Reusing {len(prior_daily)} prior daily sentiment rows (no rescore)")
        except Exception:
            prior_daily = pd.DataFrame()

    articles: List[Dict[str, Any]] = []
    for _, row in recent.iterrows():
        articles.append(row.to_dict())

    scored_recent: List[Dict[str, Any]] = []
    if articles:
        use_finbert = os.getenv("USE_FINBERT", "false").lower() in ("1", "true", "yes")
        if use_finbert:
            try:
                from sentiment_engine import score_articles_fast
                batch = score_articles_fast(articles)
                for art in batch:
                    base = {k: v for k, v in art.items() if k not in ("sentiment", "sentiment_engine")}
                    scored = score_article(base, precomputed_sentiment=art.get("sentiment"))
                    scored["sentiment_engine"] = art.get("sentiment_engine", "textblob")
                    scored["date"] = art.get("date", "")
                    scored_recent.append(scored)
            except Exception as e:
                print(f"  FinBERT batch failed ({e}); using TextBlob")
                use_finbert = False
        if not use_finbert:
            for i, art in enumerate(articles):
                if i and i % 50 == 0:
                    print(f"    TextBlob: {i}/{len(articles)}...")
                scored = score_article(art, precomputed_sentiment=article_sentiment(_text_blob(art)))
                scored["sentiment_engine"] = "textblob"
                scored["date"] = art.get("date", "")
                scored_recent.append(scored)

    rows = scored_recent

    if not rows and prior_daily.empty:
        return pd.DataFrame(columns=empty_cols)

    if rows:
        adf = pd.DataFrame(rows)
        adf["date"] = pd.to_datetime(adf["date"], errors="coerce")
        adf = adf.dropna(subset=["date"])
    elif not prior_daily.empty:
        daily = prior_daily.copy()
        daily["date"] = daily["date"].dt.strftime("%Y-%m-%d")
        # geo_risk below
        disrupt_cols = [f"topic_{k}" for k in ("refinery", "hurricane", "opec", "geopolitical", "shipping")]
        present = [c for c in disrupt_cols if c in daily.columns]
        if present:
            disruption = daily[present].sum(axis=1) / max(len(present), 1)
            daily["geo_risk_score"] = (disruption * (1.0 - daily["sentiment"].clip(-1, 1)) / 2.0).clip(0.0, 1.0).round(4)
        else:
            daily["geo_risk_score"] = 0.0
        daily["sentiment_engine"] = daily.get("sentiment_engine", "textblob")
        return daily

    adf["date_only"] = adf["date"].dt.date
    agg_map = {"sentiment": "mean", **{f"hit_{k}": "mean" for k in BUCKET_KEYS}}
    daily_new = adf.groupby("date_only", as_index=False).agg(agg_map)
    daily_new = daily_new.rename(columns={"date_only": "date", **{f"hit_{k}": f"topic_{k}" for k in BUCKET_KEYS}})
    daily_new["date"] = pd.to_datetime(daily_new["date"], errors="coerce")

    if not prior_daily.empty:
        prior_daily["date"] = pd.to_datetime(prior_daily["date"], errors="coerce")
        daily = pd.concat([prior_daily, daily_new], ignore_index=True)
        daily = daily.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    else:
        daily = daily_new

    daily["date"] = daily["date"].dt.strftime("%Y-%m-%d")

    disrupt_cols = [f"topic_{k}" for k in ("refinery", "hurricane", "opec", "geopolitical", "shipping")]
    present = [c for c in disrupt_cols if c in daily.columns]
    if present:
        disruption = daily[present].sum(axis=1) / max(len(present), 1)
        daily["geo_risk_score"] = (disruption * (1.0 - daily["sentiment"].clip(-1, 1)) / 2.0).clip(0.0, 1.0).round(4)
    else:
        daily["geo_risk_score"] = 0.0

    if "sentiment_engine" in adf.columns:
        eng_daily = adf.groupby("date_only")["sentiment_engine"].agg(
            lambda x: x.value_counts().index[0] if len(x) else "textblob"
        )
        daily["sentiment_engine"] = daily["date"].map(
            {str(k): v for k, v in eng_daily.items()}
        ).fillna("textblob")
    else:
        daily["sentiment_engine"] = "textblob"

    return daily


def latest_topic_snapshot(processed_path: str = "data/news_processed.csv") -> Dict[str, Any]:
    """Most recent day of bucket scores for decision agent."""
    import os

    out: Dict[str, Any] = {"buckets": {}, "sentiment": 0.0, "geo_risk_score": 0.0, "top_drivers": []}
    if not os.path.exists(processed_path):
        return out
    df = pd.read_csv(processed_path)
    if df.empty:
        return out
    row = df.iloc[-1]
    out["sentiment"] = float(row.get("sentiment", 0) or 0)
    out["geo_risk_score"] = float(row.get("geo_risk_score", 0) or 0)
    out["sentiment_engine"] = str(row.get("sentiment_engine", "textblob"))
    buckets = {}
    for key, display, _kws, _bull in TOPIC_BUCKETS:
        col = f"topic_{key}"
        val = float(row.get(col, 0) or 0)
        buckets[key] = {"label": display, "intensity": round(val, 3)}
    out["buckets"] = buckets

    ranked = sorted(buckets.items(), key=lambda x: x[1]["intensity"], reverse=True)
    drivers: List[str] = []
    for key, info in ranked[:3]:
        if info["intensity"] >= 0.15:
            drivers.append(f"{info['label']} ({info['intensity']:.0%} of today's headlines)")
    out["top_drivers"] = drivers
    return out


def save_processed_news(
    news_csv: str = "data/news.csv",
    output_path: str = "data/news_processed.csv",
) -> pd.DataFrame:
    daily = process_news_csv(news_csv)
    __import__("os").makedirs(__import__("os").path.dirname(output_path) or ".", exist_ok=True)
    daily.to_csv(output_path, index=False)
    return daily
