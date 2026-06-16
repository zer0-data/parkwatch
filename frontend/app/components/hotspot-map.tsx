"use client";

import { useState, useRef, useCallback, type WheelEvent, type PointerEvent } from "react";
import type { Hotspot } from "../lib/types";

type HotspotMapProps = {
  hotspots: Hotspot[];
  selectedCellId: string | null;
  onSelect: (cellId: string) => void;
};

export function HotspotMap({ hotspots, selectedCellId, onSelect }: HotspotMapProps) {
  const [scale, setScale] = useState(1);
  const [translate, setTranslate] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0 });
  const svgRef = useRef<SVGSVGElement>(null);

  const handleWheel = useCallback((e: WheelEvent<SVGSVGElement>) => {
    e.preventDefault();
    const zoomFactor = 0.1;
    const direction = e.deltaY < 0 ? 1 : -1;
    const newScale = Math.min(Math.max(0.5, scale + direction * zoomFactor * scale), 20);
    
    if (svgRef.current) {
      const rect = svgRef.current.getBoundingClientRect();
      const cursorX = e.clientX - rect.left;
      const cursorY = e.clientY - rect.top;
      
      const ratio = newScale / scale;
      const newX = cursorX - (cursorX - translate.x) * ratio;
      const newY = cursorY - (cursorY - translate.y) * ratio;
      
      setScale(newScale);
      setTranslate({ x: newX, y: newY });
    } else {
      setScale(newScale);
    }
  }, [scale, translate]);

  const handlePointerDown = (e: PointerEvent<SVGSVGElement>) => {
    setIsDragging(true);
    dragStart.current = { x: e.clientX - translate.x, y: e.clientY - translate.y };
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const handlePointerMove = (e: PointerEvent<SVGSVGElement>) => {
    if (!isDragging) return;
    setTranslate({
      x: e.clientX - dragStart.current.x,
      y: e.clientY - dragStart.current.y
    });
  };

  const handlePointerUp = (e: PointerEvent<SVGSVGElement>) => {
    setIsDragging(false);
    e.currentTarget.releasePointerCapture(e.pointerId);
  };

  const handleReset = () => {
    setScale(1);
    setTranslate({ x: 0, y: 0 });
  };

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

  const latitudes = hotspots.map((item) => item.latitude);
  const longitudes = hotspots.map((item) => item.longitude);
  const counts = hotspots.map((item) => item.violation_count);
  const minLat = Math.min(...latitudes);
  const maxLat = Math.max(...latitudes);
  const minLon = Math.min(...longitudes);
  const maxLon = Math.max(...longitudes);
  const minCount = Math.min(...counts);
  const maxCount = Math.max(...counts);

  return (
    <section className="panel map-panel" aria-label="Hotspot map area" style={{ position: 'relative' }}>
      <div className="section-heading">
        <div>
          <p className="eyebrow">Spatial view</p>
          <h2>Hotspot scatter view</h2>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <button 
            onClick={handleReset} 
            style={{ 
              background: 'rgba(255,255,255,0.1)', 
              border: '1px solid var(--line)', 
              color: 'var(--ink)', 
              borderRadius: '6px', 
              padding: '6px 12px', 
              cursor: 'pointer', 
              fontSize: '0.8rem',
              fontWeight: 700
            }}
          >
            Reset Map
          </button>
          <span className="pill">{hotspots.length.toLocaleString("en-IN")} grid cells</span>
        </div>
      </div>

      <div className="map-canvas" style={{ touchAction: 'none' }}>
        <div className="map-gridlines" aria-hidden="true" />
        <svg 
          ref={svgRef}
          className="scatter-svg" 
          role="img" 
          aria-label="Hotspot grid cells by latitude and longitude"
          onWheel={handleWheel}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
          style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
        >
          <g transform={`translate(${translate.x}, ${translate.y}) scale(${scale})`}>
            {hotspots.map((hotspot) => {
              const cx = normalize(hotspot.longitude, minLon, maxLon);
              const cy = 100 - normalize(hotspot.latitude, minLat, maxLat);
              const selected = hotspot.grid_cell_id === selectedCellId;
              
              const visualRadius =
                4 + normalize(hotspot.violation_count, minCount, maxCount) * 12;
              const radius = visualRadius / scale;

              return (
                <g key={hotspot.grid_cell_id} 
                   className={`scatter-point ${selected ? "selected" : ""}`}
                   onClick={() => onSelect(hotspot.grid_cell_id)}
                   style={{ cursor: 'pointer' }}
                >
                  <circle
                    cx={`${cx}%`}
                    cy={`${cy}%`}
                    r={radius}
                    fill={riskColor(hotspot.obstruction_risk_score)}
                    opacity={selected ? 1 : 0.8}
                    stroke={selected ? "#fff" : "rgba(255,255,255,0.5)"}
                    strokeWidth={(selected ? 2 : 1) / scale}
                  >
                    <title>
                      {`${hotspot.grid_cell_id}: ${hotspot.obstruction_risk_score} score, ${hotspot.violation_count} violations`}
                    </title>
                  </circle>
                  <text
                    x={`${cx}%`}
                    y={`${cy}%`}
                    dy={(radius + 12 / scale)}
                    textAnchor="middle"
                    fill="var(--ink)"
                    fontSize={`${11 / scale}px`}
                    fontWeight="800"
                    pointerEvents="none"
                    style={{ textShadow: '0 2px 4px rgba(0,0,0,0.9)' }}
                  >
                    {hotspot.violation_count}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>
      </div>

      <div className="map-legend">
        <span>Lower score</span>
        <span className="legend-line" />
        <span>Higher score</span>
        <span className="size-note" style={{ marginLeft: 'auto' }}>Size = violation count. Drag to pan, scroll to zoom.</span>
      </div>
    </section>
  );
}

function normalize(value: number, minimum: number, maximum: number) {
  if (maximum === minimum) {
    return 50;
  }
  return ((value - minimum) / (maximum - minimum)) * 100;
}

function riskColor(score: number) {
  if (score >= 70) return "var(--coral)";
  if (score >= 55) return "var(--amber)";
  if (score >= 35) return "var(--teal)";
  return "var(--blue-dark)";
}
