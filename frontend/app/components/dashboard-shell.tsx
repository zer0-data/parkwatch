"use client";

import { useEffect, useMemo, useState } from "react";
import type {
  HeatmapPoint,
  ForecastResponse,
  Hotspot,
  StationSummary,
  Summary,
  TemporalHour,
  TemporalWeekday
} from "../lib/types";
import { HotspotDetailPanel } from "./hotspot-detail-panel";
import { HotspotMap } from "./hotspot-map";
import { ForecastPanel } from "./forecast-panel";
import { MetricCards } from "./metric-cards";
import { RankedHotspotTable } from "./ranked-hotspot-table";
import { TemporalHeatmap } from "./temporal-heatmap";

type DashboardShellProps = {
  summary: Summary;
  hotspots: Hotspot[];
  stations: StationSummary[];
  hourly: TemporalHour[];
  weekday: TemporalWeekday[];
  heatmap: HeatmapPoint[];
  forecast: ForecastResponse;
};

export function DashboardShell({
  summary,
  hotspots,
  stations,
  hourly,
  weekday,
  heatmap,
  forecast
}: DashboardShellProps) {
  const [activeTab, setActiveTab] = useState<"overview" | "map" | "forecast">("overview");
  const [stationFilter, setStationFilter] = useState("All stations");
  const [confidenceFilter, setConfidenceFilter] = useState("All confidence");
  const [selectedCellId, setSelectedCellId] = useState<string | null>(
    hotspots[0]?.grid_cell_id ?? null
  );

  const stationOptions = useMemo(
    () => [
      "All stations",
      ...stations.map((station) => station.station).sort((a, b) => a.localeCompare(b))
    ],
    [stations]
  );

  const filteredHotspots = useMemo(
    () =>
      hotspots.filter((hotspot) => {
        const stationMatches =
          stationFilter === "All stations" || hotspot.dominant_station === stationFilter;
        const confidenceMatches =
          confidenceFilter === "All confidence" || hotspot.confidence === confidenceFilter;
        return stationMatches && confidenceMatches;
      }),
    [confidenceFilter, hotspots, stationFilter]
  );

  useEffect(() => {
    if (!filteredHotspots.length) {
      setSelectedCellId(null);
      return;
    }

    if (!filteredHotspots.some((hotspot) => hotspot.grid_cell_id === selectedCellId)) {
      setSelectedCellId(filteredHotspots[0].grid_cell_id);
    }
  }, [filteredHotspots, selectedCellId]);

  const selectedHotspot = useMemo(
    () =>
      filteredHotspots.find((hotspot) => hotspot.grid_cell_id === selectedCellId) ??
      null,
    [filteredHotspots, selectedCellId]
  );

  return (
    <main className="page-shell">
      <section className="hero-band dashboard-hero">
        <div>
          <p className="eyebrow">Bengaluru parking violations</p>
          <h1>ParkWatch Dashboard</h1>
          <p>
            Explore hotspot patterns using the Obstruction Risk Score. This is a
            Congestion-Risk Proxy from official parking violation records; the dataset
            does not contain traffic speed or measured delay.
          </p>
        </div>
        <div className="hero-facts" aria-label="Dataset summary">
          <span>{summary.hotspot_count.toLocaleString("en-IN")} grid hotspots</span>
          <span>{summary.edge_count.toLocaleString("en-IN")} spatial edges</span>
          <span>{summary.metadata.timezone ?? "Asia/Kolkata"}</span>
        </div>
      </section>

      <MetricCards summary={summary} stations={stations} hotspots={filteredHotspots} />

      <section className="tab-bar" aria-label="Dashboard tabs">
        <button
          className={activeTab === "overview" ? "active" : ""}
          type="button"
          onClick={() => setActiveTab("overview")}
        >
          Overview
        </button>
        <button
          className={activeTab === "map" ? "active" : ""}
          type="button"
          onClick={() => setActiveTab("map")}
        >
          Spatial Map
        </button>
        <button
          className={activeTab === "forecast" ? "active" : ""}
          type="button"
          onClick={() => setActiveTab("forecast")}
        >
          Forecast
        </button>
      </section>

      {activeTab === "forecast" && <ForecastPanel forecast={forecast} />}

      {(activeTab === "overview" || activeTab === "map") && (
        <section className="filter-panel" aria-label="Dashboard filters">
          <label>
            <span>Police station</span>
            <select
              value={stationFilter}
              onChange={(event) => setStationFilter(event.target.value)}
            >
              {stationOptions.map((station) => (
                <option key={station} value={station}>
                  {station}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Confidence</span>
            <select
              value={confidenceFilter}
              onChange={(event) => setConfidenceFilter(event.target.value)}
            >
              <option>All confidence</option>
              <option>High</option>
              <option>Medium</option>
              <option>Low</option>
            </select>
          </label>
          <strong>{filteredHotspots.length.toLocaleString("en-IN")} matching hotspots</strong>
        </section>
      )}

      {activeTab === "map" && (
        <section className="dashboard-grid">
          <HotspotMap
            hotspots={filteredHotspots}
            selectedCellId={selectedCellId}
            onSelect={setSelectedCellId}
          />
          <HotspotDetailPanel hotspot={selectedHotspot} />
        </section>
      )}

      {activeTab === "overview" && (
        <section className="dashboard-grid lower-grid">
          <RankedHotspotTable
            hotspots={filteredHotspots}
            selectedCellId={selectedCellId}
            onSelect={setSelectedCellId}
          />
          <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
            <HotspotDetailPanel hotspot={selectedHotspot} />
            <TemporalHeatmap hourly={hourly} weekday={weekday} heatmap={heatmap} />
          </div>
        </section>
      )}
    </main>
  );
}
