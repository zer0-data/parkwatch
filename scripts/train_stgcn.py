"""Spatio-Temporal Graph Convolutional Network (STGCN) forecaster.

Captures time-evolving violation activity across the filtered cell graph by
combining 1D temporal convolutions with graph-based spatial aggregation.

Architecture - one ST-Conv block followed by a prediction head:

  Input  : (N, T, 1)         - N cells, T weekly counts, 1 feature
  +-------------------------------------------------------------+
  |  ST-Conv Block                                              |
  |  Temporal Conv1d (in=T, out=T')  - captures temporal trends |
  |  Spatial GCN                     - aggregates from neighbours|
  |  Temporal Conv1d (in=T', out=T'')- re-captures after spatial|
  +-------------------------------------------------------------+
  Flatten + Linear head -> predicted count (N,)

The spatial GCN layer has TWO implementations (auto-selected):
  1. GCNConv from PyTorch Geometric (preferred, faster)
  2. Manual normalised adjacency matmul using torch.sparse
     (no C++ extensions, works anywhere PyTorch runs)

The --use-sparse flag forces the manual implementation.
Without the flag, the script auto-detects PyG and falls back automatically.

Static node features (mean_severity, junction_share, etc.) are concatenated
to the temporal features before the spatial layer for richer representations.

Outputs:
  forecast_stgcn.json    - predictions in heuristic schema
  model_comparison.json  - final bake-off table with all 4 models

Usage:
  # CPU (default, works locally and on Lightning AI)
  python scripts/train_stgcn.py

  # GPU
  python scripts/train_stgcn.py --device cuda

  # Force manual sparse adjacency (no PyG needed)
  python scripts/train_stgcn.py --use-sparse

  # Custom
  python scripts/train_stgcn.py \\
      --artifacts-dir backend/app/data/processed/ml_artifacts \\
      --output-dir    backend/app/data/processed \\
      --epochs 150 --temporal-channels 16 --spatial-channels 32 \\
      --window 4 --device cpu
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
# Dependency checks
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
    raise SystemExit("PyTorch not installed. See https://pytorch.org/get-started/locally/")

# Try to import PyG GCNConv - if unavailable, we use the manual sparse fallback
try:
    from torch_geometric.nn import GCNConv  # type: ignore
    HAS_PYG = True
except ImportError:
    HAS_PYG = False

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
        description="Train STGCN violation-count forecaster and write forecast_stgcn.json."
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
    parser.add_argument("--window", type=int, default=4,
                        help="Input temporal window (number of prior weeks). Default 4.")
    parser.add_argument("--temporal-channels", type=int, default=16,
                        help="Channels in the temporal Conv1d layers. Default 16.")
    parser.add_argument("--spatial-channels", type=int, default=32,
                        help="Output channels of the spatial GCN layer. Default 32.")
    parser.add_argument("--epochs", type=int, default=150,
                        help="Training epochs per fold. Default 150.")
    parser.add_argument("--lr", type=float, default=0.005,
                        help="Adam learning rate. Default 0.005.")
    parser.add_argument("--device", type=str, default="cpu",
                        choices=["cpu", "cuda"],
                        help="Compute device. Default cpu.")
    parser.add_argument("--use-sparse", action="store_true",
                        help="Force manual torch.sparse adjacency (bypasses PyG GCNConv).")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
def load_csv_dicts(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"Missing: {path}  -  run export_ml_artifacts.py first.")
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
# Sparse adjacency (manual GCN - no PyG required)
# ---------------------------------------------------------------------------
def build_normalised_adj(
    cell_index: dict[str, int],
    edge_dicts: list[dict[str, str]],
    N: int,
    device: torch.device,
) -> torch.Tensor:
    """Compute D^{-1/2} A D^{-1/2} as a dense tensor.

    A_hat = A + I  (self-loops so each node aggregates itself)
    D     = degree matrix of A_hat
    Returns: D^{-1/2} A_hat D^{-1/2}  shape (N, N)
    """
    # Build adjacency with self-loops
    A = torch.zeros(N, N, dtype=torch.float32)
    for edge in edge_dicts:
        s = cell_index.get(edge["source"])
        t = cell_index.get(edge["target"])
        if s is not None and t is not None:
            w = float(edge["weight"])
            A[s, t] += w
            A[t, s] += w
    # Self-loops
    A += torch.eye(N, dtype=torch.float32)
    # Degree
    D_diag = A.sum(dim=1)          # (N,)
    D_inv_sqrt = 1.0 / torch.sqrt(D_diag.clamp(min=1e-6))
    # D^{-1/2} A D^{-1/2}
    A_norm = D_inv_sqrt.unsqueeze(1) * A * D_inv_sqrt.unsqueeze(0)
    return A_norm.to(device)


# ---------------------------------------------------------------------------
# Manual GCN layer (uses dense normalised adjacency)
# ---------------------------------------------------------------------------
class ManualGCNLayer(nn.Module):
    """A = normalised adjacency (N, N); applies  A @ X @ W."""

    def __init__(self, in_channels: int, out_channels: int, A_norm: torch.Tensor) -> None:
        super().__init__()
        self.register_buffer("A_norm", A_norm)
        self.linear = nn.Linear(in_channels, out_channels, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (N, in_channels)
        # A_norm @ x: (N, in_channels)  - spatial aggregation
        x_agg = torch.matmul(self.A_norm, x)   # (N, in_channels)
        return self.linear(x_agg)               # (N, out_channels)


# ---------------------------------------------------------------------------
# PyG-based GCN layer wrapper (keeps same interface as ManualGCNLayer)
# ---------------------------------------------------------------------------
class PyGGCNLayer(nn.Module):
    """Thin wrapper around PyG GCNConv that accepts a pre-built edge_index."""

    def __init__(self, in_channels: int, out_channels: int, edge_index: torch.Tensor) -> None:
        super().__init__()
        self.conv = GCNConv(in_channels, out_channels, add_self_loops=True)
        self.register_buffer("edge_index", edge_index)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.conv(x, self.edge_index)


# ---------------------------------------------------------------------------
# STGCN model
# ---------------------------------------------------------------------------
STATIC_FEATURES = [
    "mean_severity", "junction_share", "high_share",
    "temporal_concentration", "active_days", "active_weeks",
    "device_days", "neighbor_influence",
]
N_STATIC = len(STATIC_FEATURES)


class STGCNBlock(nn.Module):
    """One Spatio-Temporal Conv block:

    (N, T, C_in)
     -> Temporal Conv1d    (N, T', C_temp)
     -> Spatial GCN        (N, T', C_spatial)      [applied per time step]
     -> Temporal Conv1d    (N, T'', C_temp)
     -> Flatten + Linear   (N, 1)
    """

    def __init__(
        self,
        T: int,
        C_in: int,          # input channels (1 for raw counts + static)
        C_temp: int,        # temporal conv output channels
        C_spatial: int,     # spatial GCN output channels
        gcn_layer: nn.Module,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        self.T = T
        self.C_in = C_in

        # Temporal layer 1: conv over time dimension
        # Input : (N, C_in, T)  ->  output: (N, C_temp, T)
        self.temp_conv1 = nn.Conv1d(C_in, C_temp, kernel_size=3, padding=1)

        # Spatial layer: applied to each time step independently
        # Input per step: (N, C_temp)  ->  output: (N, C_spatial)
        self.gcn = gcn_layer
        self.C_spatial = C_spatial

        # Temporal layer 2: conv over time after spatial aggregation
        # Input : (N, C_spatial, T)  ->  output: (N, C_temp, T-2)
        # Using kernel_size=3, no padding -> reduces T by 2
        self.temp_conv2 = nn.Conv1d(C_spatial, C_temp, kernel_size=3, padding=0)

        # How many time steps remain after temp_conv2?
        T_out = T - 2   # kernel_size=3, no padding
        self.flatten_dim = C_temp * T_out
        self.head = nn.Linear(self.flatten_dim, 1)
        self.dropout = nn.Dropout(dropout)
        self.relu = nn.ReLU()

    def forward(self, x_seq: torch.Tensor) -> torch.Tensor:
        """x_seq: (N, T, C_in) - sequence of node features over time."""
        N, T, C_in = x_seq.shape

        # --- Temporal conv 1 ---
        # Reshape to (N, C_in, T) for Conv1d
        x_t = x_seq.permute(0, 2, 1)               # (N, C_in, T)
        x_t = self.relu(self.temp_conv1(x_t))       # (N, C_temp, T)
        x_t = self.dropout(x_t)

        # --- Spatial GCN (per time step) ---
        C_temp = x_t.shape[1]
        x_spatial_steps = []
        for t in range(T):
            step_feat = x_t[:, :, t]                # (N, C_temp)
            step_out = self.relu(self.gcn(step_feat))  # (N, C_spatial)
            x_spatial_steps.append(step_out)
        # Stack: (N, C_spatial, T)
        x_s = torch.stack(x_spatial_steps, dim=2)   # (N, C_spatial, T)
        x_s = self.dropout(x_s)

        # --- Temporal conv 2 ---
        x_t2 = self.relu(self.temp_conv2(x_s))      # (N, C_temp, T-2)

        # --- Prediction head ---
        x_flat = x_t2.reshape(N, -1)                # (N, C_temp * (T-2))
        out = self.head(x_flat)                      # (N, 1)
        return out.squeeze(-1)                       # (N,)


# ---------------------------------------------------------------------------
# Feature matrix builders
# ---------------------------------------------------------------------------
def build_sequence_tensor(
    cell_ids: list[str],
    matrix: dict[str, dict[str, int]],
    node_features: dict[str, dict[str, float]],
    train_weeks: list[str],
    window: int,
) -> torch.Tensor:
    """Return (N, window, 1 + N_STATIC) input tensor.

    Channel 0 : normalised weekly violation count
    Channels 1..: static node features (repeated across time)
    """
    recent = train_weeks[-window:] if len(train_weeks) >= window else train_weeks
    # Pad left with zeros if fewer weeks
    pad = window - len(recent)

    rows = []
    for cell_id in cell_ids:
        counts = matrix.get(cell_id, {})
        nf = node_features.get(cell_id, {})
        time_steps = []
        # Padded zeros first
        for _ in range(pad):
            static = [nf.get(f, 0.0) for f in STATIC_FEATURES]
            time_steps.append([0.0] + static)
        # Actual weeks (chronological order)
        for w in recent:
            count = float(counts.get(w, 0))
            static = [nf.get(f, 0.0) for f in STATIC_FEATURES]
            time_steps.append([count] + static)
        rows.append(time_steps)

    # (N, window, 1 + N_STATIC)
    return torch.tensor(rows, dtype=torch.float32)


def build_target_tensor(
    cell_ids: list[str],
    matrix: dict[str, dict[str, int]],
    target_week: str,
) -> torch.Tensor:
    targets = [float(matrix.get(cid, {}).get(target_week, 0)) for cid in cell_ids]
    return torch.tensor(targets, dtype=torch.float32)


# ---------------------------------------------------------------------------
# Normalise sequence tensor across nodes and time (z-score per channel)
# ---------------------------------------------------------------------------
def normalise_seq(
    X: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Normalise (N, T, C) tensor per channel across N and T."""
    N, T, C = X.shape
    X_flat = X.reshape(-1, C)       # (N*T, C)
    mean = X_flat.mean(dim=0)       # (C,)
    std = X_flat.std(dim=0)         # (C,)
    std[std < 1e-6] = 1.0
    X_norm = (X - mean) / std
    return X_norm, mean, std


# ---------------------------------------------------------------------------
# Percentile helper
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
def stgcn_reason_codes(
    predicted: float,
    mean_severity: float,
    junction_share: float,
    high_share: float,
    forecast_stability: float,
) -> list[str]:
    reasons = ["STGCN_FORECAST_OF_OBSERVED_VIOLATIONS"]
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
    reasons.append("SPATIO_TEMPORAL_GRAPH_CONV")
    return reasons


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    args = parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    # Resolve device
    use_cuda = args.device == "cuda" and torch.cuda.is_available()
    device = torch.device("cuda" if use_cuda else "cpu")
    if args.device == "cuda" and not torch.cuda.is_available():
        print("[WARNING] CUDA requested but not available - using CPU")

    # Decide spatial GCN backend
    use_sparse = args.use_sparse or not HAS_PYG
    backend_name = "manual torch.sparse" if use_sparse else "PyG GCNConv"

    print("\n" + "=" * 60)
    print("  ParkWatch - STGCN Forecaster")
    print(f"  Device  : {device}")
    print(f"  GCN backend: {backend_name}")
    print("=" * 60)

    artifacts_dir = args.artifacts_dir
    output_dir = args.output_dir
    window = args.window
    C_in = 1 + N_STATIC  # violation count + static features

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

    cell_ids: list[str] = [row["cell_id"] for row in matrix_dicts]
    cell_index: dict[str, int] = {cid: i for i, cid in enumerate(cell_ids)}
    N = len(cell_ids)

    node_features: dict[str, dict[str, float]] = {}
    for row in node_dicts:
        cid = row["cell_id"]
        node_features[cid] = {
            k: float(v) for k, v in row.items()
            if k not in ("cell_id", "confidence", "peak_weekday")
        }

    matrix: dict[str, dict[str, int]] = {}
    for row in matrix_dicts:
        cid = row["cell_id"]
        matrix[cid] = {w: int(row[w]) for w in all_weeks}

    print(f"      Cells: {N:,} | Weeks: {len(all_weeks)} | Edges: {len(edge_dicts):,}")
    print(f"      Window: {window} | C_in: {C_in} | Holdout: {holdout_weeks}")

    # ------------------------------------------------------------------
    # Build graph structures
    # ------------------------------------------------------------------
    print(f"\n[2/6] Building graph ({backend_name})")

    if use_sparse:
        A_norm = build_normalised_adj(cell_index, edge_dicts, N, device)
        print(f"      Normalised adjacency: ({N}, {N}) dense tensor")
    else:
        # Build edge_index for PyG
        src_list, dst_list = [], []
        for edge in edge_dicts:
            s = cell_index.get(edge["source"])
            t = cell_index.get(edge["target"])
            if s is not None and t is not None:
                src_list.extend([s, t])
                dst_list.extend([t, s])
        edge_index = torch.tensor([src_list, dst_list], dtype=torch.long).to(device)
        print(f"      edge_index: {edge_index.shape[1] // 2} undirected edges (PyG)")

    # ------------------------------------------------------------------
    # Rolling-origin backtest
    # ------------------------------------------------------------------
    print(f"\n[3/6] Rolling-origin backtest")

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

        # Build all training time steps for this fold
        X_steps: list[torch.Tensor] = []   # each: (N, window, C_in)
        y_steps: list[torch.Tensor] = []   # each: (N,)

        for t_idx in range(window, len(train_weeks)):
            prior = train_weeks[:t_idx]
            target = train_weeks[t_idx]
            X_step = build_sequence_tensor(cell_ids, matrix, node_features, prior, window)
            y_step = build_target_tensor(cell_ids, matrix, target)
            X_steps.append(X_step)
            y_steps.append(y_step)

        if not X_steps:
            continue

        # Compute normalisation statistics from training data
        X_all_stacked = torch.cat(X_steps, dim=0)  # (n_steps * N, window, C_in)
        # Normalise per channel
        X_all_flat = X_all_stacked.reshape(-1, C_in)
        feat_mean = X_all_flat.mean(dim=0)
        feat_std = X_all_flat.std(dim=0)
        feat_std[feat_std < 1e-6] = 1.0

        # Instantiate model + GCN layer
        if use_sparse:
            gcn_layer = ManualGCNLayer(args.temporal_channels, args.spatial_channels, A_norm)
        else:
            gcn_layer = PyGGCNLayer(args.temporal_channels, args.spatial_channels, edge_index)

        model = STGCNBlock(
            T=window,
            C_in=C_in,
            C_temp=args.temporal_channels,
            C_spatial=args.spatial_channels,
            gcn_layer=gcn_layer,
            dropout=0.2,
        ).to(device)

        optimizer = torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)

        # Train
        model.train()
        n_steps = len(X_steps)
        for epoch in range(args.epochs):
            total_loss = 0.0
            for step_i in range(n_steps):
                x_raw = X_steps[step_i]                          # (N, window, C_in)
                x_norm = (x_raw - feat_mean) / feat_std          # normalise
                x_t = x_norm.to(device)
                y_t = y_steps[step_i].to(device)

                optimizer.zero_grad()
                pred = model(x_t)                                # (N,)
                loss = F.mse_loss(pred, y_t)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                total_loss += loss.item()
            scheduler.step()
            if (epoch + 1) % 50 == 0:
                print(f"        [{holdout_week}] Epoch {epoch+1:3d}/{args.epochs} - MSE: {total_loss/n_steps:.4f}")

        # Evaluate on holdout week
        model.eval()
        X_holdout = build_sequence_tensor(cell_ids, matrix, node_features, train_weeks, window)
        X_holdout_norm = (X_holdout - feat_mean) / feat_std
        with torch.no_grad():
            preds_h = model(X_holdout_norm.to(device)).cpu().numpy()
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
    # Train final model on ALL data
    # ------------------------------------------------------------------
    print(f"\n[4/6] Training final model on all {len(all_weeks)} weeks -> {forecast_week}")

    X_final_steps, y_final_steps = [], []
    for t_idx in range(window, len(all_weeks)):
        prior = all_weeks[:t_idx]
        target = all_weeks[t_idx]
        X_final_steps.append(
            build_sequence_tensor(cell_ids, matrix, node_features, prior, window)
        )
        y_final_steps.append(build_target_tensor(cell_ids, matrix, target))

    X_all_final = torch.cat(X_final_steps, dim=0)
    X_all_flat_final = X_all_final.reshape(-1, C_in)
    feat_mean_f = X_all_flat_final.mean(dim=0)
    feat_std_f = X_all_flat_final.std(dim=0)
    feat_std_f[feat_std_f < 1e-6] = 1.0

    if use_sparse:
        gcn_final = ManualGCNLayer(args.temporal_channels, args.spatial_channels, A_norm)
    else:
        gcn_final = PyGGCNLayer(args.temporal_channels, args.spatial_channels, edge_index)

    final_model = STGCNBlock(
        T=window,
        C_in=C_in,
        C_temp=args.temporal_channels,
        C_spatial=args.spatial_channels,
        gcn_layer=gcn_final,
        dropout=0.2,
    ).to(device)

    final_optimizer = torch.optim.Adam(final_model.parameters(), lr=args.lr, weight_decay=1e-4)
    final_scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(final_optimizer, T_max=args.epochs)

    n_steps_f = len(X_final_steps)
    final_model.train()
    for epoch in range(args.epochs):
        total_loss = 0.0
        for step_i in range(n_steps_f):
            x_raw = X_final_steps[step_i]
            x_norm = (x_raw - feat_mean_f) / feat_std_f
            x_t = x_norm.to(device)
            y_t = y_final_steps[step_i].to(device)
            final_optimizer.zero_grad()
            pred = final_model(x_t)
            loss = F.mse_loss(pred, y_t)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(final_model.parameters(), 1.0)
            final_optimizer.step()
            total_loss += loss.item()
        final_scheduler.step()
        if (epoch + 1) % 50 == 0:
            print(f"        [Final] Epoch {epoch+1:3d}/{args.epochs} - MSE: {total_loss/n_steps_f:.4f}")

    # Predict forecast week
    X_forecast_raw = build_sequence_tensor(cell_ids, matrix, node_features, all_weeks, window)
    X_forecast_norm = (X_forecast_raw - feat_mean_f) / feat_std_f
    final_model.eval()
    with torch.no_grad():
        preds_forecast = final_model(X_forecast_norm.to(device)).cpu().numpy()
    preds_forecast = np.maximum(preds_forecast, 0.0)
    print(f"      Predictions: {len(cell_ids):,} cells")

    # ------------------------------------------------------------------
    # Build forecast JSON items
    # ------------------------------------------------------------------
    print(f"\n[5/6] Building forecast items")

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
                "forecast_reason_codes": stgcn_reason_codes(
                    predicted_count, mean_sev, junc_share, high_share, forecast_stability
                ),
                "reason_codes": stgcn_reason_codes(
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
    print(f"\n[6/6] Writing outputs to: {output_dir.resolve()}")
    output_dir.mkdir(parents=True, exist_ok=True)

    model_hyperparams = {
        "window": window,
        "temporal_channels": args.temporal_channels,
        "spatial_channels": args.spatial_channels,
        "epochs": args.epochs,
        "learning_rate": args.lr,
        "device": str(device),
        "gcn_backend": backend_name,
        "seed": args.seed,
        "architecture": (
            f"STGCNBlock: Conv1d({C_in}->{args.temporal_channels}) -> "
            f"GCN({args.temporal_channels}->{args.spatial_channels}) -> "
            f"Conv1d({args.spatial_channels}->{args.temporal_channels}) -> Linear(1)"
        ),
    }

    forecast_payload: dict[str, Any] = {
        "forecast_type": "future observed parking violations",
        "model": "STGCN",
        "not_measured_congestion": True,
        "method": (
            "Spatio-Temporal Graph Convolutional Network. "
            f"ST-Conv block: Temporal Conv1d -> Spatial GCN ({backend_name}) -> "
            "Temporal Conv1d -> Linear head. "
            f"Input: (N={N}, T={window}, C={C_in}). "
            "Captures rippling spatial spillovers across time."
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

    forecast_path = output_dir / "forecast_stgcn.json"
    write_json(forecast_path, forecast_payload)
    print(f"      forecast_stgcn.json    - {len(forecast_items):,} cells")

    # Update model_comparison.json
    comparison_path = output_dir / "model_comparison.json"
    existing_comparison = load_json(comparison_path) or {
        "description": (
            "Rolling-origin holdout MAE/MAPE comparison across all models. "
            "Identical holdout weeks ensure fair comparison."
        ),
        "models": [],
    }
    stgcn_entry: dict[str, Any] = {
        "name": "STGCN",
        "description": (
            "Spatio-temporal GCN: Conv1d (temporal) + GCN (spatial) + Conv1d + Linear. "
            f"Window={window} weeks, GCN backend={backend_name}."
        ),
        "script": "scripts/train_stgcn.py",
        "forecast_file": "forecast_stgcn.json",
        "mae": mae,
        "mape": mape,
        "evaluated_points": evaluated_points,
        "holdout_weeks": holdout_weeks,
        "hyperparameters": model_hyperparams,
    }
    models_list = existing_comparison.get("models", [])
    models_list = [m for m in models_list if m.get("name") != "STGCN"]
    models_list.append(stgcn_entry)
    models_list.sort(key=lambda m: m.get("mae") or float("inf"))
    existing_comparison["models"] = models_list
    existing_comparison["last_updated"] = datetime.now(tz=timezone.utc).isoformat()
    write_json(comparison_path, existing_comparison)
    print(f"      model_comparison.json  - {len(models_list)} models")

    # ------------------------------------------------------------------
    # Final bake-off table
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  STGCN TRAINING COMPLETE  -  FINAL BAKE-OFF")
    print("=" * 60)
    all_models = existing_comparison.get("models", [])
    print(f"  {'Model':<22} {'MAE':>8}  {'MAPE':>8}  {'n':>8}")
    print(f"  {'-'*22} {'-'*8}  {'-'*8}  {'-'*8}")
    for m in all_models:
        mae_str = f"{m['mae']:.4f}" if m.get("mae") is not None else "N/A"
        mape_str = f"{m['mape']:.2f}%" if m.get("mape") is not None else "N/A"
        n_str = str(m.get("evaluated_points") or "")
        print(f"  {m['name']:<22} {mae_str:>8}  {mape_str:>8}  {n_str:>8}")
    print("=" * 60)
    print(f"\n  Outputs:  {output_dir.resolve()}")
    print("  forecast_stgcn.json  |  model_comparison.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
