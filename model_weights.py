"""
Learning loop: update ensemble weights from post-mortem outcomes.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from config import DEFAULT_ENSEMBLE_WEIGHTS, MODEL_WEIGHTS_PATH
from ensemble_models import load_model_weights, save_model_weights

PERFORMANCE_PATH = "data/model_performance_summary.json"


def update_weights_from_evaluations(evaluations: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """
    Adjust technical/fundamental/news weights based on which component
    direction matched the realized move.
    """
    if not evaluations:
        return load_model_weights()

    weights = load_model_weights()
    learning_rate = 0.08

    for ev in evaluations:
        product = ev.get("product")
        if not product or product not in weights:
            continue
        ensemble = ev.get("ensemble_components") or {}
        if not ensemble:
            continue

        actual_dir = ev.get("actual_direction", "FLAT")
        w = weights[product]

        for component in ("technical", "fundamental", "news"):
            comp = ensemble.get(component) or {}
            ret = float(comp.get("return_pct", 0))
            pred_dir = "UP" if ret > 0.05 else "DOWN" if ret < -0.05 else "FLAT"
            if pred_dir == actual_dir and actual_dir != "FLAT":
                w[component] = w.get(component, 0.33) + learning_rate
            elif pred_dir != actual_dir and pred_dir != "FLAT" and actual_dir != "FLAT":
                w[component] = max(0.05, w.get(component, 0.33) - learning_rate)

        total = sum(w.values()) or 1.0
        weights[product] = {k: round(v / total, 4) for k, v in w.items()}

    save_model_weights(weights)
    return weights


def compute_model_metrics(eval_log_path: str = "data/prediction_eval_log.csv") -> Dict[str, Any]:
    """MAE, RMSE, direction accuracy per product/horizon and per model stack."""
    if not os.path.exists(eval_log_path):
        return {}

    df = pd.read_csv(eval_log_path)
    if df.empty:
        return {}

    summary: Dict[str, Any] = {"updated_at": pd.Timestamp.now().isoformat(), "products": {}, "models": {}}

    for product in df["product"].unique():
        summary["products"][product] = {}
        sub = df[df["product"] == product]
        for horizon in sub["horizon"].unique():
            hsub = sub[sub["horizon"] == horizon].tail(30)
            if hsub.empty:
                continue
            errors = hsub["error"].astype(float)
            summary["products"][product][horizon] = {
                "mae": round(float(errors.abs().mean()), 6),
                "rmse": round(float(np.sqrt((errors ** 2).mean())), 6),
                "mae_pct": round(float(hsub["abs_error_pct"].mean()), 3),
                "direction_accuracy": round(float(hsub["direction_correct"].mean()), 3),
                "bias_pct": round(float(hsub["error_pct"].mean()), 3),
                "n_samples": len(hsub),
            }

    if "model" in df.columns:
        for model in df["model"].dropna().unique():
            msub = df[df["model"] == model].tail(50)
            if msub.empty:
                continue
            summary["models"][model] = {
                "mae_pct": round(float(msub["abs_error_pct"].mean()), 3),
                "direction_accuracy": round(float(msub["direction_correct"].mean()), 3),
                "n_samples": len(msub),
            }

    os.makedirs("data", exist_ok=True)
    with open(PERFORMANCE_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return summary


def ensure_default_weights() -> None:
    if not os.path.exists(MODEL_WEIGHTS_PATH):
        save_model_weights({k: dict(v) for k, v in DEFAULT_ENSEMBLE_WEIGHTS.items()})
