"use client";

import { useMemo, useState } from "react";
import type { Hotspot } from "../lib/types";
import { hotspotContext, hotspotName } from "../lib/hotspot-labels";
import {
  buildImpactEstimates,
  ENFORCEMENT_SCENARIOS,
  formatPct,
  totalExposure
} from "../lib/impact";

type ImpactScenarioPanelProps = {
  hotspots: Hotspot[];
  allHotspots: Hotspot[];
};

export function ImpactScenarioPanel({ hotspots, allHotspots }: ImpactScenarioPanelProps) {
  const [scenarioKey, setScenarioKey] =
    useState<(typeof ENFORCEMENT_SCENARIOS)[number]["key"]>("moderate");
  const scenario =
    ENFORCEMENT_SCENARIOS.find((item) => item.key === scenarioKey) ??
    ENFORCEMENT_SCENARIOS[1];
  const estimates = useMemo(
    () => buildImpactEstimates(hotspots, allHotspots, scenario, 30),
    [allHotspots, hotspots, scenario]
  );
  const filteredExposure = totalExposure(hotspots);
  const cityExposure = totalExposure(allHotspots);
  const topTenReducedExposure = estimates
    .slice(0, 10)
    .reduce((sum, item) => sum + item.reducedExposure, 0);
  const filteredReductionPct =
    filteredExposure > 0 ? (topTenReducedExposure / filteredExposure) * 100 : 0;
  const cityReductionPct = cityExposure > 0 ? (topTenReducedExposure / cityExposure) * 100 : 0;

  const exportImpactCsv = () => {
    const header = [
      "rank",
      "location",
      "station",
      "cell_id",
      "scenario",
      "modeled_obstruction_exposure",
      "estimated_reduced_exposure",
      "hotspot_proxy_reduction_pct",
      "filtered_proxy_reduction_pct",
      "city_proxy_reduction_pct"
    ];
    const rows = estimates.map((item, index) => [
      index + 1,
      hotspotName(item.hotspot),
      item.hotspot.dominant_station ?? "",
      item.hotspot.grid_cell_id,
      scenario.label,
      item.exposure.toFixed(2),
      item.reducedExposure.toFixed(2),
      item.hotspotExposureReductionPct.toFixed(1),
      item.filteredExposureReductionPct.toFixed(3),
      item.cityExposureReductionPct.toFixed(3)
    ]);
    const csv = [header, ...rows]
      .map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(","))
      .join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "parkwatch-obstruction-exposure-scenario.csv";
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section className="impact-layout">
      <div className="panel impact-intro">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Scenario impact proxy</p>
            <h2>Modeled obstruction exposure reduction</h2>
          </div>
          <button className="export-button" type="button" onClick={exportImpactCsv}>
            Export CSV
          </button>
        </div>
        <p>
          This scenario estimates how much official-CSV-derived obstruction exposure
          would fall if targeted enforcement reduced repeat observed violations. It is
          not measured congestion reduction.
        </p>
        <div className="scenario-control" aria-label="Enforcement scenario">
          {ENFORCEMENT_SCENARIOS.map((item) => (
            <button
              className={item.key === scenario.key ? "active" : ""}
              key={item.key}
              type="button"
              onClick={() => setScenarioKey(item.key)}
            >
              <strong>{item.label}</strong>
              <span>{(item.repeatViolationReduction * 100).toFixed(0)}%</span>
            </button>
          ))}
        </div>
        <p className="muted">{scenario.description}</p>
      </div>

      <div className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Top 10 scenario total</p>
            <h2>Proxy impact summary</h2>
          </div>
        </div>
        <div className="impact-metrics">
          <span>
            <strong>{Math.round(topTenReducedExposure).toLocaleString("en-IN")}</strong>
            Reduced exposure units
          </span>
          <span>
            <strong>{formatPct(filteredReductionPct)}</strong>
            Of current filtered exposure
          </span>
          <span>
            <strong>{formatPct(cityReductionPct)}</strong>
            Of citywide exposure proxy
          </span>
        </div>
        <p className="muted">
          Exposure units combine violation count, severity, peak concentration,
          recurrence, and confidence. They are useful for comparing action scenarios,
          not for claiming speed, delay, or travel-time gains.
        </p>
      </div>

      <div className="panel impact-table-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Ranked proxy impact</p>
            <h2>Where enforcement changes the modeled exposure most</h2>
          </div>
          <span className="pill">{estimates.length} shown</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Location</th>
                <th>Station</th>
                <th>Exposure units</th>
                <th>Reduced units</th>
                <th>Hotspot proxy drop</th>
                <th>Filtered share</th>
                <th>City proxy share</th>
              </tr>
            </thead>
            <tbody>
              {estimates.map((item) => (
                <tr key={item.hotspot.grid_cell_id}>
                  <td>
                    <strong className="location-name">{hotspotName(item.hotspot)}</strong>
                    <span className="cell-meta">{hotspotContext(item.hotspot)}</span>
                  </td>
                  <td>{item.hotspot.dominant_station ?? "Unknown"}</td>
                  <td>{Math.round(item.exposure).toLocaleString("en-IN")}</td>
                  <td>{Math.round(item.reducedExposure).toLocaleString("en-IN")}</td>
                  <td>{formatPct(item.hotspotExposureReductionPct)}</td>
                  <td>{formatPct(item.filteredExposureReductionPct)}</td>
                  <td>{formatPct(item.cityExposureReductionPct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
