"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { Hotspot } from "../lib/types";

type HotspotMapProps = {
  hotspots: Hotspot[];
  selectedCellId: string | null;
  onSelect: (cellId: string) => void;
  mode?: "scatter" | "interactive";
};

const BENGALURU_CENTER: [number, number] = [12.9716, 77.5946];
const ZOOM_LEVEL = 12;
const TOP_N_OPTIONS = [250, 500, 750] as const;
type ColorMetric = "risk" | "priority" | "confidence";
type SizeMetric = "violations" | "risk" | "priority";

export function HotspotMap({ hotspots, selectedCellId, onSelect, mode = "scatter" }: HotspotMapProps) {
  const mapRef = useRef<L.Map | null>(null);
  const markersGroupRef = useRef<L.LayerGroup | null>(null);
  const markersMapRef = useRef<Map<string, L.CircleMarker>>(new Map());
  const mapIdRef = useRef(`hotspot-map-${mode}-${Math.random().toString(36).slice(2)}`);
  const [colorMetric, setColorMetric] = useState<ColorMetric>("risk");
  const [sizeMetric, setSizeMetric] = useState<SizeMetric>(mode === "interactive" ? "priority" : "violations");
  const [topN, setTopN] = useState<(typeof TOP_N_OPTIONS)[number]>(500);

  const displayHotspots = useMemo(() => hotspots.slice(0, topN), [hotspots, topN]);
  const mapTitle = mode === "interactive" ? "Interactive hotspot explorer" : "Hotspot scatter view";
  const mapSubtitle =
    mode === "interactive"
      ? "Click a zone to sync the detail panel. Controls tune the operational signal shown on the map."
      : "Bubble size and color summarize filtered enforcement pressure across Bengaluru.";

  // Initialize map
  useEffect(() => {
    if (!mapRef.current) {
      delete (L.Icon.Default.prototype as any)._getIconUrl;
      L.Icon.Default.mergeOptions({
        iconRetinaUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png",
        iconUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png",
        shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
      });

      const map = L.map(mapIdRef.current).setView(BENGALURU_CENTER, ZOOM_LEVEL);

      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19,
      }).addTo(map);

      mapRef.current = map;
      markersGroupRef.current = L.layerGroup().addTo(map);
    }

    return () => {
      mapRef.current?.remove();
      mapRef.current = null;
      markersGroupRef.current = null;
      markersMapRef.current.clear();
    };
  }, []);

  // Update points
  useEffect(() => {
    if (!mapRef.current || !markersGroupRef.current) return;

    markersGroupRef.current.clearLayers();
    markersMapRef.current.clear();

    const counts = displayHotspots.map((h) => metricValue(h, sizeMetric));
    const minCount = counts.length ? Math.min(...counts) : 0;
    const maxCount = counts.length ? Math.max(...counts) : 1;

    displayHotspots.forEach((hotspot) => {
      // Normalize violation count for visual radius
      const value = metricValue(hotspot, sizeMetric);
      const normalizedCount = maxCount === minCount ? 0.5 : (value - minCount) / (maxCount - minCount);
      const radius = 5 + normalizedCount * (mode === "interactive" ? 14 : 11);
      const { color, fillColor } = markerColors(hotspot, colorMetric);

      const marker = L.circleMarker([hotspot.latitude, hotspot.longitude], {
        radius,
        fillColor,
        color,
        weight: 1,
        opacity: 0.8,
        fillOpacity: 0.7,
      }).addTo(markersGroupRef.current!);

      marker.bindPopup(`
        <div class="popup-content">
          <strong>${escapeHtml(hotspot.representative_location ?? hotspot.grid_cell_id)}</strong>
          <p>Risk: ${hotspot.obstruction_risk_score.toFixed(1)} | Priority: ${hotspot.enforcement_priority_score.toFixed(1)}</p>
          <p>Violations: ${hotspot.violation_count}</p>
          <p>${escapeHtml(hotspot.dominant_station ?? "Unknown station")}</p>
        </div>
      `);
      marker.bindTooltip(
        `${escapeHtml(hotspot.grid_cell_id)}<br/>Risk ${hotspot.obstruction_risk_score.toFixed(1)} | Priority ${hotspot.enforcement_priority_score.toFixed(1)}`,
        { direction: "top", offset: [0, -12] }
      );

      marker.on("click", () => {
        onSelect(hotspot.grid_cell_id);
      });

      markersMapRef.current.set(hotspot.grid_cell_id, marker);
    });

    if (displayHotspots.length > 1) {
      const bounds = L.latLngBounds(displayHotspots.map((item) => [item.latitude, item.longitude]));
      mapRef.current.fitBounds(bounds, { padding: [28, 28], maxZoom: 14 });
    }
  }, [colorMetric, displayHotspots, mode, onSelect, sizeMetric]);

  // Highlight selected marker
  useEffect(() => {
    markersMapRef.current.forEach((marker, cellId) => {
      if (cellId === selectedCellId) {
        marker.setStyle({
          weight: 3,
          opacity: 1,
          fillOpacity: 0.9,
          color: "#000",
        });
        marker.openPopup();
      } else {
        const hotspot = hotspots.find(h => h.grid_cell_id === cellId);
        if (hotspot) {
          const { color } = markerColors(hotspot, colorMetric);

          marker.setStyle({
            weight: 1,
            opacity: 0.8,
            fillOpacity: 0.7,
            color,
          });
        }
      }
    });
  }, [selectedCellId, hotspots, colorMetric]);

  if (!hotspots.length) {
    return (
      <section className="panel map-panel" aria-label="Hotspot map area">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Spatial view</p>
            <h2>{mapTitle}</h2>
          </div>
        </div>
        <div className="empty-state">No hotspots match the current filters.</div>
      </section>
    );
  }

  return (
    <section className="panel map-panel" aria-label="Hotspot map area" style={{ display: "flex", flexDirection: "column" }}>
      <div className="section-heading">
        <div>
          <p className="eyebrow">Spatial view</p>
            <h2>{mapTitle}</h2>
            <span className="cell-meta">{mapSubtitle}</span>
          </div>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <span className="pill">
            Showing {displayHotspots.length.toLocaleString("en-IN")} of {hotspots.length.toLocaleString("en-IN")} cells
          </span>
        </div>
      </div>

      <div className="map-controls" aria-label="Map display controls">
        <label>
          Color
          <select value={colorMetric} onChange={(event) => setColorMetric(event.target.value as ColorMetric)}>
            <option value="risk">Risk</option>
            <option value="priority">Priority</option>
            <option value="confidence">Confidence</option>
          </select>
        </label>
        <label>
          Size
          <select value={sizeMetric} onChange={(event) => setSizeMetric(event.target.value as SizeMetric)}>
            <option value="violations">Violations</option>
            <option value="risk">Risk</option>
            <option value="priority">Priority</option>
          </select>
        </label>
        <label>
          Points
          <select value={topN} onChange={(event) => setTopN(Number(event.target.value) as typeof topN)}>
            {TOP_N_OPTIONS.map((option) => (
              <option key={option} value={option}>{option}</option>
            ))}
          </select>
        </label>
      </div>

      <div style={{ flex: 1, position: 'relative', minHeight: '500px', width: '100%', borderRadius: '8px', overflow: 'hidden', border: '1px solid var(--line)' }}>
        <div id={mapIdRef.current} style={{ position: 'absolute', top: 0, bottom: 0, left: 0, right: 0, width: '100%', height: '100%' }} />
      </div>

      <div className="map-legend" style={{ marginTop: '16px', display: 'flex', alignItems: 'center', gap: '12px' }}>
        <span>Lower score</span>
        <span className="legend-line" style={{ background: 'linear-gradient(to right, #3b82f6, #14b8a6, #f59e0b, #f43f5e)', height: '8px', width: '100px', borderRadius: '4px' }} />
        <span>Higher score</span>
        <span className="size-note" style={{ marginLeft: 'auto', fontSize: '0.85rem', color: 'var(--text-muted)' }}>
          Color = {colorMetric}. Size = {sizeMetric}. Map limited for performance.
        </span>
      </div>

      <style jsx>{`
        :global(.popup-content) {
          font-size: 13px;
        }
        :global(.popup-content strong) {
          display: block;
          margin-bottom: 4px;
          color: #1e293b;
        }
        :global(.popup-content p) {
          margin: 2px 0;
          color: #475569;
        }
      `}</style>
    </section>
  );
}

function metricValue(hotspot: Hotspot, metric: SizeMetric) {
  if (metric === "risk") return hotspot.obstruction_risk_score;
  if (metric === "priority") return hotspot.enforcement_priority_score;
  return hotspot.violation_count;
}

function markerColors(hotspot: Hotspot, metric: ColorMetric) {
  if (metric === "confidence") {
    if (hotspot.confidence === "High") return { color: "#0f766e", fillColor: "#14b8a6" };
    if (hotspot.confidence === "Medium") return { color: "#b45309", fillColor: "#f59e0b" };
    return { color: "#be123c", fillColor: "#f43f5e" };
  }
  const score = metric === "priority" ? hotspot.enforcement_priority_score : hotspot.obstruction_risk_score;
  if (score >= 70) return { color: "#be123c", fillColor: "#f43f5e" };
  if (score >= 55) return { color: "#b45309", fillColor: "#f59e0b" };
  if (score >= 35) return { color: "#0f766e", fillColor: "#14b8a6" };
  return { color: "#1e3a8a", fillColor: "#3b82f6" };
}

function escapeHtml(value: string) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
