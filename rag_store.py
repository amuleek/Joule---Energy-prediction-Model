"""
Retrieval-augmented generation store for EIA reports, news, and market commentary.
Uses TF-IDF over SQLite-stored documents (no external vector DB required).
Optional OpenAI embeddings when OPENAI_API_KEY is set.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from database import fetch_documents, init_db, insert_document

GEO_KEYWORDS = ("iran", "russia", "saudi", "opec", "hormuz", "venezuela", "ukraine", "middle east")
ENERGY_KEYWORDS = ("refinery", "inventory", "crude", "gasoline", "diesel", "hurricane", "outage", "pipeline")


class RAGStore:
    def __init__(self):
        init_db()
        self._vectorizer: Optional[TfidfVectorizer] = None
        self._matrix = None
        self._docs: List[Dict[str, Any]] = []

    def index_news_csv(self, path: str = "data/news.csv", max_rows: int = 0) -> int:
        if not os.path.exists(path):
            return 0
        max_rows = max_rows or int(os.getenv("RAG_MAX_INDEX", "80"))
        df = pd.read_csv(path)
        if df.empty:
            return 0
        if "date" in df.columns:
            df["_dt"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["_dt"]).sort_values("_dt").tail(max_rows)
        n = 0
        for _, row in df.iterrows():
            title = str(row.get("title", "") or "")
            desc = str(row.get("description", "") or "")
            body = f"{title}. {desc}".strip()
            if len(body) < 20:
                continue
            pub = str(row.get("date", ""))[:10]
            tags = self._tag_text(body)
            insert_document(source="news", title=title[:200], body=body, published_at=pub, tags=tags)
            n += 1
        self._invalidate_cache()
        return n

    def index_text(self, source: str, title: str, body: str, published_at: str = "", tags: Optional[List[str]] = None) -> int:
        if len(body.strip()) < 15:
            return 0
        doc_id = insert_document(source=source, title=title, body=body, published_at=published_at, tags=tags or self._tag_text(body))
        self._invalidate_cache()
        return doc_id

    def _tag_text(self, text: str) -> List[str]:
        t = text.lower()
        tags = []
        for kw in GEO_KEYWORDS:
            if kw in t:
                tags.append(f"geo:{kw}")
        for kw in ENERGY_KEYWORDS:
            if kw in t:
                tags.append(f"topic:{kw}")
        return tags

    def _invalidate_cache(self) -> None:
        self._vectorizer = None
        self._matrix = None
        self._docs = []

    def _build_index(self) -> None:
        self._docs = fetch_documents(limit=800)
        if not self._docs:
            return
        texts = [f"{d.get('title', '')} {d.get('body', '')}" for d in self._docs]
        self._vectorizer = TfidfVectorizer(max_features=4000, stop_words="english", ngram_range=(1, 2))
        self._matrix = self._vectorizer.fit_transform(texts)

    def search(self, query: str, top_k: int = 5, tag_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self._docs or self._matrix is None:
            self._build_index()
        if not self._docs or self._matrix is None:
            return []

        q_vec = self._vectorizer.transform([query])
        scores = cosine_similarity(q_vec, self._matrix).flatten()
        ranked = scores.argsort()[::-1]

        results = []
        for idx in ranked:
            if scores[idx] < 0.05:
                break
            doc = self._docs[idx]
            if tag_filter and tag_filter not in str(doc.get("tags", "")):
                continue
            results.append({
                "title": doc.get("title", ""),
                "snippet": doc.get("body", "")[:280],
                "source": doc.get("source", ""),
                "published_at": doc.get("published_at", ""),
                "score": round(float(scores[idx]), 4),
                "tags": doc.get("tags", ""),
            })
            if len(results) >= top_k:
                break
        return results

    def context_for_product(self, product_key: str, meta: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        queries = {
            "RBOB_Gasoline": "gasoline RBOB refinery outage inventory driving season",
            "ULSD_Diesel": "diesel distillate heating oil inventory refinery",
            "Crude_Oil": "crude oil OPEC Saudi Iran Russia production export",
        }
        q = queries.get(product_key, "crude oil energy market")
        if meta and meta.get("geo_risk_score", 0) > 0.05:
            q += " geopolitical Iran Russia Saudi Arabia conflict"
        return self.search(q, top_k=5)


def build_rag_context(meta: Dict[str, Any]) -> Dict[str, Any]:
    store = RAGStore()
    # Index only a small recent slice (full reindex is very slow)
    if os.getenv("RAG_SKIP_INDEX", "true").lower() not in ("1", "true", "yes"):
        store.index_news_csv()
    ctx = {}
    for pk in ("RBOB_Gasoline", "ULSD_Diesel", "Crude_Oil"):
        hits = store.context_for_product(pk, meta)
        if hits:
            ctx[pk] = hits
    return ctx
