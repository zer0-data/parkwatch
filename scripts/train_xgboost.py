"""XGBoost sliding-window violation count forecaster.

Reads the ML artifacts produced by export_ml_artifacts.py and trains an
XGBRegressor using rolling-origin cross-validation (identical holdout weeks
to the heuristic baseline, so MAE comparison is fair).

Feature engineering per (cell, target_week) sample:
  Temporal lags:
    lag_1 .. lag_4      - violation count for each of the 4 prior weeks
    avg_2               - mean of lag_1, lag_2
    avg_4               - mean of lag_1 .. lag_4
    prev_avg_4          - mean of weeks T-8..T-5 (baseline for trend)
    trend               - avg_4 / prev_avg_4, clamped to [0.35, 2.0]
  Spatial:
    spatial_lag         - edge-weight-averaged neighbour avg_4 counts
  Static node features:
    mean_severity, junction_share, high_share, temporal_concentration,
    active_days, active_weeks, device_days, neighbor_influence

Outputs:
  forecast_xgboost.json      - predictions in same schema as forecast.json
  model_comparison.json      - updated bake-off table (MAE / MAPE / n)

Usage:
  # From the repo root after running export_ml_artifacts.py
  python scripts/train_xgboost.py

  # Custom paths
  python scripts/train_xgboost.py \\
      --artifacts-dir backend/app/data/processed/ml_artifacts \\
      --output-dir    backend/app/data/processed \\
      --n-estimators  400 \\
      --window        4
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Optional dependency check - give a clear message before crashing
# ---------------------------------------------------------------------------
try:
    import xgboost as xgb  # type: ignore
except ImportError:
    raise SystemExit(
        "\nxgboost is not installed.\n"
        "Install it with:  pip install xgboost\n"
        "Then re-run this script."
    )

try:
    import numpy as np  # type: ignore
except ImportError:
    raise SystemExit(
        "\nnumpy is not installed.\n"
        "Install it with:  pip install numpy\n"
        "Then re-run this script."
    )

# Allow importing helpers from sibling scripts
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from preprocess_official_csv import next_iso_week_label  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WINDOW = 4        # number of prior weeks used as input
QUANTILE_80 = 0.8 # percentile for prediction intervals (mirrors heuristic)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train XGBoost violation-count forecaster and write forecast_xgboost.json."
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path("backend/app/data/processed/ml_artifacts"),
        help="Directory containing nodes.csv, weekly_matrix.csv, edges.csv "
             "(output of export_ml_artifacts.py).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("backend/app/data/processed"),
        help="Directory to write forecast_xgboost.json and model_comparison.json.",
    )
    parser.add_argument(
        "--n-estimators",
        type=int,
        default=400,
        help="Number of XGBoost trees (default 400).",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=5,
        help="Maximum XGBoost tree depth (default 5).",
    )
    parser.add_argument(
        "--learning-rate",
        type=float,
        default=0.05,
        help="XGBoost learning rate / eta (default 0.05).",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=WINDOW,
        help="Number of prior weeks used as lag features (default 4).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
def load_csv_dicts(path: Path) -> list[dict[str, str]]:
    """Read a CSV file into a list of string-keyed dicts."""
    if not path.exists():
        raise SystemExit(
            f"Missing file: {path}\n"
            "Run  python scripts/export_ml_artifacts.py  first."
        )
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------
def compute_spatial_lag(
    cell_id: str,
    adj: dict[str, list[tuple[str, float]]],
    matrix: dict[str, dict[str, int]],
    weeks: list[str],
    window: int,
) -> float:
    """Weighted average of neighbour avg_4 counts.

    For each neighbour of cell_id, compute the average count over the
    most recent `window` training weeks and weight by edge weight.
    """
    neighbours = adj.get(cell_id, [])
    if not neighbours:
        return 0.0
    weighted_sum = 0.0
    weight_sum = 0.0
    recent = weeks[-window:] if len(weeks) >= window else weeks
    for neighbour_id, weight in neighbours:
        nb_counts = matrix.get(neighbour_id, {})
        nb_avg = sum(nb_counts.get(w, 0) for w in recent) / max(len(recent), 1)
        weighted_sum += nb_avg * weight
        weight_sum += weight
    return weighted_sum / weight_sum if weight_sum > 0 else 0.0


def build_features(
    cell_id: str,
    train_weeks: list[str],   # all weeks strictly before the target
    target_week: str,
    matrix: dict[str, dict[str, int]],
    adj: dict[str, list[tuple[str, float]]],
    node_features: dict[str, dict[str, float]],
    window: int,
) -> dict[str, float] | None:
    """Return a flat feature dict for one (cell, target_week) pair.

    Returns None if there are not enough prior weeks to fill the window.
    """
    if len(train_weeks) < window:
        return None

    counts = matrix.get(cell_id, {})
    recent_weeks = train_weeks[-window:]  # last `window` weeks before target

    # --- Temporal lag features ---
    lags = [counts.get(w, 0) for w in reversed(recent_weeks)]
    # lags[0] = most recent, lags[window-1] = oldest in window
    lag_1 = float(lags[0])
    lag_2 = float(lags[1]) if len(lags) > 1 else 0.0
    lag_3 = float(lags[2]) if len(lags) > 2 else 0.0
    lag_4 = float(lags[3]) if len(lags) > 3 else 0.0

    avg_2 = (lag_1 + lag_2) / 2.0
    avg_4 = sum(float(x) for x in lags[:4]) / min(window, 4)

    # Previous window (for trend) - weeks T-8..T-5
    prev_weeks = train_weeks[-2 * window: -window]
    if prev_weeks:
        prev_avg_4 = sum(counts.get(w, 0) for w in prev_weeks) / len(prev_weeks)
    else:
        prev_avg_4 = avg_4  # no prior window -> assume flat trend

    if prev_avg_4 <= 0:
        trend = 1.5 if avg_4 > 0 else 1.0
    else:
        trend = avg_4 / prev_avg_4
    trend = float(min(max(trend, 0.35), 2.0))

    # --- Spatial lag ---
    spatial_lag = compute_spatial_lag(cell_id, adj, matrix, train_weeks, window)

    # --- Static node features ---
    nf = node_features.get(cell_id, {})
    mean_severity = nf.get("mean_severity", 0.0)
    junction_share = nf.get("junction_share", 0.0)
    high_share = nf.get("high_share", 0.0)
    temporal_conc = nf.get("temporal_concentration", 0.0)
    active_days = nf.get("active_days", 0.0)
    active_weeks_count = nf.get("active_weeks", 0.0)
    device_days = nf.get("device_days", 0.0)
    neighbor_inf = nf.get("neighbor_influence", 0.0)

    return {
        "lag_1": lag_1,
        "lag_2": lag_2,
        "lag_3": lag_3,
        "lag_4": lag_4,
        "avg_2": avg_2,
        "avg_4": avg_4,
        "prev_avg_4": prev_avg_4,
        "trend": trend,
        "spatial_lag": spatial_lag,
        "mean_severity": mean_severity,
        "junction_share": junction_share,
        "high_share": high_share,
        "temporal_concentration": temporal_conc,
        "active_days": active_days,
        "active_weeks": active_weeks_count,
        "device_days": device_days,
        "neighbor_influence": neighbor_inf,
    }


FEATURE_NAMES = [
    "lag_1", "lag_2", "lag_3", "lag_4",
    "avg_2", "avg_4", "prev_avg_4", "trend",
    "spatial_lag",
    "mean_severity", "junction_share", "high_share",
    "temporal_concentration", "active_days", "active_weeks",
    "device_days", "neighbor_influence",
]


# ---------------------------------------------------------------------------
# Percentile helper (mirrors heuristic's implementation)
# ---------------------------------------------------------------------------
def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, max(0, math.ceil((len(s) - 1) * quantile)))
    return s[idx]


# ---------------------------------------------------------------------------
# Forecast reason codes (XGBoost-specific)
# ---------------------------------------------------------------------------
def xgb_reason_codes(
    predicted_count: float,
    trend: float,
    spatial_lag: float,
    mean_severity: float,
    junction_share: float,
    forecast_stability: float,
) -> list[str]:
    reasons = ["XGB_FORECAST_OF_OBSERVED_VIOLATIONS"]
    if predicted_count >= 10:
        reasons.append("HIGH_PREDICTED_WEEKLY_COUNT")
    if trend >= 1.2:
        reasons.append("RECENT_INCREASE")
    if spatial_lag > 0:
        reasons.append("GRAPH_NEIGHBOUR_ACTIVITY")
    if mean_severity >= 2.0:
        reasons.append("HIGH_MEAN_SEVERITY")
    if junction_share >= 0.25:
        reasons.append("JUNCTION_PROXIMITY")
    if forecast_stability >= 70:
        reasons.append("STABLE_WEEKLY_EVIDENCE")
    return reasons


# ---------------------------------------------------------------------------
# Model comparison updater
# ---------------------------------------------------------------------------
def update_model_comparison(
    path: Path,
    model_entry: dict[str, Any],
) -> None:
    """Read existing model_comparison.json (if any), update this model's entry, write back."""
    existing: dict[str, Any] = load_json(path) or {
        "description": "Rolling-origin holdout MAE/MAPE comparison across models. "
                       "All models use the identical holdout weeks for fair comparison.",
        "models": [],
    }
    # Replace entry for this model name if it already exists
    models: list[dict] = existing.get("models", [])
    models = [m for m in models if m.get("name") != model_entry["name"]]
    models.append(model_entry)
    # Sort by MAE ascending (lower is better; None last)
    models.sort(key=lambda m: m.get("mae") or float("inf"))
    existing["models"] = models
    existing["last_updated"] = datetime.now(tz=timezone.utc).isoformat()
    write_json(path, existing)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    args = parse_args()
    artifacts_dir = args.artifacts_dir
    output_dir = args.output_dir
    window = args.window

    print("\n" + "=" * 60)
    print("  ParkWatch - XGBoost Forecaster")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Load artifacts
    # ------------------------------------------------------------------
    print(f"\n[1/6] Loading ML artifacts from: {artifacts_dir.resolve()}")

    node_dicts = load_csv_dicts(artifacts_dir / "nodes.csv")
    print(f"      nodes.csv          - {len(node_dicts):,} cells")

    matrix_dicts = load_csv_dicts(artifacts_dir / "weekly_matrix.csv")
    print(f"      weekly_matrix.csv  - {len(matrix_dicts):,} cells")

    edge_dicts = load_csv_dicts(artifacts_dir / "edges.csv")
    print(f"      edges.csv          - {len(edge_dicts):,} edges")

    # Load metadata to get week list and holdout weeks
    meta = load_json(artifacts_dir / "ml_artifacts_metadata.json")
    if meta is None:
        raise SystemExit(
            "ml_artifacts_metadata.json not found. "
            "Run export_ml_artifacts.py first."
        )
    all_weeks: list[str] = meta["timeline"]["weeks"]
    holdout_weeks: list[str] = meta["timeline"]["holdout_weeks"]
    forecast_week: str = meta["timeline"]["forecast_week"]

    print(f"      ISO weeks          - {len(all_weeks)}  ({all_weeks[0]} -> {all_weeks[-1]})")
    print(f"      Holdout weeks      - {holdout_weeks}")
    print(f"      Forecast target    - {forecast_week}")

    # ------------------------------------------------------------------
    # Build in-memory structures
    # ------------------------------------------------------------------
    print("\n[2/6] Building in-memory structures")

    # node_features: cell_id -> {feature_name -> float}
    node_features: dict[str, dict[str, float]] = {}
    for row in node_dicts:
        cell_id = row["cell_id"]
        node_features[cell_id] = {
            k: float(v) for k, v in row.items()
            if k not in ("cell_id", "confidence", "peak_weekday")
        }

    # matrix: cell_id -> {week -> int}
    cell_ids = [row["cell_id"] for row in matrix_dicts]
    matrix: dict[str, dict[str, int]] = {}
    for row in matrix_dicts:
        cell_id = row["cell_id"]
        matrix[cell_id] = {w: int(row[w]) for w in all_weeks}

    # adjacency list: cell_id -> [(neighbour_id, weight)]
    adj: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for edge in edge_dicts:
        src, tgt, w = edge["source"], edge["target"], float(edge["weight"])
        adj[src].append((tgt, w))
        adj[tgt].append((src, w))

    print(f"      Cells : {len(cell_ids):,}")
    print(f"      Adj   : {len(adj):,} cells have at least one neighbour")

    # ------------------------------------------------------------------
    # Rolling-origin backtest
    # ------------------------------------------------------------------
    print(f"\n[3/6] Rolling-origin backtest (window = {window} weeks)")
    print(f"      Holdout weeks: {holdout_weeks}")

    error_sum = 0.0
    ape_sum = 0.0
    evaluated_points = 0
    residuals_by_cell: dict[str, list[float]] = defaultdict(list)
    global_residuals: list[float] = []

    fold_summaries: list[dict] = []

    for holdout_week in holdout_weeks:
        train_weeks = [w for w in all_weeks if w < holdout_week]
        if len(train_weeks) < window:
            print(f"      Skipping {holdout_week} - not enough training weeks ({len(train_weeks)} < {window})")
            continue

        # Build training set: all (cell, week) pairs where target < holdout_week
        # and there are enough prior weeks
        X_train_rows, y_train = [], []
        for cell_id in cell_ids:
            for t_idx in range(window, len(train_weeks)):
                t_week = train_weeks[t_idx]
                prior_weeks = train_weeks[:t_idx]
                feats = build_features(
                    cell_id, prior_weeks, t_week, matrix, adj, node_features, window
                )
                if feats is None:
                    continue
                X_train_rows.append([feats[f] for f in FEATURE_NAMES])
                y_train.append(float(matrix[cell_id].get(t_week, 0)))

        if not X_train_rows:
            print(f"      Skipping {holdout_week} - no training samples generated")
            continue

        X_train = np.array(X_train_rows, dtype=np.float32)
        y_train_arr = np.array(y_train, dtype=np.float32)

        # Train XGBoost
        model = xgb.XGBRegressor(
            n_estimators=args.n_estimators,
            max_depth=args.max_depth,
            learning_rate=args.learning_rate,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=3,
            reg_alpha=0.1,
            reg_lambda=1.0,
            random_state=args.seed,
            n_jobs=-1,
            verbosity=0,
        )
        model.fit(X_train, y_train_arr)

        # Evaluate on holdout week
        fold_errors = []
        for cell_id in cell_ids:
            feats = build_features(
                cell_id, train_weeks, holdout_week, matrix, adj, node_features, window
            )
            if feats is None:
                continue
            x = np.array([[feats[f] for f in FEATURE_NAMES]], dtype=np.float32)
            predicted = float(max(0.0, model.predict(x)[0]))
            actual = float(matrix[cell_id].get(holdout_week, 0))
            abs_err = abs(predicted - actual)
            error_sum += abs_err
            fold_errors.append(abs_err)
            global_residuals.append(abs_err)
            residuals_by_cell[cell_id].append(abs_err)
            if actual > 0:
                ape_sum += abs_err / actual
            evaluated_points += 1

        fold_mae = sum(fold_errors) / len(fold_errors) if fold_errors else 0.0
        fold_summaries.append({"week": holdout_week, "mae": round(fold_mae, 4), "n": len(fold_errors)})
        print(f"      Fold {holdout_week}: MAE = {fold_mae:.4f}  (n = {len(fold_errors):,})")

    mae = round(error_sum / evaluated_points, 4) if evaluated_points else None
    mape = round((ape_sum / evaluated_points) * 100.0, 4) if evaluated_points else None
    print(f"\n      -- Holdout MAE  : {mae}")
    print(f"         Holdout MAPE : {mape}%")
    print(f"         Total points : {evaluated_points:,}")

    # ------------------------------------------------------------------
    # Train final model on ALL weeks, predict forecast week
    # ------------------------------------------------------------------
    print(f"\n[4/6] Training final model on all {len(all_weeks)} weeks -> predicting {forecast_week}")

    X_final_rows, y_final = [], []
    for cell_id in cell_ids:
        for t_idx in range(window, len(all_weeks)):
            t_week = all_weeks[t_idx]
            prior_weeks = all_weeks[:t_idx]
            feats = build_features(
                cell_id, prior_weeks, t_week, matrix, adj, node_features, window
            )
            if feats is None:
                continue
            X_final_rows.append([feats[f] for f in FEATURE_NAMES])
            y_final.append(float(matrix[cell_id].get(t_week, 0)))

    X_final = np.array(X_final_rows, dtype=np.float32)
    y_final_arr = np.array(y_final, dtype=np.float32)

    final_model = xgb.XGBRegressor(
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        learning_rate=args.learning_rate,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=3,
        reg_alpha=0.1,
        reg_lambda=1.0,
        random_state=args.seed,
        n_jobs=-1,
        verbosity=0,
    )
    final_model.fit(X_final, y_final_arr)
    print(f"      Final model trained on {len(X_final_rows):,} samples")

    # Feature importance summary
    importances = final_model.feature_importances_
    top_features = sorted(
        zip(FEATURE_NAMES, importances), key=lambda x: x[1], reverse=True
    )[:5]
    print("      Top-5 features by importance:")
    for fname, imp in top_features:
        print(f"        {fname:<28} {imp:.4f}")

    # ------------------------------------------------------------------
    # Generate forecast items
    # ------------------------------------------------------------------
    print(f"\n[5/6] Generating forecast items for {len(cell_ids):,} cells")

    global_interval_err = percentile(global_residuals, QUANTILE_80) if global_residuals else 1.0
    raw_predictions: list[tuple[str, float, dict]] = []

    for cell_id in cell_ids:
        feats = build_features(
            cell_id, all_weeks, forecast_week, matrix, adj, node_features, window
        )
        if feats is None:
            predicted_count = 0.0
        else:
            x = np.array([[feats[f] for f in FEATURE_NAMES]], dtype=np.float32)
            predicted_count = float(max(0.0, final_model.predict(x)[0]))
        raw_predictions.append((cell_id, predicted_count, feats or {}))

    max_prediction = max((p for _, p, _ in raw_predictions), default=1.0)

    forecast_items: list[dict[str, Any]] = []
    for cell_id, predicted_count, feats in raw_predictions:
        nf = node_features.get(cell_id, {})
        cell_interval_err = (
            percentile(residuals_by_cell[cell_id], QUANTILE_80)
            if residuals_by_cell.get(cell_id)
            else global_interval_err
        )
        interval_low = max(0.0, predicted_count - cell_interval_err)
        interval_high = predicted_count + cell_interval_err

        # Forecast stability: how consistent are the per-fold residuals for this cell?
        cell_residuals = residuals_by_cell.get(cell_id, [])
        if cell_residuals:
            residual_cv = (
                (sum((r - (sum(cell_residuals) / len(cell_residuals))) ** 2 for r in cell_residuals)
                 / len(cell_residuals)) ** 0.5
                / max(sum(cell_residuals) / len(cell_residuals), 0.01)
            )
            forecast_stability = round(
                max(0.0, min(100.0, 100.0 * (1.0 - min(residual_cv, 1.0)))), 2
            )
        else:
            forecast_stability = 0.0

        # predicted_obstruction_risk: relative rank within batch (mirrors heuristic)
        predicted_obstruction_risk = round(
            100.0 * predicted_count / max(max_prediction, 1.0), 2
        )

        # Historical window for display
        historical_weeks = [
            {"week": w, "violation_count": matrix[cell_id].get(w, 0)}
            for w in all_weeks[-12:]
        ]

        trend_val = feats.get("trend", 1.0)
        spatial_lag_val = feats.get("spatial_lag", 0.0)
        mean_sev = nf.get("mean_severity", 0.0)
        junc_share = nf.get("junction_share", 0.0)

        forecast_items.append(
            {
                "grid_cell_id": cell_id,
                "latitude": nf.get("lat", 0.0),
                "longitude": nf.get("lon", 0.0),
                "predicted_week": forecast_week,
                "predicted_violation_count": round(predicted_count, 2),
                "prediction_interval_low": round(interval_low, 2),
                "prediction_interval_high": round(interval_high, 2),
                "predicted_obstruction_risk": predicted_obstruction_risk,
                "forecast_stability": forecast_stability,
                "last_1_week_count": matrix[cell_id].get(all_weeks[-1], 0),
                "last_2_week_avg": round(
                    sum(matrix[cell_id].get(w, 0) for w in all_weeks[-2:])
                    / min(len(all_weeks), 2),
                    2,
                ),
                "last_4_week_avg": round(
                    sum(matrix[cell_id].get(w, 0) for w in all_weeks[-4:])
                    / min(len(all_weeks), 4),
                    2,
                ),
                "historical_weeks": historical_weeks,
                "features_used": {k: round(feats.get(k, 0.0), 4) for k in FEATURE_NAMES},
                "forecast_reason_codes": xgb_reason_codes(
                    predicted_count, trend_val, spatial_lag_val,
                    mean_sev, junc_share, forecast_stability,
                ),
                "reason_codes": xgb_reason_codes(
                    predicted_count, trend_val, spatial_lag_val,
                    mean_sev, junc_share, forecast_stability,
                ),
            }
        )

    # Sort by predicted count descending
    forecast_items.sort(
        key=lambda it: (it["predicted_violation_count"], it["grid_cell_id"]),
        reverse=True,
    )

    # ------------------------------------------------------------------
    # Write forecast_xgboost.json
    # ------------------------------------------------------------------
    print(f"\n[6/6] Writing outputs to: {output_dir.resolve()}")

    output_dir.mkdir(parents=True, exist_ok=True)
    xgb_model_meta = {
        "n_estimators": args.n_estimators,
        "max_depth": args.max_depth,
        "learning_rate": args.learning_rate,
        "window": window,
        "seed": args.seed,
        "top_features": [
            {"feature": fname, "importance": round(float(imp), 4)}
            for fname, imp in top_features
        ],
    }

    forecast_payload: dict[str, Any] = {
        "forecast_type": "future observed parking violations",
        "model": "XGBoost",
        "not_measured_congestion": True,
        "method": (
            f"XGBoost sliding-window regressor (window={window} weeks). "
            "Features: lag_1..lag_4, rolling averages, trend ratio, spatial lag "
            "(edge-weighted neighbour avg), and static node features "
            "(mean_severity, junction_share, high_share, active_days, etc.). "
            "Training: rolling-origin holdout matching the heuristic baseline protocol."
        ),
        "forecast_week": forecast_week,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "holdout": {
            "weeks": holdout_weeks,
            "mae": mae,
            "mape": mape,
            "evaluated_points": evaluated_points,
            "validation_type": "rolling-origin weekly backtest",
            "fold_summaries": fold_summaries,
        },
        "model_hyperparameters": xgb_model_meta,
        "items": forecast_items,
    }

    forecast_path = output_dir / "forecast_xgboost.json"
    write_json(forecast_path, forecast_payload)
    print(f"      forecast_xgboost.json  - {len(forecast_items):,} cells")

    # ------------------------------------------------------------------
    # Update model_comparison.json
    # ------------------------------------------------------------------
    comparison_path = output_dir / "model_comparison.json"

    # Try to read heuristic MAE from existing forecast.json for comparison
    baseline_entry = None
    heuristic_forecast = load_json(output_dir / "forecast.json")
    if heuristic_forecast and "holdout" in heuristic_forecast:
        h = heuristic_forecast["holdout"]
        baseline_entry = {
            "name": "Heuristic Baseline",
            "description": "Hand-weighted formula: last1/last2/last4 counts, trend, "
                           "station-normalized activity, graph-neighbour influence.",
            "script": "scripts/preprocess_official_csv.py",
            "forecast_file": "forecast.json",
            "mae": h.get("mae"),
            "mape": h.get("mape"),
            "evaluated_points": h.get("evaluated_points"),
            "holdout_weeks": h.get("weeks"),
        }

    xgb_entry: dict[str, Any] = {
        "name": "XGBoost",
        "description": (
            f"XGBRegressor with {window}-week lag window, spatial lag, "
            "and static node features."
        ),
        "script": "scripts/train_xgboost.py",
        "forecast_file": "forecast_xgboost.json",
        "mae": mae,
        "mape": mape,
        "evaluated_points": evaluated_points,
        "holdout_weeks": holdout_weeks,
        "hyperparameters": xgb_model_meta,
    }

    existing_comparison = load_json(comparison_path) or {
        "description": (
            "Rolling-origin holdout MAE/MAPE comparison across all models. "
            "Identical holdout weeks ensure fair comparison."
        ),
        "models": [],
    }
    models_list: list[dict] = existing_comparison.get("models", [])
    # Insert heuristic if it's not already there and we found it
    if baseline_entry:
        models_list = [m for m in models_list if m.get("name") != "Heuristic Baseline"]
        models_list.append(baseline_entry)
    models_list = [m for m in models_list if m.get("name") != "XGBoost"]
    models_list.append(xgb_entry)
    models_list.sort(key=lambda m: m.get("mae") or float("inf"))

    existing_comparison["models"] = models_list
    existing_comparison["last_updated"] = datetime.now(tz=timezone.utc).isoformat()
    write_json(comparison_path, existing_comparison)
    print(f"      model_comparison.json  - updated ({len(models_list)} models tracked)")

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  XGBOOST TRAINING COMPLETE")
    print("=" * 60)
    if baseline_entry and baseline_entry.get("mae") is not None and mae is not None:
        baseline_mae = baseline_entry["mae"]
        delta = mae - baseline_mae
        direction = "better down" if delta < 0 else "worse up"
        print(f"  Heuristic baseline MAE : {baseline_mae}")
        print(f"  XGBoost MAE            : {mae}  ({direction} by {abs(delta):.4f})")
    else:
        print(f"  XGBoost MAE            : {mae}")
    print(f"  XGBoost MAPE           : {mape}%")
    print(f"  Evaluated points       : {evaluated_points:,}")
    print(f"  Forecast cells         : {len(forecast_items):,}")
    print(f"  forecast_xgboost.json  : {forecast_path.resolve()}")
    print(f"  model_comparison.json  : {comparison_path.resolve()}")
    print("=" * 60)
    print("\nNext step (Lightning AI): python scripts/train_graphsage.py")


if __name__ == "__main__":
    main()
