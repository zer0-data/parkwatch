"use client";

import { useEffect, useMemo, useState } from "react";
import type { DelayExposureResponse, ForecastResponse, Hotspot } from "../lib/types";
import { hotspotContext, hotspotName } from "../lib/hotspot-labels";
import { buildDelayCandidates } from "../lib/delay-candidates";
import {
  buildImpactEstimates,
  ENFORCEMENT_SCENARIOS,
  formatPct,
  totalExposure
} from "../lib/impact";

type ImpactScenarioPanelProps = {
  hotspots: Hotspot[];
  allHotspots: Hotspot[];
  forecast: ForecastResponse;
};

export function ImpactScenarioPanel({ hotspots, allHotspots, forecast }: ImpactScenarioPanelProps) {
  const [scenarioKey, setScenarioKey] =
    useState<(typeof ENFORCEMENT_SCENARIOS)[number]["key"]>("moderate");
  const [delayExposure, setDelayExposure] = useState<DelayExposureResponse | null>(null);
  const [delayStatus, setDelayStatus] = useState<"loading" | "ready" | "fallback">("loading");
  const scenario =
    ENFORCEMENT_SCENARIOS.find((item) => item.key === scenarioKey) ??
    ENFORCEMENT_SCENARIOS[1];
  const candidates = useMemo(
    () => buildDelayCandidates(hotspots, forecast).slice(0, 12),
    [forecast, hotspots]
  );
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
  const delayItems = delayExposure?.items ?? [];

  useEffect(() => {
    if (!candidates.length) {
      setDelayExposure(null);
      setDelayStatus("fallback");
      return;
    }

    const controller = new AbortController();
    setDelayStatus("loading");
    fetch("/api/backend/mappls/delay-exposure", {
      method: "POST",
      headers: {
        accept: "application/json",
        "content-type": "application/json"
      },
      body: JSON.stringify({
        candidates,
        scenario_reduction: scenario.repeatViolationReduction
      }),
      cache: "no-store",
      signal: controller.signal
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Delay exposure request failed (${response.status})`);
        }
        return response.json() as Promise<DelayExposureResponse>;
      })
      .then((payload) => {
        setDelayExposure(payload);
        setDelayStatus(payload.source.toLowerCase().includes("heuristic") ? "fallback" : "ready");
      })
      .catch((error) => {
        if (error.name === "AbortError") return;
        setDelayExposure(null);
        setDelayStatus("fallback");
      });

    return () => controller.abort();
  }, [candidates, scenario]);

  const exportImpactCsv = () => {
    const header = [
      "rank",
      "location",
      "station",
      "cell_id",
      "scenario",
      "predicted_violations",
      "forecast_priority",
      "traffic_eta_minutes",
      "freeflow_eta_minutes",
      "traffic_delay_minutes",
      "estimated_delay_exposure_minutes",
      "reduced_delay_exposure_minutes",
      "delay_source",
      "modeled_obstruction_exposure",
      "estimated_reduced_exposure",
      "hotspot_proxy_reduction_pct",
      "filtered_proxy_reduction_pct",
      "city_proxy_reduction_pct"
    ];
    const estimatesById = new Map(estimates.map((item) => [item.hotspot.grid_cell_id, item]));
    const rows = delayItems.map((item, index) => {
      const proxy = estimatesById.get(item.grid_cell_id);
      return [
        index + 1,
        item.location,
        item.station ?? "",
        item.grid_cell_id,
        scenario.label,
        item.predicted_violations.toFixed(1),
        item.forecast_priority.toFixed(1),
        item.traffic_eta_minutes?.toFixed(1) ?? "",
        item.freeflow_eta_minutes?.toFixed(1) ?? "",
        item.traffic_delay_minutes.toFixed(1),
        item.estimated_delay_exposure_minutes.toFixed(1),
        item.reduced_delay_exposure_minutes.toFixed(1),
        item.source,
        proxy?.exposure.toFixed(2) ?? "",
        proxy?.reducedExposure.toFixed(2) ?? "",
        proxy?.hotspotExposureReductionPct.toFixed(1) ?? "",
        proxy?.filteredExposureReductionPct.toFixed(3) ?? "",
        proxy?.cityExposureReductionPct.toFixed(3) ?? ""
      ];
    });
    const csv = [header, ...rows]
      .map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(","))
      .join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "parkwatch-traffic-delay-exposure-scenario.csv";
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section className="impact-layout">
      <div className="panel impact-intro">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Traffic impact</p>
            <h2>Estimated traffic-delay exposure</h2>
          </div>
          <button className="export-button" type="button" onClick={exportImpactCsv}>
            Export CSV
          </button>
        </div>
        <p>
          This scenario combines GraphSAGE pressure, official violation severity, and
          Mappls traffic-versus-road-baseline ETA to estimate parking-attributed delay
          exposure for selected enforcement hotspots.
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
        <div className="planner-source-row">
          <span className="pill">{delayExposure?.source ?? "Delay exposure planning"}</span>
          {delayStatus === "loading" && <span className="pill">Estimating delay...</span>}
          {delayExposure?.cached && <span className="pill">Cached</span>}
          {delayExposure?.fallback_reason && <span className="pill">{delayExposure.fallback_reason}</span>}
        </div>
      </div>

      <div className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Top route candidates</p>
            <h2>Delay exposure summary</h2>
          </div>
        </div>
        <div className="impact-metrics">
          <span>
            <strong>{Math.round(delayExposure?.total_delay_exposure_minutes ?? 0).toLocaleString("en-IN")}</strong>
            Est. delay exposure min
          </span>
          <span>
            <strong>{Math.round(delayExposure?.total_reduced_delay_exposure_minutes ?? 0).toLocaleString("en-IN")}</strong>
            Scenario-reduced min
          </span>
          <span>
            <strong>{formatPct(filteredReductionPct)}</strong>
            Obstruction proxy share
          </span>
        </div>
        <p className="muted">
          Delay exposure is a planning heuristic: Mappls/OSM road timing plus parking
          pressure and obstruction severity. It is not a measured public delay reduction.
        </p>
      </div>

      <div className="panel impact-table-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Ranked traffic-delay exposure</p>
            <h2>Where targeted enforcement may matter most</h2>
          </div>
          <span className="pill">{delayItems.length} shown</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Location</th>
                <th>Station</th>
                <th>Predicted</th>
                <th>Traffic ETA</th>
                <th>Baseline ETA</th>
                <th>Traffic delay</th>
                <th>Delay exposure</th>
                <th>Scenario reduced</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {delayItems.map((item) => (
                <tr key={item.grid_cell_id}>
                  <td>
                    <strong className="location-name">{item.location}</strong>
                    <span className="cell-meta">{item.grid_cell_id}</span>
                  </td>
                  <td>{item.station ?? "Unknown"}</td>
                  <td>{item.predicted_violations.toFixed(1)}</td>
                  <td>{item.traffic_eta_minutes?.toFixed(1) ?? "n/a"}</td>
                  <td>{item.freeflow_eta_minutes?.toFixed(1) ?? "n/a"}</td>
                  <td>{item.traffic_delay_minutes.toFixed(1)}</td>
                  <td>{Math.round(item.estimated_delay_exposure_minutes).toLocaleString("en-IN")}</td>
                  <td>{Math.round(item.reduced_delay_exposure_minutes).toLocaleString("en-IN")}</td>
                  <td>{item.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
