"""
FinBERT-style financial sentiment with TextBlob fallback.
FinBERT is used only for recent headlines (CPU-safe); older rows use TextBlob.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

FINBERT_MODEL = os.getenv("FINBERT_MODEL", "ProsusAI/finbert")
USE_FINBERT = os.getenv("USE_FINBERT", "false").lower() in ("1", "true", "yes")
MAX_FINBERT_CHARS = 512
# Cap FinBERT runs per pipeline (each call is slow on CPU)
FINBERT_MAX_ARTICLES = int(os.getenv("FINBERT_MAX_ARTICLES", "80"))
FINBERT_BATCH_SIZE = int(os.getenv("FINBERT_BATCH_SIZE", "8"))


@lru_cache(maxsize=1)
def _finbert_pipeline():
    if not USE_FINBERT:
        return None
    try:
        from transformers import pipeline
        return pipeline(
            "sentiment-analysis",
            model=FINBERT_MODEL,
            tokenizer=FINBERT_MODEL,
            truncation=True,
            max_length=128,
            device=-1,  # CPU
        )
    except Exception as e:
        print(f"FinBERT unavailable ({e}); using TextBlob fallback.")
        return None


def _textblob_score(text: str) -> float:
    try:
        from textblob import TextBlob
        return float(TextBlob(text[:2000]).sentiment.polarity)
    except Exception:
        return 0.0


def _label_to_polarity(label: str, score: float) -> float:
    label = label.lower()
    if "positive" in label:
        return float(score)
    if "negative" in label:
        return -float(score)
    return 0.0


def _finbert_score(text: str) -> Optional[float]:
    pipe = _finbert_pipeline()
    if pipe is None or not text.strip():
        return None
    try:
        out = pipe(text.strip()[:MAX_FINBERT_CHARS])[0]
        return _label_to_polarity(str(out.get("label", "")), float(out.get("score", 0.5)))
    except Exception:
        return None


def _finbert_batch(texts: List[str]) -> List[Optional[float]]:
    pipe = _finbert_pipeline()
    if pipe is None:
        return [None] * len(texts)
    snippets = [t.strip()[:MAX_FINBERT_CHARS] for t in texts]
    try:
        results = pipe(snippets, batch_size=FINBERT_BATCH_SIZE)
        return [_label_to_polarity(str(r.get("label", "")), float(r.get("score", 0.5))) for r in results]
    except Exception:
        return [_finbert_score(t) for t in texts]


def score_text(text: str, prefer_finbert: bool = True) -> Tuple[float, str]:
    if not text or not str(text).strip():
        return 0.0, "none"
    if prefer_finbert and USE_FINBERT:
        fb = _finbert_score(str(text))
        if fb is not None:
            return float(max(-1.0, min(1.0, fb))), "finbert"
    return _textblob_score(str(text)), "textblob"


def score_article_text(title: str, description: str = "", prefer_finbert: bool = True) -> Dict[str, Any]:
    combined = f"{title or ''}. {description or ''}".strip()
    polarity, engine = score_text(combined, prefer_finbert=prefer_finbert)
    return {
        "sentiment": round(polarity, 4),
        "sentiment_engine": engine,
    }


def score_articles_fast(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Score articles: FinBERT for the first N (recent), TextBlob for the rest.
    One model call per article (no duplicate title pass).
    """
    n_finbert = min(FINBERT_MAX_ARTICLES, len(articles)) if USE_FINBERT else 0
    out: List[Dict[str, Any]] = []

    if n_finbert > 0:
        print(f"  FinBERT sentiment: {n_finbert} recent articles (batch size {FINBERT_BATCH_SIZE})...")
        texts = [
            f"{a.get('title', '')}. {a.get('description', '')}".strip()[:MAX_FINBERT_CHARS]
            for a in articles[:n_finbert]
        ]
        scores = _finbert_batch(texts)
        for i, (art, sc) in enumerate(zip(articles[:n_finbert], scores)):
            polarity = sc if sc is not None else _textblob_score(texts[i])
            out.append({
                **art,
                "sentiment": round(float(polarity), 4),
                "sentiment_engine": "finbert" if sc is not None else "textblob",
            })

    if len(articles) > n_finbert:
        rest = len(articles) - n_finbert
        print(f"  TextBlob sentiment: {rest} older articles (fast)...")
        for art in articles[n_finbert:]:
            blob = f"{art.get('title', '')} {art.get('description', '')}".strip()
            out.append({
                **art,
                "sentiment": round(_textblob_score(blob), 4),
                "sentiment_engine": "textblob",
            })

    return out
