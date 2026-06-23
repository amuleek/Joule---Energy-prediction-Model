"""
Timestamped SQLite store for market data, predictions, outcomes, and RAG documents.
CSV files remain the primary ML pipeline input; the DB is the system of record.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

DB_PATH = os.getenv("MARKET_DB_PATH", "data/market_data.db")


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or "data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def get_db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS market_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                metric TEXT NOT NULL,
                value REAL,
                unit TEXT,
                observed_at TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                meta_json TEXT,
                UNIQUE(source, metric, observed_at)
            );

            CREATE TABLE IF NOT EXISTS predictions_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issued_at TEXT NOT NULL,
                product TEXT NOT NULL,
                horizon TEXT NOT NULL,
                predicted_price REAL,
                spot_price REAL,
                model_stack TEXT,
                ensemble_json TEXT,
                reasoning TEXT,
                meta_json TEXT
            );

            CREATE TABLE IF NOT EXISTS prediction_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issued_at TEXT NOT NULL,
                target_date TEXT NOT NULL,
                product TEXT NOT NULL,
                horizon TEXT NOT NULL,
                predicted REAL,
                actual REAL,
                error REAL,
                error_pct REAL,
                mae REAL,
                rmse REAL,
                direction_correct INTEGER,
                evaluated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS model_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_name TEXT NOT NULL,
                product TEXT NOT NULL,
                horizon TEXT NOT NULL,
                mae REAL,
                rmse REAL,
                direction_accuracy REAL,
                bias REAL,
                n_samples INTEGER,
                updated_at TEXT NOT NULL,
                UNIQUE(model_name, product, horizon)
            );

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                title TEXT,
                body TEXT NOT NULL,
                published_at TEXT,
                tags TEXT,
                ingested_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_obs_metric_date ON market_observations(metric, observed_at);
            CREATE INDEX IF NOT EXISTS idx_pred_log_issued ON predictions_log(issued_at, product);
            CREATE INDEX IF NOT EXISTS idx_outcomes_product ON prediction_outcomes(product, horizon);
            CREATE INDEX IF NOT EXISTS idx_docs_published ON documents(published_at);
            """
        )


def upsert_observation(
    source: str,
    metric: str,
    value: Optional[float],
    observed_at: str,
    unit: str = "",
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    init_db()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO market_observations (source, metric, value, unit, observed_at, ingested_at, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, metric, observed_at) DO UPDATE SET
                value=excluded.value, unit=excluded.unit, ingested_at=excluded.ingested_at, meta_json=excluded.meta_json
            """,
            (
                source,
                metric,
                value,
                unit,
                observed_at,
                datetime.now().isoformat(),
                json.dumps(meta or {}),
            ),
        )


def log_prediction(
    issued_at: str,
    product: str,
    horizon: str,
    predicted_price: float,
    spot_price: float,
    model_stack: str = "",
    ensemble: Optional[Dict[str, Any]] = None,
    reasoning: str = "",
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    init_db()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO predictions_log
            (issued_at, product, horizon, predicted_price, spot_price, model_stack, ensemble_json, reasoning, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                issued_at,
                product,
                horizon,
                predicted_price,
                spot_price,
                model_stack,
                json.dumps(ensemble or {}),
                reasoning,
                json.dumps(meta or {}),
            ),
        )


def log_outcome(
    issued_at: str,
    target_date: str,
    product: str,
    horizon: str,
    predicted: float,
    actual: float,
    direction_correct: bool,
) -> None:
    error = predicted - actual
    error_pct = (error / actual * 100) if actual else 0.0
    init_db()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO prediction_outcomes
            (issued_at, target_date, product, horizon, predicted, actual, error, error_pct,
             mae, rmse, direction_correct, evaluated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                issued_at,
                target_date,
                product,
                horizon,
                predicted,
                actual,
                error,
                error_pct,
                abs(error),
                error ** 2,
                1 if direction_correct else 0,
                datetime.now().isoformat(),
            ),
        )


def upsert_model_performance(
    model_name: str,
    product: str,
    horizon: str,
    mae: float,
    rmse: float,
    direction_accuracy: float,
    bias: float,
    n_samples: int,
) -> None:
    init_db()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO model_performance
            (model_name, product, horizon, mae, rmse, direction_accuracy, bias, n_samples, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(model_name, product, horizon) DO UPDATE SET
                mae=excluded.mae, rmse=excluded.rmse, direction_accuracy=excluded.direction_accuracy,
                bias=excluded.bias, n_samples=excluded.n_samples, updated_at=excluded.updated_at
            """,
            (
                model_name,
                product,
                horizon,
                mae,
                rmse,
                direction_accuracy,
                bias,
                n_samples,
                datetime.now().isoformat(),
            ),
        )


def insert_document(
    source: str,
    body: str,
    title: str = "",
    published_at: str = "",
    tags: Optional[List[str]] = None,
) -> int:
    init_db()
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO documents (source, title, body, published_at, tags, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                source,
                title,
                body,
                published_at,
                ",".join(tags or []),
                datetime.now().isoformat(),
            ),
        )
        return int(cur.lastrowid)


def fetch_documents(limit: int = 500) -> List[Dict[str, Any]]:
    init_db()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, source, title, body, published_at, tags FROM documents ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def sync_csv_row(source: str, metric: str, row: Dict[str, Any], date_col: str = "date") -> None:
    """Upsert one row of a CSV into market_observations."""
    dt = str(row.get(date_col, ""))[:10]
    if not dt:
        return
    val = row.get(metric)
    if val is None or (isinstance(val, float) and val != val):
        return
    try:
        upsert_observation(source, metric, float(val), dt)
    except (TypeError, ValueError):
        pass


_OBS_UPSERT_SQL = """
    INSERT INTO market_observations (source, metric, value, unit, observed_at, ingested_at, meta_json)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(source, metric, observed_at) DO UPDATE SET
        value=excluded.value, unit=excluded.unit,
        ingested_at=excluded.ingested_at, meta_json=excluded.meta_json
"""


def sync_dataframe(source: str, df, metrics: Iterable[str], date_col: str = "date") -> int:
    """Bulk-upsert CSV rows in one transaction (avoids per-cell connect overhead)."""
    if df is None or df.empty:
        return 0

    metric_list = [m for m in metrics if m in df.columns and m != date_col]
    if not metric_list:
        return 0

    ingested_at = datetime.now().isoformat()
    payload: List[tuple] = []

    for row in df.itertuples(index=False):
        row_dict = row._asdict() if hasattr(row, "_asdict") else dict(zip(df.columns, row))
        dt = str(row_dict.get(date_col, ""))[:10]
        if not dt or dt == "nan":
            continue
        for m in metric_list:
            val = row_dict.get(m)
            if val is None or (isinstance(val, float) and val != val):
                continue
            try:
                payload.append((source, m, float(val), "", dt, ingested_at, "{}"))
            except (TypeError, ValueError):
                continue

    if not payload:
        return 0

    init_db()
    with get_db() as conn:
        conn.executemany(_OBS_UPSERT_SQL, payload)
    return len(payload)
