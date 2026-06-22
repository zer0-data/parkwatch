from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import httpx

from ..models import PatrolCandidate


EARTH_RADIUS_KM = 6371.0
DEFAULT_BASE_URL = "https://apis.mappls.com/advancedmaps/v1"
CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache"
CACHE_FILE = CACHE_DIR / "mappls_patrol_plans.json"
DELAY_CACHE_FILE = CACHE_DIR / "mappls_delay_exposure.json"
CONTEXT_KEYWORDS = ["metro", "bus stop", "market", "hospital", "school", "junction"]
OSRM_BASE_URL = "https://router.project-osrm.org"


def build_patrol_plan(candidates: list[PatrolCandidate]) -> dict[str, Any]:
    key = os.getenv("MAPPLS_REST_KEY", "").strip()
    cache_key = f"{'mappls' if key else 'fallback'}:{_cache_key(candidates)}"
    cached = _read_cache().get(cache_key)
    if cached:
        cached["cached"] = True
        return cached

    if not key:
        return _fallback_plan(candidates, "MAPPLS_REST_KEY is not configured")

    base_url = os.getenv("MAPPLS_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    timeout = float(os.getenv("MAPPLS_TIMEOUT_SECONDS", "8"))

    try:
        with httpx.Client(timeout=timeout) as client:
            matrix = _fetch_distance_matrix(client, base_url, key, candidates, traffic=True)
            route_mode = "mappls_traffic_eta"
            routing_source = "Mappls Traffic ETA"
            if matrix is None:
                matrix = _fetch_distance_matrix(client, base_url, key, candidates, traffic=False)
                route_mode = "mappls_road_distance"
                routing_source = "Mappls Road Distance"
            if matrix is None:
                return _fallback_plan(candidates, "Mappls distance matrix did not return usable costs")

            route_indexes = _build_route(candidates, matrix["costs"])
            ordered = [candidates[index] for index in route_indexes]
            segments = _segments_from_matrix(ordered, route_indexes, matrix)
            geometry = _fetch_route_geometry(client, base_url, key, ordered, traffic=route_mode == "mappls_traffic_eta")
            if not geometry:
                geometry = [(item.latitude, item.longitude) for item in ordered]

            labels = _fetch_reverse_labels(client, base_url, key, ordered[: min(5, len(ordered))])
            nearby: dict[str, list[str]] = {}
            for stop in ordered[: min(3, len(ordered))]:
                nearby.update(_fetch_nearby_context(client, base_url, key, stop))

            response = _response(
                route_mode=route_mode,
                routing_source=routing_source,
                stops=ordered,
                segments=segments,
                geometry=geometry,
                labels=labels,
                nearby_by_cell=nearby,
            )
            _write_cache_entry(cache_key, response)
            return response
    except Exception as exc:
        return _fallback_plan(candidates, f"Mappls request failed: {exc.__class__.__name__}")


def build_delay_exposure(
    candidates: list[PatrolCandidate],
    scenario_reduction: float = 0.2,
) -> dict[str, Any]:
    key = os.getenv("MAPPLS_REST_KEY", "").strip()
    cache_key = (
        f"{'mappls' if key else 'fallback'}:{_cache_key(candidates)}"
        f":{round(scenario_reduction, 3)}"
    )
    cached = _read_json_cache(DELAY_CACHE_FILE).get(cache_key)
    if cached:
        cached["cached"] = True
        return cached

    base_url = os.getenv("MAPPLS_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    timeout = float(os.getenv("MAPPLS_TIMEOUT_SECONDS", "8"))
    rows: list[dict[str, Any]] = []
    fallback_reasons: list[str] = []

    with httpx.Client(timeout=timeout) as client:
        for candidate in candidates:
            traffic = None
            freeflow = None
            source = "Heuristic fallback"
            if key:
                try:
                    traffic = _fetch_local_corridor_summary(
                        client, base_url, key, candidate, traffic=True
                    )
                except Exception as exc:
                    fallback_reasons.append(f"{candidate.grid_cell_id}: traffic {exc.__class__.__name__}")
                try:
                    freeflow = _fetch_local_corridor_summary(
                        client, base_url, key, candidate, traffic=False
                    )
                except Exception as exc:
                    fallback_reasons.append(f"{candidate.grid_cell_id}: freeflow {exc.__class__.__name__}")
            else:
                fallback_reasons.append("MAPPLS_REST_KEY is not configured")

            if freeflow is None:
                try:
                    freeflow = _fetch_osrm_corridor_summary(client, candidate)
                    source = "OSRM/OSM baseline + heuristic traffic prior"
                except Exception:
                    freeflow = _heuristic_corridor_summary(candidate)

            if traffic is not None and freeflow is not None:
                source = "Mappls Traffic ETA + Mappls road baseline"

            rows.append(_delay_item(candidate, traffic, freeflow, scenario_reduction, source))

    rows.sort(key=lambda item: item["estimated_delay_exposure_minutes"], reverse=True)
    for index, row in enumerate(rows, start=1):
        row["rank"] = index

    response = {
        "source": _combined_delay_source(rows),
        "cached": False,
        "fallback_reason": "; ".join(dict.fromkeys(fallback_reasons))[:500] or None,
        "total_delay_exposure_minutes": round(
            sum(item["estimated_delay_exposure_minutes"] for item in rows), 1
        ),
        "total_reduced_delay_exposure_minutes": round(
            sum(item["reduced_delay_exposure_minutes"] for item in rows), 1
        ),
        "items": rows,
    }
    _write_json_cache_entry(DELAY_CACHE_FILE, cache_key, response)
    return response


def reverse_geocode(lat: float, lon: float) -> dict[str, Any]:
    key = os.getenv("MAPPLS_REST_KEY", "").strip()
    if not key:
        return {"label": None, "source": "unavailable", "detail": "MAPPLS_REST_KEY is not configured"}

    base_url = os.getenv("MAPPLS_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    timeout = float(os.getenv("MAPPLS_TIMEOUT_SECONDS", "8"))
    try:
        with httpx.Client(timeout=timeout) as client:
            payload = _get_json(
                client,
                f"{base_url}/{key}/rev_geocode",
                {"lat": lat, "lng": lon, "region": "IND"},
            )
        return {"label": _extract_label(payload), "source": "Mappls Reverse Geocode"}
    except Exception as exc:
        return {"label": None, "source": "fallback", "detail": exc.__class__.__name__}


def nearby_context(lat: float, lon: float) -> dict[str, Any]:
    key = os.getenv("MAPPLS_REST_KEY", "").strip()
    if not key:
        return {"items": [], "source": "unavailable", "detail": "MAPPLS_REST_KEY is not configured"}

    base_url = os.getenv("MAPPLS_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    timeout = float(os.getenv("MAPPLS_TIMEOUT_SECONDS", "8"))
    try:
        with httpx.Client(timeout=timeout) as client:
            candidate = PatrolCandidate(
                grid_cell_id="ad-hoc",
                latitude=lat,
                longitude=lon,
                location="Selected coordinate",
                predictedViolations=0,
                forecastPriority=0,
                obstructionRisk=0,
            )
            items = _fetch_nearby_context(client, base_url, key, candidate).get("ad-hoc", [])
        return {"items": items, "source": "Mappls Nearby"}
    except Exception as exc:
        return {"items": [], "source": "fallback", "detail": exc.__class__.__name__}


def _fetch_distance_matrix(
    client: httpx.Client,
    base_url: str,
    key: str,
    candidates: list[PatrolCandidate],
    *,
    traffic: bool,
) -> dict[str, list[list[float | None]]] | None:
    coordinates = ";".join(f"{item.longitude},{item.latitude}" for item in candidates)
    path = "distance_matrix_eta" if traffic else "distance_matrix"
    payload = _get_json(
        client,
        f"{base_url}/{key}/{path}/driving/{coordinates}",
        {"rtype": 1 if traffic else 0, "region": "IND"},
    )
    distances = _extract_square_matrix(payload, ["distances", "distance", "distanceMeters"])
    durations = _extract_square_matrix(payload, ["durations", "duration", "durationSeconds", "times"])
    if distances is None and durations is None:
        return None

    count = len(candidates)
    costs: list[list[float | None]] = []
    for row in range(count):
        cost_row: list[float | None] = []
        for col in range(count):
            duration = _matrix_value(durations, row, col)
            distance = _matrix_value(distances, row, col)
            if traffic and duration is not None:
                cost_row.append(max(duration / 60.0, 0.01))
            elif distance is not None:
                cost_row.append(max(_distance_to_km(distance), 0.01))
            elif duration is not None:
                cost_row.append(max(duration / 60.0, 0.01))
            else:
                cost_row.append(None)
        costs.append(cost_row)

    return {"costs": costs, "distances": distances or [], "durations": durations or []}


def _fetch_route_geometry(
    client: httpx.Client,
    base_url: str,
    key: str,
    route: list[PatrolCandidate],
    *,
    traffic: bool,
) -> list[tuple[float, float]]:
    if len(route) < 2:
        return [(item.latitude, item.longitude) for item in route]
    coordinates = ";".join(f"{item.longitude},{item.latitude}" for item in route)
    path = "route_eta" if traffic else "route_adv"
    payload = _get_json(
        client,
        f"{base_url}/{key}/{path}/driving/{coordinates}",
        {"geometries": "geojson", "overview": "full", "rtype": 1 if traffic else 0, "region": "IND"},
    )
    return _extract_geometry(payload)


def _fetch_local_corridor_summary(
    client: httpx.Client,
    base_url: str,
    key: str,
    candidate: PatrolCandidate,
    *,
    traffic: bool,
) -> dict[str, float]:
    start, end = _corridor_points(candidate)
    path = "route_eta" if traffic else "route_adv"
    coordinates = f"{start[1]},{start[0]};{end[1]},{end[0]}"
    payload = _get_json(
        client,
        f"{base_url}/{key}/{path}/driving/{coordinates}",
        {"geometries": "geojson", "overview": "false", "rtype": 1 if traffic else 0, "region": "IND"},
    )
    return _extract_route_summary(payload) or _heuristic_corridor_summary(candidate)


def _fetch_osrm_corridor_summary(
    client: httpx.Client,
    candidate: PatrolCandidate,
) -> dict[str, float]:
    start, end = _corridor_points(candidate)
    base_url = os.getenv("OSRM_BASE_URL", OSRM_BASE_URL).rstrip("/")
    coordinates = f"{start[1]},{start[0]};{end[1]},{end[0]}"
    payload = _get_json(
        client,
        f"{base_url}/route/v1/driving/{coordinates}",
        {"overview": "false", "annotations": "duration,distance"},
    )
    return _extract_route_summary(payload) or _heuristic_corridor_summary(candidate)


def _corridor_points(candidate: PatrolCandidate) -> tuple[tuple[float, float], tuple[float, float]]:
    corridor_km = 0.7
    lat_rad = math.radians(candidate.latitude)
    lon_delta = (corridor_km / 2) / (111.32 * max(math.cos(lat_rad), 0.2))
    return (
        (candidate.latitude, candidate.longitude - lon_delta),
        (candidate.latitude, candidate.longitude + lon_delta),
    )


def _extract_route_summary(payload: Any) -> dict[str, float] | None:
    route = None
    routes = payload.get("routes") if isinstance(payload, dict) else None
    if isinstance(routes, list) and routes:
        route = routes[0]
    elif isinstance(payload, dict):
        route = payload
    if not isinstance(route, dict):
        return None
    duration = _to_float(route.get("duration") or route.get("durationSeconds") or route.get("time"))
    distance = _to_float(route.get("distance") or route.get("distanceMeters") or route.get("length"))
    if duration is None:
        duration = _to_float(_find_key(route, "duration"))
    if distance is None:
        distance = _to_float(_find_key(route, "distance"))
    if distance is None:
        return None
    return {
        "distance_km": round(_distance_to_km(distance), 3),
        "eta_minutes": round(duration / 60.0, 2) if duration is not None else round(_distance_to_km(distance) / 20 * 60, 2),
    }


def _heuristic_corridor_summary(candidate: PatrolCandidate) -> dict[str, float]:
    start, end = _corridor_points(candidate)
    a = PatrolCandidate(
        grid_cell_id="corridor-a",
        latitude=start[0],
        longitude=start[1],
        location="corridor-a",
        predictedViolations=0,
        forecastPriority=0,
        obstructionRisk=0,
    )
    b = PatrolCandidate(
        grid_cell_id="corridor-b",
        latitude=end[0],
        longitude=end[1],
        location="corridor-b",
        predictedViolations=0,
        forecastPriority=0,
        obstructionRisk=0,
    )
    distance = haversine_km(a, b)
    return {"distance_km": round(distance, 3), "eta_minutes": round(distance / 18 * 60, 2)}


def _delay_item(
    candidate: PatrolCandidate,
    traffic: dict[str, float] | None,
    freeflow: dict[str, float],
    scenario_reduction: float,
    source: str,
) -> dict[str, Any]:
    road_distance = traffic["distance_km"] if traffic else freeflow["distance_km"]
    freeflow_eta = freeflow["eta_minutes"]
    if traffic:
        traffic_eta = traffic["eta_minutes"]
        raw_delay = max(0.0, traffic_eta - freeflow_eta)
    else:
        traffic_eta = None
        raw_delay = 0.0

    pressure_weight = min(1.6, 0.55 + candidate.forecast_priority / 100)
    severity_weight = min(1.5, 0.7 + candidate.obstruction_risk / 180)
    road_weight = _road_importance_weight(candidate)
    peak_weight = 1.15 if candidate.peak_window and "unknown" not in candidate.peak_window.lower() else 1.0
    obstruction_prior = max(0.15, road_distance * 1.2) * (candidate.obstruction_risk / 100)
    delay_base = raw_delay + obstruction_prior
    exposure = (
        delay_base
        * max(candidate.predicted_violations, 1)
        * pressure_weight
        * severity_weight
        * road_weight
        * peak_weight
    )
    confidence = "High" if traffic and raw_delay > 0 else "Medium" if traffic else "Heuristic"

    return {
        "rank": 0,
        "grid_cell_id": candidate.grid_cell_id,
        "latitude": candidate.latitude,
        "longitude": candidate.longitude,
        "location": candidate.location,
        "station": candidate.station,
        "predicted_violations": round(candidate.predicted_violations, 1),
        "forecast_priority": round(candidate.forecast_priority, 1),
        "obstruction_risk": round(candidate.obstruction_risk, 1),
        "road_distance_km": round(road_distance, 3),
        "traffic_eta_minutes": round(traffic_eta, 1) if traffic_eta is not None else None,
        "freeflow_eta_minutes": round(freeflow_eta, 1),
        "traffic_delay_minutes": round(raw_delay, 1),
        "estimated_delay_exposure_minutes": round(exposure, 1),
        "reduced_delay_exposure_minutes": round(exposure * scenario_reduction, 1),
        "road_importance_weight": round(road_weight, 2),
        "parking_pressure_weight": round(pressure_weight, 2),
        "confidence": confidence,
        "source": source,
    }


def _road_importance_weight(candidate: PatrolCandidate) -> float:
    text = " ".join(
        value.lower()
        for value in [candidate.location, candidate.context or "", candidate.peak_window or ""]
    )
    if any(term in text for term in ["main road", "ring road", "highway", "flyover"]):
        return 1.35
    if any(term in text for term in ["junction", "cross", "metro", "bus", "market"]):
        return 1.2
    if "road" in text:
        return 1.1
    return 1.0


def _combined_delay_source(rows: list[dict[str, Any]]) -> str:
    sources = {row["source"] for row in rows}
    if len(sources) == 1:
        return next(iter(sources))
    if any("Mappls Traffic" in source for source in sources):
        return "Mixed Mappls/OSM/heuristic delay exposure"
    return "Heuristic delay exposure"


def _fetch_reverse_labels(
    client: httpx.Client,
    base_url: str,
    key: str,
    stops: list[PatrolCandidate],
) -> dict[str, str]:
    labels: dict[str, str] = {}
    for stop in stops:
        try:
            payload = _get_json(
                client,
                f"{base_url}/{key}/rev_geocode",
                {"lat": stop.latitude, "lng": stop.longitude, "region": "IND"},
            )
            label = _extract_label(payload)
            if label:
                labels[stop.grid_cell_id] = label
        except Exception:
            continue
    return labels


def _fetch_nearby_context(
    client: httpx.Client,
    base_url: str,
    key: str,
    stop: PatrolCandidate,
) -> dict[str, list[str]]:
    found: list[str] = []
    for keyword in CONTEXT_KEYWORDS[:4]:
        try:
            payload = _get_json(
                client,
                f"{base_url}/{key}/nearby_search",
                {
                    "keywords": keyword,
                    "refLocation": f"{stop.latitude},{stop.longitude}",
                    "radius": 500,
                    "region": "IND",
                },
            )
            label = _extract_label(payload)
            if label:
                found.append(f"{keyword}: {label}")
        except Exception:
            continue
    return {stop.grid_cell_id: found[:4]}


def _get_json(client: httpx.Client, url: str, params: dict[str, Any]) -> dict[str, Any]:
    response = client.get(url, params=params)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {"items": payload}


def _fallback_plan(candidates: list[PatrolCandidate], reason: str) -> dict[str, Any]:
    matrix = _haversine_matrix(candidates)
    route_indexes = _build_route(candidates, matrix)
    ordered = [candidates[index] for index in route_indexes]
    segments = _segments_from_matrix(
        ordered,
        route_indexes,
        {"costs": matrix, "distances": matrix, "durations": []},
        source="Haversine fallback",
    )
    return _response(
        route_mode="haversine_fallback",
        routing_source="Haversine fallback",
        stops=ordered,
        segments=segments,
        geometry=[(item.latitude, item.longitude) for item in ordered],
        fallback_reason=reason,
    )


def _response(
    *,
    route_mode: str,
    routing_source: str,
    stops: list[PatrolCandidate],
    segments: list[dict[str, Any]],
    geometry: list[tuple[float, float]],
    labels: dict[str, str] | None = None,
    nearby_by_cell: dict[str, list[str]] | None = None,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    labels = labels or {}
    nearby_by_cell = nearby_by_cell or {}
    total_distance = round(sum(segment["distance_km"] for segment in segments), 3)
    eta_values = [segment["eta_minutes"] for segment in segments if segment.get("eta_minutes") is not None]
    return {
        "route_mode": route_mode,
        "routing_source": routing_source,
        "total_distance_km": total_distance,
        "total_eta_minutes": round(sum(eta_values), 1) if eta_values else None,
        "fallback_reason": fallback_reason,
        "cached": False,
        "stops": [
            {
                "stop": index + 1,
                "grid_cell_id": stop.grid_cell_id,
                "latitude": stop.latitude,
                "longitude": stop.longitude,
                "location": labels.get(stop.grid_cell_id) or stop.location,
                "context": stop.context,
                "station": stop.station,
                "predicted_violations": stop.predicted_violations,
                "forecast_priority": stop.forecast_priority,
                "obstruction_risk": stop.obstruction_risk,
                "peak_window": stop.peak_window,
                "mappls_label": labels.get(stop.grid_cell_id),
                "nearby_context": nearby_by_cell.get(stop.grid_cell_id, []),
            }
            for index, stop in enumerate(stops)
        ],
        "segments": segments,
        "route_geometry": geometry,
    }


def _segments_from_matrix(
    ordered: list[PatrolCandidate],
    route_indexes: list[int],
    matrix: dict[str, Any],
    source: str | None = None,
) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for index in range(1, len(ordered)):
        src = route_indexes[index - 1]
        dst = route_indexes[index]
        distance = _matrix_value(matrix.get("distances"), src, dst)
        duration = _matrix_value(matrix.get("durations"), src, dst)
        cost = _matrix_value(matrix.get("costs"), src, dst)
        distance_km = _distance_to_km(distance) if distance is not None else float(cost or 0)
        eta_minutes = duration / 60.0 if duration is not None else None
        segments.append(
            {
                "from_cell_id": ordered[index - 1].grid_cell_id,
                "to_cell_id": ordered[index].grid_cell_id,
                "distance_km": round(distance_km, 3),
                "eta_minutes": round(eta_minutes, 1) if eta_minutes is not None else None,
                "source": source or "Mappls",
            }
        )
    return segments


def _build_route(candidates: list[PatrolCandidate], costs: list[list[float | None]]) -> list[int]:
    if len(candidates) <= 1:
        return list(range(len(candidates)))
    start = 0
    goal_mask = (1 << len(candidates)) - 1
    open_set = [{"current": start, "mask": 1 << start, "g": 0.0, "f": 0.0}]
    best = {(start, 1 << start): 0.0}
    came_from: dict[tuple[int, int], tuple[int, int]] = {}

    while open_set:
        open_set.sort(key=lambda item: item["f"])
        node = open_set.pop(0)
        state = (int(node["current"]), int(node["mask"]))
        if state[1] == goal_mask:
            return _reconstruct_indexes(came_from, state)

        for nxt in range(len(candidates)):
            bit = 1 << nxt
            if state[1] & bit:
                continue
            edge_cost = costs[state[0]][nxt]
            if edge_cost is None:
                edge_cost = haversine_km(candidates[state[0]], candidates[nxt])
            next_state = (nxt, state[1] | bit)
            tentative = float(node["g"]) + float(edge_cost)
            if tentative >= best.get(next_state, math.inf):
                continue
            came_from[next_state] = state
            best[next_state] = tentative
            open_set.append(
                {
                    "current": nxt,
                    "mask": next_state[1],
                    "g": tentative,
                    "f": tentative + _heuristic(candidates, costs, nxt, next_state[1]),
                }
            )
    return list(range(len(candidates)))


def _heuristic(
    candidates: list[PatrolCandidate],
    costs: list[list[float | None]],
    current: int,
    mask: int,
) -> float:
    nearest = math.inf
    for index in range(len(candidates)):
        if mask & (1 << index):
            continue
        cost = costs[current][index]
        nearest = min(nearest, float(cost) if cost is not None else haversine_km(candidates[current], candidates[index]))
    return nearest if math.isfinite(nearest) else 0.0


def _reconstruct_indexes(
    came_from: dict[tuple[int, int], tuple[int, int]],
    end_state: tuple[int, int],
) -> list[int]:
    path = [end_state]
    cursor = end_state
    while cursor in came_from:
        cursor = came_from[cursor]
        path.append(cursor)
    return [state[0] for state in reversed(path)]


def _haversine_matrix(candidates: list[PatrolCandidate]) -> list[list[float]]:
    return [[0.0 if i == j else haversine_km(a, b) for j, b in enumerate(candidates)] for i, a in enumerate(candidates)]


def haversine_km(a: PatrolCandidate, b: PatrolCandidate) -> float:
    lat1 = math.radians(a.latitude)
    lat2 = math.radians(b.latitude)
    delta_lat = math.radians(b.latitude - a.latitude)
    delta_lon = math.radians(b.longitude - a.longitude)
    sin_lat = math.sin(delta_lat / 2)
    sin_lon = math.sin(delta_lon / 2)
    h = sin_lat * sin_lat + math.cos(lat1) * math.cos(lat2) * sin_lon * sin_lon
    return 2 * EARTH_RADIUS_KM * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def _extract_square_matrix(payload: Any, keys: list[str]) -> list[list[float | None]] | None:
    for key in keys:
        found = _find_key(payload, key)
        if isinstance(found, list) and found and all(isinstance(row, list) for row in found):
            return [[_to_float(value) for value in row] for row in found]
    rows = _find_key(payload, "results") or _find_key(payload, "rows")
    if isinstance(rows, list):
        matrix: list[list[float | None]] = []
        for row in rows:
            elements = row.get("elements") if isinstance(row, dict) else None
            if not isinstance(elements, list):
                continue
            matrix.append([_element_cost(element, keys) for element in elements])
        if matrix:
            return matrix
    return None


def _extract_geometry(payload: Any) -> list[tuple[float, float]]:
    geometry = _find_key(payload, "geometry")
    if isinstance(geometry, dict):
        coords = geometry.get("coordinates")
        if isinstance(coords, list):
            return _coords_to_latlon(coords)
    if isinstance(geometry, list):
        return _coords_to_latlon(geometry)
    coords = _find_key(payload, "coordinates")
    if isinstance(coords, list):
        return _coords_to_latlon(coords)
    return []


def _coords_to_latlon(coords: list[Any]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for item in coords:
        if isinstance(item, list) and len(item) >= 2 and all(isinstance(value, (int, float)) for value in item[:2]):
            lon, lat = float(item[0]), float(item[1])
            points.append((lat, lon))
        elif isinstance(item, list):
            points.extend(_coords_to_latlon(item))
    return points


def _extract_label(payload: Any) -> str | None:
    for key in ["formatted_address", "formattedAddress", "placeName", "place_name", "address", "label", "name"]:
        found = _find_key(payload, key)
        if isinstance(found, str) and found.strip():
            return found.strip()
    return None


def _find_key(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        for candidate, nested in value.items():
            if candidate == key:
                return nested
        for nested in value.values():
            found = _find_key(nested, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_key(nested, key)
            if found is not None:
                return found
    return None


def _element_cost(element: Any, keys: list[str]) -> float | None:
    if not isinstance(element, dict):
        return _to_float(element)
    for key in keys:
        value = element.get(key)
        if isinstance(value, dict):
            value = value.get("value")
        number = _to_float(value)
        if number is not None:
            return number
    return None


def _matrix_value(matrix: Any, row: int, col: int) -> float | None:
    if not isinstance(matrix, list) or row >= len(matrix):
        return None
    row_value = matrix[row]
    if not isinstance(row_value, list) or col >= len(row_value):
        return None
    return _to_float(row_value[col])


def _distance_to_km(value: float) -> float:
    # Mappls route/matrix distances are usually meters; haversine fallback costs
    # are already kilometers. Bengaluru patrol segments should stay well below
    # 50 km, so larger raw values are treated as meters.
    return value / 1000.0 if value > 50 else value


def _to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _cache_key(candidates: list[PatrolCandidate]) -> str:
    payload = [
        {
            "id": item.grid_cell_id,
            "lat": round(item.latitude, 5),
            "lon": round(item.longitude, 5),
            "priority": round(item.forecast_priority, 2),
        }
        for item in candidates
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _read_cache() -> dict[str, Any]:
    return _read_json_cache(CACHE_FILE)


def _read_json_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_cache_entry(key: str, response: dict[str, Any]) -> None:
    _write_json_cache_entry(CACHE_FILE, key, response)


def _write_json_cache_entry(path: Path, key: str, response: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = _read_json_cache(path)
    cache[key] = response
    path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
