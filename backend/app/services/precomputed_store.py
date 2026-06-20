from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


class PrecomputedDataError(RuntimeError):
    pass


class PrecomputedStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or Path(__file__).resolve().parents[1] / "data" / "processed"
        self.metadata = self._load_json("metadata.json")
        self.hotspots: list[dict[str, Any]] = self._load_json("hotspots.json")
        self.edges: list[dict[str, Any]] = self._load_json("graph_edges.json")
        self.temporal: dict[str, Any] = self._load_json("temporal.json")
        self.hotspots_by_id = {
            hotspot["grid_cell_id"]: hotspot for hotspot in self.hotspots
        }
        self.forecast_source, self.forecast = self._load_forecast()
        self.weekly_timeseries: dict[str, list[dict[str, Any]]] = self._load_json(
            "weekly_timeseries.json"
        )
        self.cell_timeseries: dict[str, list[dict[str, Any]]] = self._load_json(
            "cell_timeseries.json"
        )
        self.edges_by_cell = self._index_edges(self.edges)

    def _load_json(self, filename: str) -> Any:
        path = self.data_dir / filename
        if not path.exists():
            raise PrecomputedDataError(
                f"Missing precomputed file: {path}. Run `python scripts/preprocess_official_csv.py`."
            )
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except json.JSONDecodeError as exc:
            raise PrecomputedDataError(f"Invalid JSON in precomputed file: {path}") from exc

    def _load_optional_json(self, filename: str) -> Any | None:
        path = self.data_dir / filename
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except json.JSONDecodeError as exc:
            raise PrecomputedDataError(f"Invalid JSON in precomputed file: {path}") from exc

    def _load_forecast(self) -> tuple[str, dict[str, Any]]:
        forecast_source = "forecast_graphsage.json"
        forecast = self._load_optional_json(forecast_source)
        if forecast is None:
            forecast_source = "forecast.json"
            forecast = self._load_json(forecast_source)
        return forecast_source, self._normalize_forecast(forecast, forecast_source)

    def _normalize_forecast(
        self, forecast: dict[str, Any], forecast_source: str
    ) -> dict[str, Any]:
        normalized = forecast.copy()
        normalized["forecast_source"] = forecast_source
        normalized["model"] = normalized.get("model") or (
            "GraphSAGE" if forecast_source == "forecast_graphsage.json" else "Heuristic"
        )

        items = []
        max_predicted = max(
            (
                float(item.get("predicted_violation_count", 0))
                for item in normalized.get("items", [])
            ),
            default=1.0,
        )
        for item in normalized.get("items", []):
            normalized_item = item.copy()
            hotspot = self.hotspots_by_id.get(normalized_item.get("grid_cell_id"), {})
            predicted_count = float(normalized_item.get("predicted_violation_count", 0))
            predicted_risk = float(
                normalized_item.get(
                    "predicted_obstruction_risk",
                    100.0 * predicted_count / max(max_predicted, 1.0),
                )
            )
            normalized_item.setdefault("station", hotspot.get("dominant_station"))
            normalized_item.setdefault("junction", hotspot.get("dominant_junction"))
            normalized_item.setdefault("location", hotspot.get("representative_location"))
            normalized_item.setdefault("predicted_obstruction_risk", round(predicted_risk, 2))
            normalized_item.setdefault(
                "predicted_enforcement_priority",
                round(min(100.0, predicted_risk * 0.7 + predicted_count * 1.2), 2),
            )
            normalized_item.setdefault("confidence", hotspot.get("confidence") or "Model")
            normalized_item.setdefault("neighbor_influence", hotspot.get("neighbor_influence", 0))
            normalized_item.setdefault("forecast_reason_codes", item.get("reason_codes", []))
            normalized_item.setdefault("reason_codes", item.get("forecast_reason_codes", []))
            items.append(normalized_item)

        normalized["items"] = items
        return normalized

    @staticmethod
    def _index_edges(edges: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        indexed: dict[str, list[dict[str, Any]]] = {}
        for edge in edges:
            indexed.setdefault(edge["source"], []).append(edge)
            indexed.setdefault(edge["target"], []).append(edge)
        return indexed

    def data_ready(self) -> bool:
        return precomputed_files_ready(self.data_dir)

    def summary(self) -> dict[str, Any]:
        stations = {item.get("dominant_station") for item in self.hotspots}
        stations.discard(None)
        return {
            "hotspot_count": len(self.hotspots),
            "edge_count": len(self.edges),
            "station_count": len(stations),
            "total_violations": sum(item["violation_count"] for item in self.hotspots),
            "score_name": self.metadata.get("score_name", "Obstruction Risk Score"),
            "score_note": self.metadata.get(
                "score_note", "This is a congestion-risk proxy, not measured congestion."
            ),
            "metadata": self.metadata,
        }

    def filtered_hotspots(
        self, limit: int, station: str | None, confidence: str | None
    ) -> list[dict[str, Any]]:
        station_filter = station.casefold() if station else None
        confidence_filter = confidence.casefold() if confidence else None
        results = []
        for hotspot in self.hotspots:
            if station_filter:
                hotspot_station = (hotspot.get("dominant_station") or "").casefold()
                if hotspot_station != station_filter:
                    continue
            if confidence_filter and hotspot.get("confidence", "").casefold() != confidence_filter:
                continue
            results.append(hotspot)
            if len(results) >= limit:
                break
        return results

    def get_hotspot(self, cell_id: str) -> dict[str, Any] | None:
        return self.hotspots_by_id.get(cell_id)

    def timeseries(self, cell_id: str) -> list[dict[str, Any]] | None:
        if cell_id not in self.hotspots_by_id:
            return None
        return self.cell_timeseries.get(cell_id, [])

    def weekly_series(self, cell_id: str) -> list[dict[str, Any]] | None:
        if cell_id not in self.hotspots_by_id:
            return None
        return self.weekly_timeseries.get(cell_id, [])

    def stations(self) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for hotspot in self.hotspots:
            station = hotspot.get("dominant_station")
            if not station:
                continue
            row = grouped.setdefault(
                station,
                {
                    "station": station,
                    "hotspot_count": 0,
                    "violation_count": 0,
                    "risk_score_sum": 0.0,
                },
            )
            row["hotspot_count"] += 1
            row["violation_count"] += hotspot["violation_count"]
            row["risk_score_sum"] += hotspot["obstruction_risk_score"]

        stations = []
        for row in grouped.values():
            stations.append(
                {
                    "station": row["station"],
                    "hotspot_count": row["hotspot_count"],
                    "violation_count": row["violation_count"],
                    "mean_obstruction_risk_score": round(
                        row["risk_score_sum"] / row["hotspot_count"], 2
                    ),
                }
            )
        return sorted(stations, key=lambda item: item["violation_count"], reverse=True)

    def cell_graph(self, cell_id: str) -> dict[str, Any] | None:
        node = self.get_hotspot(cell_id)
        if node is None:
            return None
        edges = self.edges_by_cell.get(cell_id, [])
        neighbor_ids = {
            edge["target"] if edge["source"] == cell_id else edge["source"]
            for edge in edges
        }
        neighbors = [
            self.hotspots_by_id[neighbor_id]
            for neighbor_id in neighbor_ids
            if neighbor_id in self.hotspots_by_id
        ]
        neighbors.sort(
            key=lambda item: (item["obstruction_risk_score"], item["violation_count"]),
            reverse=True,
        )
        return {
            "cell_id": cell_id,
            "node": node,
            "neighbors": neighbors,
            "edges": edges,
        }


@lru_cache(maxsize=1)
def get_store() -> PrecomputedStore:
    return PrecomputedStore()


def precomputed_files_ready(data_dir: Path | None = None) -> bool:
    resolved_data_dir = data_dir or Path(__file__).resolve().parents[1] / "data" / "processed"
    required = [
        "metadata.json",
        "hotspots.json",
        "graph_edges.json",
        "temporal.json",
        "forecast.json",
        "weekly_timeseries.json",
        "cell_timeseries.json",
    ]
    return all((resolved_data_dir / filename).exists() for filename in required)
