"use client";

import { useEffect, useState } from "react";
import type { GraphResponse, Hotspot, TimeseriesPoint } from "../lib/types";

type DetailState =
  | { status: "idle"; timeseries: TimeseriesPoint[]; graph: GraphResponse | null }
  | { status: "loading"; timeseries: TimeseriesPoint[]; graph: GraphResponse | null }
  | { status: "ready"; timeseries: TimeseriesPoint[]; graph: GraphResponse }
  | { status: "error"; timeseries: TimeseriesPoint[]; graph: GraphResponse | null };

type HotspotDetailPanelProps = {
  hotspot: Hotspot | null;
};

export function HotspotDetailPanel({ hotspot }: HotspotDetailPanelProps) {
  const [detail, setDetail] = useState<DetailState>({
    status: "idle",
    timeseries: [],
    graph: null
  });

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
      fetch(`/api/backend/graph/${hotspot.grid_cell_id}`).then((response) => {
        if (!response.ok) throw new Error("Graph request failed");
        return response.json() as Promise<GraphResponse>;
      })
    ])
      .then(([timeseries, graph]) => {
        if (active) {
          setDetail({ status: "ready", timeseries, graph });
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

  return (
    <aside className="panel detail-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Hotspot detail</p>
          <h2>{hotspot.grid_cell_id}</h2>
        </div>
        <span className={`confidence ${hotspot.confidence.toLowerCase()}`}>
          {hotspot.confidence}
        </span>
      </div>

      <div className="score-ring" aria-label="Obstruction Risk Score">
        <strong>{hotspot.obstruction_risk_score.toFixed(1)}</strong>
        <span>Obstruction Risk Score</span>
      </div>

      <dl className="detail-list">
        <div>
          <dt>Confidence</dt>
          <dd>{hotspot.confidence}</dd>
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
        <h3>Graph neighborhood</h3>
        <NeighborhoodGraph graph={detail.graph} selectedCellId={hotspot.grid_cell_id} />
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

function NeighborhoodGraph({
  graph,
  selectedCellId
}: {
  graph: GraphResponse | null;
  selectedCellId: string;
}) {
  const neighbors = graph?.neighbors.slice(0, 10) ?? [];
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
          />
        );
      })}
      {neighbors.map((neighbor, index) => {
        const angle = (index / Math.max(neighbors.length, 1)) * Math.PI * 2 - Math.PI / 2;
        const x = center.x + Math.cos(angle) * radius;
        const y = center.y + Math.sin(angle) * radius;
        const r = 7 + Math.min(neighbor.violation_count / 300, 12);
        return (
          <circle
            key={neighbor.grid_cell_id}
            cx={x}
            cy={y}
            r={r}
            fill={neighbor.obstruction_risk_score >= 55 ? "#d88a17" : "#12a5a3"}
          >
            <title>
              {`${neighbor.grid_cell_id}: ${neighbor.obstruction_risk_score} score`}
            </title>
          </circle>
        );
      })}
      <circle className="network-center" cx={center.x} cy={center.y} r="18" />
      <text x={center.x} y={center.y + 4} textAnchor="middle">
        Cell
      </text>
    </svg>
  );
}
