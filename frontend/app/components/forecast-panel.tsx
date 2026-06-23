"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import type { ForecastItem, ForecastResponse, ModelEvidence } from "../lib/types";
import { forecastHotspotContext, forecastHotspotName } from "../lib/hotspot-labels";

type ForecastPanelProps = {
  forecast: ForecastResponse;
};

export function ForecastPanel({ forecast }: ForecastPanelProps) {
  const [modelEvidence, setModelEvidence] = useState<ModelEvidence | null>(null);
  const topItem = forecast.items[0] ?? null;
  const modelLabel = forecast.model ? `${forecast.model} forecast` : "Graph-enhanced forecast";
  const highConfidenceCount = forecast.items.filter((item) => displayConfidence(item) === "High").length;
  const priorityCandidates = forecast.items.filter(
    (item) => forecastPriority(item) >= 60 && displayConfidence(item) !== "Low"
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

  useEffect(() => {
    let active = true;
    fetch("/api/backend/model-evidence", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: ModelEvidence | null) => {
        if (active) setModelEvidence(payload);
      })
      .catch(() => {
        if (active) setModelEvidence(null);
      });
    return () => {
      active = false;
    };
  }, []);
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
      forecastPriority(item).toFixed(1),
      item.forecast_stability.toFixed(1),
      displayConfidence(item),
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
            <p className="eyebrow">{modelLabel}</p>
            <h2>Next-week observed violation forecast</h2>
          </div>
          <div className="table-actions">
            <Link className="explain-link" href="/explainer">What does this mean?</Link>
            {forecast.forecast_source && <span className="pill">{forecast.forecast_source}</span>}
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

      <div className="panel model-evidence-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Model evidence</p>
            <h2>Forecast artifact and validation</h2>
          </div>
          <span className="pill">{modelEvidence?.forecast_source ?? forecast.forecast_source ?? "forecast artifact"}</span>
        </div>
        <div className="forecast-metrics secondary">
          <span>
            <strong>{modelEvidence?.active_model ?? forecast.model ?? "Model"}</strong>
            Active model
          </span>
          <span>
            <strong>{modelEvidence?.holdout.mae?.toFixed(2) ?? forecast.holdout.mae?.toFixed(2) ?? "n/a"}</strong>
            Holdout MAE
          </span>
          <span>
            <strong>{modelEvidence?.holdout.mape?.toFixed(1) ?? forecast.holdout.mape?.toFixed(1) ?? "n/a"}%</strong>
            Holdout MAPE
          </span>
          <span>
            <strong>{modelEvidence?.holdout.validation_type ?? forecast.holdout.validation_type ?? "artifact"}</strong>
            Validation
          </span>
        </div>
        <p className="muted">
          {modelEvidence?.note ??
            "Forecasts estimate observed violation pressure; they do not measure congestion or verified delay reduction."}
        </p>
        {modelEvidence?.available ? (
          <pre className="model-evidence-json">
            {JSON.stringify(modelEvidence.comparison, null, 2).slice(0, 1600)}
          </pre>
        ) : (
          <p className="muted">
            No model_comparison.json artifact is available in the processed data directory.
            The dashboard is showing the active forecast artifact only.
          </p>
        )}
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
                  <td>{forecastPriority(item).toFixed(1)}</td>
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
                    <span className={`confidence ${displayConfidence(item).toLowerCase()}`}>
                      {displayConfidence(item)}
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
      low: week.violation_count,
      high: week.violation_count,
      predicted: false
    })),
    {
      label: item.predicted_week ?? "Predicted",
      value: item.predicted_violation_count,
      low: item.prediction_interval_low,
      high: item.prediction_interval_high,
      predicted: true
    }
  ];

  return (
    <>
      <div className="chart-legend" aria-label="Forecast chart legend">
        <span><i className="legend-swatch line" />Historical weekly violations</span>
        <span><i className="legend-swatch area" />Prediction interval</span>
        <span><i className="legend-swatch predicted" />Predicted week center</span>
      </div>
      <div className="forecast-chart">
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={points} margin={{ top: 16, right: 18, bottom: 8, left: 0 }}>
            <CartesianGrid stroke="rgba(148, 163, 184, 0.18)" />
            <XAxis dataKey="label" stroke="#94a3b8" tick={{ fontSize: 11 }} />
            <YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} width={38} />
            <Tooltip
              contentStyle={{
                background: "#020617",
                border: "1px solid rgba(148, 163, 184, 0.28)",
                borderRadius: "8px",
                color: "#e2e8f0"
              }}
              formatter={(value: number, name: string) => [value.toFixed(1), name]}
            />
            <Area type="monotone" dataKey="high" stroke="none" fill="rgba(59, 130, 246, 0.14)" />
            <Area type="monotone" dataKey="low" stroke="none" fill="rgba(2, 6, 23, 0.72)" />
            <Line type="monotone" dataKey="value" name="violations" stroke="#2dd4bf" strokeWidth={3} dot={{ r: 4 }} activeDot={{ r: 6 }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
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
          <dd>{forecastPriority(item).toFixed(1)}</dd>
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

function forecastPriority(item: ForecastItem) {
  return item.predicted_enforcement_priority ?? item.predicted_obstruction_risk;
}

function displayConfidence(item: ForecastItem) {
  return item.confidence ?? "Model";
}
