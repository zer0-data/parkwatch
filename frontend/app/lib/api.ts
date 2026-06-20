import type {
  CopilotRequest,
  CopilotResponse,
  GraphResponse,
  ForecastResponse,
  HeatmapPoint,
  Hotspot,
  StationSummary,
  Summary,
  TemporalHour,
  TemporalWeekday,
  TimeseriesPoint
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { accept: "application/json" },
    cache: "no-store"
  });

  if (!response.ok) {
    throw new Error(`Backend request failed: ${path} (${response.status})`);
  }

  return response.json() as Promise<T>;
}

export async function getDashboardData() {
  const [summary, hotspots, stations, hourly, weekday, heatmap, forecast] = await Promise.all([
    getJson<Summary>("/api/summary"),
    getJson<Hotspot[]>("/api/hotspots?limit=10000"),
    getJson<StationSummary[]>("/api/stations"),
    getJson<TemporalHour[]>("/api/temporal/hourly"),
    getJson<TemporalWeekday[]>("/api/temporal/weekday"),
    getJson<HeatmapPoint[]>("/api/temporal/heatmap"),
    getJson<ForecastResponse>("/api/forecast?limit=100")
  ]);

  return { summary, hotspots, stations, hourly, weekday, heatmap, forecast };
}

export async function getHotspotDetail(cellId: string) {
  const [timeseries, graph] = await Promise.all([
    getJson<TimeseriesPoint[]>(`/api/timeseries/${cellId}`),
    getJson<GraphResponse>(`/api/graph/${cellId}`)
  ]);

  return { timeseries, graph };
}

export async function askCopilot(payload: CopilotRequest) {
  const response = await fetch("/api/backend/copilot", {
    method: "POST",
    headers: {
      accept: "application/json",
      "content-type": "application/json"
    },
    body: JSON.stringify(payload),
    cache: "no-store"
  });

  if (!response.ok) {
    throw new Error(`Copilot request failed (${response.status})`);
  }

  return response.json() as Promise<CopilotResponse>;
}
