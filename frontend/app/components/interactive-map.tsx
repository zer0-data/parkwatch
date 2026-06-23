"use client";

import React, { useEffect, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { Hotspot } from "../lib/types";

type InteractiveMapProps = {
  hotspots: Hotspot[];
  selectedCellId: string | null;
  onSelect: (cellId: string) => void;
};

const BENGALURU_CENTER: [number, number] = [12.9716, 77.5946];
const ZOOM_LEVEL = 12;

export function InteractiveMap({
  hotspots,
  selectedCellId,
  onSelect,
}: InteractiveMapProps) {
  const mapRef = React.useRef<L.Map | null>(null);
  const markersRef = React.useRef<Map<string, L.CircleMarker>>(new Map());
  const heatmapLayerRef = React.useRef<L.LayerGroup | null>(null);

  // Initialize map
  useEffect(() => {
    if (!mapRef.current) {
      // Fix for react-leaflet icon issues
      delete (L.Icon.Default.prototype as any)._getIconUrl;
      L.Icon.Default.mergeOptions({
        iconRetinaUrl:
          "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png",
        iconUrl:
          "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png",
        shadowUrl:
          "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
      });

      const map = L.map("map").setView(BENGALURU_CENTER, ZOOM_LEVEL);

      // Use OpenStreetMap (free)
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19,
      }).addTo(map);

      mapRef.current = map;

      // Add heatmap layer group
      heatmapLayerRef.current = L.layerGroup().addTo(map);
    }
  }, []);

  // Update markers when hotspots change
  useEffect(() => {
    if (!mapRef.current || !heatmapLayerRef.current) return;

    // Clear existing markers
    markersRef.current.forEach((marker) => {
      heatmapLayerRef.current?.removeLayer(marker);
    });
    markersRef.current.clear();

    // Add new markers
    hotspots.forEach((hotspot) => {
      const riskScore = hotspot.obstruction_risk_score;

      // Determine color based on risk
      let color = "#22c55e"; // Low - green
      let fillColor = "#86efac";
      if (riskScore > 70) {
        color = "#dc2626"; // High - red
        fillColor = "#fca5a5";
      } else if (riskScore > 50) {
        color = "#f97316"; // Medium - orange
        fillColor = "#fed7aa";
      }

      // Size based on risk
      const radius = 6 + (riskScore / 100) * 10;

      const marker = L.circleMarker(
        [hotspot.latitude, hotspot.longitude],
        {
          radius,
          fillColor,
          color,
          weight: 2,
          opacity: 0.8,
          fillOpacity: 0.7,
        }
      ).addTo(heatmapLayerRef.current!);

      // Popup with hotspot info
      marker.bindPopup(`
        <div class="popup-content">
          <strong>${hotspot.grid_cell_id}</strong>
          <p>Risk: ${riskScore.toFixed(1)}</p>
          <p>Station: ${hotspot.dominant_station || "N/A"}</p>
          <p>Count: ${hotspot.violation_count}</p>
        </div>
      `);

      // Click handler
      marker.on("click", () => {
        onSelect(hotspot.grid_cell_id);
      });

      // Tooltip on hover
      marker.bindTooltip(
        `${hotspot.grid_cell_id}<br/>Risk: ${riskScore.toFixed(1)}`,
        {
          permanent: false,
          direction: "top",
          offset: [0, -20],
        }
      );

      markersRef.current.set(hotspot.grid_cell_id, marker);
    });
  }, [hotspots, onSelect]);

  // Highlight selected marker
  useEffect(() => {
    markersRef.current.forEach((marker, cellId) => {
      if (cellId === selectedCellId) {
        marker.setStyle({
          weight: 4,
          opacity: 1,
          fillOpacity: 0.9,
        });
        marker.openPopup();
      } else {
        marker.setStyle({
          weight: 2,
          opacity: 0.8,
          fillOpacity: 0.7,
        });
      }
    });
  }, [selectedCellId]);

  return (
    <div className="interactive-map-container">
      <div id="map" className="leaflet-map" />
      <style jsx>{`
        .interactive-map-container {
          width: 100%;
          border-radius: 8px;
          overflow: hidden;
          border: 1px solid #e2e8f0;
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        }

        .leaflet-map {
          width: 100%;
          height: 500px;
        }

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

        :global(.leaflet-popup-content-wrapper) {
          border-radius: 6px;
          box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
        }

        :global(.leaflet-popup-tip) {
          background: white;
        }
      `}</style>
    </div>
  );
}
