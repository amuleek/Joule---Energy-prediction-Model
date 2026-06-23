"""
Apply safe defaults so the daily pipeline finishes in minutes, not hours.
Call at the very start of prediction_engine (before any ML imports).
"""
from __future__ import annotations

import os


def apply_fast_defaults() -> None:
    """Force fast settings unless PIPELINE_FAST=false."""
    if os.getenv("PIPELINE_FAST", "true").lower() in ("0", "false", "no"):
        return
    fast = {
        "USE_FINBERT": "false",
        "NEWS_SENTIMENT_DAYS": "7",
        "NEWS_MAX_ARTICLES": "150",
        "FINBERT_MAX_ARTICLES": "40",
        "RAG_SKIP_INDEX": "true",
        "RAG_MAX_INDEX": "80",
        "CATBOOST_RETRAIN_EACH_RUN": "false",
        "FAST_ENSEMBLE": "true",
        "SKIP_XGB_IMPORTANCE": "true",
    }
    for key, val in fast.items():
        os.environ[key] = val
