const datasetFields = [
  "latitude and longitude",
  "location",
  "violation_type",
  "created_datetime",
  "device_id",
  "police_station",
  "junction_name",
  "validation_status"
];

const engines = [
  {
    name: "Hotspot Detection Engine",
    body:
      "The offline pipeline reads the provided violation CSV, converts records into 0.001-degree grid cells, and computes repeated-observation signals including volume, recurrence, severity, junction share, validation, device support, and nearby-cell activity."
  },
  {
    name: "GraphSAGE Forecast Engine",
    body:
      "When forecast_graphsage.json is present, ParkWatch serves the trained GraphSAGE forecast first. The model ranks future observed parking violation pressure while the app keeps the standard forecast as a fallback."
  },
  {
    name: "A* Patrol Planner",
    body:
      "The planner chooses forecast-priority zones, treats them as a coordinate enforcement graph, and runs A* with haversine distance as the heuristic. Leaflet visualizes the stop order, route line, and action list."
  },
  {
    name: "Scenario Impact Engine",
    body:
      "Scenario controls estimate how targeted enforcement choices change modeled obstruction-exposure coverage across selected hotspots and the citywide hotspot set."
  }
];

const scoreSignals = [
  "Obstruction Risk Score combines violation volume, recurrence, severity, junction share, validation, and graph-neighbor influence.",
  "Enforcement Priority adds station-normalized volume, recent activity, trend, peak-hour concentration, confidence, and stability.",
  "Forecast priority highlights next-week observed violation pressure and supports patrol sequencing.",
  "Confidence describes evidence density from repeated records, active days, and device-days."
];

export default function MethodologyPage() {
  return (
    <main className="page-shell methodology-page">
      <section className="hero-band methodology-hero">
        <div>
          <p className="eyebrow">ParkWatch AI engine</p>
          <h1>From parking violations to targeted enforcement plans.</h1>
          <p>
            ParkWatch combines hotspot analytics, graph forecasting, A* patrol
            sequencing, and scenario planning to help traffic teams prioritize illegal
            parking enforcement around Bengaluru.
          </p>
        </div>
      </section>

      <section className="method-grid">
        <article className="method-section wide">
          <h2>System Overview</h2>
          <p>
            ParkWatch has an offline preprocessing pipeline, a FastAPI backend, and a
            Next.js dashboard. The pipeline builds hotspot scores, graph features,
            forecasts, temporal summaries, and export-ready JSON. The dashboard turns
            those outputs into maps, rankings, forecasts, A* patrol plans, scenario
            comparisons, and reports.
          </p>
        </article>

        {engines.map((engine) => (
          <article key={engine.name}>
            <h2>{engine.name}</h2>
            <p>{engine.body}</p>
          </article>
        ))}

        <article>
          <h2>Dataset Fields Used</h2>
          <ul className="method-list">
            {datasetFields.map((field) => (
              <li key={field}>{field}</li>
            ))}
          </ul>
        </article>

        <article>
          <h2>Decision Signals</h2>
          <ul className="method-list">
            {scoreSignals.map((signal) => (
              <li key={signal}>{signal}</li>
            ))}
          </ul>
        </article>

        <article className="method-section wide">
          <h2>Scoring Formula</h2>
          <p>
            The hotspot engine keeps the core score interpretable while the priority
            score adds operational timing and station context:
          </p>
          <pre className="formula-block">{`Obstruction Risk =
0.30 * violation volume
+ 0.15 * active-day recurrence
+ 0.10 * device-day support
+ 0.20 * mean severity
+ 0.10 * junction share
+ 0.10 * graph-neighbor influence
+ 0.05 * validation share

Enforcement Priority =
0.28 * Obstruction Risk Score
+ 0.18 * station-normalized violation volume
+ 0.14 * recent 4-week activity
+ 0.12 * peak-hour temporal concentration
+ 0.10 * recent trend ratio
+ 0.08 * graph-neighbor influence
+ 0.06 * confidence evidence level
+ 0.04 * stability`}</pre>
        </article>

        <article className="method-section wide">
          <h2>Interpretation Note</h2>
          <p>
            ParkWatch uses provided parking violation records for planning intelligence.
            The A* planner runs on a dataset-derived coordinate hotspot graph, not a
            road-network graph. Road-speed, measured-delay, and exact
            congestion-reduction claims require additional traffic data.
          </p>
        </article>
      </section>
    </main>
  );
}
