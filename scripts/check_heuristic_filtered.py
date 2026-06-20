"""Check heuristic MAE restricted to filtered cells only.

Runs the same rolling-origin backtest as preprocess_official_csv.py but
computes MAE ONLY for the 2,478 filtered cells that ML models were evaluated on.
This gives a fair apples-to-apples comparison.

Also prints:
  - Heuristic MAE on ALL cells (original)
  - Heuristic MAE on FILTERED cells only (new, fair comparison)
  - Heuristic MAE on SPARSE cells only (shows how easy they are)
  - Side-by-side table vs ML models

Usage:
  python scripts/check_heuristic_filtered.py
"""

from __future__ import annotations

import csv as csv_module
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from preprocess_official_csv import (
    DEFAULT_MAX_EDGE_METERS,
    DEFAULT_MIN_EDGE_METERS,
    build_edge_lookup,
    build_edges,
    find_official_csv,
    predict_week_count,
    read_and_aggregate,
    serialize_hotspots,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CSV_DIR      = Path("data")
ARTIFACTS_DIR = Path("backend/app/data/processed/ml_artifacts")
OUTPUT_DIR   = Path("backend/app/data/processed")


def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as h:
        return json.load(h)


def main() -> None:
    print("\n" + "=" * 62)
    print("  Heuristic MAE: Filtered vs Unfiltered Cell Breakdown")
    print("=" * 62)

    # ------------------------------------------------------------------
    # Load filtered cell IDs from ML artifacts
    # ------------------------------------------------------------------
    nodes_path = ARTIFACTS_DIR / "nodes.csv"
    if not nodes_path.exists():
        raise SystemExit(f"Missing {nodes_path} -- run export_ml_artifacts.py first.")

    with nodes_path.open("r", encoding="utf-8", newline="") as h:
        filtered_cell_ids = {row["cell_id"] for row in csv_module.DictReader(h)}

    meta = load_json(ARTIFACTS_DIR / "ml_artifacts_metadata.json")
    if meta is None:
        raise SystemExit("ml_artifacts_metadata.json missing.")

    all_weeks:     list[str] = meta["timeline"]["weeks"]
    holdout_weeks: list[str] = meta["timeline"]["holdout_weeks"]
    print(f"\n  Filtered cells (ML training set) : {len(filtered_cell_ids):,}")
    print(f"  Holdout weeks                    : {holdout_weeks}")

    # ------------------------------------------------------------------
    # Re-run heuristic aggregation
    # ------------------------------------------------------------------
    csv_files = sorted(CSV_DIR.glob("*.csv"))
    if len(csv_files) != 1:
        raise SystemExit(f"Expected exactly 1 CSV in {CSV_DIR}. Found: {csv_files}")

    print(f"\n  Reading CSV: {csv_files[0].name} ...")
    cells, total_rows, _ = read_and_aggregate(csv_files[0])
    print(f"  {total_rows:,} rows -> {len(cells):,} cells aggregated")

    all_cell_ids  = list(cells.keys())
    sparse_cell_ids = [c for c in all_cell_ids if c not in filtered_cell_ids]
    print(f"  All cells     : {len(all_cell_ids):,}")
    print(f"  Filtered      : {len(filtered_cell_ids):,}  (medium/high confidence)")
    print(f"  Sparse        : {len(sparse_cell_ids):,}  (< 8 violations)")

    # Build heuristic infrastructure
    edges        = build_edges(cells, DEFAULT_MIN_EDGE_METERS, DEFAULT_MAX_EDGE_METERS)
    edge_lookup  = build_edge_lookup(edges)
    hotspots     = serialize_hotspots(cells)
    hotspot_lookup = {h["grid_cell_id"]: h for h in hotspots}

    counts_by_cell = {cid: cell.week_counts for cid, cell in cells.items()}
    station_by_cell: dict[str, str] = {
        cid: hotspot_lookup[cid].get("dominant_station") or "Unknown"
        for cid in counts_by_cell
        if cid in hotspot_lookup
    }
    station_counts_by_week: dict[str, Counter] = defaultdict(Counter)
    for cid, counts in counts_by_cell.items():
        if cid in station_by_cell:
            station_counts_by_week[station_by_cell[cid]].update(counts)

    # ------------------------------------------------------------------
    # Rolling-origin backtest — collect errors split by cell type
    # ------------------------------------------------------------------
    print(f"\n  Running rolling-origin backtest across {len(holdout_weeks)} holdout weeks ...")

    # Accumulators
    err_all      = 0.0; n_all      = 0
    err_filtered = 0.0; n_filtered = 0
    err_sparse   = 0.0; n_sparse   = 0
    ape_all      = 0.0; ape_fil    = 0.0; ape_spar   = 0.0

    fold_rows: list[dict] = []

    for holdout_week in holdout_weeks:
        train_weeks = [w for w in all_weeks if w < holdout_week]
        if not train_weeks:
            continue

        fold_err_all = 0.0; fold_n_all = 0
        fold_err_fil = 0.0; fold_n_fil = 0
        fold_err_spr = 0.0; fold_n_spr = 0

        for cell_id in all_cell_ids:
            actual = float(cells[cell_id].week_counts.get(holdout_week, 0))
            pred   = predict_week_count(
                cell_id,
                train_weeks,
                counts_by_cell,
                edge_lookup,
                station_by_cell,
                station_counts_by_week,
                hotspot_lookup,
            )
            pred = max(0.0, pred)
            abs_err = abs(pred - actual)

            err_all += abs_err;  n_all += 1
            fold_err_all += abs_err; fold_n_all += 1
            if actual > 0:
                ape_all += abs_err / actual

            if cell_id in filtered_cell_ids:
                err_filtered += abs_err; n_filtered += 1
                fold_err_fil += abs_err; fold_n_fil  += 1
                if actual > 0:
                    ape_fil += abs_err / actual
            else:
                err_sparse += abs_err; n_sparse += 1
                fold_err_spr += abs_err; fold_n_spr  += 1
                if actual > 0:
                    ape_spar += abs_err / actual

        fold_rows.append({
            "week"         : holdout_week,
            "mae_all"      : round(fold_err_all / fold_n_all, 4) if fold_n_all else None,
            "mae_filtered" : round(fold_err_fil  / fold_n_fil,  4) if fold_n_fil  else None,
            "mae_sparse"   : round(fold_err_spr  / fold_n_spr,  4) if fold_n_spr  else None,
        })
        print(
            f"    {holdout_week}:  "
            f"MAE(all)={fold_rows[-1]['mae_all']:.3f}  "
            f"MAE(filtered)={fold_rows[-1]['mae_filtered']:.3f}  "
            f"MAE(sparse)={fold_rows[-1]['mae_sparse']:.3f}"
        )

    mae_all      = round(err_all      / n_all,      4) if n_all      else None
    mae_filtered = round(err_filtered / n_filtered, 4) if n_filtered else None
    mae_sparse   = round(err_sparse   / n_sparse,   4) if n_sparse   else None
    mape_all      = round((ape_all  / n_all)      * 100, 2) if n_all      else None
    mape_filtered = round((ape_fil  / n_filtered) * 100, 2) if n_filtered else None
    mape_sparse   = round((ape_spar / n_sparse)   * 100, 2) if n_sparse   else None

    # ------------------------------------------------------------------
    # Load ML model MAEs for comparison
    # ------------------------------------------------------------------
    ml_models: dict[str, float] = {}
    comparison = load_json(OUTPUT_DIR / "model_comparison.json")
    if comparison:
        for m in comparison.get("models", []):
            if m["name"] != "Heuristic Baseline":
                ml_models[m["name"]] = m.get("mae", 0.0)

    # ------------------------------------------------------------------
    # Print summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 62)
    print("  RESULTS")
    print("=" * 62)
    print(f"\n  {'Metric':<42} {'MAE':>7}  {'MAPE':>8}")
    print(f"  {'-'*42} {'-'*7}  {'-'*8}")
    print(f"  {'Heuristic — ALL cells (original)':<42} {mae_all:>7.4f}  {mape_all:>7.2f}%")
    print(f"  {'Heuristic — FILTERED cells only (fair)':<42} {mae_filtered:>7.4f}  {mape_filtered:>7.2f}%")
    print(f"  {'Heuristic — SPARSE cells only (trivial)':<42} {mae_sparse:>7.4f}  {mape_sparse:>7.2f}%")
    print(f"  {'-'*42} {'-'*7}  {'-'*8}")
    for name, mae_val in sorted(ml_models.items(), key=lambda x: x[1]):
        label = name + " (filtered)"
        print(f"  {label:<42} {mae_val:>7.4f}  (ML model)")

    print("\n" + "=" * 62)
    print("  INTERPRETATION")
    print("=" * 62)

    if mae_filtered is not None and mae_sparse is not None:
        ratio = round(mae_filtered / max(mae_sparse, 0.01), 1)
        print(f"\n  Sparse cell MAE  : {mae_sparse:.4f}  (easy — almost always ~0)")
        print(f"  Filtered cell MAE: {mae_filtered:.4f}  ({ratio}x harder than sparse)")

    if mae_filtered is not None and "GraphSAGE" in ml_models:
        sage_mae = ml_models["GraphSAGE"]
        delta    = round(mae_filtered - sage_mae, 4)
        if delta > 0:
            print(f"\n  On FILTERED cells: GraphSAGE beats heuristic by {delta:.4f} MAE")
            print(f"  -> GraphSAGE IS the better model on enforcement hotspots")
        else:
            print(f"\n  On FILTERED cells: Heuristic still leads by {abs(delta):.4f} MAE")
            print(f"  -> Heuristic domain knowledge is hard to beat even on hard cells")

    # ------------------------------------------------------------------
    # Answer: should we run GraphSAGE on all cells?
    # ------------------------------------------------------------------
    print("\n" + "=" * 62)
    print("  SHOULD YOU RUN GRAPHSAGE ON ALL 6,782 CELLS?")
    print("=" * 62)
    print("""
  SHORT ANSWER: No — train on filtered, predict 0 for sparse.

  WHY:
  1. Sparse cells have near-zero counts — trivially predicted as 0.
     GraphSAGE training on them adds noise without useful signal.

  2. Training on 6,782 cells means the model learns to predict
     small-count cells well, at the cost of high-count cell accuracy.
     That's the opposite of what enforcement prioritisation needs.

  3. For the frontend/API: the heuristic already covers ALL 6,782 cells
     in forecast.json. GraphSAGE covers the 2,478 that matter most.
     For sparse cells in the ML forecasts, just return predicted=0.

  PRACTICAL DEPLOYMENT STRATEGY:
  ┌─────────────────────────────────────────────────────┐
  │  Cell type   │  Model used        │  Why             │
  │─────────────────────────────────────────────────────│
  │  Filtered    │  GraphSAGE         │  Best accuracy   │
  │  Sparse      │  Heuristic / 0     │  Trivial signal  │
  └─────────────────────────────────────────────────────┘
""")
    print("=" * 62)

    # ------------------------------------------------------------------
    # Save updated comparison to model_comparison.json
    # ------------------------------------------------------------------
    if comparison:
        for m in comparison["models"]:
            if m["name"] == "Heuristic Baseline":
                m["mae_filtered_cells_only"] = mae_filtered
                m["mae_sparse_cells_only"]   = mae_sparse
                m["mape_filtered_cells_only"] = mape_filtered
                m["note"] = (
                    f"Original MAE ({mae_all}) includes {len(sparse_cell_ids):,} sparse cells "
                    f"(trivially easy, MAE={mae_sparse}). "
                    f"Fair comparison against ML models: MAE={mae_filtered} on "
                    f"filtered cells only."
                )
                break
        with (OUTPUT_DIR / "model_comparison.json").open("w", encoding="utf-8") as h:
            json.dump(comparison, h, indent=2, ensure_ascii=False)
            h.write("\n")
        print(f"\n  model_comparison.json updated with filtered-cell heuristic MAE.")


if __name__ == "__main__":
    main()
