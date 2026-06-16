import type { ForecastItem, ForecastResponse } from "../lib/types";

type ForecastPanelProps = {
  forecast: ForecastResponse;
};

export function ForecastPanel({ forecast }: ForecastPanelProps) {
  const topItem = forecast.items[0] ?? null;

  return (
    <section className="forecast-layout">
      <div className="panel forecast-intro">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Graph-enhanced forecast</p>
            <h2>Next-week observed violation forecast</h2>
          </div>
          <span className="pill">{forecast.forecast_week ?? "Next week"}</span>
        </div>
        <p>
          This is a forecast of future observed parking violations, not measured
          congestion. The baseline uses recent weekly counts plus graph-neighbor
          activity from nearby hotspot cells.
        </p>
        <div className="forecast-metrics">
          <span>
            <strong>{forecast.holdout.mae?.toFixed(2) ?? "n/a"}</strong>
            Holdout MAE
          </span>
          <span>
            <strong>{forecast.holdout.mape?.toFixed(1) ?? "n/a"}%</strong>
            Holdout MAPE
          </span>
          <span>
            <strong>{forecast.holdout.evaluated_points.toLocaleString("en-IN")}</strong>
            Evaluation points
          </span>
        </div>
      </div>

      <div className="panel forecast-chart-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Historical vs predicted</p>
            <h2>{topItem?.grid_cell_id ?? "No forecast"}</h2>
          </div>
        </div>
        {topItem && <ForecastChart item={topItem} />}
      </div>

      <div className="panel forecast-table-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Top predicted hotspots</p>
            <h2>Predicted count and risk</h2>
          </div>
          <span className="pill">{forecast.items.length} shown</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Cell</th>
                <th>Station</th>
                <th>Predicted count</th>
                <th>Predicted risk</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {forecast.items.slice(0, 25).map((item) => (
                <tr key={item.grid_cell_id}>
                  <td>{item.grid_cell_id}</td>
                  <td>{item.station ?? "Unknown"}</td>
                  <td>{item.predicted_violation_count.toFixed(1)}</td>
                  <td>{item.predicted_obstruction_risk.toFixed(1)}</td>
                  <td>
                    <span className={`confidence ${item.confidence.toLowerCase()}`}>
                      {item.confidence}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function ForecastChart({ item }: { item: ForecastItem }) {
  const points = [
    ...item.historical_weeks.map((week) => ({
      label: week.week,
      value: week.violation_count,
      predicted: false
    })),
    {
      label: item.predicted_week ?? "Predicted",
      value: item.predicted_violation_count,
      predicted: true
    }
  ];
  const maxValue = Math.max(...points.map((point) => point.value), 1);
  const path = points
    .map((point, index) => {
      const x = points.length <= 1 ? 0 : (index / (points.length - 1)) * 420;
      const y = 160 - (point.value / maxValue) * 132;
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");

  return (
    <>
      <svg className="forecast-chart" viewBox="0 0 420 180" role="img" aria-label="Historical versus predicted weekly violations">
        <path d={path} />
        {points.map((point, index) => {
          const x = points.length <= 1 ? 0 : (index / (points.length - 1)) * 420;
          const y = 160 - (point.value / maxValue) * 132;
          return (
            <circle
              key={`${point.label}-${index}`}
              className={point.predicted ? "predicted" : ""}
              cx={x}
              cy={y}
              r={point.predicted ? 6 : 4}
            >
              <title>{`${point.label}: ${point.value.toFixed(1)} violations`}</title>
            </circle>
          );
        })}
      </svg>
      <dl className="forecast-detail-list">
        <div>
          <dt>Predicted count</dt>
          <dd>{item.predicted_violation_count.toFixed(1)}</dd>
        </div>
        <div>
          <dt>Predicted risk</dt>
          <dd>{item.predicted_obstruction_risk.toFixed(1)}</dd>
        </div>
        <div>
          <dt>Station</dt>
          <dd>{item.station ?? "Unknown"}</dd>
        </div>
      </dl>
    </>
  );
}
