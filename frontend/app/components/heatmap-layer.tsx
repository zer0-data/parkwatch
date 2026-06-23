"use client";

import React, { useEffect, useRef, useState } from "react";
import type { Hotspot } from "../lib/types";

type HeatmapLayerProps = {
  hotspots: Hotspot[];
  selectedCellId: string | null;
  onSelect?: (cellId: string) => void;
  title?: string;
};

const BENGALURU_BOUNDS = {
  lat_min: 12.8,
  lat_max: 13.2,
  lon_min: 77.4,
  lon_max: 77.8,
};

const CANVAS_WIDTH = 700;
const CANVAS_HEIGHT = 500;
const PADDING = 50;
const MAP_WIDTH = CANVAS_WIDTH - PADDING * 2;
const MAP_HEIGHT = CANVAS_HEIGHT - PADDING * 2;

export function HeatmapLayer({
  hotspots,
  selectedCellId,
  onSelect,
  title = "Risk Heatmap",
}: HeatmapLayerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hoveredHotspot, setHoveredHotspot] = useState<Hotspot | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const pixelRatio = window.devicePixelRatio || 1;
    canvas.width = CANVAS_WIDTH * pixelRatio;
    canvas.height = CANVAS_HEIGHT * pixelRatio;
    canvas.style.width = `${CANVAS_WIDTH}px`;
    canvas.style.height = `${CANVAS_HEIGHT}px`;
    ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);

    ctx.fillStyle = "#06111f";
    ctx.fillRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
    ctx.fillStyle = "rgba(15, 23, 42, 0.78)";
    ctx.fillRect(PADDING, PADDING, MAP_WIDTH, MAP_HEIGHT);

    const cellSize = 20;
    const gridCols = Math.ceil(MAP_WIDTH / cellSize);
    const gridRows = Math.ceil(MAP_HEIGHT / cellSize);
    const grid: number[][] = Array(gridRows)
      .fill(null)
      .map(() => Array(gridCols).fill(0));

    hotspots.forEach((hotspot) => {
      const point = projectPoint(hotspot.latitude, hotspot.longitude);
      if (
        point.x >= PADDING &&
        point.x <= PADDING + MAP_WIDTH &&
        point.y >= PADDING &&
        point.y <= PADDING + MAP_HEIGHT
      ) {
        const col = Math.floor((point.x - PADDING) / cellSize);
        const row = Math.floor((point.y - PADDING) / cellSize);
        if (col >= 0 && col < gridCols && row >= 0 && row < gridRows) {
          grid[row][col] = Math.max(grid[row][col], hotspot.obstruction_risk_score);
        }
      }
    });

    for (let row = 0; row < gridRows; row++) {
      for (let col = 0; col < gridCols; col++) {
        const risk = grid[row][col];
        if (risk === 0) continue;

        const alpha = risk / 100;
        let color = "rgba(20, 184, 166";
        if (risk > 70) color = "rgba(244, 63, 94";
        else if (risk > 50) color = "rgba(245, 158, 11";

        ctx.fillStyle = `${color}, ${0.2 + alpha * 0.58})`;
        ctx.fillRect(PADDING + col * cellSize, PADDING + row * cellSize, cellSize, cellSize);
      }
    }

    ctx.strokeStyle = "rgba(148, 163, 184, 0.42)";
    ctx.lineWidth = 1;
    ctx.strokeRect(PADDING, PADDING, MAP_WIDTH, MAP_HEIGHT);

    const selected = hotspots.find((item) => item.grid_cell_id === selectedCellId);
    if (selected) {
      const point = projectPoint(selected.latitude, selected.longitude);
      ctx.beginPath();
      ctx.arc(point.x, point.y, 11, 0, Math.PI * 2);
      ctx.strokeStyle = "#f8fafc";
      ctx.lineWidth = 3;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(point.x, point.y, 16, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(45, 212, 191, 0.65)";
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    ctx.fillStyle = "#94a3b8";
    ctx.font = "12px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("77.4E", PADDING + 20, CANVAS_HEIGHT - 15);
    ctx.fillText("77.8E", PADDING + MAP_WIDTH - 20, CANVAS_HEIGHT - 15);
    ctx.textAlign = "right";
    ctx.fillText("12.8N", PADDING - 15, PADDING + MAP_HEIGHT + 5);
    ctx.fillText("13.2N", PADDING - 15, PADDING + 5);

    drawLegend(ctx);
  }, [hotspots, selectedCellId]);

  const handlePointer = (event: React.PointerEvent<HTMLCanvasElement>) => {
    setHoveredHotspot(nearestHotspot(event, hotspots));
  };

  const handleClick = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const hotspot = nearestHotspot(event, hotspots);
    if (hotspot) onSelect?.(hotspot.grid_cell_id);
  };

  return (
    <section className="panel heatmap-layer">
      <h3>{title}</h3>
      <p className="heatmap-subtitle">
        Color intensity shows estimated obstruction-risk pressure across zones. Click a zone to inspect it.
      </p>
      <div className="planner-source-row">
        <span className="pill">{hotspots.length.toLocaleString("en-IN")} filtered zones</span>
        {hoveredHotspot && (
          <span className="pill">
            {hoveredHotspot.grid_cell_id}: risk {hoveredHotspot.obstruction_risk_score.toFixed(1)}
          </span>
        )}
      </div>
      <div className="heatmap-wrapper">
        <canvas
          ref={canvasRef}
          className="heatmap-canvas"
          onPointerMove={handlePointer}
          onPointerLeave={() => setHoveredHotspot(null)}
          onClick={handleClick}
        />
      </div>

      <style jsx>{`
        .heatmap-layer {
          padding: 1.5rem;
        }

        .heatmap-layer h3 {
          margin: 0 0 0.5rem 0;
          font-size: 1.1rem;
          color: var(--text);
        }

        .heatmap-subtitle {
          margin: 0 0 1rem 0;
          font-size: 0.85rem;
          color: var(--text-muted);
        }

        .heatmap-wrapper {
          background: rgba(2, 6, 23, 0.45);
          border: 1px solid var(--line);
          border-radius: 8px;
          overflow: hidden;
          display: flex;
          justify-content: center;
          align-items: center;
          padding: 1rem;
        }

        .heatmap-canvas {
          max-width: 100%;
          height: auto;
          display: block;
          cursor: crosshair;
        }
      `}</style>
    </section>
  );
}

function drawLegend(ctx: CanvasRenderingContext2D) {
  const legendX = CANVAS_WIDTH - 200;
  const legendY = 20;
  ctx.fillStyle = "rgba(2, 6, 23, 0.86)";
  ctx.fillRect(legendX - 10, legendY, 190, 110);
  ctx.strokeStyle = "rgba(148, 163, 184, 0.32)";
  ctx.lineWidth = 1;
  ctx.strokeRect(legendX - 10, legendY, 190, 110);

  ctx.fillStyle = "#e2e8f0";
  ctx.font = "bold 12px sans-serif";
  ctx.textAlign = "left";
  ctx.fillText("Risk level", legendX, legendY + 18);

  [
    { color: "#14b8a6", label: "Low (0-50)" },
    { color: "#f59e0b", label: "Medium (50-70)" },
    { color: "#f43f5e", label: "High (70+)" },
  ].forEach((item, index) => {
    const y = legendY + 35 + index * 22;
    ctx.fillStyle = item.color;
    ctx.fillRect(legendX + 5, y - 8, 12, 12);
    ctx.fillStyle = "#cbd5e1";
    ctx.font = "11px sans-serif";
    ctx.fillText(item.label, legendX + 25, y + 2);
  });
}

function projectPoint(lat: number, lon: number) {
  return {
    x:
      PADDING +
      ((lon - BENGALURU_BOUNDS.lon_min) /
        (BENGALURU_BOUNDS.lon_max - BENGALURU_BOUNDS.lon_min)) *
        MAP_WIDTH,
    y:
      PADDING +
      MAP_HEIGHT -
      ((lat - BENGALURU_BOUNDS.lat_min) /
        (BENGALURU_BOUNDS.lat_max - BENGALURU_BOUNDS.lat_min)) *
        MAP_HEIGHT,
  };
}

function nearestHotspot(event: React.PointerEvent<HTMLCanvasElement>, hotspots: Hotspot[]) {
  const rect = event.currentTarget.getBoundingClientRect();
  const scaleX = CANVAS_WIDTH / rect.width;
  const scaleY = CANVAS_HEIGHT / rect.height;
  const x = (event.clientX - rect.left) * scaleX;
  const y = (event.clientY - rect.top) * scaleY;
  let nearest: Hotspot | null = null;
  let bestDistance = Infinity;
  for (const hotspot of hotspots) {
    const point = projectPoint(hotspot.latitude, hotspot.longitude);
    const distance = Math.hypot(point.x - x, point.y - y);
    if (distance < bestDistance) {
      nearest = hotspot;
      bestDistance = distance;
    }
  }
  return bestDistance <= 24 ? nearest : null;
}
