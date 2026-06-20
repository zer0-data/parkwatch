from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    data_ready: bool


class SummaryResponse(BaseModel):
    hotspot_count: int
    edge_count: int
    station_count: int
    total_violations: int
    score_name: str
    score_note: str
    metadata: dict[str, Any]


class GridCell(BaseModel):
    size_degrees: float
    lat_index: int
    lon_index: int


class Hotspot(BaseModel):
    grid_cell_id: str
    grid: GridCell
    latitude: float
    longitude: float
    violation_count: int
    active_days: int
    active_weeks: int
    active_months: int | None = None
    device_days: int
    mean_severity: float
    junction_share: float
    approved_count: int
    validated_count: int
    dominant_station: str | None = None
    dominant_junction: str | None = None
    representative_location: str | None = None
    peak_hour: int | None = None
    peak_weekday: str | None = None
    peak_month: str | None = None
    dominant_violation_type: str | None = None
    neighbor_influence: float
    obstruction_risk_score: float = Field(ge=0, le=100)
    enforcement_priority_score: float = Field(ge=0, le=100)
    station_normalized_volume: float
    temporal_concentration: float
    recent_activity_score: float
    recent_trend_ratio: float
    stability_score: float = Field(ge=0, le=100)
    priority_band: str
    risk_score_type: str
    model_version: str | None = None
    confidence: str
    reason_codes: list[str]


class TimeseriesPoint(BaseModel):
    date: str
    violation_count: int


class StationSummary(BaseModel):
    station: str
    hotspot_count: int
    violation_count: int
    mean_obstruction_risk_score: float


class TemporalHourlyPoint(BaseModel):
    hour: int = Field(ge=0, le=23)
    violation_count: int


class TemporalWeekdayPoint(BaseModel):
    weekday: str
    violation_count: int


class TemporalHeatmapPoint(BaseModel):
    weekday: str
    hour: int = Field(ge=0, le=23)
    violation_count: int


class GraphEdge(BaseModel):
    source: str
    target: str
    distance_meters: float
    weight: float


class CellGraphResponse(BaseModel):
    cell_id: str
    node: Hotspot
    neighbors: list[Hotspot]
    edges: list[GraphEdge]


class WeeklyTimeseriesPoint(BaseModel):
    week: str
    violation_count: int


class ForecastItem(BaseModel):
    grid_cell_id: str
    station: str | None = None
    junction: str | None = None
    location: str | None = None
    latitude: float
    longitude: float
    predicted_week: str | None = None
    predicted_violation_count: float
    prediction_interval_low: float
    prediction_interval_high: float
    predicted_obstruction_risk: float = Field(ge=0, le=100)
    # Optional: heuristic-only fields not present in ML model forecasts
    predicted_enforcement_priority: float = Field(default=0.0, ge=0, le=100)
    forecast_stability: float = Field(ge=0, le=100)
    confidence: str | None = None
    neighbor_influence: float = 0.0
    last_1_week_count: int
    last_2_week_avg: float
    last_4_week_avg: float
    historical_weeks: list[WeeklyTimeseriesPoint]
    forecast_reason_codes: list[str]
    reason_codes: list[str]


class ForecastResponse(BaseModel):
    forecast_type: str
    not_measured_congestion: bool
    method: str
    forecast_week: str | None = None
    holdout: dict[str, Any]
    items: list[ForecastItem]
