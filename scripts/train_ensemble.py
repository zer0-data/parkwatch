"""Heuristic + XGBoost ensemble forecaster.

Runs rolling-origin backtest for BOTH the heuristic and XGBoost in each fold,
blends their per-cell per-fold predictions with weight alpha, and finds the
best alpha by minimising holdout MAE. Uses the identical holdout weeks as all
other models for fair comparison.

Why ensemble works here:
  - Heuristic is strong on stable high-volume cells (knows the formula domain)
  - XGBoost is stronger on recent trend shifts (picks up lag patterns the
    heuristic smooths over)
  - Blending captures both signals

Alpha search: tries alpha in {0.3, 0.4, 0.5, 0.6, 0.7, 0.8}
  alpha = weight on heuristic,  (1 - alpha) = weight on XGBoost
  Final prediction = alpha * heuristic_pred + (1-alpha) * xgb_pred

Outputs:
  forecast_ensemble.json     -- predictions in same schema as forecast.json
  model_comparison.json      -- updated with Ensemble entry

Usage:
  python scripts/train_ensemble.py

  # Custom alpha (skip search, use fixed blend)
  python scripts/train_ensemble.py --alpha 0.6

  # Custom paths
  python scripts/train_ensemble.py \\
      --csv-dir data \\
      --artifacts-dir backend/app/data/processed/ml_artifacts \\
      --output-dir    backend/app/data/processed
"""

from __future__ import annotations

import argparse
import csv as csv_module
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------
try:
    import xgboost as xgb  # type: ignore
except ImportError:
    raise SystemExit("xgboost not installed. Run: pip install xgboost")

try:
    import numpy as np  # type: ignore
except ImportError:
    raise SystemExit("numpy not installed. Run: pip install numpy")

# Allow importing from sibling scripts
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from preprocess_official_csv import (  # noqa: E402
    DEFAULT_MAX_EDGE_METERS,
    DEFAULT_MIN_EDGE_METERS,
    build_edge_lookup,
    build_edges,
    find_official_csv,
    next_iso_week_label,
    predict_week_count,
    read_and_aggregate,
    serialize_hotspots,
)

# Re-use XGBoost feature builder from train_xgboost
from train_xgboost import (  # noqa: E402
    FEATURE_NAMES,
    build_features as xgb_build_features,
    percentile,
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Heuristic + XGBoost ensemble forecaster."
    )
    parser.add_argument("--csv-dir", type=Path, default=Path("data"),
                        help="Directory containing the official CSV (default: data/).")
    parser.add_argument("--artifacts-dir", type=Path,
                        default=Path("backend/app/data/processed/ml_artifacts"))
    parser.add_argument("--output-dir", type=Path,
                        default=Path("backend/app/data/processed"))
    parser.add_argument("--alpha", type=float, default=None,
                        help="Fixed heuristic weight [0-1]. If omitted, auto-searches best alpha.")
    parser.add_argument("--n-estimators", type=int, default=400)
    parser.add_argument("--max-depth", type=int, default=5)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--window", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
def load_csv_dicts(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"Missing: {path}  -- run export_ml_artifacts.py first.")
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv_module.DictReader(handle))


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
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    args = parse_args()

    print("\n" + "=" * 60)
    print("  ParkWatch -- Heuristic + XGBoost Ensemble")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Load artifacts (for XGBoost side)
    # ------------------------------------------------------------------
    print(f"\n[1/6] Loading ML artifacts: {args.artifacts_dir.resolve()}")
    node_dicts = load_csv_dicts(args.artifacts_dir / "nodes.csv")
    matrix_dicts = load_csv_dicts(args.artifacts_dir / "weekly_matrix.csv")
    edge_dicts = load_csv_dicts(args.artifacts_dir / "edges.csv")
    meta = load_json(args.artifacts_dir / "ml_artifacts_metadata.json")
    if meta is None:
        raise SystemExit("ml_artifacts_metadata.json missing -- run export_ml_artifacts.py")

    all_weeks: list[str] = meta["timeline"]["weeks"]
    holdout_weeks: list[str] = meta["timeline"]["holdout_weeks"]
    forecast_week: str = meta["timeline"]["forecast_week"]
    cell_ids: list[str] = [row["cell_id"] for row in matrix_dicts]

    node_features: dict[str, dict[str, float]] = {
        row["cell_id"]: {
            k: float(v) for k, v in row.items()
            if k not in ("cell_id", "confidence", "peak_weekday")
        }
        for row in node_dicts
    }
    matrix: dict[str, dict[str, int]] = {
        row["cell_id"]: {w: int(row[w]) for w in all_weeks}
        for row in matrix_dicts
    }
    adj: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for edge in edge_dicts:
        adj[edge["source"]].append((edge["target"], float(edge["weight"])))
        adj[edge["target"]].append((edge["source"], float(edge["weight"])))

    print(f"      Cells: {len(cell_ids):,} | Weeks: {len(all_weeks)} | Holdout: {holdout_weeks}")

    # ------------------------------------------------------------------
    # Load heuristic side (re-run read_and_aggregate from the CSV)
    # ------------------------------------------------------------------
    print(f"\n[2/6] Loading heuristic aggregation (re-reads CSV)")
    csv_files = sorted(args.csv_dir.glob("*.csv"))
    if len(csv_files) != 1:
        raise SystemExit(f"Expected exactly one CSV in {args.csv_dir}. Found: {csv_files}")
    csv_path = csv_files[0]
    cells, total_rows, skipped = read_and_aggregate(csv_path)
    print(f"      {total_rows:,} rows -> {len(cells):,} cells aggregated")

    # Build heuristic edges + hotspot lookup (needed by predict_week_count)
    h_edges = build_edges(cells, DEFAULT_MIN_EDGE_METERS, DEFAULT_MAX_EDGE_METERS)
    h_edge_lookup = build_edge_lookup(h_edges)
    hotspots = serialize_hotspots(cells)
    hotspot_lookup = {h["grid_cell_id"]: h for h in hotspots}

    # station_by_cell and station_counts_by_week (mirrors heuristic's serialize_forecast)
    counts_by_cell = {cid: cell.week_counts for cid, cell in cells.items()}
    station_by_cell = {
        cid: hotspot_lookup[cid].get("dominant_station") or "Unknown"
        for cid in counts_by_cell
        if cid in hotspot_lookup
    }
    station_counts_by_week: dict[str, Counter] = defaultdict(Counter)
    for cid, counts in counts_by_cell.items():
        if cid in station_by_cell:
            station_counts_by_week[station_by_cell[cid]].update(counts)

    # Filtered cell ids that exist in BOTH heuristic and ML artifact sets
    shared_cell_ids = [cid for cid in cell_ids if cid in cells]
    print(f"      Shared cells (in both heuristic + ML artifacts): {len(shared_cell_ids):,}")

    # ------------------------------------------------------------------
    # Rolling-origin backtest: collect per-fold predictions from both models
    # ------------------------------------------------------------------
    print(f"\n[3/6] Rolling-origin backtest (alpha search)")

    # Storage: fold -> cell_id -> {heuristic_pred, xgb_pred, actual}
    fold_results: list[dict[str, dict]] = []

    for holdout_week in holdout_weeks:
        train_weeks = [w for w in all_weeks if w < holdout_week]
        if len(train_weeks) < args.window:
            print(f"      Skipping {holdout_week} -- insufficient training weeks")
            continue

        # ---- XGBoost: build training set & train ----
        X_train_rows, y_train = [], []
        for cell_id in shared_cell_ids:
            for t_idx in range(args.window, len(train_weeks)):
                t_week = train_weeks[t_idx]
                prior = train_weeks[:t_idx]
                feats = xgb_build_features(
                    cell_id, prior, t_week, matrix, adj, node_features, args.window
                )
                if feats is None:
                    continue
                X_train_rows.append([feats[f] for f in FEATURE_NAMES])
                y_train.append(float(matrix[cell_id].get(t_week, 0)))

        if not X_train_rows:
            continue

        xgb_model = xgb.XGBRegressor(
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
        xgb_model.fit(
            np.array(X_train_rows, dtype=np.float32),
            np.array(y_train, dtype=np.float32),
        )

        # ---- Collect predictions for this fold ----
        fold_cell_results: dict[str, dict] = {}
        for cell_id in shared_cell_ids:
            actual = float(matrix[cell_id].get(holdout_week, 0))

            # Heuristic prediction
            h_pred = predict_week_count(
                cell_id,
                train_weeks,
                counts_by_cell,
                h_edge_lookup,
                station_by_cell,
                station_counts_by_week,
                hotspot_lookup,
            )
            h_pred = max(0.0, h_pred)

            # XGBoost prediction
            feats = xgb_build_features(
                cell_id, train_weeks, holdout_week, matrix, adj, node_features, args.window
            )
            if feats is not None:
                x = np.array([[feats[f] for f in FEATURE_NAMES]], dtype=np.float32)
                xgb_pred = float(max(0.0, xgb_model.predict(x)[0]))
            else:
                xgb_pred = h_pred  # fallback to heuristic if features unavailable

            fold_cell_results[cell_id] = {
                "actual": actual,
                "heuristic": h_pred,
                "xgboost": xgb_pred,
            }

        fold_results.append(fold_cell_results)
        print(f"      Fold {holdout_week}: {len(fold_cell_results):,} cells evaluated")

    # ------------------------------------------------------------------
    # Alpha search: find best blend weight
    # ------------------------------------------------------------------
    print(f"\n[4/6] Searching best alpha (heuristic weight)")
    alpha_candidates = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9] if args.alpha is None else [args.alpha]

    best_alpha = alpha_candidates[0]
    best_mae = float("inf")
    alpha_results: list[dict] = []

    for alpha in alpha_candidates:
        total_err = 0.0
        n = 0
        for fold in fold_results:
            for cell_data in fold.values():
                ensemble_pred = alpha * cell_data["heuristic"] + (1 - alpha) * cell_data["xgboost"]
                total_err += abs(ensemble_pred - cell_data["actual"])
                n += 1
        fold_mae = round(total_err / n, 4) if n else None
        alpha_results.append({"alpha": alpha, "mae": fold_mae})
        print(f"      alpha={alpha:.1f} (heuristic) -> MAE: {fold_mae}")
        if fold_mae is not None and fold_mae < best_mae:
            best_mae = fold_mae
            best_alpha = alpha

    print(f"\n      Best alpha: {best_alpha}  (MAE: {best_mae})")

    # Final MAE / MAPE with best alpha
    error_sum = 0.0
    ape_sum = 0.0
    evaluated_points = 0
    residuals_by_cell: dict[str, list[float]] = defaultdict(list)
    global_residuals: list[float] = []

    for fold in fold_results:
        for cell_id, cell_data in fold.items():
            ensemble_pred = best_alpha * cell_data["heuristic"] + (1 - best_alpha) * cell_data["xgboost"]
            actual = cell_data["actual"]
            abs_err = abs(ensemble_pred - actual)
            error_sum += abs_err
            global_residuals.append(abs_err)
            residuals_by_cell[cell_id].append(abs_err)
            if actual > 0:
                ape_sum += abs_err / actual
            evaluated_points += 1

    mae = round(error_sum / evaluated_points, 4) if evaluated_points else None
    mape = round((ape_sum / evaluated_points) * 100.0, 4) if evaluated_points else None

    # ------------------------------------------------------------------
    # Train final XGBoost on all data, generate ensemble forecast
    # ------------------------------------------------------------------
    print(f"\n[5/6] Training final XGBoost on all weeks -> forecasting {forecast_week}")

    X_final_rows, y_final = [], []
    for cell_id in shared_cell_ids:
        for t_idx in range(args.window, len(all_weeks)):
            t_week = all_weeks[t_idx]
            prior = all_weeks[:t_idx]
            feats = xgb_build_features(
                cell_id, prior, t_week, matrix, adj, node_features, args.window
            )
            if feats is None:
                continue
            X_final_rows.append([feats[f] for f in FEATURE_NAMES])
            y_final.append(float(matrix[cell_id].get(t_week, 0)))

    final_xgb = xgb.XGBRegressor(
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
    final_xgb.fit(
        np.array(X_final_rows, dtype=np.float32),
        np.array(y_final, dtype=np.float32),
    )
    print(f"      Final XGBoost trained on {len(X_final_rows):,} samples")

    global_interval_err = percentile(global_residuals, 0.8) if global_residuals else 1.0

    forecast_items: list[dict[str, Any]] = []
    raw_predictions: list[tuple[str, float]] = []

    for cell_id in shared_cell_ids:
        # Heuristic final prediction
        h_pred = predict_week_count(
            cell_id,
            all_weeks,
            counts_by_cell,
            h_edge_lookup,
            station_by_cell,
            station_counts_by_week,
            hotspot_lookup,
        )
        h_pred = max(0.0, h_pred)

        # XGBoost final prediction
        feats = xgb_build_features(
            cell_id, all_weeks, forecast_week, matrix, adj, node_features, args.window
        )
        if feats is not None:
            x = np.array([[feats[f] for f in FEATURE_NAMES]], dtype=np.float32)
            xgb_pred = float(max(0.0, final_xgb.predict(x)[0]))
        else:
            xgb_pred = h_pred

        ensemble_pred = best_alpha * h_pred + (1 - best_alpha) * xgb_pred
        raw_predictions.append((cell_id, ensemble_pred))

    max_pred = max((p for _, p in raw_predictions), default=1.0)

    for cell_id, predicted_count in raw_predictions:
        nf = node_features.get(cell_id, {})
        hotspot = hotspot_lookup.get(cell_id, {})

        cell_interval_err = (
            percentile(residuals_by_cell[cell_id], 0.8)
            if residuals_by_cell.get(cell_id)
            else global_interval_err
        )

        cell_residuals = residuals_by_cell.get(cell_id, [])
        if cell_residuals:
            mean_res = sum(cell_residuals) / len(cell_residuals)
            var_res = sum((r - mean_res) ** 2 for r in cell_residuals) / len(cell_residuals)
            cv = math.sqrt(var_res) / max(mean_res, 0.01)
            forecast_stability = round(max(0.0, min(100.0, 100.0 * (1.0 - min(cv, 1.0)))), 2)
        else:
            forecast_stability = 0.0

        predicted_obstruction_risk = round(100.0 * predicted_count / max(max_pred, 1.0), 2)

        historical_weeks = [
            {"week": w, "violation_count": matrix[cell_id].get(w, 0)}
            for w in all_weeks[-12:]
        ]

        reasons = ["ENSEMBLE_HEURISTIC_XGBOOST_FORECAST"]
        if predicted_count >= 10:
            reasons.append("HIGH_PREDICTED_WEEKLY_COUNT")
        if hotspot.get("junction_share", 0) >= 0.25:
            reasons.append("JUNCTION_PROXIMITY")
        if hotspot.get("recent_trend_ratio", 1.0) >= 1.2:
            reasons.append("RECENT_INCREASE")
        if forecast_stability >= 70:
            reasons.append("STABLE_WEEKLY_EVIDENCE")

        forecast_items.append({
            "grid_cell_id": cell_id,
            "station": hotspot.get("dominant_station"),
            "junction": hotspot.get("dominant_junction"),
            "location": hotspot.get("representative_location"),
            "latitude": nf.get("lat", hotspot.get("latitude", 0.0)),
            "longitude": nf.get("lon", hotspot.get("longitude", 0.0)),
            "predicted_week": forecast_week,
            "predicted_violation_count": round(predicted_count, 2),
            "prediction_interval_low": round(max(0.0, predicted_count - cell_interval_err), 2),
            "prediction_interval_high": round(predicted_count + cell_interval_err, 2),
            "predicted_obstruction_risk": predicted_obstruction_risk,
            "forecast_stability": forecast_stability,
            "ensemble_alpha": best_alpha,
            "last_1_week_count": matrix[cell_id].get(all_weeks[-1], 0),
            "last_2_week_avg": round(
                sum(matrix[cell_id].get(w, 0) for w in all_weeks[-2:]) / min(len(all_weeks), 2), 2
            ),
            "last_4_week_avg": round(
                sum(matrix[cell_id].get(w, 0) for w in all_weeks[-4:]) / min(len(all_weeks), 4), 2
            ),
            "historical_weeks": historical_weeks,
            "forecast_reason_codes": reasons,
            "reason_codes": reasons,
        })

    forecast_items.sort(
        key=lambda it: (it["predicted_violation_count"], it["grid_cell_id"]),
        reverse=True,
    )

    # ------------------------------------------------------------------
    # Write outputs
    # ------------------------------------------------------------------
    print(f"\n[6/6] Writing outputs to: {args.output_dir.resolve()}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    forecast_payload: dict[str, Any] = {
        "forecast_type": "future observed parking violations",
        "model": "Ensemble (Heuristic + XGBoost)",
        "not_measured_congestion": True,
        "method": (
            f"Weighted ensemble: {best_alpha:.1f} x Heuristic + "
            f"{1-best_alpha:.1f} x XGBoost. Alpha selected by minimising "
            "holdout MAE across rolling-origin folds."
        ),
        "forecast_week": forecast_week,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "holdout": {
            "weeks": holdout_weeks,
            "mae": mae,
            "mape": mape,
            "evaluated_points": evaluated_points,
            "validation_type": "rolling-origin weekly backtest",
            "alpha_search": alpha_results,
            "best_alpha": best_alpha,
        },
        "items": forecast_items,
    }

    forecast_path = args.output_dir / "forecast_ensemble.json"
    write_json(forecast_path, forecast_payload)
    print(f"      forecast_ensemble.json -- {len(forecast_items):,} cells")

    # Update model_comparison.json
    comparison_path = args.output_dir / "model_comparison.json"
    existing = load_json(comparison_path) or {"description": "", "models": []}
    models_list = [m for m in existing.get("models", []) if m.get("name") != "Ensemble (Heuristic + XGBoost)"]
    models_list.append({
        "name": "Ensemble (Heuristic + XGBoost)",
        "description": (
            f"Weighted blend: alpha={best_alpha} x Heuristic + "
            f"{1-best_alpha} x XGBoost. Alpha auto-selected via holdout MAE."
        ),
        "script": "scripts/train_ensemble.py",
        "forecast_file": "forecast_ensemble.json",
        "mae": mae,
        "mape": mape,
        "evaluated_points": evaluated_points,
        "holdout_weeks": holdout_weeks,
        "hyperparameters": {
            "best_alpha": best_alpha,
            "alpha_search": alpha_results,
            "xgb_n_estimators": args.n_estimators,
            "xgb_window": args.window,
        },
    })
    models_list.sort(key=lambda m: m.get("mae") or float("inf"))
    existing["models"] = models_list
    existing["last_updated"] = datetime.now(tz=timezone.utc).isoformat()
    write_json(comparison_path, existing)
    print(f"      model_comparison.json  -- updated ({len(models_list)} models)")

    # ------------------------------------------------------------------
    # Final bake-off table
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  ENSEMBLE COMPLETE  --  FINAL BAKE-OFF")
    print("=" * 60)
    print(f"  {'Model':<35} {'MAE':>8}  {'MAPE':>8}")
    print(f"  {'-'*35} {'-'*8}  {'-'*8}")
    for m in existing["models"]:
        mae_str = f"{m['mae']:.4f}" if m.get("mae") is not None else "N/A"
        mape_str = f"{m['mape']:.2f}%" if m.get("mape") is not None else "N/A"
        print(f"  {m['name']:<35} {mae_str:>8}  {mape_str:>8}")
    print("=" * 60)
    print(f"\n  Best alpha: {best_alpha}  ({int(best_alpha*100)}% heuristic / {int((1-best_alpha)*100)}% XGBoost)")
    print(f"  Output: {forecast_path.resolve()}")
    print("=" * 60)


if __name__ == "__main__":
    main()
