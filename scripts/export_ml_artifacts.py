"""Export ML-ready artifacts from the official ParkWatch CSV.

Re-uses the aggregation logic from preprocess_official_csv.py (imported as a
module) so there is no duplicated parsing code and no double CSV read.

Outputs (written to --output-dir):
  nodes.csv          - one row per filtered cell with static features
  weekly_matrix.csv  - (cells x weeks) violation-count pivot table
  edges.csv          - graph edges between filtered cells only
  ml_artifacts_metadata.json - provenance + filter settings

Sparsity filter (configurable):
  Default: violation_count >= 8  AND  active_days >= 2
  (equivalent to "Medium" or "High" confidence in the heuristic baseline)
  Rationale: zero-inflated cells produce deceptively good MAE if a model
  just predicts 0 everywhere; filtering them gives honest benchmark numbers.

Usage:
  # From the repo root (one CSV must already be in data/)
  python scripts/export_ml_artifacts.py

  # Custom paths
  python scripts/export_ml_artifacts.py \\
      --input data/violations.csv \\
      --output-dir backend/app/data/processed/ml_artifacts \\
      --min-violations 8 \\
      --min-active-days 2
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Import from sibling script - no package structure needed
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from preprocess_official_csv import (  # noqa: E402
    DEFAULT_MAX_EDGE_METERS,
    DEFAULT_MIN_EDGE_METERS,
    build_edges,
    confidence_label,
    find_official_csv,
    next_iso_week_label,
    read_and_aggregate,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_MIN_VIOLATIONS = 8
DEFAULT_MIN_ACTIVE_DAYS = 2


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export ML-ready CSV artifacts from the ParkWatch official CSV."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Path to the official parking violation CSV. "
             "Defaults to the only .csv file in data/.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("backend/app/data/processed/ml_artifacts"),
        help="Directory to write nodes.csv, weekly_matrix.csv, edges.csv.",
    )
    parser.add_argument(
        "--min-edge-meters",
        type=float,
        default=DEFAULT_MIN_EDGE_METERS,
        help="Minimum Haversine distance (m) for a graph edge.",
    )
    parser.add_argument(
        "--max-edge-meters",
        type=float,
        default=DEFAULT_MAX_EDGE_METERS,
        help="Maximum Haversine distance (m) for a graph edge.",
    )
    parser.add_argument(
        "--min-violations",
        type=int,
        default=DEFAULT_MIN_VIOLATIONS,
        help="Sparsity filter: minimum total violations per cell (default 8).",
    )
    parser.add_argument(
        "--min-active-days",
        type=int,
        default=DEFAULT_MIN_ACTIVE_DAYS,
        help="Sparsity filter: minimum active days per cell (default 2).",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    """Write a list of dicts to a CSV file with a header row."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Main export logic
# ---------------------------------------------------------------------------
def main() -> None:
    args = parse_args()
    csv_path = args.input or find_official_csv()

    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")
    if args.min_edge_meters >= args.max_edge_meters:
        raise SystemExit("--min-edge-meters must be less than --max-edge-meters")

    # ------------------------------------------------------------------
    # Step 1: Read + aggregate (streaming, memory-efficient)
    # ------------------------------------------------------------------
    print(f"\n[1/5] Reading and aggregating CSV: {csv_path}")
    cells, total_rows, skipped_rows = read_and_aggregate(csv_path)
    print(
        f"      {total_rows:,} rows read | "
        f"{skipped_rows:,} skipped | "
        f"{len(cells):,} raw grid cells"
    )

    # ------------------------------------------------------------------
    # Step 2: Sparsity filter
    # ------------------------------------------------------------------
    print(
        f"\n[2/5] Applying sparsity filter "
        f"(violations >= {args.min_violations}, active_days >= {args.min_active_days})"
    )
    filtered = {
        cell_id: cell
        for cell_id, cell in cells.items()
        if (
            cell.violation_count >= args.min_violations
            and len(cell.active_days) >= args.min_active_days
        )
    }
    n_removed = len(cells) - len(filtered)
    print(f"      Kept {len(filtered):,} cells | removed {n_removed:,} sparse cells")

    # Confidence breakdown of kept cells
    conf_counts = {"High": 0, "Medium": 0}
    for cell in filtered.values():
        conf = confidence_label(
            cell.violation_count, len(cell.active_days), len(cell.device_days)
        )
        conf_counts[conf] = conf_counts.get(conf, 0) + 1
    print(f"      Confidence breakdown: {conf_counts}")

    # ------------------------------------------------------------------
    # Step 3: Build graph edges on filtered set only
    # ------------------------------------------------------------------
    print(
        f"\n[3/5] Building graph edges "
        f"({args.min_edge_meters:.0f}m - {args.max_edge_meters:.0f}m) "
        f"on {len(filtered):,} filtered cells"
    )
    edges = build_edges(filtered, args.min_edge_meters, args.max_edge_meters)
    print(f"      {len(edges):,} edges built")

    # Mean/max degree
    degree: dict[str, int] = {}
    for edge in edges:
        degree[edge["source"]] = degree.get(edge["source"], 0) + 1
        degree[edge["target"]] = degree.get(edge["target"], 0) + 1
    if degree:
        mean_deg = sum(degree.values()) / len(degree)
        max_deg = max(degree.values())
        print(f"      Degree - mean: {mean_deg:.1f}, max: {max_deg}")
    isolated = len(filtered) - len(degree)
    if isolated:
        print(f"      Warning: {isolated} filtered cells have no edges (isolated nodes)")

    # ------------------------------------------------------------------
    # Step 4: Collect ISO weeks and compute forecast week
    # ------------------------------------------------------------------
    all_weeks = sorted(
        {week for cell in filtered.values() for week in cell.week_counts}
    )
    forecast_week = next_iso_week_label(all_weeks[-1]) if all_weeks else None
    print(
        f"\n[4/5] Timeline: {len(all_weeks)} ISO weeks  "
        f"[{all_weeks[0]} to {all_weeks[-1]}]  |  "
        f"forecast target: {forecast_week}"
    )

    # Holdout protocol (mirrors heuristic exactly)
    holdout_weeks = all_weeks[-8:] if len(all_weeks) >= 12 else all_weeks[-4:]
    print(f"      Holdout weeks (same as heuristic): {holdout_weeks}")

    # ------------------------------------------------------------------
    # Step 5: Write artifacts
    # ------------------------------------------------------------------
    print(f"\n[5/5] Writing artifacts to: {args.output_dir.resolve()}")
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- nodes.csv ---
    node_rows = []
    for cell_id, cell in filtered.items():
        avg_lat = cell.lat_sum / cell.violation_count
        avg_lon = cell.lon_sum / cell.violation_count
        mean_severity = cell.severity_sum / cell.violation_count
        junction_share = cell.junction_count / cell.violation_count
        high_share = cell.high_count / cell.violation_count
        medium_share = cell.medium_count / cell.violation_count
        validation_share = (
            cell.validated_count / cell.violation_count
        )
        approved_share = (
            cell.approved_count / cell.violation_count
        )
        # Peak hour (most common hour across all observed violations)
        peak_hour = (
            max(cell.hour_counts, key=cell.hour_counts.get)
            if cell.hour_counts
            else -1
        )
        # Peak weekday
        peak_weekday = (
            max(cell.weekday_counts, key=cell.weekday_counts.get)
            if cell.weekday_counts
            else "Unknown"
        )
        conf = confidence_label(
            cell.violation_count, len(cell.active_days), len(cell.device_days)
        )
        # Temporal concentration: fraction of violations in the single busiest hour
        temporal_concentration = (
            max(cell.hour_counts.values()) / cell.violation_count
            if cell.hour_counts
            else 0.0
        )
        # Neighbour influence (populated by build_edges, already set on cell)
        node_rows.append(
            {
                "cell_id": cell_id,
                "lat": round(avg_lat, 7),
                "lon": round(avg_lon, 7),
                "total_violations": cell.violation_count,
                "active_days": len(cell.active_days),
                "active_weeks": len(cell.active_weeks),
                "active_months": len(cell.active_months),
                "device_days": len(cell.device_days),
                "mean_severity": round(mean_severity, 4),
                "junction_share": round(junction_share, 4),
                "high_share": round(high_share, 4),
                "medium_share": round(medium_share, 4),
                "validation_share": round(validation_share, 4),
                "approved_share": round(approved_share, 4),
                "temporal_concentration": round(temporal_concentration, 4),
                "neighbor_influence": round(cell.neighbor_influence, 4),
                "peak_hour": peak_hour,
                "peak_weekday": peak_weekday,
                "confidence": conf,
            }
        )

    node_fieldnames = [
        "cell_id", "lat", "lon",
        "total_violations", "active_days", "active_weeks", "active_months", "device_days",
        "mean_severity", "junction_share", "high_share", "medium_share",
        "validation_share", "approved_share", "temporal_concentration", "neighbor_influence",
        "peak_hour", "peak_weekday", "confidence",
    ]
    nodes_path = output_dir / "nodes.csv"
    write_csv(nodes_path, node_rows, node_fieldnames)
    print(f"      nodes.csv          - {len(node_rows):,} rows, {len(node_fieldnames)} columns")

    # --- weekly_matrix.csv ---
    # Rows = cells, columns = ISO weeks, values = violation count (0 if absent)
    matrix_rows = []
    for cell_id, cell in filtered.items():
        row: dict = {"cell_id": cell_id}
        for week in all_weeks:
            row[week] = cell.week_counts.get(week, 0)
        matrix_rows.append(row)

    week_fieldnames = ["cell_id"] + all_weeks
    matrix_path = output_dir / "weekly_matrix.csv"
    write_csv(matrix_path, matrix_rows, week_fieldnames)
    print(
        f"      weekly_matrix.csv  - {len(matrix_rows):,} rows x {len(all_weeks)} weeks"
    )

    # Summary stats for the matrix
    all_counts = [
        cell.week_counts.get(week, 0)
        for cell in filtered.values()
        for week in all_weeks
    ]
    nonzero = sum(1 for c in all_counts if c > 0)
    sparsity = 1.0 - nonzero / max(len(all_counts), 1)
    print(f"      Matrix sparsity    - {sparsity:.1%} zero entries (expected for violation data)")

    # --- edges.csv ---
    edge_rows = [
        {
            "source": e["source"],
            "target": e["target"],
            "distance_meters": e["distance_meters"],
            "weight": e["weight"],
        }
        for e in edges
    ]
    edges_path = output_dir / "edges.csv"
    write_csv(edges_path, edge_rows, ["source", "target", "distance_meters", "weight"])
    print(f"      edges.csv          - {len(edge_rows):,} rows")

    # --- ml_artifacts_metadata.json ---
    metadata = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "source_csv": str(csv_path),
        "sparsity_filter": {
            "min_violations": args.min_violations,
            "min_active_days": args.min_active_days,
            "description": "Cells with fewer violations or active days are excluded "
                           "to prevent zero-inflated bias in model training.",
        },
        "cell_counts": {
            "raw": len(cells),
            "filtered": len(filtered),
            "removed_sparse": n_removed,
            "confidence_breakdown": conf_counts,
        },
        "graph": {
            "edge_count": len(edges),
            "edge_distance_meters": {
                "minimum": args.min_edge_meters,
                "maximum": args.max_edge_meters,
            },
            "isolated_nodes": isolated,
        },
        "timeline": {
            "week_count": len(all_weeks),
            "first_week": all_weeks[0] if all_weeks else None,
            "last_week": all_weeks[-1] if all_weeks else None,
            "forecast_week": forecast_week,
            "holdout_weeks": holdout_weeks,
            "weeks": all_weeks,
        },
        "matrix_sparsity": round(sparsity, 4),
        "files": {
            "nodes": str(nodes_path),
            "weekly_matrix": str(matrix_path),
            "edges": str(edges_path),
        },
    }
    meta_path = output_dir / "ml_artifacts_metadata.json"
    with meta_path.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"      ml_artifacts_metadata.json - written")

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  EXPORT COMPLETE")
    print("=" * 60)
    print(f"  Filtered cells : {len(filtered):,}")
    print(f"  ISO weeks      : {len(all_weeks)}  ({all_weeks[0]} to {all_weeks[-1]})")
    print(f"  Graph edges    : {len(edges):,}")
    print(f"  Forecast week  : {forecast_week}")
    print(f"  Holdout weeks  : {holdout_weeks}")
    print(f"  Output dir     : {output_dir.resolve()}")
    print("=" * 60)
    print("\nNext step: python scripts/train_xgboost.py")


if __name__ == "__main__":
    main()
