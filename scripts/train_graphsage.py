"""GraphSAGE spatial violation-count forecaster.

Reads ML artifacts from export_ml_artifacts.py and trains a 2-layer
GraphSAGE network using PyTorch Geometric. This model is "pure spatial" -
the temporal history is encoded as independent input channels per node
(e.g. 4-week lag counts as 4 features), rather than a recurrent or
convolutional sequence. This isolates the value of spatial message passing
vs. the tabular XGBoost baseline.

Architecture:
  Input : (N, F)  - N cells, F features (lag_1..lag_4 + static node features)
  Layer 1: SAGEConv(F, 64) + ReLU + Dropout(0.3)
  Layer 2: SAGEConv(64, 32) + ReLU
  Head   : Linear(32, 1)  ->  predicted violation count

Training:
  Loss: MSE (smooth gradient for count regression)
  Eval: MAE (matches heuristic backtest metric)
  Same rolling-origin holdout weeks as heuristic and XGBoost.

Outputs:
  forecast_graphsage.json  - predictions in heuristic schema
  model_comparison.json    - updated bake-off table

Requirements (install on Lightning AI):
  conda install pytorch torchvision torchaudio pytorch-cuda=12.1 -c pytorch -c nvidia
  pip install torch-geometric
  # For torch-scatter / torch-sparse (Lightning AI conda resolves these):
  pip install pyg-lib torch-scatter torch-sparse \\
      -f https://data.pyg.org/whl/torch-2.x.x+cu121.html

Usage:
  python scripts/train_graphsage.py

  # GPU
  python scripts/train_graphsage.py --device cuda

  # Custom
  python scripts/train_graphsage.py \\
      --artifacts-dir backend/app/data/processed/ml_artifacts \\
      --output-dir    backend/app/data/processed \\
      --epochs        200 \\
      --lr            0.005 \\
      --device        cpu
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
# Dependency checks with clear error messages
# ---------------------------------------------------------------------------
try:
    import numpy as np  # type: ignore
except ImportError:
    raise SystemExit("numpy not installed. Run: pip install numpy")

try:
    import torch  # type: ignore
    import torch.nn as nn  # type: ignore
    import torch.nn.functional as F  # type: ignore
except ImportError:
    raise SystemExit("PyTorch not installed. Follow: https://pytorch.org/get-started/locally/")

try:
    from torch_geometric.nn import SAGEConv  # type: ignore
    from torch_geometric.data import Data  # type: ignore
    HAS_PYG = True
except ImportError:
    HAS_PYG = False
    print(
        "\n[WARNING] torch-geometric not found. "
        "GraphSAGE requires PyTorch Geometric.\n"
        "Install with:\n"
        "  pip install torch-geometric\n"
        "  pip install pyg-lib torch-scatter torch-sparse "
        "-f https://data.pyg.org/whl/torch-<version>+<cuda>.html\n"
        "Exiting.\n"
    )
    sys.exit(1)

# Allow importing helpers from sibling scripts
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from preprocess_official_csv import next_iso_week_label  # noqa: E402


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train 2-layer GraphSAGE forecaster and write forecast_graphsage.json."
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path("backend/app/data/processed/ml_artifacts"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("backend/app/data/processed"),
    )
    parser.add_argument("--epochs", type=int, default=200,
                        help="Training epochs per fold (default 200).")
    parser.add_argument("--lr", type=float, default=0.005,
                        help="Learning rate (default 0.005).")
    parser.add_argument("--hidden", type=int, default=64,
                        help="Hidden dimension for first SAGEConv layer (default 64).")
    parser.add_argument("--dropout", type=float, default=0.3,
                        help="Dropout probability (default 0.3).")
    parser.add_argument("--window", type=int, default=4,
                        help="Number of prior weeks used as lag channels (default 4).")
    parser.add_argument("--device", type=str, default="cpu",
                        choices=["cpu", "cuda"],
                        help="Compute device (default cpu).")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
def load_csv_dicts(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(
            f"Missing: {path}\nRun export_ml_artifacts.py first."
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
# GraphSAGE model definition
# ---------------------------------------------------------------------------
class GraphSAGEForecaster(nn.Module):
    """2-layer GraphSAGE regression head for weekly violation count prediction.

    Input node features:
      lag_1 .. lag_W   - violation counts for the W prior weeks
      mean_severity     - mean severity score (1=Low, 2=Medium, 3=High)
      junction_share    - fraction of violations at junctions
      high_share        - fraction of high-severity violations
      temporal_conc     - fraction of violations in peak hour
      active_days       - number of distinct active days (normalized)
      active_weeks      - number of distinct active weeks (normalized)
      device_days       - unique device-day pairs (normalized)
      neighbor_inf      - raw neighbour influence value (from edge weights)
    """

    def __init__(self, in_channels: int, hidden: int = 64, dropout: float = 0.3) -> None:
        super().__init__()
        self.conv1 = SAGEConv(in_channels, hidden)
        self.conv2 = SAGEConv(hidden, hidden // 2)
        self.head = nn.Linear(hidden // 2, 1)
        self.dropout = dropout

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        x = self.conv1(x, edge_index)
        x = F.relu(x)
        x = F.dropout(x, p=self.dropout, training=self.training)
        x = self.conv2(x, edge_index)
        x = F.relu(x)
        out = self.head(x)          # (N, 1)
        return out.squeeze(-1)       # (N,)


# ---------------------------------------------------------------------------
# Feature builder
# ---------------------------------------------------------------------------
STATIC_FEATURES = [
    "mean_severity", "junction_share", "high_share",
    "temporal_concentration", "active_days", "active_weeks",
    "device_days", "neighbor_influence",
]


def build_node_feature_matrix(
    cell_ids: list[str],
    matrix: dict[str, dict[str, int]],
    node_features: dict[str, dict[str, float]],
    train_weeks: list[str],
    window: int,
) -> np.ndarray:
    """Return (N, window + len(STATIC_FEATURES)) numpy array.

    For each node, the features are:
      [lag_1, lag_2, ..., lag_W, mean_severity, junction_share, ...]
    where lag_1 is the count in the most recent training week.
    """
    rows = []
    recent = train_weeks[-window:] if len(train_weeks) >= window else train_weeks
    for cell_id in cell_ids:
        counts = matrix.get(cell_id, {})
        lag_feats = [float(counts.get(w, 0)) for w in reversed(recent)]
        # Pad to window length if fewer weeks available
        while len(lag_feats) < window:
            lag_feats.append(0.0)

        nf = node_features.get(cell_id, {})
        static_feats = [nf.get(f, 0.0) for f in STATIC_FEATURES]
        rows.append(lag_feats + static_feats)
    return np.array(rows, dtype=np.float32)


def build_target_vector(
    cell_ids: list[str],
    matrix: dict[str, dict[str, int]],
    target_week: str,
) -> np.ndarray:
    return np.array(
        [float(matrix.get(cell_id, {}).get(target_week, 0)) for cell_id in cell_ids],
        dtype=np.float32,
    )


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------
def normalise(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Z-score normalisation. Returns (X_norm, mean, std)."""
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std == 0] = 1.0  # avoid division by zero for constant columns
    return (X - mean) / std, mean, std


# ---------------------------------------------------------------------------
# Percentile (mirrors heuristic)
# ---------------------------------------------------------------------------
def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, max(0, math.ceil((len(s) - 1) * q)))
    return s[idx]


# ---------------------------------------------------------------------------
# Reason codes
# ---------------------------------------------------------------------------
def sage_reason_codes(
    predicted: float,
    mean_severity: float,
    junction_share: float,
    high_share: float,
    forecast_stability: float,
) -> list[str]:
    reasons = ["GRAPHSAGE_FORECAST_OF_OBSERVED_VIOLATIONS"]
    if predicted >= 10:
        reasons.append("HIGH_PREDICTED_WEEKLY_COUNT")
    if mean_severity >= 2.0:
        reasons.append("HIGH_MEAN_SEVERITY")
    if junction_share >= 0.25:
        reasons.append("JUNCTION_PROXIMITY")
    if high_share >= 0.35:
        reasons.append("HIGH_SEVERITY_MIX")
    if forecast_stability >= 70:
        reasons.append("STABLE_WEEKLY_EVIDENCE")
    return reasons


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    args = parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    device = torch.device(args.device if torch.cuda.is_available() or args.device == "cpu" else "cpu")
    if args.device == "cuda" and not torch.cuda.is_available():
        print("[WARNING] CUDA not available, falling back to CPU")
        device = torch.device("cpu")

    print("\n" + "=" * 60)
    print("  ParkWatch - GraphSAGE Forecaster")
    print(f"  Device: {device}")
    print("=" * 60)

    artifacts_dir = args.artifacts_dir
    output_dir = args.output_dir
    window = args.window

    # ------------------------------------------------------------------
    # Load artifacts
    # ------------------------------------------------------------------
    print(f"\n[1/6] Loading ML artifacts from: {artifacts_dir.resolve()}")
    node_dicts = load_csv_dicts(artifacts_dir / "nodes.csv")
    matrix_dicts = load_csv_dicts(artifacts_dir / "weekly_matrix.csv")
    edge_dicts = load_csv_dicts(artifacts_dir / "edges.csv")
    meta = load_json(artifacts_dir / "ml_artifacts_metadata.json")
    if meta is None:
        raise SystemExit("ml_artifacts_metadata.json missing - run export_ml_artifacts.py")

    all_weeks: list[str] = meta["timeline"]["weeks"]
    holdout_weeks: list[str] = meta["timeline"]["holdout_weeks"]
    forecast_week: str = meta["timeline"]["forecast_week"]
    print(f"      Cells: {len(node_dicts):,} | Weeks: {len(all_weeks)} | Edges: {len(edge_dicts):,}")
    print(f"      Holdout: {holdout_weeks} | Forecast: {forecast_week}")

    # Build node index (ordered, stable)
    cell_ids: list[str] = [row["cell_id"] for row in matrix_dicts]
    cell_index: dict[str, int] = {cid: i for i, cid in enumerate(cell_ids)}
    N = len(cell_ids)

    # node_features dict
    node_features: dict[str, dict[str, float]] = {}
    for row in node_dicts:
        cid = row["cell_id"]
        node_features[cid] = {
            k: float(v) for k, v in row.items()
            if k not in ("cell_id", "confidence", "peak_weekday")
        }

    # matrix dict
    matrix: dict[str, dict[str, int]] = {}
    for row in matrix_dicts:
        cid = row["cell_id"]
        matrix[cid] = {w: int(row[w]) for w in all_weeks}

    # edge_index (COO format for PyG): shape (2, E)
    src_list, dst_list = [], []
    for edge in edge_dicts:
        s = cell_index.get(edge["source"])
        t = cell_index.get(edge["target"])
        if s is not None and t is not None:
            # Undirected: add both directions
            src_list.extend([s, t])
            dst_list.extend([t, s])
    edge_index = torch.tensor([src_list, dst_list], dtype=torch.long).to(device)
    print(f"      Graph: {N} nodes, {edge_index.shape[1] // 2} undirected edges")

    in_channels = window + len(STATIC_FEATURES)
    print(f"      Node feature dim: {in_channels} ({window} lags + {len(STATIC_FEATURES)} static)")

    # ------------------------------------------------------------------
    # Rolling-origin backtest
    # ------------------------------------------------------------------
    print(f"\n[2/6] Rolling-origin backtest")
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
            print(f"      Skipping {holdout_week} - only {len(train_weeks)} training weeks")
            continue

        # Build feature matrix and targets for all training time steps
        # We train on every (feature_week, target_week) pair within train_weeks
        X_list, y_list = [], []
        for t_idx in range(window, len(train_weeks)):
            prior = train_weeks[:t_idx]
            target = train_weeks[t_idx]
            X_step = build_node_feature_matrix(cell_ids, matrix, node_features, prior, window)
            y_step = build_target_vector(cell_ids, matrix, target)
            X_list.append(X_step)
            y_list.append(y_step)

        if not X_list:
            continue

        # Stack all time steps: shape (T_steps * N, F)
        X_all = np.vstack(X_list)
        y_all = np.concatenate(y_list)

        # Normalise features
        X_norm, feat_mean, feat_std = normalise(X_all)

        # Build per-step PyG Data objects for training
        # (Each step uses the same edge_index but different node features)
        model = GraphSAGEForecaster(in_channels, hidden=args.hidden, dropout=args.dropout).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=50, gamma=0.5)

        # We train epoch-by-epoch over all time steps (each as a separate graph snapshot)
        n_steps = len(X_list)
        model.train()
        for epoch in range(args.epochs):
            total_loss = 0.0
            for step_i in range(n_steps):
                X_step_norm = (X_list[step_i] - feat_mean) / feat_std
                x_tensor = torch.tensor(X_step_norm, dtype=torch.float32).to(device)
                y_tensor = torch.tensor(y_list[step_i], dtype=torch.float32).to(device)

                optimizer.zero_grad()
                pred = model(x_tensor, edge_index)
                loss = F.mse_loss(pred, y_tensor)
                loss.backward()
                optimizer.step()
                total_loss += loss.item()
            scheduler.step()
            if (epoch + 1) % 50 == 0:
                avg_loss = total_loss / n_steps
                print(f"        [{holdout_week}] Epoch {epoch+1:3d}/{args.epochs} - MSE loss: {avg_loss:.4f}")

        # Evaluate on holdout week
        model.eval()
        X_holdout = build_node_feature_matrix(cell_ids, matrix, node_features, train_weeks, window)
        X_holdout_norm = (X_holdout - feat_mean) / feat_std
        x_h = torch.tensor(X_holdout_norm, dtype=torch.float32).to(device)
        with torch.no_grad():
            preds_h = model(x_h, edge_index).cpu().numpy()
        preds_h = np.maximum(preds_h, 0.0)

        fold_errors = []
        for i, cell_id in enumerate(cell_ids):
            predicted = float(preds_h[i])
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
        print(f"      Fold {holdout_week}: MAE = {fold_mae:.4f}")

    mae = round(error_sum / evaluated_points, 4) if evaluated_points else None
    mape = round((ape_sum / evaluated_points) * 100.0, 4) if evaluated_points else None
    print(f"\n      -- Holdout MAE  : {mae}")
    print(f"         Holdout MAPE : {mape}%")
    print(f"         Total points : {evaluated_points:,}")

    # ------------------------------------------------------------------
    # Train final model on ALL weeks
    # ------------------------------------------------------------------
    print(f"\n[3/6] Training final model on all {len(all_weeks)} weeks -> predicting {forecast_week}")

    X_list_final, y_list_final = [], []
    for t_idx in range(window, len(all_weeks)):
        prior = all_weeks[:t_idx]
        target = all_weeks[t_idx]
        X_step = build_node_feature_matrix(cell_ids, matrix, node_features, prior, window)
        y_step = build_target_vector(cell_ids, matrix, target)
        X_list_final.append(X_step)
        y_list_final.append(y_step)

    X_all_final = np.vstack(X_list_final)
    _, feat_mean_final, feat_std_final = normalise(X_all_final)

    final_model = GraphSAGEForecaster(in_channels, hidden=args.hidden, dropout=args.dropout).to(device)
    final_optimizer = torch.optim.Adam(final_model.parameters(), lr=args.lr, weight_decay=1e-4)
    final_scheduler = torch.optim.lr_scheduler.StepLR(final_optimizer, step_size=50, gamma=0.5)

    n_steps_final = len(X_list_final)
    final_model.train()
    for epoch in range(args.epochs):
        total_loss = 0.0
        for step_i in range(n_steps_final):
            X_step_norm = (X_list_final[step_i] - feat_mean_final) / feat_std_final
            x_tensor = torch.tensor(X_step_norm, dtype=torch.float32).to(device)
            y_tensor = torch.tensor(y_list_final[step_i], dtype=torch.float32).to(device)
            final_optimizer.zero_grad()
            pred = final_model(x_tensor, edge_index)
            loss = F.mse_loss(pred, y_tensor)
            loss.backward()
            final_optimizer.step()
            total_loss += loss.item()
        final_scheduler.step()
        if (epoch + 1) % 50 == 0:
            print(f"        [Final] Epoch {epoch+1:3d}/{args.epochs} - MSE loss: {total_loss/n_steps_final:.4f}")

    # Predict forecast week
    X_forecast = build_node_feature_matrix(cell_ids, matrix, node_features, all_weeks, window)
    X_forecast_norm = (X_forecast - feat_mean_final) / feat_std_final
    final_model.eval()
    with torch.no_grad():
        preds_forecast = final_model(
            torch.tensor(X_forecast_norm, dtype=torch.float32).to(device),
            edge_index,
        ).cpu().numpy()
    preds_forecast = np.maximum(preds_forecast, 0.0)
    print(f"      Predictions generated for {len(cell_ids):,} cells")

    # ------------------------------------------------------------------
    # Build forecast JSON
    # ------------------------------------------------------------------
    print(f"\n[4/6] Building forecast items")

    global_interval_err = percentile(global_residuals, 0.8) if global_residuals else 1.0
    max_prediction = float(max(preds_forecast)) if len(preds_forecast) else 1.0

    forecast_items: list[dict[str, Any]] = []
    for i, cell_id in enumerate(cell_ids):
        predicted_count = float(preds_forecast[i])
        nf = node_features.get(cell_id, {})

        cell_interval_err = (
            percentile(residuals_by_cell[cell_id], 0.8)
            if residuals_by_cell.get(cell_id)
            else global_interval_err
        )
        interval_low = max(0.0, predicted_count - cell_interval_err)
        interval_high = predicted_count + cell_interval_err

        cell_residuals = residuals_by_cell.get(cell_id, [])
        if cell_residuals:
            mean_res = sum(cell_residuals) / len(cell_residuals)
            var_res = sum((r - mean_res) ** 2 for r in cell_residuals) / len(cell_residuals)
            cv = math.sqrt(var_res) / max(mean_res, 0.01)
            forecast_stability = round(max(0.0, min(100.0, 100.0 * (1.0 - min(cv, 1.0)))), 2)
        else:
            forecast_stability = 0.0

        predicted_obstruction_risk = round(100.0 * predicted_count / max(max_prediction, 1.0), 2)

        historical_weeks = [
            {"week": w, "violation_count": matrix[cell_id].get(w, 0)}
            for w in all_weeks[-12:]
        ]

        mean_sev = nf.get("mean_severity", 0.0)
        junc_share = nf.get("junction_share", 0.0)
        high_share = nf.get("high_share", 0.0)

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
                    / min(len(all_weeks), 2), 2
                ),
                "last_4_week_avg": round(
                    sum(matrix[cell_id].get(w, 0) for w in all_weeks[-4:])
                    / min(len(all_weeks), 4), 2
                ),
                "historical_weeks": historical_weeks,
                "forecast_reason_codes": sage_reason_codes(
                    predicted_count, mean_sev, junc_share, high_share, forecast_stability
                ),
                "reason_codes": sage_reason_codes(
                    predicted_count, mean_sev, junc_share, high_share, forecast_stability
                ),
            }
        )

    forecast_items.sort(
        key=lambda it: (it["predicted_violation_count"], it["grid_cell_id"]),
        reverse=True,
    )

    # ------------------------------------------------------------------
    # Write outputs
    # ------------------------------------------------------------------
    print(f"\n[5/6] Writing outputs to: {output_dir.resolve()}")
    output_dir.mkdir(parents=True, exist_ok=True)

    model_hyperparams = {
        "hidden_dim": args.hidden,
        "dropout": args.dropout,
        "epochs": args.epochs,
        "learning_rate": args.lr,
        "window": window,
        "seed": args.seed,
        "device": str(device),
        "architecture": "2-layer GraphSAGE + Linear head",
    }

    forecast_payload: dict[str, Any] = {
        "forecast_type": "future observed parking violations",
        "model": "GraphSAGE",
        "not_measured_congestion": True,
        "method": (
            f"2-layer GraphSAGE (SAGEConv) regression. "
            f"Node features: {window} weekly lag counts + "
            f"{len(STATIC_FEATURES)} static features. "
            "Temporal history treated as independent input channels (pure spatial GNN). "
            "Edge aggregation via SAGEConv mean aggregator. "
            "MSE training loss, MAE evaluation metric."
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
        "model_hyperparameters": model_hyperparams,
        "items": forecast_items,
    }

    forecast_path = output_dir / "forecast_graphsage.json"
    write_json(forecast_path, forecast_payload)
    print(f"      forecast_graphsage.json - {len(forecast_items):,} cells")

    # Update model_comparison.json
    comparison_path = output_dir / "model_comparison.json"
    existing_comparison = load_json(comparison_path) or {
        "description": (
            "Rolling-origin holdout MAE/MAPE comparison across all models. "
            "Identical holdout weeks ensure fair comparison."
        ),
        "models": [],
    }
    sage_entry: dict[str, Any] = {
        "name": "GraphSAGE",
        "description": (
            f"2-layer SAGEConv network, {window}-week lag channels + static node features. "
            "Pure spatial GNN - no recurrent/convolutional temporal layer."
        ),
        "script": "scripts/train_graphsage.py",
        "forecast_file": "forecast_graphsage.json",
        "mae": mae,
        "mape": mape,
        "evaluated_points": evaluated_points,
        "holdout_weeks": holdout_weeks,
        "hyperparameters": model_hyperparams,
    }
    models_list = existing_comparison.get("models", [])
    models_list = [m for m in models_list if m.get("name") != "GraphSAGE"]
    models_list.append(sage_entry)
    models_list.sort(key=lambda m: m.get("mae") or float("inf"))
    existing_comparison["models"] = models_list
    existing_comparison["last_updated"] = datetime.now(tz=timezone.utc).isoformat()
    write_json(comparison_path, existing_comparison)
    print(f"      model_comparison.json  - updated ({len(models_list)} models tracked)")

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  GRAPHSAGE TRAINING COMPLETE")
    print("=" * 60)
    print(f"  GraphSAGE MAE          : {mae}")
    print(f"  GraphSAGE MAPE         : {mape}%")
    print(f"  Evaluated points       : {evaluated_points:,}")
    print(f"  Forecast cells         : {len(forecast_items):,}")
    print(f"  forecast_graphsage.json: {forecast_path.resolve()}")
    print("=" * 60)
    print("\nNext step: python scripts/train_stgcn.py")


if __name__ == "__main__":
    main()
