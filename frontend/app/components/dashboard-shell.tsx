"use client";

import Link from "next/link";
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
import { InteractiveMap } from "./interactive-map";
import { HeatmapLayer } from "./heatmap-layer";
import { ForecastPanel } from "./forecast-panel";
import { MetricCards } from "./metric-cards";
import { RankedHotspotTable } from "./ranked-hotspot-table";
import { TemporalHeatmap } from "./temporal-heatmap";
import { Tabs, Tab, Box, FormControl, InputLabel, Select, MenuItem, Button, Typography } from "@mui/material";

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
  const [activeTab, setActiveTab] = useState<"overview" | "map" | "interactive" | "heatmap" | "forecast">("overview");
  const [stationFilter, setStationFilter] = useState("All stations");
  const [confidenceFilter, setConfidenceFilter] = useState("All confidence");
  const [violationTypeFilter, setViolationTypeFilter] = useState("All violations");
  const [weekdayFilter, setWeekdayFilter] = useState("All weekdays");
  const [hourFilter, setHourFilter] = useState("All hours");
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

  const violationTypeOptions = useMemo(
    () => [
      "All violations",
      ...Array.from(
        new Set(
          hotspots
            .map((hotspot) => hotspot.dominant_violation_type)
            .filter((value): value is string => Boolean(value))
        )
      ).sort((a, b) => a.localeCompare(b))
    ],
    [hotspots]
  );

  const weekdayOptions = useMemo(
    () => [
      "All weekdays",
      ...Array.from(
        new Set(
          hotspots
            .map((hotspot) => hotspot.peak_weekday)
            .filter((value): value is string => Boolean(value))
        )
      )
    ],
    [hotspots]
  );

  const scoreBenchmarks = useMemo(
    () => ({
      maxViolationCount: Math.max(...hotspots.map((hotspot) => hotspot.violation_count), 1),
      maxActiveDays: Math.max(...hotspots.map((hotspot) => hotspot.active_days), 1),
      maxDeviceDays: Math.max(...hotspots.map((hotspot) => hotspot.device_days), 1),
      maxNeighborInfluence: Math.max(...hotspots.map((hotspot) => hotspot.neighbor_influence), 1)
    }),
    [hotspots]
  );

  const filteredHotspots = useMemo(
    () =>
      hotspots.filter((hotspot) => {
        const stationMatches =
          stationFilter === "All stations" || hotspot.dominant_station === stationFilter;
        const confidenceMatches =
          confidenceFilter === "All confidence" || hotspot.confidence === confidenceFilter;
        const violationMatches =
          violationTypeFilter === "All violations" ||
          hotspot.dominant_violation_type === violationTypeFilter;
        const weekdayMatches =
          weekdayFilter === "All weekdays" || hotspot.peak_weekday === weekdayFilter;
        const hourMatches =
          hourFilter === "All hours" || hotspot.peak_hour === Number(hourFilter);
        return (
          stationMatches &&
          confidenceMatches &&
          violationMatches &&
          weekdayMatches &&
          hourMatches
        );
      }),
    [confidenceFilter, hourFilter, hotspots, stationFilter, violationTypeFilter, weekdayFilter]
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

  const exportPriorityCsv = () => {
    const header = [
      "rank",
      "location",
      "station",
      "cell_id",
      "enforcement_priority_score",
      "obstruction_risk_score",
      "violations",
      "confidence",
      "priority_band",
      "peak_weekday",
      "peak_hour",
      "dominant_violation"
    ];
    const rows = filteredHotspots.map((hotspot, index) => [
      index + 1,
      hotspot.representative_location ?? hotspot.dominant_junction ?? hotspot.grid_cell_id,
      hotspot.dominant_station ?? "",
      hotspot.grid_cell_id,
      hotspot.enforcement_priority_score.toFixed(1),
      hotspot.obstruction_risk_score.toFixed(1),
      hotspot.violation_count,
      hotspot.confidence,
      hotspot.priority_band,
      hotspot.peak_weekday ?? "",
      hotspot.peak_hour ?? "",
      hotspot.dominant_violation_type ?? ""
    ]);
    const csv = [header, ...rows]
      .map((row) =>
        row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(",")
      )
      .join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "parkwatch-enforcement-priority-zones.csv";
    link.click();
    URL.revokeObjectURL(url);
  };

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
          <Link className="explain-link hero-explain-link" href="/explainer">
            What do these representations mean?
          </Link>
        </div>
        <div className="hero-facts" aria-label="Dataset summary">
          <span>{summary.hotspot_count.toLocaleString("en-IN")} grid hotspots</span>
          <span>{summary.edge_count.toLocaleString("en-IN")} spatial edges</span>
          <span>{summary.metadata.timezone ?? "Asia/Kolkata"}</span>
        </div>
      </section>

      <MetricCards summary={summary} stations={stations} hotspots={filteredHotspots} />

      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
        <Tabs value={activeTab} onChange={(e, val) => setActiveTab(val)} aria-label="Dashboard tabs">
          <Tab value="overview" label="Overview" />
          <Tab value="map" label="Scatter Map" />
          <Tab value="interactive" label="Interactive Map" />
          <Tab value="heatmap" label="Heatmap View" />
          <Tab value="forecast" label="Forecast" />
        </Tabs>
      </Box>

      {activeTab === "forecast" && <ForecastPanel forecast={forecast} />}

      {(activeTab === "overview" || activeTab === "map" || activeTab === "interactive" || activeTab === "heatmap") && (
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, mb: 4, alignItems: 'center', p: 2, bgcolor: 'background.paper', borderRadius: 2 }}>
          <FormControl size="small" sx={{ minWidth: 150 }}>
            <InputLabel>Police station</InputLabel>
            <Select
              value={stationFilter}
              label="Police station"
              onChange={(event) => setStationFilter(event.target.value)}
            >
              {stationOptions.map((station) => (
                <MenuItem key={station} value={station}>
                  {station}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          
          <FormControl size="small" sx={{ minWidth: 150 }}>
            <InputLabel>Confidence</InputLabel>
            <Select
              value={confidenceFilter}
              label="Confidence"
              onChange={(event) => setConfidenceFilter(event.target.value)}
            >
              <MenuItem value="All confidence">All confidence</MenuItem>
              <MenuItem value="High">High</MenuItem>
              <MenuItem value="Medium">Medium</MenuItem>
              <MenuItem value="Low">Low</MenuItem>
            </Select>
          </FormControl>

          <FormControl size="small" sx={{ minWidth: 150 }}>
            <InputLabel>Violation type</InputLabel>
            <Select
              value={violationTypeFilter}
              label="Violation type"
              onChange={(event) => setViolationTypeFilter(event.target.value)}
            >
              {violationTypeOptions.map((violationType) => (
                <MenuItem key={violationType} value={violationType}>
                  {violationType}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <FormControl size="small" sx={{ minWidth: 150 }}>
            <InputLabel>Peak weekday</InputLabel>
            <Select
              value={weekdayFilter}
              label="Peak weekday"
              onChange={(event) => setWeekdayFilter(event.target.value)}
            >
              {weekdayOptions.map((weekdayName) => (
                <MenuItem key={weekdayName} value={weekdayName}>
                  {weekdayName}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <FormControl size="small" sx={{ minWidth: 150 }}>
            <InputLabel>Peak hour</InputLabel>
            <Select value={hourFilter} label="Peak hour" onChange={(event) => setHourFilter(event.target.value)}>
              <MenuItem value="All hours">All hours</MenuItem>
              {Array.from({ length: 24 }, (_, hour) => (
                <MenuItem key={hour} value={hour}>
                  {hour.toString().padStart(2, "0")}:00
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <Button variant="outlined" color="primary" onClick={exportPriorityCsv}>
            Export CSV
          </Button>

          <Typography variant="body2" sx={{ ml: 'auto', fontWeight: 600 }}>
            {filteredHotspots.length.toLocaleString("en-IN")} matching hotspots
          </Typography>
        </Box>
      )}

      {activeTab === "interactive" && (
        <section className="dashboard-grid">
          <div style={{ gridColumn: '1 / -1' }}>
            <InteractiveMap
              hotspots={filteredHotspots}
              selectedCellId={selectedCellId}
              onSelect={setSelectedCellId}
            />
          </div>
          <HotspotDetailPanel hotspot={selectedHotspot} scoreBenchmarks={scoreBenchmarks} />
        </section>
      )}

      {activeTab === "heatmap" && (
        <section className="dashboard-grid">
          <div style={{ gridColumn: '1 / -1' }}>
            <HeatmapLayer
              hotspots={filteredHotspots}
              selectedCellId={selectedCellId}
              title="Risk Heatmap - Color Intensity Shows Risk"
            />
          </div>
          <HotspotDetailPanel hotspot={selectedHotspot} scoreBenchmarks={scoreBenchmarks} />
        </section>
      )}

      {activeTab === "map" && (
        <section className="dashboard-grid">
          <HotspotMap
            hotspots={filteredHotspots}
            selectedCellId={selectedCellId}
            onSelect={setSelectedCellId}
          />
          <HotspotDetailPanel hotspot={selectedHotspot} scoreBenchmarks={scoreBenchmarks} />
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
            <HotspotDetailPanel hotspot={selectedHotspot} scoreBenchmarks={scoreBenchmarks} />
            <TemporalHeatmap hourly={hourly} weekday={weekday} heatmap={heatmap} />
          </div>
        </section>
      )}
    </main>
  );
}
