from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from .models import (
    CellGraphResponse,
    CopilotRequest,
    CopilotResponse,
    DelayExposureRequest,
    DelayExposureResponse,
    ForecastResponse,
    HealthResponse,
    Hotspot,
    PatrolPlanRequest,
    PatrolPlanResponse,
    StationSummary,
    SummaryResponse,
    TemporalHeatmapPoint,
    TemporalHourlyPoint,
    TemporalWeekdayPoint,
    TimeseriesPoint,
    WeeklyTimeseriesPoint,
)
from .services.copilot import answer_copilot
from .services.mappls import (
    build_delay_exposure,
    build_patrol_plan,
    nearby_context,
    reverse_geocode,
)
from .services.precomputed_store import (
    PrecomputedDataError,
    get_store,
    precomputed_files_ready,
)


app = FastAPI(
    title="ParkWatch API",
    version="0.1.0",
    description="Read-only API over ParkWatch precomputed official-dataset JSON outputs.",
)


@app.on_event("startup")
def warm_precomputed_store() -> None:
    get_store()


@app.exception_handler(PrecomputedDataError)
async def precomputed_data_error_handler(
    request: Request, exc: PrecomputedDataError
) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "detail": str(exc),
            "path": str(request.url.path),
        },
    )


@app.get("/api/health", response_model=HealthResponse)
def health() -> dict[str, object]:
    return {"status": "ok", "data_ready": precomputed_files_ready()}


@app.get("/api/summary", response_model=SummaryResponse)
def summary() -> dict[str, object]:
    return get_store().summary()


@app.get("/api/hotspots", response_model=list[Hotspot])
def hotspots(
    limit: int = Query(default=100, ge=1, le=10000),
    station: str | None = Query(default=None),
    confidence: str | None = Query(default=None, pattern="^(High|Medium|Low)$"),
) -> list[dict[str, object]]:
    return get_store().filtered_hotspots(limit, station, confidence)


@app.get("/api/hotspots/{cell_id}", response_model=Hotspot)
def hotspot_detail(cell_id: str) -> dict[str, object]:
    hotspot = get_store().get_hotspot(cell_id)
    if hotspot is None:
        raise HTTPException(status_code=404, detail=f"Hotspot not found: {cell_id}")
    return hotspot


@app.get("/api/timeseries/{cell_id}", response_model=list[TimeseriesPoint])
def hotspot_timeseries(cell_id: str) -> list[dict[str, object]]:
    timeseries = get_store().timeseries(cell_id)
    if timeseries is None:
        raise HTTPException(status_code=404, detail=f"Hotspot not found: {cell_id}")
    return timeseries


@app.get("/api/timeseries/{cell_id}/weekly", response_model=list[WeeklyTimeseriesPoint])
def hotspot_weekly_timeseries(cell_id: str) -> list[dict[str, object]]:
    timeseries = get_store().weekly_series(cell_id)
    if timeseries is None:
        raise HTTPException(status_code=404, detail=f"Hotspot not found: {cell_id}")
    return timeseries


@app.get("/api/stations", response_model=list[StationSummary])
def stations() -> list[dict[str, object]]:
    return get_store().stations()


@app.get("/api/temporal/hourly", response_model=list[TemporalHourlyPoint])
def temporal_hourly() -> list[dict[str, object]]:
    return get_store().temporal["hourly"]


@app.get("/api/temporal/weekday", response_model=list[TemporalWeekdayPoint])
def temporal_weekday() -> list[dict[str, object]]:
    return get_store().temporal["weekday"]


@app.get("/api/temporal/heatmap", response_model=list[TemporalHeatmapPoint])
def temporal_heatmap() -> list[dict[str, object]]:
    return get_store().temporal["heatmap"]


@app.get("/api/graph/{cell_id}", response_model=CellGraphResponse)
def graph(cell_id: str) -> dict[str, object]:
    cell_graph = get_store().cell_graph(cell_id)
    if cell_graph is None:
        raise HTTPException(status_code=404, detail=f"Hotspot not found: {cell_id}")
    return cell_graph


@app.get("/api/forecast", response_model=ForecastResponse)
def forecast(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, object]:
    payload = get_store().forecast.copy()
    payload["items"] = payload.get("items", [])[:limit]
    return payload


@app.get("/api/model-evidence")
def model_evidence() -> dict[str, object]:
    return get_store().model_evidence()


@app.post("/api/copilot", response_model=CopilotResponse)
async def copilot(request: CopilotRequest, response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return await answer_copilot(request, get_store())


@app.post("/api/mappls/patrol-plan", response_model=PatrolPlanResponse)
def mappls_patrol_plan(request: PatrolPlanRequest) -> dict[str, object]:
    return build_patrol_plan(request.candidates)


@app.post("/api/mappls/delay-exposure", response_model=DelayExposureResponse)
def mappls_delay_exposure(request: DelayExposureRequest) -> dict[str, object]:
    return build_delay_exposure(request.candidates, request.scenario_reduction)


@app.get("/api/mappls/reverse-geocode")
def mappls_reverse_geocode(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
) -> dict[str, object]:
    return reverse_geocode(lat, lon)


@app.get("/api/mappls/nearby")
def mappls_nearby(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
) -> dict[str, object]:
    return nearby_context(lat, lon)
