export type Confidence = "High" | "Medium" | "Low" | "Model";

export type Summary = {
  hotspot_count: number;
  edge_count: number;
  station_count: number;
  total_violations: number;
  score_name: string;
  score_note: string;
  metadata: {
    rows_read?: number;
    timezone?: string;
    generated_at?: string;
  };
};

export type Hotspot = {
  grid_cell_id: string;
  latitude: number;
  longitude: number;
  violation_count: number;
  active_days: number;
  active_weeks: number;
  active_months?: number;
  device_days: number;
  mean_severity: number;
  junction_share: number;
  approved_count: number;
  validated_count: number;
  dominant_station: string | null;
  dominant_junction: string | null;
  representative_location: string | null;
  peak_hour: number | null;
  peak_weekday: string | null;
  peak_month: string | null;
  dominant_violation_type: string | null;
  neighbor_influence: number;
  obstruction_risk_score: number;
  enforcement_priority_score: number;
  station_normalized_volume: number;
  temporal_concentration: number;
  recent_activity_score: number;
  recent_trend_ratio: number;
  stability_score: number;
  priority_band: "Deploy first" | "Schedule patrol" | "Monitor";
  risk_score_type: string;
  model_version?: string;
  confidence: Confidence;
  reason_codes: string[];
};

export type StationSummary = {
  station: string;
  hotspot_count: number;
  violation_count: number;
  mean_obstruction_risk_score: number;
};

export type TemporalHour = {
  hour: number;
  violation_count: number;
};

export type TemporalWeekday = {
  weekday: string;
  violation_count: number;
};

export type HeatmapPoint = {
  weekday: string;
  hour: number;
  violation_count: number;
};

export type TimeseriesPoint = {
  date: string;
  violation_count: number;
};

export type WeeklyTimeseriesPoint = {
  week: string;
  violation_count: number;
};

export type GraphEdge = {
  source: string;
  target: string;
  distance_meters: number;
  weight: number;
};

export type GraphResponse = {
  cell_id: string;
  node: Hotspot;
  neighbors: Hotspot[];
  edges: GraphEdge[];
};

export type ForecastItem = {
  grid_cell_id: string;
  station: string | null;
  junction: string | null;
  location: string | null;
  latitude: number;
  longitude: number;
  predicted_week: string | null;
  predicted_violation_count: number;
  prediction_interval_low: number;
  prediction_interval_high: number;
  predicted_obstruction_risk: number;
  predicted_enforcement_priority?: number | null;
  forecast_stability: number;
  confidence?: Confidence | null;
  neighbor_influence?: number | null;
  last_1_week_count: number;
  last_2_week_avg: number;
  last_4_week_avg: number;
  historical_weeks: { week: string; violation_count: number }[];
  forecast_reason_codes: string[];
  reason_codes: string[];
};

export type ForecastResponse = {
  forecast_type: string;
  model?: string | null;
  forecast_source?: string | null;
  not_measured_congestion: boolean;
  method: string;
  forecast_week: string | null;
  holdout: {
    weeks: string[];
    mae: number | null;
    mape: number | null;
    evaluated_points: number;
    validation_type?: string;
  };
  items: ForecastItem[];
};

export type ModelEvidence = {
  available: boolean;
  comparison: unknown | null;
  active_model: string | null;
  forecast_source: string | null;
  forecast_week: string | null;
  holdout: ForecastResponse["holdout"];
  note: string;
};

export type CopilotFilters = {
  station?: string | null;
  confidence?: string | null;
  violation_type?: string | null;
  weekday?: string | null;
  hour?: number | null;
};

export type CopilotRequest = {
  question: string;
  mode: string;
  active_tab: string;
  selected_cell_id: string | null;
  filters: CopilotFilters;
};

export type CopilotResponse = {
  answer: string;
  provider: "hf" | "local_fallback" | string;
  model: string | null;
  cached: boolean;
  evidence: { label: string; value: string }[];
  warnings: string[];
};

export type PatrolPlanStop = {
  stop: number;
  grid_cell_id: string;
  latitude: number;
  longitude: number;
  location: string;
  context: string | null;
  station: string | null;
  predicted_violations: number;
  forecast_priority: number;
  obstruction_risk: number;
  peak_window: string | null;
  mappls_label: string | null;
  nearby_context: string[];
};

export type PatrolPlanSegment = {
  from_cell_id: string;
  to_cell_id: string;
  distance_km: number;
  eta_minutes: number | null;
  source: string;
};

export type PatrolPlanResponse = {
  route_mode: "mappls_traffic_eta" | "mappls_road_distance" | "haversine_fallback" | string;
  routing_source: string;
  total_distance_km: number;
  total_eta_minutes: number | null;
  fallback_reason: string | null;
  cached: boolean;
  stops: PatrolPlanStop[];
  segments: PatrolPlanSegment[];
  route_geometry: [number, number][];
};

export type DelayExposureItem = {
  rank: number;
  grid_cell_id: string;
  latitude: number;
  longitude: number;
  location: string;
  station: string | null;
  predicted_violations: number;
  forecast_priority: number;
  obstruction_risk: number;
  road_distance_km: number;
  traffic_eta_minutes: number | null;
  freeflow_eta_minutes: number | null;
  traffic_delay_minutes: number;
  estimated_delay_exposure_minutes: number;
  reduced_delay_exposure_minutes: number;
  road_importance_weight: number;
  parking_pressure_weight: number;
  confidence: string;
  source: string;
};

export type DelayExposureResponse = {
  source: string;
  cached: boolean;
  fallback_reason: string | null;
  total_delay_exposure_minutes: number;
  total_reduced_delay_exposure_minutes: number;
  items: DelayExposureItem[];
};
