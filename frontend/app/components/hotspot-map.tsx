"use client";

import React, { useEffect, useRef, useState } from "react";
// @ts-ignore
import { mappls, mappls_plugin } from "mappls-web-maps";
import type { Hotspot } from "../lib/types";

type HotspotMapProps = {
  hotspots: Hotspot[];
  selectedCellId: string | null;
  onSelect: (cellId: string) => void;
};

const BENGALURU_CENTER = [12.9716, 77.5946];
const ZOOM_LEVEL = 12;
const MAX_POINTS = 500; // Limit points shown

export function HotspotMap({ hotspots, selectedCellId, onSelect }: HotspotMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapObjectRef = useRef<any>(null);
  const mapplsRef = useRef<any>(null);
  const markersMapRef = useRef<Map<string, any>>(new Map());
  const [mapLoaded, setMapLoaded] = useState(false);

  // Initialize map
  useEffect(() => {
    if (typeof window === "undefined" || !containerRef.current) return;
    if (mapplsRef.current) return; // already initialized

    const token = process.env.NEXT_PUBLIC_MAPPLS_TOKEN || "";
    mapplsRef.current = new mappls();

    mapplsRef.current.initialize(token, { map: true }, () => {
      // Map API initialized
      if (!mapObjectRef.current) {
        mapObjectRef.current = mapplsRef.current.Map({
          id: "scatter-map",
          center: BENGALURU_CENTER,
          zoom: ZOOM_LEVEL,
          traffic: true,
        });

        // Add a small delay to ensure the map is ready for drawing
        setTimeout(() => setMapLoaded(true), 500);
      }
    });

    return () => {
      // Cleanup map logic if necessary, though Mappls doesn't always need explicit destroy
      // Just clear our refs
      if (markersMapRef.current) {
        markersMapRef.current.forEach((marker) => {
          try {
            mapplsRef.current.removeLayer({ map: mapObjectRef.current, layer: marker });
          } catch (e) {}
        });
        markersMapRef.current.clear();
      }
    };
  }, []);

  // Update points
  useEffect(() => {
    if (!mapLoaded || !mapObjectRef.current || !mapplsRef.current) return;

    // Clear existing markers
    markersMapRef.current.forEach((marker) => {
      mapplsRef.current.removeLayer({ map: mapObjectRef.current, layer: marker });
    });
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

      // Draw using mappls.Circle
      // Note: Mappls radius is typically in meters on the map. 
      // To simulate screen pixel radius, we multiply by a factor depending on zoom, 
      // but a fixed radius works as a basic implementation.
      const circleRadius = radius * 15; // Rough approximation for zoom 12

      const marker = new mapplsRef.current.Circle({
        map: mapObjectRef.current,
        center: { lat: hotspot.latitude, lng: hotspot.longitude },
        radius: circleRadius,
        fillColor,
        fillOpacity: 0.7,
        strokeColor: color,
        strokeOpacity: 0.8,
        strokeWeight: 1,
        popupHtml: `
          <div class="popup-content">
            <strong>${hotspot.grid_cell_id}</strong>
            <p>Risk: ${riskScore.toFixed(1)}</p>
            <p>Violations: ${hotspot.violation_count}</p>
          </div>
        `
      });

      marker.addListener("click", () => {
        onSelect(hotspot.grid_cell_id);
      });

      markersMapRef.current.set(hotspot.grid_cell_id, marker);
    });
  }, [hotspots, onSelect, mapLoaded]);

  // Highlight selected marker
  useEffect(() => {
    if (!mapLoaded || !mapObjectRef.current || !mapplsRef.current) return;

    markersMapRef.current.forEach((marker, cellId) => {
      if (cellId === selectedCellId) {
        // Unfortunately, dynamic style updates in mappls-web-maps often require re-creating the circle
        // or using setOptions if available. For simplicity, we just use popup here.
        // Try opening the popup if supported by the SDK, or reposition map.
        // Some Mappls circles support setOptions:
        try {
           if (marker.setOptions) {
             marker.setOptions({
               strokeWeight: 3,
               strokeColor: "#000",
               fillOpacity: 0.9
             });
           }
        } catch(e) {}
      } else {
        const hotspot = hotspots.find(h => h.grid_cell_id === cellId);
        if (hotspot) {
          const riskScore = hotspot.obstruction_risk_score;
          let color = "#1e3a8a";
          if (riskScore >= 70) color = "#be123c";
          else if (riskScore >= 55) color = "#b45309";
          else if (riskScore >= 35) color = "#0f766e";

          try {
            if (marker.setOptions) {
               marker.setOptions({
                 strokeWeight: 1,
                 strokeColor: color,
                 fillOpacity: 0.7
               });
            }
          } catch(e) {}
        }
      }
    });
  }, [selectedCellId, hotspots, mapLoaded]);

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
        <div id="scatter-map" ref={containerRef} style={{ position: 'absolute', top: 0, bottom: 0, left: 0, right: 0, width: '100%', height: '100%' }} />
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
