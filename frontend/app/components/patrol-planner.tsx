"use client";

import { useEffect, useMemo, useRef, useState } from "react";
// @ts-ignore
import { mappls, mappls_plugin } from "mappls-web-maps";
import type { ForecastItem, ForecastResponse, Hotspot, PatrolPlanResponse } from "../lib/types";
import { forecastHotspotContext, forecastHotspotName, hotspotContext, hotspotName } from "../lib/hotspot-labels";

type PatrolPlannerProps = {
  hotspots: Hotspot[];
  forecast: ForecastResponse;
};

type PatrolCandidate = {
  grid_cell_id: string;
  latitude: number;
  longitude: number;
  location: string;
  context: string;
  station: string;
  predictedViolations: number;
  forecastPriority: number;
  obstructionRisk: number;
  peakWindow: string;
  source: "forecast" | "hotspot";
};

const BENGALURU_CENTER = [12.9716, 77.5946];
const DEFAULT_STOP_COUNT = 8;
const MAX_STOP_COUNT = 10;
const EARTH_RADIUS_KM = 6371;

export function PatrolPlanner({ hotspots, forecast }: PatrolPlannerProps) {
  const [stopCount, setStopCount] = useState(DEFAULT_STOP_COUNT);
  const [roadPlan, setRoadPlan] = useState<PatrolPlanResponse | null>(null);
  const [plannerStatus, setPlannerStatus] = useState<"loading" | "ready" | "fallback">("loading");
  const containerRef = useRef<HTMLDivElement>(null);
  const mapObjectRef = useRef<any>(null);
  const mapplsRef = useRef<any>(null);
  const markersRef = useRef<any[]>([]);
  const polylineRef = useRef<any>(null);
  const [mapLoaded, setMapLoaded] = useState(false);

  const candidates = useMemo(
    () => buildCandidates(hotspots, forecast).slice(0, stopCount),
    [forecast, hotspots, stopCount]
  );

  const fallbackRoute = useMemo(() => buildAStarRoute(candidates), [candidates]);
  const planStops = roadPlan?.stops ?? [];
  const displayStops = planStops.length > 0 ? planStops : fallbackRoute.map(localStop);
  const totalDistanceKm = roadPlan?.total_distance_km ?? routeDistanceKm(fallbackRoute);
  const totalEtaMinutes = roadPlan?.total_eta_minutes ?? null;
  const routeGeometry =
    roadPlan?.route_geometry && roadPlan.route_geometry.length > 1
      ? roadPlan.route_geometry
      : fallbackRoute.map((item) => [item.latitude, item.longitude] as [number, number]);
  const coveredPredictedViolations = displayStops.reduce(
    (sum, item) => sum + item.predicted_violations,
    0
  );
  const coveredPriority = displayStops.reduce((sum, item) => sum + item.forecast_priority, 0);
  const averageExposure =
    displayStops.length > 0
      ? displayStops.reduce((sum, item) => sum + item.obstruction_risk, 0) / displayStops.length
      : 0;
  const routingSource = roadPlan?.routing_source ?? "Haversine fallback";
  const isFallback = !roadPlan || roadPlan.route_mode === "haversine_fallback";

  useEffect(() => {
    if (candidates.length === 0) {
      setRoadPlan(null);
      setPlannerStatus("fallback");
      return;
    }

    const controller = new AbortController();
    setPlannerStatus("loading");

    fetch("/api/backend/mappls/patrol-plan", {
      method: "POST",
      headers: {
        accept: "application/json",
        "content-type": "application/json"
      },
      body: JSON.stringify({ candidates }),
      cache: "no-store",
      signal: controller.signal
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Patrol plan request failed (${response.status})`);
        }
        return response.json() as Promise<PatrolPlanResponse>;
      })
      .then((plan) => {
        setRoadPlan(plan);
        setPlannerStatus(plan.route_mode === "haversine_fallback" ? "fallback" : "ready");
      })
      .catch((error) => {
        if (error.name === "AbortError") return;
        setRoadPlan(null);
        setPlannerStatus("fallback");
      });

    return () => controller.abort();
  }, [candidates]);

  useEffect(() => {
    if (typeof window === "undefined" || !containerRef.current) return;
    if (mapplsRef.current) return; // already initialized

    const token = process.env.NEXT_PUBLIC_MAPPLS_TOKEN || "";
    mapplsRef.current = new mappls();

    mapplsRef.current.initialize(token, { map: true }, () => {
      if (!mapObjectRef.current) {
        mapObjectRef.current = mapplsRef.current.Map({
          id: "patrol-planner-map",
          center: BENGALURU_CENTER,
          zoom: 12,
          traffic: true,
        });

        setTimeout(() => setMapLoaded(true), 500);
      }
    });

    return () => {
      if (markersRef.current.length > 0) {
        markersRef.current.forEach(marker => {
          try {
            mapplsRef.current.removeLayer({ map: mapObjectRef.current, layer: marker });
          } catch(e) {}
        });
        markersRef.current = [];
      }
      if (polylineRef.current) {
        try {
          mapplsRef.current.removeLayer({ map: mapObjectRef.current, layer: polylineRef.current });
        } catch(e) {}
        polylineRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!mapLoaded || !mapObjectRef.current || !mapplsRef.current) return;

    // Clear old route
    markersRef.current.forEach(marker => {
      try {
        mapplsRef.current.removeLayer({ map: mapObjectRef.current, layer: marker });
      } catch(e) {}
    });
    markersRef.current = [];

    if (polylineRef.current) {
      try {
        mapplsRef.current.removeLayer({ map: mapObjectRef.current, layer: polylineRef.current });
      } catch(e) {}
      polylineRef.current = null;
    }

    if (!displayStops.length) return;

    const points = routeGeometry.map((pt: any) => {
      if (Array.isArray(pt)) return { lat: pt[0], lng: pt[1] };
      if (pt.lat && pt.lng) return pt;
      if (pt.latitude && pt.longitude) return { lat: pt.latitude, lng: pt.longitude };
      return pt;
    });

    polylineRef.current = new mapplsRef.current.Polyline({
      map: mapObjectRef.current,
      paths: points,
      strokeColor: isFallback ? "#f59e0b" : "#2dd4bf",
      strokeOpacity: 0.9,
      strokeWeight: 4,
      fitbounds: true,
    });

    displayStops.forEach((item, index) => {
      const marker = new mapplsRef.current.Marker({
        map: mapObjectRef.current,
        position: { lat: item.latitude, lng: item.longitude },
        html: `<div class="patrol-stop-icon" style="background: #1e293b; color: white; width: 34px; height: 34px; display: flex; align-items: center; justify-content: center; border-radius: 50%; border: 2px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.3); font-weight: bold;"><span>${index + 1}</span></div>`,
        popupHtml: `
          <div class="popup-content">
            <strong>Stop ${index + 1}: ${escapeHtml(item.location)}</strong>
            <p>${escapeHtml(item.station ?? "Unknown")}</p>
            <p>Predicted violations: ${item.predicted_violations.toFixed(1)}</p>
            <p>Forecast priority: ${item.forecast_priority.toFixed(1)}</p>
            <p>${escapeHtml(routingSource)}</p>
          </div>
        `
      });
      markersRef.current.push(marker);
    });
  }, [displayStops, isFallback, routeGeometry, routingSource, mapLoaded]);

  const exportCsv = () => {
    const header = [
      "stop",
      "location",
      "station",
      "cell_id",
      "latitude",
      "longitude",
      "predicted_violations",
      "forecast_priority",
      "obstruction_risk",
      "peak_window",
      "road_distance_km",
      "eta_minutes",
      "routing_source",
      "mappls_label",
      "nearby_context"
    ];
    const rows = displayStops.map((item, index) => {
      const segment = index === 0 ? null : roadPlan?.segments[index - 1] ?? null;
      return [
      index + 1,
      item.location,
      item.station ?? "Unknown",
      item.grid_cell_id,
      item.latitude,
      item.longitude,
      item.predicted_violations.toFixed(1),
      item.forecast_priority.toFixed(1),
      item.obstruction_risk.toFixed(1),
      item.peak_window ?? "",
      segment?.distance_km.toFixed(3) ?? "",
      segment?.eta_minutes?.toFixed(1) ?? "",
      routingSource,
      item.mappls_label ?? "",
      item.nearby_context.join("; ")
      ];
    });
    const csv = [header, ...rows]
      .map((row) =>
        row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(",")
      )
      .join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "parkwatch-a-star-patrol-plan.csv";
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section className="patrol-layout">
      <div className="panel patrol-intro">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Road-aware A* patrol sequence</p>
            <h2>Forecast-aware enforcement planner</h2>
          </div>
          <div className="table-actions">
            <label className="planner-control">
              <span>Stops</span>
              <select
                value={stopCount}
                onChange={(event) => setStopCount(Number(event.target.value))}
              >
                {Array.from({ length: MAX_STOP_COUNT - 2 }, (_, index) => index + 3).map(
                  (count) => (
                    <option key={count} value={count}>
                      Top {count}
                    </option>
                  )
                )}
              </select>
            </label>
            <button className="export-button" type="button" onClick={exportCsv}>
              Export patrol CSV
            </button>
          </div>
        </div>
        <p>
          ParkWatch turns GraphSAGE forecast-priority zones into a targeted enforcement
          plan. A* sequences selected hotspots with Mappls road ETA or road distance when
          available, then falls back to haversine coordinate distance if needed.
        </p>
        <div className="forecast-metrics secondary">
          <span>
            <strong>{displayStops.length}</strong>
            Patrol stops
          </span>
          <span>
            <strong>{totalEtaMinutes === null ? "n/a" : `${totalEtaMinutes.toFixed(0)} min`}</strong>
            Road-aware ETA
          </span>
          <span>
            <strong>{totalDistanceKm.toFixed(1)} km</strong>
            {isFallback ? "Straight-line fallback" : "Road distance"}
          </span>
          <span>
            <strong>{coveredPredictedViolations.toFixed(1)}</strong>
            Covered predicted violations
          </span>
          <span>
            <strong>{averageExposure.toFixed(1)}</strong>
            Avg obstruction exposure
          </span>
        </div>
        <div className="planner-source-row">
          <span className="pill">{routingSource}</span>
          {plannerStatus === "loading" && <span className="pill">Planning route...</span>}
          {roadPlan?.cached && <span className="pill">Cached</span>}
          {roadPlan?.fallback_reason && <span className="pill">{roadPlan.fallback_reason}</span>}
        </div>
      </div>

      <div className="panel patrol-map-panel">
        <div id="patrol-planner-map" className="patrol-map" />
      </div>

      <div className="panel patrol-table-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Action list</p>
            <h2>A* patrol order</h2>
          </div>
          <span className="pill">{forecast.model ?? "Forecast"} source</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Stop</th>
                <th>Zone</th>
                <th>Station</th>
                <th>Predicted</th>
                <th>Priority</th>
                <th>Risk</th>
                <th>Peak window</th>
              </tr>
            </thead>
            <tbody>
              {displayStops.map((item, index) => (
                <tr key={item.grid_cell_id}>
                  <td>
                    <span className="patrol-stop-badge">{index + 1}</span>
                  </td>
                  <td>
                    <strong className="location-name">{item.location}</strong>
                    <span className="cell-meta">{item.context}</span>
                    {item.nearby_context.length > 0 && (
                      <span className="cell-meta">{item.nearby_context.join(" | ")}</span>
                    )}
                  </td>
                  <td>{item.station ?? "Unknown"}</td>
                  <td>{item.predicted_violations.toFixed(1)}</td>
                  <td>{item.forecast_priority.toFixed(1)}</td>
                  <td>{item.obstruction_risk.toFixed(1)}</td>
                  <td>{item.peak_window ?? "Unknown"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted">
          {isFallback
            ? "Fallback route uses coordinate distance because Mappls road intelligence is unavailable."
            : "Road-aware patrol routing uses Mappls ETA or distance. Congestion impact claims still require traffic-flow validation."}
        </p>
      </div>
    </section>
  );
}

function buildCandidates(hotspots: Hotspot[], forecast: ForecastResponse): PatrolCandidate[] {
  const hotspotsById = new Map(hotspots.map((hotspot) => [hotspot.grid_cell_id, hotspot]));
  const forecastCandidates = forecast.items
    .map((item) => {
      const hotspot = hotspotsById.get(item.grid_cell_id);
      if (!hotspot) return null;
      return forecastCandidate(item, hotspot);
    })
    .filter((item): item is PatrolCandidate => Boolean(item));

  if (forecastCandidates.length > 0) {
    return forecastCandidates.sort(candidateSort);
  }

  return hotspots
    .map((hotspot) => hotspotCandidate(hotspot))
    .sort(candidateSort);
}

function forecastCandidate(item: ForecastItem, hotspot: Hotspot): PatrolCandidate {
  return {
    grid_cell_id: item.grid_cell_id,
    latitude: item.latitude,
    longitude: item.longitude,
    location: forecastHotspotName(item),
    context: forecastHotspotContext(item),
    station: item.station ?? hotspot.dominant_station ?? "Unknown",
    predictedViolations: item.predicted_violation_count,
    forecastPriority: item.predicted_enforcement_priority ?? item.predicted_obstruction_risk,
    obstructionRisk: item.predicted_obstruction_risk,
    peakWindow: formatPeakWindow(hotspot),
    source: "forecast"
  };
}

function hotspotCandidate(hotspot: Hotspot): PatrolCandidate {
  return {
    grid_cell_id: hotspot.grid_cell_id,
    latitude: hotspot.latitude,
    longitude: hotspot.longitude,
    location: hotspotName(hotspot),
    context: hotspotContext(hotspot),
    station: hotspot.dominant_station ?? "Unknown",
    predictedViolations: hotspot.violation_count,
    forecastPriority: hotspot.enforcement_priority_score,
    obstructionRisk: hotspot.obstruction_risk_score,
    peakWindow: formatPeakWindow(hotspot),
    source: "hotspot"
  };
}

function localStop(item: PatrolCandidate, index: number) {
  return {
    stop: index + 1,
    grid_cell_id: item.grid_cell_id,
    latitude: item.latitude,
    longitude: item.longitude,
    location: item.location,
    context: item.context,
    station: item.station,
    predicted_violations: item.predictedViolations,
    forecast_priority: item.forecastPriority,
    obstruction_risk: item.obstructionRisk,
    peak_window: item.peakWindow,
    mappls_label: null,
    nearby_context: []
  };
}

function candidateSort(a: PatrolCandidate, b: PatrolCandidate) {
  return (
    b.forecastPriority - a.forecastPriority ||
    b.predictedViolations - a.predictedViolations ||
    b.obstructionRisk - a.obstructionRisk
  );
}

function buildAStarRoute(candidates: PatrolCandidate[]) {
  if (candidates.length <= 1) return candidates;

  const startIndex = 0;
  const goalMask = (1 << candidates.length) - 1;
  const startMask = 1 << startIndex;
  const startKey = stateKey(startIndex, startMask);
  const open = [
    {
      current: startIndex,
      mask: startMask,
      g: 0,
      f: heuristic(candidates, startIndex, startMask)
    }
  ];
  const best = new Map<string, number>([[startKey, 0]]);
  const cameFrom = new Map<string, string>();

  while (open.length > 0) {
    open.sort((a, b) => a.f - b.f);
    const node = open.shift()!;
    const currentKey = stateKey(node.current, node.mask);

    if (node.mask === goalMask) {
      return reconstructRoute(candidates, cameFrom, currentKey);
    }

    for (let next = 0; next < candidates.length; next += 1) {
      const nextBit = 1 << next;
      if (node.mask & nextBit) continue;

      const nextMask = node.mask | nextBit;
      const tentativeG =
        node.g + haversineKm(candidates[node.current], candidates[next]);
      const nextKey = stateKey(next, nextMask);

      if (tentativeG >= (best.get(nextKey) ?? Number.POSITIVE_INFINITY)) continue;

      cameFrom.set(nextKey, currentKey);
      best.set(nextKey, tentativeG);
      open.push({
        current: next,
        mask: nextMask,
        g: tentativeG,
        f: tentativeG + heuristic(candidates, next, nextMask)
      });
    }
  }

  return candidates;
}

function reconstructRoute(
  candidates: PatrolCandidate[],
  cameFrom: Map<string, string>,
  endKey: string
) {
  const pathKeys = [endKey];
  let cursor = endKey;
  while (cameFrom.has(cursor)) {
    cursor = cameFrom.get(cursor)!;
    pathKeys.push(cursor);
  }

  return pathKeys
    .reverse()
    .map((key) => candidates[Number(key.split(":")[0])])
    .filter((item): item is PatrolCandidate => Boolean(item));
}

function heuristic(candidates: PatrolCandidate[], current: number, mask: number) {
  let nearest = Number.POSITIVE_INFINITY;
  for (let index = 0; index < candidates.length; index += 1) {
    if (mask & (1 << index)) continue;
    nearest = Math.min(nearest, haversineKm(candidates[current], candidates[index]));
  }
  return Number.isFinite(nearest) ? nearest : 0;
}

function stateKey(current: number, mask: number) {
  return `${current}:${mask}`;
}

function routeDistanceKm(route: PatrolCandidate[]) {
  let total = 0;
  for (let index = 1; index < route.length; index += 1) {
    total += haversineKm(route[index - 1], route[index]);
  }
  return total;
}

function haversineKm(
  a: Pick<PatrolCandidate, "latitude" | "longitude">,
  b: Pick<PatrolCandidate, "latitude" | "longitude">
) {
  const lat1 = toRadians(a.latitude);
  const lat2 = toRadians(b.latitude);
  const deltaLat = toRadians(b.latitude - a.latitude);
  const deltaLon = toRadians(b.longitude - a.longitude);
  const sinLat = Math.sin(deltaLat / 2);
  const sinLon = Math.sin(deltaLon / 2);
  const h =
    sinLat * sinLat + Math.cos(lat1) * Math.cos(lat2) * sinLon * sinLon;
  return 2 * EARTH_RADIUS_KM * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}

function toRadians(value: number) {
  return (value * Math.PI) / 180;
}

function formatPeakWindow(hotspot: Hotspot) {
  const weekday = hotspot.peak_weekday ?? "Unknown";
  const hour =
    hotspot.peak_hour === null || hotspot.peak_hour === undefined
      ? "unknown hour"
      : `${hotspot.peak_hour.toString().padStart(2, "0")}:00`;
  return `${weekday}, ${hour}`;
}

function escapeHtml(value: string) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
