"""
Walk-forward backtest: train the production predictor on history up to each cutoff
date, then compare forecasts to realized prices at calendar horizons (1, 7, 14, 30
days) — matching Prophet future steps (next day / week / biweekly / month).

Usage:
  python scripts/backtest_predictions.py
  python scripts/backtest_predictions.py --data data/final_data.csv --min-train 15
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Project root on path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from predictor import EnergyPricePredictor

PRODUCT_KEYS = {
    'RBOB_Gasoline': 'RBOB',
    'ULSD_Diesel': 'ULSD',
    'Crude_Oil': 'Crude',
}

from forecast_horizons import PREDICTION_HORIZONS

HORIZONS = tuple((key, days) for key, days, _, _ in PREDICTION_HORIZONS)


@dataclass
class ErrorRow:
    cutoff: pd.Timestamp
    product: str
    horizon: str
    pred: float
    actual: float


def load_final_data(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Data file not found: {path}")
    df = pd.read_csv(path)
    if df.empty or 'date' not in df.columns:
        raise ValueError("CSV must be non-empty and include a 'date' column")
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date']).sort_values('date').reset_index(drop=True)
    return df


def actual_on_or_after(full: pd.DataFrame, col: str, target: pd.Timestamp) -> Optional[float]:
    """First observed price for ``col`` on or after ``target`` (calendar alignment)."""
    sub = full.loc[full['date'] >= target]
    if sub.empty:
        return None
    val = sub.iloc[0][col]
    if pd.isna(val):
        return None
    return float(val)


def run_backtest(
    full: pd.DataFrame,
    min_train_rows: int,
    verbose: bool = False,
) -> Tuple[List[ErrorRow], str]:
    predictor = EnergyPricePredictor()
    errors: List[ErrorRow] = []
    last_model = ''

    for end in range(min_train_rows - 1, len(full) - 1):
        train = full.iloc[: end + 1].copy()
        last_date = train['date'].iloc[-1]
        preds = predictor.generate_predictions(train)
        if not preds:
            continue
        last_model = getattr(predictor, '_last_model_used', '')

        for pkey, col in PRODUCT_KEYS.items():
            if pkey not in preds or col not in full.columns:
                continue
            block = preds[pkey]
            if not block:
                continue
            for hname, days in HORIZONS:
                if hname not in block:
                    continue
                target = last_date + pd.Timedelta(days=days)
                act = actual_on_or_after(full, col, target)
                if act is None:
                    continue
                pred = float(block[hname])
                errors.append(
                    ErrorRow(
                        cutoff=last_date,
                        product=pkey,
                        horizon=hname,
                        pred=pred,
                        actual=act,
                    )
                )
        if verbose:
            print(f"  cutoff {last_date.date()} model={last_model} ok")

    return errors, last_model


def summarize(errors: List[ErrorRow]) -> None:
    if not errors:
        print("No backtest points (need more history after cutoffs, or predictions empty).")
        return

    df = pd.DataFrame([e.__dict__ for e in errors])
    df['abs_err'] = (df['pred'] - df['actual']).abs()
    df['ape'] = (df['abs_err'] / df['actual'].replace(0, np.nan)) * 100.0

    print("\nWalk-forward backtest (calendar horizons vs first price on/after target date)")
    print("=" * 72)
    for (product, horizon), g in df.groupby(['product', 'horizon']):
        mae = g['abs_err'].mean()
        mape = g['ape'].dropna().mean()
        n = len(g)
        print(f"  {product:16} {horizon:10}  n={n:4}  MAE={mae:.6f}  MAPE={mape:.2f}%")

    print("\nOverall by horizon")
    print("-" * 72)
    for horizon, g in df.groupby('horizon'):
        mae = g['abs_err'].mean()
        mape = g['ape'].dropna().mean()
        print(f"  {horizon:10}  n={len(g):4}  MAE={mae:.6f}  MAPE={mape:.2f}%")


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward prediction backtest")
    parser.add_argument(
        '--data',
        default=os.path.join(_ROOT, 'data', 'final_data.csv'),
        help='Path to final_data.csv',
    )
    parser.add_argument(
        '--min-train',
        type=int,
        default=15,
        help='Minimum rows of history before first cutoff (VAR needs ~10+ complete rows)',
    )
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()

    full = load_final_data(args.data)
    if len(full) < args.min_train + 2:
        print(
            f"Need at least min_train+2 rows (have {len(full)}, min_train={args.min_train})."
        )
        sys.exit(1)

    errors, _ = run_backtest(full, args.min_train, verbose=args.verbose)
    summarize(errors)


if __name__ == '__main__':
    main()
