import type { Hotspot } from "../lib/types";

type RankedHotspotTableProps = {
  hotspots: Hotspot[];
  selectedCellId: string | null;
  onSelect: (cellId: string) => void;
};

export function RankedHotspotTable({
  hotspots,
  selectedCellId,
  onSelect
}: RankedHotspotTableProps) {
  const topRows = hotspots.slice(0, 40);
  const selectedHotspot =
    hotspots.find((hotspot) => hotspot.grid_cell_id === selectedCellId) ?? null;
  const rows =
    selectedHotspot && !topRows.some((hotspot) => hotspot.grid_cell_id === selectedHotspot.grid_cell_id)
      ? [...topRows, selectedHotspot]
      : topRows;

  return (
    <section className="panel table-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Ranked hotspots</p>
          <h2>Highest Obstruction Risk Score</h2>
        </div>
        <span className="pill">{hotspots.length} shown</span>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Cell</th>
              <th>Station</th>
              <th>Score</th>
              <th>Violations</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((hotspot) => (
              <tr
                key={hotspot.grid_cell_id}
                className={hotspot.grid_cell_id === selectedCellId ? "active-row" : ""}
                onClick={() => onSelect(hotspot.grid_cell_id)}
              >
                <td>{hotspot.grid_cell_id}</td>
                <td>{hotspot.dominant_station ?? "Unknown"}</td>
                <td>{hotspot.obstruction_risk_score.toFixed(1)}</td>
                <td>{hotspot.violation_count.toLocaleString("en-IN")}</td>
                <td>
                  <span className={`confidence ${hotspot.confidence.toLowerCase()}`}>
                    {hotspot.confidence}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
