"use client";

import React, { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { Hotspot } from "../lib/types";

type HotspotMapProps = {
  hotspots: Hotspot[];
  selectedCellId: string | null;
  onSelect: (cellId: string) => void;
};

const BENGALURU_CENTER: [number, number] = [12.9716, 77.5946];
const ZOOM_LEVEL = 12;
const MAX_POINTS = 500; // Limit points shown

export function HotspotMap({ hotspots, selectedCellId, onSelect }: HotspotMapProps) {
  const mapRef = useRef<L.Map | null>(null);
  const markersGroupRef = useRef<L.LayerGroup | null>(null);
  const markersMapRef = useRef<Map<string, L.CircleMarker>>(new Map());

  // Initialize map
  useEffect(() => {
    if (!mapRef.current) {
      delete (L.Icon.Default.prototype as any)._getIconUrl;
      L.Icon.Default.mergeOptions({
        iconRetinaUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png",
        iconUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png",
        shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
      });

      const map = L.map("scatter-map").setView(BENGALURU_CENTER, ZOOM_LEVEL);

      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19,
      }).addTo(map);

      mapRef.current = map;
      markersGroupRef.current = L.layerGroup().addTo(map);
    }
  }, []);

  // Update points
  useEffect(() => {
    if (!mapRef.current || !markersGroupRef.current) return;

    markersGroupRef.current.clearLayers();
    markersMapRef.current.clear();

    const displayHotspots = hotspots.slice(0, MAX_POINTS);

    const counts = displayHotspots.map((h) => h.violation_count);
    const minCount = counts.length ? Math.min(...counts) : 0;
    const maxCount = counts.length ? Math.max(...counts) : 1;

    displayHotspots.forEach((hotspot) => {
      // Normalize violation count for visual radius
      const normalizedCount = maxCount === minCount ? 0.5 : (hotspot.violation_count - minCount) / (maxCount - minCount);
      const radius = 4 + normalizedCount * 12;

      const riskScore = hotspot.obstruction_risk_score;
      let color = "#1e3a8a"; // Blue-dark
      let fillColor = "#3b82f6";

      if (riskScore >= 70) {
        color = "#be123c"; // Coral/Red
        fillColor = "#f43f5e";
      } else if (riskScore >= 55) {
        color = "#b45309"; // Amber
        fillColor = "#f59e0b";
      } else if (riskScore >= 35) {
        color = "#0f766e"; // Teal
        fillColor = "#14b8a6";
      }

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
          <strong>${hotspot.grid_cell_id}</strong>
          <p>Risk: ${riskScore.toFixed(1)}</p>
          <p>Violations: ${hotspot.violation_count}</p>
        </div>
      `);

      marker.on("click", () => {
        onSelect(hotspot.grid_cell_id);
      });

      markersMapRef.current.set(hotspot.grid_cell_id, marker);
    });
  }, [hotspots, onSelect]);

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
          const riskScore = hotspot.obstruction_risk_score;
          let color = "#1e3a8a";
          if (riskScore >= 70) color = "#be123c";
          else if (riskScore >= 55) color = "#b45309";
          else if (riskScore >= 35) color = "#0f766e";

          marker.setStyle({
            weight: 1,
            opacity: 0.8,
            fillOpacity: 0.7,
            color,
          });
        }
      }
    });
  }, [selectedCellId, hotspots]);

  if (!hotspots.length) {
    return (
      <section className="panel map-panel" aria-label="Hotspot map area">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Spatial view</p>
            <h2>Hotspot scatter view</h2>
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
          <h2>Hotspot scatter view</h2>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <span className="pill">
            Showing {Math.min(hotspots.length, MAX_POINTS).toLocaleString("en-IN")} of {hotspots.length.toLocaleString("en-IN")} cells
          </span>
        </div>
      </div>

      <div style={{ flex: 1, position: 'relative', minHeight: '500px', width: '100%', borderRadius: '8px', overflow: 'hidden', border: '1px solid var(--line)' }}>
        <div id="scatter-map" style={{ position: 'absolute', top: 0, bottom: 0, left: 0, right: 0, width: '100%', height: '100%' }} />
      </div>

      <div className="map-legend" style={{ marginTop: '16px', display: 'flex', alignItems: 'center', gap: '12px' }}>
        <span>Lower score</span>
        <span className="legend-line" style={{ background: 'linear-gradient(to right, #3b82f6, #14b8a6, #f59e0b, #f43f5e)', height: '8px', width: '100px', borderRadius: '4px' }} />
        <span>Higher score</span>
        <span className="size-note" style={{ marginLeft: 'auto', fontSize: '0.85rem', color: 'var(--text-muted)' }}>
          Size = violation count. Map limited to top {MAX_POINTS} for performance.
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
