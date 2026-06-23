"use client";

import { useEffect, useState } from "react";
import { hotspotContext, hotspotName } from "../lib/hotspot-labels";
import type { GraphResponse, Hotspot, TimeseriesPoint, WeeklyTimeseriesPoint } from "../lib/types";

type DetailState =
  | { status: "idle"; timeseries: TimeseriesPoint[]; weekly: WeeklyTimeseriesPoint[]; graph: GraphResponse | null }
  | { status: "loading"; timeseries: TimeseriesPoint[]; weekly: WeeklyTimeseriesPoint[]; graph: GraphResponse | null }
  | { status: "ready"; timeseries: TimeseriesPoint[]; weekly: WeeklyTimeseriesPoint[]; graph: GraphResponse }
  | { status: "error"; timeseries: TimeseriesPoint[]; weekly: WeeklyTimeseriesPoint[]; graph: GraphResponse | null };

type HotspotDetailPanelProps = {
  hotspot: Hotspot | null;
  scoreBenchmarks: {
    maxViolationCount: number;
    maxActiveDays: number;
    maxDeviceDays: number;
    maxNeighborInfluence: number;
  };
  onSelect?: (cellId: string) => void;
};

export function HotspotDetailPanel({ hotspot, scoreBenchmarks, onSelect }: HotspotDetailPanelProps) {
  const [detail, setDetail] = useState<DetailState>({
    status: "idle",
    timeseries: [],
    weekly: [],
    graph: null
  });
  const [showScoreBreakdown, setShowScoreBreakdown] = useState(false);

  useEffect(() => {
    if (!hotspot) {
      return;
    }

    let active = true;
    setDetail((current) => ({ ...current, status: "loading" }));

    Promise.all([
      fetch(`/api/backend/timeseries/${hotspot.grid_cell_id}`).then((response) => {
        if (!response.ok) throw new Error("Timeseries request failed");
        return response.json() as Promise<TimeseriesPoint[]>;
      }),
      fetch(`/api/backend/timeseries/${hotspot.grid_cell_id}/weekly`).then((response) => {
        if (!response.ok) throw new Error("Weekly timeseries request failed");
        return response.json() as Promise<WeeklyTimeseriesPoint[]>;
      }),
      fetch(`/api/backend/graph/${hotspot.grid_cell_id}`).then((response) => {
        if (!response.ok) throw new Error("Graph request failed");
        return response.json() as Promise<GraphResponse>;
      })
    ])
      .then(([timeseries, weekly, graph]) => {
        if (active) {
          setDetail({ status: "ready", timeseries, weekly, graph });
        }
      })
      .catch(() => {
        if (active) {
          setDetail((current) => ({ ...current, status: "error" }));
        }
      });

    return () => {
      active = false;
    };
  }, [hotspot]);

  if (!hotspot) {
    return (
      <aside className="panel detail-panel">
        <p className="eyebrow">Hotspot detail</p>
        <h2>Select a hotspot</h2>
      </aside>
    );
  }

  const maxSeries = Math.max(...detail.timeseries.map((item) => item.violation_count), 1);
  const trendPath = buildTrendPath(detail.timeseries.slice(-60));
  const weeklyPath = buildWeeklyPath(detail.weekly.slice(-16));
  const maxWeekly = Math.max(...detail.weekly.map((item) => item.violation_count), 1);
  const scoreBreakdown = buildScoreBreakdown(hotspot, scoreBenchmarks);

  return (
    <aside className="panel detail-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Hotspot detail</p>
          <h2>{hotspotName(hotspot)}</h2>
          <span className="cell-meta">{hotspotContext(hotspot)}</span>
        </div>
        <span className={`confidence ${hotspot.confidence.toLowerCase()}`}>
          {hotspot.confidence}
        </span>
      </div>

      <button
        className="score-ring"
        type="button"
        aria-expanded={showScoreBreakdown}
        aria-label="Show Obstruction Risk Score calculation"
        onClick={() => setShowScoreBreakdown((current) => !current)}
      >
        <strong>{hotspot.obstruction_risk_score.toFixed(1)}</strong>
        <span>Obstruction Risk Score</span>
      </button>

      {showScoreBreakdown && (
        <section className="score-breakdown" aria-label="Obstruction Risk Score calculation">
          <div className="score-breakdown-head">
            <strong>Score calculation</strong>
            <span>{scoreBreakdown.total.toFixed(1)} computed from CSV-only features</span>
          </div>
          {scoreBreakdown.components.map((component) => (
            <div className="score-component" key={component.label}>
              <span>{component.label}</span>
              <meter min="0" max={component.maxContribution} value={component.contribution} />
              <strong>{component.contribution.toFixed(1)}</strong>
            </div>
          ))}
          <p>
            Components are normalized against the loaded hotspot set. The result is an
            obstruction-risk proxy, not measured traffic delay.
          </p>
          <div className="score-breakdown-head">
            <strong>Enforcement priority model</strong>
            <span>{hotspot.enforcement_priority_score.toFixed(1)} action score · {hotspot.priority_band}</span>
          </div>
          <div className="priority-factors">
            <span>Station volume {(hotspot.station_normalized_volume * 100).toFixed(0)}%</span>
            <span>Recent activity {(hotspot.recent_activity_score * 100).toFixed(0)}%</span>
            <span>Peak concentration {(hotspot.temporal_concentration * 100).toFixed(0)}%</span>
            <span>Trend {hotspot.recent_trend_ratio.toFixed(2)}x</span>
            <span>Stability {hotspot.stability_score.toFixed(1)}</span>
          </div>
        </section>
      )}

      <dl className="detail-list">
        <div>
          <dt>Confidence</dt>
          <dd>{hotspot.confidence}</dd>
        </div>
        <div>
          <dt>Enforcement priority</dt>
          <dd>
            {hotspot.enforcement_priority_score.toFixed(1)} · {hotspot.priority_band}
          </dd>
        </div>
        <div>
          <dt>Station</dt>
          <dd>{hotspot.dominant_station ?? "Unknown"}</dd>
        </div>
        <div>
          <dt>Junction</dt>
          <dd>{hotspot.dominant_junction ?? "No dominant junction"}</dd>
        </div>
        <div>
          <dt>Location</dt>
          <dd>{hotspot.representative_location ?? "Location unavailable"}</dd>
        </div>
        <div>
          <dt>Violation count</dt>
          <dd>{hotspot.violation_count.toLocaleString("en-IN")}</dd>
        </div>
        <div>
          <dt>Active days / weeks</dt>
          <dd>
            {hotspot.active_days.toLocaleString("en-IN")} days /{" "}
            {hotspot.active_weeks.toLocaleString("en-IN")} weeks
          </dd>
        </div>
        <div>
          <dt>Peak hour</dt>
          <dd>
            {hotspot.peak_hour === null ? "unknown hour" : `${hotspot.peak_hour}:00`}
          </dd>
        </div>
        <div>
          <dt>Peak weekday</dt>
          <dd>{hotspot.peak_weekday ?? "Unknown"}</dd>
        </div>
        <div>
          <dt>Dominant violation</dt>
          <dd>{hotspot.dominant_violation_type ?? "Unknown"}</dd>
        </div>
      </dl>

      <section className="mini-section">
        <h3>Why this zone is risky</h3>
        <div className="reason-list">
          {hotspot.reason_codes.map((reason) => (
            <span key={reason}>{reason.replaceAll("_", " ")}</span>
          ))}
        </div>
      </section>

      <section className="mini-section">
        <h3>Trend chart</h3>
        <div className="chart-legend" aria-label="Trend chart legend">
          <span><i className="legend-swatch line" />Daily violations</span>
          <span><i className="legend-swatch area" />Recent 60-day range</span>
        </div>
        {detail.status === "loading" && <p className="muted">Loading detail...</p>}
        {detail.status === "error" && <p className="muted">Detail data unavailable.</p>}
        <svg className="trend-chart" viewBox="0 0 320 120" role="img" aria-label="Daily violation trend chart">
          <path className="trend-area" d={`${trendPath} L 320 116 L 0 116 Z`} />
          <path className="trend-line" d={trendPath} />
          {detail.timeseries.slice(-60).map((point, index, points) => {
            const x = points.length <= 1 ? 0 : (index / (points.length - 1)) * 320;
            const y = 112 - (point.violation_count / maxSeries) * 96;
            return (
              <circle key={point.date} cx={x} cy={y} r="2.4">
                <title>{`${point.date}: ${point.violation_count} violations`}</title>
              </circle>
            );
          })}
        </svg>
      </section>

      <section className="mini-section">
        <h3>Weekly pressure evidence</h3>
        <div className="chart-legend" aria-label="Weekly trend chart legend">
          <span><i className="legend-swatch predicted" />Weekly observed violations</span>
          <span><i className="legend-swatch area" />Last 16-week evidence</span>
        </div>
        <svg className="trend-chart" viewBox="0 0 320 120" role="img" aria-label="Weekly observed violation trend chart">
          <path className="trend-area" d={`${weeklyPath} L 320 116 L 0 116 Z`} />
          <path className="trend-line weekly" d={weeklyPath} />
          {detail.weekly.slice(-16).map((point, index, points) => {
            const x = points.length <= 1 ? 0 : (index / (points.length - 1)) * 320;
            const y = 112 - (point.violation_count / maxWeekly) * 96;
            return (
              <circle key={point.week} cx={x} cy={y} r="3">
                <title>{`${point.week}: ${point.violation_count} violations`}</title>
              </circle>
            );
          })}
        </svg>
        <p>
          Weekly recurrence supports the forecast-priority story; it is observed
          violation pressure, not measured congestion.
        </p>
      </section>

      <section className="mini-section">
        <h3>Graph neighborhood</h3>
        <NeighborhoodGraph graph={detail.graph} selectedCellId={hotspot.grid_cell_id} onSelect={onSelect} />
        <p>
          {detail.graph?.neighbors.length ?? 0} nearby grid cells within the precomputed
          graph. Neighbor influence is derived only from dataset coordinates.
        </p>
      </section>
    </aside>
  );
}

function buildTrendPath(points: TimeseriesPoint[]) {
  if (!points.length) {
    return "M 0 116";
  }

  const maxValue = Math.max(...points.map((point) => point.violation_count), 1);
  return points
    .map((point, index) => {
      const x = points.length <= 1 ? 0 : (index / (points.length - 1)) * 320;
      const y = 112 - (point.violation_count / maxValue) * 96;
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
}

function buildWeeklyPath(points: WeeklyTimeseriesPoint[]) {
  if (!points.length) {
    return "M 0 116";
  }

  const maxValue = Math.max(...points.map((point) => point.violation_count), 1);
  return points
    .map((point, index) => {
      const x = points.length <= 1 ? 0 : (index / (points.length - 1)) * 320;
      const y = 112 - (point.violation_count / maxValue) * 96;
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
}

function buildScoreBreakdown(
  hotspot: Hotspot,
  benchmarks: HotspotDetailPanelProps["scoreBenchmarks"]
) {
  const validationShare =
    hotspot.violation_count > 0 ? hotspot.validated_count / hotspot.violation_count : 0;
  const components = [
    {
      label: "Violation volume",
      maxContribution: 30,
      contribution: 30 * scale(hotspot.violation_count, benchmarks.maxViolationCount)
    },
    {
      label: "Active-day recurrence",
      maxContribution: 15,
      contribution: 15 * scale(hotspot.active_days, benchmarks.maxActiveDays)
    },
    {
      label: "Device-day support",
      maxContribution: 10,
      contribution: 10 * scale(hotspot.device_days, benchmarks.maxDeviceDays)
    },
    {
      label: "Mean severity",
      maxContribution: 20,
      contribution: 20 * Math.min(Math.max((hotspot.mean_severity - 1) / 2, 0), 1)
    },
    {
      label: "Junction share",
      maxContribution: 10,
      contribution: 10 * Math.min(Math.max(hotspot.junction_share, 0), 1)
    },
    {
      label: "Neighbor influence",
      maxContribution: 10,
      contribution: 10 * scale(hotspot.neighbor_influence, benchmarks.maxNeighborInfluence)
    },
    {
      label: "Validation share",
      maxContribution: 5,
      contribution: 5 * Math.min(Math.max(validationShare, 0), 1)
    }
  ];

  return {
    total: components.reduce((sum, component) => sum + component.contribution, 0),
    components
  };
}

function scale(value: number, maximum: number) {
  if (maximum <= 0) return 0;
  return Math.min(value / maximum, 1);
}

function NeighborhoodGraph({
  graph,
  selectedCellId,
  onSelect
}: {
  graph: GraphResponse | null;
  selectedCellId: string;
  onSelect?: (cellId: string) => void;
}) {
  const neighbors = graph?.neighbors.slice(0, 10) ?? [];
  const edgeLookup = new Map(
    (graph?.edges ?? []).map((edge) => [
      edge.source === selectedCellId ? edge.target : edge.source,
      edge,
    ])
  );
  const center = { x: 160, y: 100 };
  const radius = 72;

  return (
    <svg className="network-chart" viewBox="0 0 320 200" role="img" aria-label="Graph neighborhood visualization">
      {neighbors.map((neighbor, index) => {
        const angle = (index / Math.max(neighbors.length, 1)) * Math.PI * 2 - Math.PI / 2;
        const x = center.x + Math.cos(angle) * radius;
        const y = center.y + Math.sin(angle) * radius;
        return (
          <line
            key={`${selectedCellId}-${neighbor.grid_cell_id}-edge`}
            x1={center.x}
            y1={center.y}
            x2={x}
            y2={y}
            strokeWidth={1 + Math.min((edgeLookup.get(neighbor.grid_cell_id)?.weight ?? 1) * 2, 5)}
          >
            <title>
              {`${hotspotName(neighbor)} edge weight ${(edgeLookup.get(neighbor.grid_cell_id)?.weight ?? 0).toFixed(2)}`}
            </title>
          </line>
        );
      })}
      {neighbors.map((neighbor, index) => {
        const angle = (index / Math.max(neighbors.length, 1)) * Math.PI * 2 - Math.PI / 2;
        const x = center.x + Math.cos(angle) * radius;
        const y = center.y + Math.sin(angle) * radius;
        const r = 7 + Math.min(neighbor.violation_count / 300, 12);
        const fill =
          neighbor.obstruction_risk_score >= 70
            ? "#f43f5e"
            : neighbor.obstruction_risk_score >= 55
              ? "#f59e0b"
              : "#14b8a6";
        return (
          <circle
            key={neighbor.grid_cell_id}
            cx={x}
            cy={y}
            r={r}
            fill={fill}
            onClick={() => onSelect?.(neighbor.grid_cell_id)}
            style={{ cursor: onSelect ? 'pointer' : 'default' }}
          >
            <title>
              {`${hotspotName(neighbor)}: risk ${neighbor.obstruction_risk_score.toFixed(1)}, violations ${neighbor.violation_count}`}
            </title>
          </circle>
        );
      })}
      <circle className="network-center" cx={center.x} cy={center.y} r="18" />
      <text x={center.x} y={center.y + 4} textAnchor="middle">
        Zone
      </text>
    </svg>
  );
}
