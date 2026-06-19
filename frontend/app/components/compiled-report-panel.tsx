"use client";

import type { ForecastResponse, Hotspot, StationSummary, Summary } from "../lib/types";
import { hotspotName } from "../lib/hotspot-labels";
import {
  buildImpactEstimates,
  ENFORCEMENT_SCENARIOS,
  formatPct,
  totalExposure
} from "../lib/impact";

type CompiledReportPanelProps = {
  summary: Summary;
  hotspots: Hotspot[];
  allHotspots: Hotspot[];
  stations: StationSummary[];
  forecast: ForecastResponse;
};

export function CompiledReportPanel({
  summary,
  hotspots,
  allHotspots,
  stations,
  forecast
}: CompiledReportPanelProps) {
  const moderateScenario = ENFORCEMENT_SCENARIOS[1];
  const impactEstimates = buildImpactEstimates(hotspots, allHotspots, moderateScenario, 10);
  const filteredExposure = totalExposure(hotspots);
  const cityExposure = totalExposure(allHotspots);
  const topTenReducedExposure = impactEstimates.reduce(
    (sum, item) => sum + item.reducedExposure,
    0
  );
  const topHotspots = hotspots.slice(0, 8);
  const topForecasts = forecast.items.slice(0, 8);
  const leadingStation = stations[0];
  const filteredReductionPct =
    filteredExposure > 0 ? (topTenReducedExposure / filteredExposure) * 100 : 0;
  const cityReductionPct = cityExposure > 0 ? (topTenReducedExposure / cityExposure) * 100 : 0;
  const reportText = buildReportText({
    summary,
    topHotspots,
    topForecasts,
    leadingStation,
    filteredCount: hotspots.length,
    forecast,
    topTenReducedExposure,
    filteredReductionPct,
    cityReductionPct
  });

  const downloadReport = () => {
    const url = URL.createObjectURL(new Blob([reportText], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "parkwatch-compiled-report.txt";
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section className="report-layout">
      <div className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Compiled report</p>
            <h2>Official-data-only operational brief</h2>
          </div>
          <button className="export-button" type="button" onClick={downloadReport}>
            Download TXT
          </button>
        </div>
        <p className="muted">
          This report is generated locally from the loaded backend JSON. It uses no
          external model API and does not claim measured congestion reduction.
        </p>
        <div className="report-metrics">
          <span>
            <strong>{hotspots.length.toLocaleString("en-IN")}</strong>
            Filtered hotspots
          </span>
          <span>
            <strong>{forecast.forecast_week ?? "Next week"}</strong>
            Forecast period
          </span>
          <span>
            <strong>{formatPct(filteredReductionPct)}</strong>
            Top 10 moderate proxy reduction
          </span>
          <span>
            <strong>{formatPct(cityReductionPct)}</strong>
            Citywide proxy share
          </span>
        </div>
      </div>

      <div className="panel report-preview">
        <pre>{reportText}</pre>
      </div>
    </section>
  );
}

function buildReportText({
  summary,
  topHotspots,
  topForecasts,
  leadingStation,
  filteredCount,
  forecast,
  topTenReducedExposure,
  filteredReductionPct,
  cityReductionPct
}: {
  summary: Summary;
  topHotspots: Hotspot[];
  topForecasts: ForecastResponse["items"];
  leadingStation?: StationSummary;
  filteredCount: number;
  forecast: ForecastResponse;
  topTenReducedExposure: number;
  filteredReductionPct: number;
  cityReductionPct: number;
}) {
  const lines = [
    "ParkWatch Compiled Report",
    "Official parking-violation dataset only",
    "",
    "Compliance note:",
    "ParkWatch reports obstruction-risk and enforcement-priority proxies. It does not prove measured congestion, measured delay, minutes saved, or percentage congestion reduction.",
    "",
    "Dataset summary:",
    `- Total official records: ${summary.total_violations.toLocaleString("en-IN")}`,
    `- Grid hotspots: ${summary.hotspot_count.toLocaleString("en-IN")}`,
    `- Spatial graph edges: ${summary.edge_count.toLocaleString("en-IN")}`,
    `- Filtered hotspots in this report: ${filteredCount.toLocaleString("en-IN")}`,
    leadingStation
      ? `- Leading station by violations: ${leadingStation.station} (${leadingStation.violation_count.toLocaleString("en-IN")} violations)`
      : "- Leading station by violations: unavailable",
    "",
    "Top enforcement-priority zones:",
    ...topHotspots.map(
      (hotspot, index) =>
        `${index + 1}. ${hotspotName(hotspot)} | ${hotspot.dominant_station ?? "Unknown"} | priority ${hotspot.enforcement_priority_score.toFixed(1)} | risk ${hotspot.obstruction_risk_score.toFixed(1)} | ${hotspot.violation_count.toLocaleString("en-IN")} violations | ${hotspot.priority_band}`
    ),
    "",
    "Forecast summary:",
    `- Forecast type: ${forecast.forecast_type}`,
    `- Forecast week: ${forecast.forecast_week ?? "Next week"}`,
    `- Rolling MAE: ${forecast.holdout.mae?.toFixed(2) ?? "n/a"}`,
    `- Rolling MAPE: ${forecast.holdout.mape?.toFixed(1) ?? "n/a"}%`,
    `- Evaluation points: ${forecast.holdout.evaluated_points.toLocaleString("en-IN")}`,
    "",
    "Top forecast-priority zones:",
    ...topForecasts.map(
      (item, index) =>
        `${index + 1}. ${item.location ?? item.junction ?? item.grid_cell_id} | ${item.station ?? "Unknown"} | predicted ${item.predicted_violation_count.toFixed(1)} (${item.prediction_interval_low.toFixed(1)}-${item.prediction_interval_high.toFixed(1)}) | priority ${item.predicted_enforcement_priority.toFixed(1)} | stability ${item.forecast_stability.toFixed(1)}`
    ),
    "",
    "Scenario impact proxy:",
    "- Scenario: Moderate targeted enforcement, assuming 20% fewer repeat observed violations in selected hotspots.",
    `- Top 10 reduced exposure units: ${Math.round(topTenReducedExposure).toLocaleString("en-IN")}`,
    `- Share of filtered obstruction-exposure proxy: ${formatPct(filteredReductionPct)}`,
    `- Share of citywide obstruction-exposure proxy: ${formatPct(cityReductionPct)}`,
    "",
    "Recommended wording:",
    "Use: modeled obstruction-exposure reduction, obstruction-risk proxy, enforcement-priority candidate.",
    "Avoid: measured congestion hotspot, congestion reduced by X%, minutes saved, measured delay avoided."
  ];

  return lines.join("\n");
}
