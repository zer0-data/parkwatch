import type { Hotspot, StationSummary, Summary } from "../lib/types";

type MetricCardsProps = {
  summary: Summary;
  stations: StationSummary[];
  hotspots: Hotspot[];
};

export function MetricCards({ summary, stations, hotspots }: MetricCardsProps) {
  const topRisk = hotspots[0]?.obstruction_risk_score ?? 0;
  const highConfidence = hotspots.filter((item) => item.confidence === "High").length;
  const leadingStation = stations[0]?.station ?? "Unavailable";

  return (
    <section className="metric-grid" aria-label="Key metrics">
      <article className="metric-card">
        <span>Total violations</span>
        <strong>{summary.total_violations.toLocaleString("en-IN")}</strong>
        <small>Official CSV records aggregated into hotspot cells</small>
      </article>
      <article className="metric-card">
        <span>Top score</span>
        <strong>{topRisk.toFixed(1)}</strong>
        <small>Highest Obstruction Risk Score in current ranking</small>
      </article>
      <article className="metric-card">
        <span>High confidence</span>
        <strong>{highConfidence.toLocaleString("en-IN")}</strong>
        <small>Hotspots with repeated evidence and device-day support</small>
      </article>
      <article className="metric-card">
        <span>Leading station</span>
        <strong className="metric-text">{leadingStation}</strong>
        <small>Station with the highest aggregated violation count</small>
      </article>
    </section>
  );
}
