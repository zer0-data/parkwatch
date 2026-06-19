"use client";

import Link from "next/link";
import type { ForecastItem, ForecastResponse } from "../lib/types";
import { forecastHotspotContext, forecastHotspotName } from "../lib/hotspot-labels";

type ForecastPanelProps = {
  forecast: ForecastResponse;
};

export function ForecastPanel({ forecast }: ForecastPanelProps) {
  const topItem = forecast.items[0] ?? null;
  const highConfidenceCount = forecast.items.filter((item) => item.confidence === "High").length;
  const priorityCandidates = forecast.items.filter(
    (item) => item.predicted_enforcement_priority >= 60 && item.confidence !== "Low"
  ).length;
  const averageIntervalWidth =
    forecast.items.length > 0
      ? forecast.items.reduce(
          (sum, item) => sum + (item.prediction_interval_high - item.prediction_interval_low),
          0
        ) / forecast.items.length
      : 0;
  const risingForecasts = forecast.items.filter(
    (item) => item.last_4_week_avg > 0 && item.last_1_week_count / item.last_4_week_avg >= 1.2
  ).length;
  const exportForecastCsv = () => {
    const header = [
      "rank",
      "location",
      "station",
      "cell_id",
      "predicted_violation_count",
      "prediction_interval_low",
      "prediction_interval_high",
      "predicted_enforcement_priority",
      "forecast_stability",
      "confidence",
      "forecast_reason_codes"
    ];
    const rows = forecast.items.map((item, index) => [
      index + 1,
      item.location ?? item.junction ?? item.grid_cell_id,
      item.station ?? "",
      item.grid_cell_id,
      item.predicted_violation_count.toFixed(1),
      item.prediction_interval_low.toFixed(1),
      item.prediction_interval_high.toFixed(1),
      item.predicted_enforcement_priority.toFixed(1),
      item.forecast_stability.toFixed(1),
      item.confidence,
      item.forecast_reason_codes.join("; ")
    ]);
    const csv = [header, ...rows]
      .map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(","))
      .join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "parkwatch-forecast-priority-zones.csv";
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section className="forecast-layout">
      <div className="panel forecast-intro">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Graph-enhanced forecast</p>
            <h2>Next-week observed violation forecast</h2>
          </div>
          <div className="table-actions">
            <Link className="explain-link" href="/explainer">What does this mean?</Link>
            <span className="pill">{forecast.forecast_week ?? "Next week"}</span>
          </div>
        </div>
        <p>
          This is a forecast of future observed parking violations, not measured
          congestion. Forecast v2 uses recent weekly counts, trend, station-normalized
          activity, graph-neighbor activity, temporal concentration, and stability.
        </p>
        <div className="forecast-metrics">
          <span>
            <strong>{forecast.holdout.mae?.toFixed(2) ?? "n/a"}</strong>
            Rolling MAE
          </span>
          <span>
            <strong>{forecast.holdout.mape?.toFixed(1) ?? "n/a"}%</strong>
            Rolling MAPE
          </span>
          <span>
            <strong>{forecast.holdout.evaluated_points.toLocaleString("en-IN")}</strong>
            Evaluation points
          </span>
        </div>
        <div className="forecast-metrics secondary">
          <span>
            <strong>{priorityCandidates.toLocaleString("en-IN")}</strong>
            Forecast priority candidates
          </span>
          <span>
            <strong>{highConfidenceCount.toLocaleString("en-IN")}</strong>
            High-confidence forecasts
          </span>
          <span>
            <strong>{averageIntervalWidth.toFixed(1)}</strong>
            Avg interval width
          </span>
          <span>
            <strong>{risingForecasts.toLocaleString("en-IN")}</strong>
            Rising recent signals
          </span>
        </div>
      </div>

      <div className="panel forecast-chart-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Historical vs predicted</p>
            <h2>{topItem ? forecastHotspotName(topItem) : "No forecast"}</h2>
            {topItem && <span className="cell-meta">{forecastHotspotContext(topItem)}</span>}
          </div>
        </div>
        {topItem && <ForecastChart item={topItem} />}
      </div>

      <div className="panel forecast-table-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Top predicted hotspots</p>
            <h2>Predicted range and priority</h2>
          </div>
          <div className="table-actions">
            <button className="export-button" type="button" onClick={exportForecastCsv}>
              Export CSV
            </button>
            <span className="pill">{forecast.items.length} shown</span>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Location</th>
                <th>Station</th>
                <th>Predicted range</th>
                <th>Priority</th>
                <th>Stability</th>
                <th>Recent signal</th>
                <th>Reasons</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {forecast.items.slice(0, 25).map((item) => (
                <tr key={item.grid_cell_id}>
                  <td>
                    <strong className="location-name">{forecastHotspotName(item)}</strong>
                    <span className="cell-meta">{forecastHotspotContext(item)}</span>
                  </td>
                  <td>{item.station ?? "Unknown"}</td>
                  <td>
                    {item.prediction_interval_low.toFixed(1)}-
                    {item.prediction_interval_high.toFixed(1)}
                    <span className="cell-meta">
                      center {item.predicted_violation_count.toFixed(1)}
                    </span>
                  </td>
                  <td>{item.predicted_enforcement_priority.toFixed(1)}</td>
                  <td>{item.forecast_stability.toFixed(1)}</td>
                  <td>
                    {item.last_1_week_count.toFixed(0)} last week
                    <span className="cell-meta">
                      4-week avg {item.last_4_week_avg.toFixed(1)}
                    </span>
                  </td>
                  <td>
                    <div className="reason-list compact">
                      {item.forecast_reason_codes.slice(0, 3).map((reason) => (
                        <span key={reason}>{reason.replaceAll("_", " ")}</span>
                      ))}
                    </div>
                  </td>
                  <td>
                    <span className={`confidence ${item.confidence.toLowerCase()}`}>
                      {item.confidence}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function ForecastChart({ item }: { item: ForecastItem }) {
  const points = [
    ...item.historical_weeks.map((week) => ({
      label: week.week,
      value: week.violation_count,
      predicted: false
    })),
    {
      label: item.predicted_week ?? "Predicted",
      value: item.predicted_violation_count,
      predicted: true
    }
  ];
  const maxValue = Math.max(...points.map((point) => point.value), 1);
  const path = points
    .map((point, index) => {
      const x = points.length <= 1 ? 0 : (index / (points.length - 1)) * 420;
      const y = 160 - (point.value / maxValue) * 132;
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");

  return (
    <>
      <div className="chart-legend" aria-label="Forecast chart legend">
        <span><i className="legend-swatch line" />Historical weekly violations</span>
        <span><i className="legend-swatch predicted" />Predicted week center</span>
      </div>
      <svg className="forecast-chart" viewBox="0 0 420 180" role="img" aria-label="Historical versus predicted weekly violations">
        <path d={path} />
        {points.map((point, index) => {
          const x = points.length <= 1 ? 0 : (index / (points.length - 1)) * 420;
          const y = 160 - (point.value / maxValue) * 132;
          return (
            <circle
              key={`${point.label}-${index}`}
              className={point.predicted ? "predicted" : ""}
              cx={x}
              cy={y}
              r={point.predicted ? 6 : 4}
            >
              <title>{`${point.label}: ${point.value.toFixed(1)} violations`}</title>
            </circle>
          );
        })}
      </svg>
      <dl className="forecast-detail-list">
        <div>
          <dt>Predicted count range</dt>
          <dd>
            {item.prediction_interval_low.toFixed(1)}-
            {item.prediction_interval_high.toFixed(1)}
          </dd>
        </div>
        <div>
          <dt>Predicted priority</dt>
          <dd>{item.predicted_enforcement_priority.toFixed(1)}</dd>
        </div>
        <div>
          <dt>Forecast stability</dt>
          <dd>{item.forecast_stability.toFixed(1)}</dd>
        </div>
        <div>
          <dt>Station</dt>
          <dd>{item.station ?? "Unknown"}</dd>
        </div>
      </dl>
      <div className="reason-list">
        {item.forecast_reason_codes.map((reason) => (
          <span key={reason}>{reason.replaceAll("_", " ")}</span>
        ))}
      </div>
    </>
  );
}
