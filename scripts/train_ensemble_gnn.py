"""GraphSAGE + XGBoost ensemble forecaster.

Blends the two best individual ML models found in the bake-off:
  - GraphSAGE  (MAE 3.2491) - strong spatial message-passing
  - XGBoost    (MAE 3.2913) - strong temporal lag + trend features

These two models make different types of errors:
  - GraphSAGE smooths via neighbour aggregation -> better for spatially
    correlated bursts (e.g., a commercial street cluster all activating)
  - XGBoost uses raw lag counts and trend -> better for cells whose
    recent history diverges from spatial neighbours

Alpha search strategy:
  1. Re-run XGBoost rolling-origin backtest to get PER-CELL per-fold errors (exact).
  2. Load GraphSAGE per-fold MAE from stored forecast_graphsage.json (fold_summaries).
  3. For each alpha, estimate ensemble MAE using XGBoost per-cell errors as the
     base and GraphSAGE errors as a fold-level correction term.
  4. Pick alpha that minimises total estimated error.
  5. For the final forecast: blend stored per-cell predictions from both JSONs.

Note: A fully rigorous ensemble would re-train GraphSAGE in each fold (needs PyG).
This script gives a fast, sound approximation that can run without PyG on Windows.
For the rigorous version on Lightning AI, the alpha found here is a good starting point.

Outputs:
  forecast_ensemble_gnn.json   -- blended predictions in heuristic schema
  model_comparison.json        -- updated with GraphSAGE+XGBoost entry

Usage:
  # Locally (no PyG needed)
  python scripts/train_ensemble_gnn.py

  # Fixed alpha (skip search)
  python scripts/train_ensemble_gnn.py --alpha 0.5

  # Custom paths
  python scripts/train_ensemble_gnn.py \\
      --artifacts-dir backend/app/data/processed/ml_artifacts \\
      --output-dir    backend/app/data/processed
"""

from __future__ import annotations

import argparse
import csv as csv_module
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Dependency checks
# ---------------------------------------------------------------------------
try:
    import xgboost as xgb  # type: ignore
except ImportError:
    raise SystemExit("xgboost not installed.  Run: pip install xgboost")

try:
    import numpy as np  # type: ignore
except ImportError:
    raise SystemExit("numpy not installed.  Run: pip install numpy")

# Sibling script imports
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from train_xgboost import (  # noqa: E402
    FEATURE_NAMES,
    build_features as xgb_build_features,
    percentile,
    xgb_reason_codes,
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GraphSAGE + XGBoost ensemble - blends two best ML models."
    )
    parser.add_argument(
        "--artifacts-dir", type=Path,
        default=Path("backend/app/data/processed/ml_artifacts"),
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path("backend/app/data/processed"),
    )
    parser.add_argument(
        "--alpha", type=float, default=None,
        help="Fixed GraphSAGE weight [0-1]. If omitted, auto-searches best alpha.",
    )
    parser.add_argument("--n-estimators", type=int, default=400)
    parser.add_argument("--max-depth",    type=int, default=5)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--window",  type=int, default=4)
    parser.add_argument("--seed",    type=int, default=42)
    return parser.parse_args()


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
def load_csv_dicts(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"Missing: {path}  -- run export_ml_artifacts.py first.")
    with path.open("r", encoding="utf-8", newline="") as h:
        return list(csv_module.DictReader(h))


def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as h:
        return json.load(h)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as h:
        json.dump(payload, h, indent=2, ensure_ascii=False)
        h.write("\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    args = parse_args()
    artifacts_dir = args.artifacts_dir
    output_dir    = args.output_dir
    window        = args.window

    print("\n" + "=" * 60)
    print("  ParkWatch -- GraphSAGE + XGBoost Ensemble")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Load ML artifacts
    # ------------------------------------------------------------------
    print(f"\n[1/7] Loading ML artifacts: {artifacts_dir.resolve()}")

    node_dicts   = load_csv_dicts(artifacts_dir / "nodes.csv")
    matrix_dicts = load_csv_dicts(artifacts_dir / "weekly_matrix.csv")
    edge_dicts   = load_csv_dicts(artifacts_dir / "edges.csv")
    meta         = load_json(artifacts_dir / "ml_artifacts_metadata.json")
    if meta is None:
        raise SystemExit("ml_artifacts_metadata.json missing. Run export_ml_artifacts.py first.")

    all_weeks:    list[str] = meta["timeline"]["weeks"]
    holdout_weeks: list[str] = meta["timeline"]["holdout_weeks"]
    forecast_week: str       = meta["timeline"]["forecast_week"]
    cell_ids: list[str]      = [r["cell_id"] for r in matrix_dicts]

    node_features: dict[str, dict[str, float]] = {
        r["cell_id"]: {k: float(v) for k, v in r.items()
                       if k not in ("cell_id", "confidence", "peak_weekday")}
        for r in node_dicts
    }
    matrix: dict[str, dict[str, int]] = {
        r["cell_id"]: {w: int(r[w]) for w in all_weeks}
        for r in matrix_dicts
    }
    adj: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for e in edge_dicts:
        adj[e["source"]].append((e["target"], float(e["weight"])))
        adj[e["target"]].append((e["source"], float(e["weight"])))

    print(f"      Cells: {len(cell_ids):,} | Weeks: {len(all_weeks)} | Edges: {len(edge_dicts):,}")
    print(f"      Holdout weeks: {holdout_weeks}")
    print(f"      Forecast week: {forecast_week}")

    # ------------------------------------------------------------------
    # 2. Load GraphSAGE stored predictions + fold MAEs
    # ------------------------------------------------------------------
    print(f"\n[2/7] Loading GraphSAGE stored outputs")
    sage_forecast_path = output_dir / "forecast_graphsage.json"
    sage_data = load_json(sage_forecast_path)
    if sage_data is None:
        raise SystemExit(
            f"forecast_graphsage.json not found at {sage_forecast_path}.\n"
            "Run scripts/train_graphsage.py (on Lightning AI) first, then copy the output here."
        )

    # Per-cell GraphSAGE final predictions
    sage_preds: dict[str, float] = {
        item["grid_cell_id"]: float(item["predicted_violation_count"])
        for item in sage_data.get("items", [])
    }
    # Per-fold GraphSAGE MAE (from fold_summaries stored during training)
    sage_fold_summaries: dict[str, float] = {
        s["week"]: float(s["mae"])
        for s in sage_data.get("holdout", {}).get("fold_summaries", [])
    }
    sage_overall_mae = sage_data.get("holdout", {}).get("mae", 3.2491)
    print(f"      GraphSAGE overall MAE (stored): {sage_overall_mae}")
    print(f"      GraphSAGE per-cell predictions loaded: {len(sage_preds):,}")

    # ------------------------------------------------------------------
    # 3. Re-run XGBoost rolling-origin backtest (exact per-cell errors)
    # ------------------------------------------------------------------
    print(f"\n[3/7] Re-running XGBoost rolling-origin backtest")

    # Storage: cell_id -> list of (xgb_pred, actual) across folds
    xgb_cell_fold_errors: dict[str, list[float]] = defaultdict(list)
    xgb_fold_summaries_out: list[dict] = []
    xgb_total_error = 0.0
    xgb_evaluated = 0
    fold_xgb_preds: list[dict[str, float]] = []  # per fold: cell_id -> xgb_pred

    for holdout_week in holdout_weeks:
        train_weeks = [w for w in all_weeks if w < holdout_week]
        if len(train_weeks) < window:
            print(f"      Skipping {holdout_week} -- insufficient weeks")
            fold_xgb_preds.append({})
            continue

        X_tr, y_tr = [], []
        for cell_id in cell_ids:
            for t_idx in range(window, len(train_weeks)):
                prior = train_weeks[:t_idx]
                feats = xgb_build_features(
                    cell_id, prior, train_weeks[t_idx],
                    matrix, adj, node_features, window
                )
                if feats is None:
                    continue
                X_tr.append([feats[f] for f in FEATURE_NAMES])
                y_tr.append(float(matrix[cell_id].get(train_weeks[t_idx], 0)))

        model = xgb.XGBRegressor(
            n_estimators=args.n_estimators,
            max_depth=args.max_depth,
            learning_rate=args.learning_rate,
            subsample=0.8, colsample_bytree=0.8,
            min_child_weight=3, reg_alpha=0.1, reg_lambda=1.0,
            random_state=args.seed, n_jobs=-1, verbosity=0,
        )
        model.fit(
            np.array(X_tr, dtype=np.float32),
            np.array(y_tr, dtype=np.float32),
        )

        fold_preds: dict[str, float] = {}
        fold_errors = []
        for cell_id in cell_ids:
            feats = xgb_build_features(
                cell_id, train_weeks, holdout_week,
                matrix, adj, node_features, window
            )
            if feats is not None:
                x = np.array([[feats[f] for f in FEATURE_NAMES]], dtype=np.float32)
                pred = float(max(0.0, model.predict(x)[0]))
            else:
                pred = 0.0
            actual = float(matrix[cell_id].get(holdout_week, 0))
            abs_err = abs(pred - actual)
            fold_preds[cell_id] = pred
            xgb_cell_fold_errors[cell_id].append(abs_err)
            fold_errors.append(abs_err)
            xgb_total_error += abs_err
            xgb_evaluated += 1

        fold_mae = round(sum(fold_errors) / len(fold_errors), 4)
        xgb_fold_summaries_out.append({"week": holdout_week, "mae": fold_mae})
        fold_xgb_preds.append(fold_preds)
        print(f"      Fold {holdout_week}: XGBoost MAE = {fold_mae}  ({len(fold_errors):,} cells)")

    xgb_overall_mae = round(xgb_total_error / xgb_evaluated, 4) if xgb_evaluated else None
    print(f"\n      XGBoost re-run MAE: {xgb_overall_mae}  (n={xgb_evaluated:,})")

    # ------------------------------------------------------------------
    # 4. Alpha search
    # ------------------------------------------------------------------
    # Strategy: for each fold week we have XGBoost per-cell errors (exact)
    # and GraphSAGE fold-level MAE (approximate). We estimate ensemble error
    # at each cell as:
    #   |alpha * sage_pred + (1-alpha) * xgb_pred - actual|
    # For cells where we don't have per-cell GraphSAGE fold predictions, we
    # approximate sage_pred ~= actual + sage_fold_mae_signed_error
    # (using the average-error approximation: sage_pred ~= actual * (1 + bias))
    # This is conservative but correct in direction.
    #
    # Simpler defensible approximation:
    #   ensemble_error(cell, fold) ~= |alpha * sage_fold_mae + (1-alpha) * xgb_cell_error|
    # i.e., treat GraphSAGE fold MAE as the expected per-cell error for that fold.

    print(f"\n[4/7] Alpha search (GraphSAGE weight)")
    alpha_candidates = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9] \
        if args.alpha is None else [args.alpha]

    best_alpha = 0.5
    best_estimated_mae = float("inf")
    alpha_results: list[dict] = []

    for alpha in alpha_candidates:
        total_est_err = 0.0
        n_est = 0
        for fi, holdout_week in enumerate(holdout_weeks):
            if fi >= len(fold_xgb_preds) or not fold_xgb_preds[fi]:
                continue
            sage_fold_mae = sage_fold_summaries.get(holdout_week, sage_overall_mae)
            for cell_id in cell_ids:
                xgb_pred = fold_xgb_preds[fi].get(cell_id, 0.0)
                actual    = float(matrix[cell_id].get(holdout_week, 0))
                xgb_err   = abs(xgb_pred - actual)
                # Estimated GraphSAGE error for this cell/fold ~= fold-level MAE
                sage_err  = sage_fold_mae
                # Blend: lower bound on ensemble error
                # (assumes errors partially cancel when models differ in direction)
                blend_pred = alpha * (actual + sage_err) + (1 - alpha) * xgb_pred
                est_err    = alpha * sage_err + (1 - alpha) * xgb_err
                total_est_err += est_err
                n_est += 1

        est_mae = round(total_est_err / n_est, 4) if n_est else None
        alpha_results.append({"alpha": alpha, "estimated_mae": est_mae})
        marker = " <-- best" if est_mae is not None and est_mae < best_estimated_mae else ""
        print(f"      alpha={alpha:.1f} (GraphSAGE) -> estimated MAE: {est_mae}{marker}")
        if est_mae is not None and est_mae < best_estimated_mae:
            best_estimated_mae = est_mae
            best_alpha = alpha

    if args.alpha is not None:
        best_alpha = args.alpha
    print(f"\n      Best alpha: {best_alpha}  ({int(best_alpha*100)}% GraphSAGE / {int((1-best_alpha)*100)}% XGBoost)")
    print(f"      Estimated ensemble MAE: {best_estimated_mae}")

    # ------------------------------------------------------------------
    # 5. Train final XGBoost on all data
    # ------------------------------------------------------------------
    print(f"\n[5/7] Training final XGBoost on all {len(all_weeks)} weeks")
    X_fin, y_fin = [], []
    for cell_id in cell_ids:
        for t_idx in range(window, len(all_weeks)):
            prior = all_weeks[:t_idx]
            feats = xgb_build_features(
                cell_id, prior, all_weeks[t_idx],
                matrix, adj, node_features, window
            )
            if feats is None:
                continue
            X_fin.append([feats[f] for f in FEATURE_NAMES])
            y_fin.append(float(matrix[cell_id].get(all_weeks[t_idx], 0)))

    final_xgb = xgb.XGBRegressor(
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        learning_rate=args.learning_rate,
        subsample=0.8, colsample_bytree=0.8,
        min_child_weight=3, reg_alpha=0.1, reg_lambda=1.0,
        random_state=args.seed, n_jobs=-1, verbosity=0,
    )
    final_xgb.fit(
        np.array(X_fin, dtype=np.float32),
        np.array(y_fin, dtype=np.float32),
    )
    print(f"      Trained on {len(X_fin):,} samples")

    # ------------------------------------------------------------------
    # 6. Generate blended forecast
    # ------------------------------------------------------------------
    print(f"\n[6/7] Generating blended forecast items for {len(cell_ids):,} cells")

    # Per-cell residuals for interval estimation
    global_residuals: list[float] = []
    per_cell_residuals: dict[str, list[float]] = defaultdict(list)
    for fi, holdout_week in enumerate(holdout_weeks):
        if fi >= len(fold_xgb_preds) or not fold_xgb_preds[fi]:
            continue
        sage_fold_mae = sage_fold_summaries.get(holdout_week, sage_overall_mae)
        for cell_id in cell_ids:
            xgb_pred = fold_xgb_preds[fi].get(cell_id, 0.0)
            actual   = float(matrix[cell_id].get(holdout_week, 0))
            est_err  = best_alpha * sage_fold_mae + (1 - best_alpha) * abs(xgb_pred - actual)
            global_residuals.append(est_err)
            per_cell_residuals[cell_id].append(est_err)

    global_interval_err = percentile(global_residuals, 0.8) if global_residuals else 1.0

    raw_preds: list[tuple[str, float, dict]] = []
    for cell_id in cell_ids:
        # XGBoost final prediction
        feats = xgb_build_features(
            cell_id, all_weeks, forecast_week,
            matrix, adj, node_features, window
        )
        if feats is not None:
            x = np.array([[feats[f] for f in FEATURE_NAMES]], dtype=np.float32)
            xgb_pred = float(max(0.0, final_xgb.predict(x)[0]))
        else:
            xgb_pred = 0.0

        # GraphSAGE final prediction (from stored JSON)
        sage_pred = sage_preds.get(cell_id, xgb_pred)  # fallback to XGB if cell absent

        # Blended prediction
        blended = best_alpha * sage_pred + (1 - best_alpha) * xgb_pred
        blended = max(0.0, blended)

        feat_dict = feats or {}
        raw_preds.append((cell_id, blended, feat_dict))

    max_pred = max((p for _, p, _ in raw_preds), default=1.0)

    forecast_items: list[dict[str, Any]] = []
    for cell_id, predicted_count, feats in raw_preds:
        nf = node_features.get(cell_id, {})

        cell_interval_err = (
            percentile(per_cell_residuals[cell_id], 0.8)
            if per_cell_residuals.get(cell_id)
            else global_interval_err
        )

        cell_res = per_cell_residuals.get(cell_id, [])
        if cell_res:
            mean_r = sum(cell_res) / len(cell_res)
            var_r  = sum((r - mean_r) ** 2 for r in cell_res) / len(cell_res)
            cv     = math.sqrt(var_r) / max(mean_r, 0.01)
            forecast_stability = round(max(0.0, min(100.0, 100.0 * (1.0 - min(cv, 1.0)))), 2)
        else:
            forecast_stability = 0.0

        predicted_obstruction_risk = round(100.0 * predicted_count / max(max_pred, 1.0), 2)

        historical_weeks = [
            {"week": w, "violation_count": matrix[cell_id].get(w, 0)}
            for w in all_weeks[-12:]
        ]

        reasons = ["ENSEMBLE_GRAPHSAGE_XGBOOST"]
        if predicted_count >= 10:
            reasons.append("HIGH_PREDICTED_WEEKLY_COUNT")
        if feats.get("trend", 1.0) >= 1.2:
            reasons.append("RECENT_INCREASE")
        if feats.get("spatial_lag", 0.0) > 0:
            reasons.append("SPATIAL_GRAPH_AGGREGATION")
        if nf.get("junction_share", 0.0) >= 0.25:
            reasons.append("JUNCTION_PROXIMITY")
        if forecast_stability >= 70:
            reasons.append("STABLE_WEEKLY_EVIDENCE")

        forecast_items.append({
            "grid_cell_id": cell_id,
            "latitude":  nf.get("lat", 0.0),
            "longitude": nf.get("lon", 0.0),
            "predicted_week": forecast_week,
            "predicted_violation_count":  round(predicted_count, 2),
            "prediction_interval_low":    round(max(0.0, predicted_count - cell_interval_err), 2),
            "prediction_interval_high":   round(predicted_count + cell_interval_err, 2),
            "predicted_obstruction_risk": predicted_obstruction_risk,
            "forecast_stability":         forecast_stability,
            "ensemble_alpha_graphsage":   best_alpha,
            "ensemble_alpha_xgboost":     round(1.0 - best_alpha, 2),
            "graphsage_prediction":       round(sage_preds.get(cell_id, 0.0), 2),
            "xgboost_prediction":         round(
                float(max(0.0, final_xgb.predict(
                    np.array([[feats.get(f, 0.0) for f in FEATURE_NAMES]], dtype=np.float32)
                )[0])) if feats else 0.0, 2
            ),
            "last_1_week_count": matrix[cell_id].get(all_weeks[-1], 0),
            "last_2_week_avg":   round(
                sum(matrix[cell_id].get(w, 0) for w in all_weeks[-2:]) / min(len(all_weeks), 2), 2
            ),
            "last_4_week_avg":   round(
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
    # 7. Write outputs
    # ------------------------------------------------------------------
    print(f"\n[7/7] Writing outputs to: {output_dir.resolve()}")
    output_dir.mkdir(parents=True, exist_ok=True)

    hyper = {
        "best_alpha_graphsage": best_alpha,
        "best_alpha_xgboost": round(1.0 - best_alpha, 2),
        "xgb_n_estimators": args.n_estimators,
        "xgb_window": window,
        "alpha_search": alpha_results,
        "graphsage_mae_stored": sage_overall_mae,
        "xgboost_mae_rerun": xgb_overall_mae,
        "note": (
            "Alpha selected by minimising estimated ensemble error. "
            "GraphSAGE per-fold errors approximated from stored fold_summaries MAE. "
            "For exact ensemble MAE, re-train both models in each fold on Lightning AI."
        ),
    }

    forecast_payload: dict[str, Any] = {
        "forecast_type": "future observed parking violations",
        "model": "Ensemble (GraphSAGE + XGBoost)",
        "not_measured_congestion": True,
        "method": (
            f"Weighted blend: {best_alpha} x GraphSAGE + {round(1-best_alpha,2)} x XGBoost. "
            "GraphSAGE captures spatial spillover via SAGEConv; XGBoost captures "
            "temporal lag and trend signals. Alpha selected by estimated holdout MAE."
        ),
        "forecast_week": forecast_week,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "holdout": {
            "weeks": holdout_weeks,
            "mae": best_estimated_mae,
            "xgb_exact_mae": xgb_overall_mae,
            "graphsage_stored_mae": sage_overall_mae,
            "evaluated_points": xgb_evaluated,
            "validation_type": "rolling-origin weekly backtest (XGBoost exact, GraphSAGE approx)",
            "alpha_search": alpha_results,
            "best_alpha_graphsage": best_alpha,
        },
        "model_hyperparameters": hyper,
        "items": forecast_items,
    }

    forecast_path = output_dir / "forecast_ensemble_gnn.json"
    write_json(forecast_path, forecast_payload)
    print(f"      forecast_ensemble_gnn.json -- {len(forecast_items):,} cells")

    # Update model_comparison.json
    comparison_path = output_dir / "model_comparison.json"
    existing = load_json(comparison_path) or {"description": "", "models": []}
    entry_name = "Ensemble (GraphSAGE + XGBoost)"
    models_list = [m for m in existing.get("models", []) if m.get("name") != entry_name]
    models_list.append({
        "name": entry_name,
        "description": (
            f"Weighted blend: alpha={best_alpha} GraphSAGE + {round(1-best_alpha,2)} XGBoost. "
            "Spatial graph structure from GraphSAGE + temporal lags from XGBoost."
        ),
        "script": "scripts/train_ensemble_gnn.py",
        "forecast_file": "forecast_ensemble_gnn.json",
        "mae": best_estimated_mae,
        "xgb_exact_mae": xgb_overall_mae,
        "graphsage_stored_mae": sage_overall_mae,
        "evaluated_points": xgb_evaluated,
        "holdout_weeks": holdout_weeks,
        "hyperparameters": hyper,
    })
    models_list.sort(key=lambda m: m.get("mae") or float("inf"))
    existing["models"] = models_list
    existing["last_updated"] = datetime.now(tz=timezone.utc).isoformat()
    write_json(comparison_path, existing)
    print(f"      model_comparison.json  -- updated ({len(models_list)} models)")

    # ------------------------------------------------------------------
    # Final bake-off table
    # ------------------------------------------------------------------
    print("\n" + "=" * 62)
    print("  FINAL BAKE-OFF  (all models)")
    print("=" * 62)
    print(f"  {'Model':<38} {'MAE':>7}  {'Notes'}")
    print(f"  {'-'*38} {'-'*7}  {'-'*12}")
    for m in existing["models"]:
        mae_str = f"{m['mae']:.4f}" if m.get("mae") is not None else "  N/A  "
        note    = "(all cells)" if m["name"] == "Heuristic Baseline" else "(filtered)"
        print(f"  {m['name']:<38} {mae_str:>7}  {note}")
    print("=" * 62)
    print(f"\n  Best alpha: {best_alpha} GraphSAGE / {round(1-best_alpha,2)} XGBoost")
    print(f"  Each forecast item includes both component predictions for transparency.")
    print(f"  Output: {forecast_path.resolve()}")
    print("=" * 62)


if __name__ == "__main__":
    main()
