"use client";

import React, { useEffect, useState, useRef } from "react";
// @ts-ignore
import { mappls, mappls_plugin } from "mappls-web-maps";
import type { Hotspot } from "../lib/types";

type InteractiveMapProps = {
  hotspots: Hotspot[];
  selectedCellId: string | null;
  onSelect: (cellId: string) => void;
};

const BENGALURU_CENTER = [12.9716, 77.5946];
const ZOOM_LEVEL = 12;

export function InteractiveMap({
  hotspots,
  selectedCellId,
  onSelect,
}: InteractiveMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapObjectRef = useRef<any>(null);
  const mapplsRef = useRef<any>(null);
  const markersRef = useRef<Map<string, any>>(new Map());
  const [mapLoaded, setMapLoaded] = useState(false);

  // Initialize map
  useEffect(() => {
    if (typeof window === "undefined" || !containerRef.current) return;
    if (mapplsRef.current) return; // already initialized

    const token = process.env.NEXT_PUBLIC_MAPPLS_TOKEN || "";
    mapplsRef.current = new mappls();

    mapplsRef.current.initialize(token, { map: true }, () => {
      if (!mapObjectRef.current) {
        mapObjectRef.current = mapplsRef.current.Map({
          id: "map",
          center: BENGALURU_CENTER,
          zoom: ZOOM_LEVEL,
          traffic: true,
        });

        setTimeout(() => setMapLoaded(true), 500);
      }
    });

    return () => {
      if (markersRef.current) {
        markersRef.current.forEach((marker) => {
          try {
            mapplsRef.current.removeLayer({ map: mapObjectRef.current, layer: marker });
          } catch (e) {}
        });
        markersRef.current.clear();
      }
    };
  }, []);

  // Update markers when hotspots change
  useEffect(() => {
    if (!mapLoaded || !mapObjectRef.current || !mapplsRef.current) return;

    // Clear existing markers
    markersRef.current.forEach((marker) => {
      try {
        mapplsRef.current.removeLayer({ map: mapObjectRef.current, layer: marker });
      } catch(e) {}
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
      const circleRadius = radius * 20; // scale for map view

      const marker = new mapplsRef.current.Circle({
        map: mapObjectRef.current,
        center: { lat: hotspot.latitude, lng: hotspot.longitude },
        radius: circleRadius,
        fillColor,
        fillOpacity: 0.7,
        strokeColor: color,
        strokeOpacity: 0.8,
        strokeWeight: 2,
        popupHtml: `
          <div class="popup-content">
            <strong>${hotspot.grid_cell_id}</strong>
            <p>Risk: ${riskScore.toFixed(1)}</p>
            <p>Station: ${hotspot.dominant_station || "N/A"}</p>
            <p>Count: ${hotspot.violation_count}</p>
          </div>
        `
      });

      // Click handler
      marker.addListener("click", () => {
        onSelect(hotspot.grid_cell_id);
      });

      markersRef.current.set(hotspot.grid_cell_id, marker);
    });
  }, [hotspots, onSelect, mapLoaded]);

  // Highlight selected marker
  useEffect(() => {
    if (!mapLoaded || !mapObjectRef.current || !mapplsRef.current) return;

    markersRef.current.forEach((marker, cellId) => {
      if (cellId === selectedCellId) {
        try {
          if (marker.setOptions) {
            marker.setOptions({
              strokeWeight: 4,
              fillOpacity: 0.9,
            });
          }
        } catch(e) {}
      } else {
        try {
          if (marker.setOptions) {
            marker.setOptions({
              strokeWeight: 2,
              fillOpacity: 0.7,
            });
          }
        } catch(e) {}
      }
    });
  }, [selectedCellId, mapLoaded]);

  return (
    <div className="interactive-map-container">
      <div id="map" ref={containerRef} className="mappls-map" />
      <style jsx>{`
        .interactive-map-container {
          width: 100%;
          border-radius: 8px;
          overflow: hidden;
          border: 1px solid #e2e8f0;
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        }

        .mappls-map {
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
      `}</style>
    </div>
  );
}
