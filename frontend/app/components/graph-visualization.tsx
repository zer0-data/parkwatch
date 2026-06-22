"use client";

import React, { useEffect, useRef, useMemo } from "react";
import type { Hotspot, GraphEdge } from "../lib/types";

type GraphVisualizationProps = {
  centerNode: Hotspot;
  neighbors: Hotspot[];
  edges: GraphEdge[];
  title?: string;
};

export function GraphVisualization({
  centerNode,
  neighbors,
  edges,
  title = "Hotspot Network Graph"
}: GraphVisualizationProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Calculate positions for nodes using a simple force-directed layout
  const layout = useMemo(() => {
    const nodes = [
      { id: centerNode.grid_cell_id, x: 0, y: 0, is_center: true, hotspot: centerNode }
    ];

    neighbors.forEach((neighbor, idx) => {
      const angle = (idx / neighbors.length) * Math.PI * 2;
      const radius = 150;
      nodes.push({
        id: neighbor.grid_cell_id,
        x: Math.cos(angle) * radius,
        y: Math.sin(angle) * radius,
        is_center: false,
        hotspot: neighbor
      });
    });

    return { nodes, edges };
  }, [centerNode, neighbors, edges]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const width = canvas.width;
    const height = canvas.height;
    const centerX = width / 2;
    const centerY = height / 2;

    // Clear canvas
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);

    // Draw edges
    ctx.strokeStyle = "#cbd5e1";
    ctx.lineWidth = 1;
    layout.edges.forEach((edge) => {
      const source = layout.nodes.find(n => n.id === edge.source);
      const target = layout.nodes.find(n => n.id === edge.target);

      if (source && target) {
        ctx.beginPath();
        ctx.moveTo(centerX + source.x, centerY + source.y);
        ctx.lineTo(centerX + target.x, centerY + target.y);
        ctx.stroke();
      }
    });

    // Draw nodes
    layout.nodes.forEach((node) => {
      const x = centerX + node.x;
      const y = centerY + node.y;
      const radius = node.is_center ? 20 : 12;

      // Node circle
      if (node.is_center) {
        // Center node gradient
        const gradient = ctx.createRadialGradient(x, y, 0, x, y, radius);
        gradient.addColorStop(0, "#3b82f6");
        gradient.addColorStop(1, "#1e40af");
        ctx.fillStyle = gradient;
      } else {
        // Neighbor node - color by risk score
        const riskScore = node.hotspot.obstruction_risk_score;
        if (riskScore > 70) {
          ctx.fillStyle = "#ef4444";
        } else if (riskScore > 50) {
          ctx.fillStyle = "#f97316";
        } else {
          ctx.fillStyle = "#84cc16";
        }
      }

      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fill();

      // Node border
      ctx.strokeStyle = node.is_center ? "#1e40af" : "#64748b";
      ctx.lineWidth = 2;
      ctx.stroke();

      // Label
      ctx.fillStyle = "#1e293b";
      ctx.font = "11px sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      const label = node.id.split("_").slice(0, 1).join("");
      ctx.fillText(label, x, y);
    });

    // Draw legend
    const legendX = 20;
    const legendY = 20;
    ctx.fillStyle = "rgba(255, 255, 255, 0.9)";
    ctx.fillRect(legendX - 5, legendY - 5, 220, 110);
    ctx.strokeStyle = "#e2e8f0";
    ctx.lineWidth = 1;
    ctx.strokeRect(legendX - 5, legendY - 5, 220, 110);

    ctx.fillStyle = "#1e293b";
    ctx.font = "bold 12px sans-serif";
    ctx.textAlign = "left";
    ctx.fillText("Risk Score Legend", legendX, legendY + 10);

    const legend = [
      { color: "#ef4444", label: "High (>70)" },
      { color: "#f97316", label: "Medium (50-70)" },
      { color: "#84cc16", label: "Low (<50)" }
    ];

    legend.forEach((item, idx) => {
      const y = legendY + 30 + idx * 20;
      ctx.fillStyle = item.color;
      ctx.fillRect(legendX, y - 5, 12, 12);
      ctx.fillStyle = "#475569";
      ctx.font = "11px sans-serif";
      ctx.fillText(item.label, legendX + 18, y + 1);
    });

  }, [layout, centerNode]);

  return (
    <section className="graph-visualization" ref={containerRef}>
      <div className="graph-header">
        <h3>{title}</h3>
        <p className="graph-subtitle">
          Center node in blue: selected hotspot. Connected nodes colored by risk score.
        </p>
      </div>

      <div className="canvas-container">
        <canvas
          ref={canvasRef}
          width={600}
          height={400}
          className="graph-canvas"
        />
      </div>

      <div className="graph-stats">
        <div className="stat">
          <span className="stat-label">Center Cell</span>
          <span className="stat-value">{centerNode.grid_cell_id}</span>
        </div>
        <div className="stat">
          <span className="stat-label">Connected Neighbors</span>
          <span className="stat-value">{neighbors.length}</span>
        </div>
        <div className="stat">
          <span className="stat-label">Graph Edges</span>
          <span className="stat-value">{edges.length}</span>
        </div>
        <div className="stat">
          <span className="stat-label">Avg Neighbor Risk</span>
          <span className="stat-value">
            {neighbors.length > 0 
              ? (neighbors.reduce((sum, n) => sum + n.obstruction_risk_score, 0) / neighbors.length).toFixed(1)
              : "n/a"}
          </span>
        </div>
      </div>

      <style jsx>{`
        .graph-visualization {
          padding: 1.5rem;
          background: white;
          border-radius: 8px;
          border: 1px solid #e2e8f0;
        }

        .graph-header {
          margin-bottom: 1.5rem;
        }

        .graph-header h3 {
          margin: 0 0 0.5rem 0;
          font-size: 1.1rem;
          color: #1e293b;
        }

        .graph-subtitle {
          margin: 0;
          font-size: 0.85rem;
          color: #64748b;
        }

        .canvas-container {
          background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
          border: 1px solid #e2e8f0;
          border-radius: 6px;
          overflow: hidden;
          margin-bottom: 1.5rem;
        }

        .graph-canvas {
          display: block;
          width: 100%;
          height: auto;
        }

        .graph-stats {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 1rem;
        }

        .stat {
          display: flex;
          flex-direction: column;
          gap: 0.25rem;
          padding: 1rem;
          background: #f8fafc;
          border-radius: 6px;
          border: 1px solid #e2e8f0;
        }

        .stat-label {
          font-size: 0.75rem;
          color: #64748b;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          font-weight: 500;
        }

        .stat-value {
          font-size: 1.25rem;
          color: #1e293b;
          font-weight: bold;
        }
      `}</style>
    </section>
  );
}
