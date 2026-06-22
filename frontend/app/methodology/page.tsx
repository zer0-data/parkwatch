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
      "The offline pipeline reads the provided violation CSV, converts records into 0.001-degree grid cells, and builds an enforcement graph from spatial neighbors and repeated illegal-parking observations."
  },
  {
    name: "GraphSAGE Forecast Engine",
    body:
      "When forecast_graphsage.json is present, ParkWatch serves the trained GraphSAGE forecast first. The model learns from each hotspot and its neighboring cells to rank future observed parking violation pressure, with the older heuristic forecast kept only as a fallback artifact."
  },
  {
    name: "A* Patrol Planner",
    body:
      "The planner chooses GraphSAGE forecast-priority zones and runs A* with Mappls ETA or road distance as the edge cost. If Mappls is unavailable, ParkWatch falls back to haversine coordinate distance so the patrol plan still renders."
  },
  {
    name: "Mappls Road Intelligence Layer",
    body:
      "Mappls enriches the patrol plan with road-aware distance, estimated patrol travel time, route geometry, reverse-geocoded stop labels, and nearby context for selected hotspots. Leaflet and OSM remain the resilient visualization fallback."
  },
  {
    name: "Traffic Delay Exposure Engine",
    body:
      "For selected forecast-priority hotspots, ParkWatch compares Mappls traffic ETA with a road-baseline ETA on a short local corridor, then weights that delay by GraphSAGE predicted violations, obstruction severity, peak-window evidence, and road importance. If Mappls traffic data is unavailable, the engine falls back to OSM/OSRM or a transparent haversine heuristic."
  },
  {
    name: "Scenario Impact Engine",
    body:
      "Scenario controls estimate how targeted enforcement choices change estimated traffic-delay exposure and modeled obstruction-exposure coverage across selected hotspots and the citywide hotspot set."
  }
];

const decisionSignals = [
  "GraphSAGE forecast priority is the lead AI signal when forecast_graphsage.json is available.",
  "Predicted violations estimate next-week observed illegal-parking pressure for each hotspot.",
  "Mappls road ETA and distance turn forecast-priority zones into a patrol route officers can follow.",
  "Traffic-delay exposure estimates parking-attributed delay pressure by combining road ETA deltas with forecast and obstruction signals.",
  "Hotspot and enforcement scores remain interpretable baseline signals for ranking, filtering, and fallback behavior.",
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
            ParkWatch combines hotspot analytics, graph forecasting, Mappls road-aware
            A* patrol sequencing, and scenario planning to help traffic teams prioritize
            illegal parking enforcement around Bengaluru.
          </p>
        </div>
      </section>

      <section className="method-grid">
        <article className="method-section wide">
          <h2>System Overview</h2>
          <p>
            ParkWatch has an offline preprocessing pipeline, a FastAPI backend, and a
            Next.js dashboard. The pipeline builds hotspot scores, graph features,
            GraphSAGE forecasts, temporal summaries, and export-ready JSON. The
            dashboard turns those outputs into maps, rankings, forecast-priority
            zones, Mappls-enhanced patrol plans, scenario comparisons, and reports.
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
            {decisionSignals.map((signal) => (
              <li key={signal}>{signal}</li>
            ))}
          </ul>
        </article>

        <article className="method-section wide">
          <h2>GraphSAGE Forecast Flow</h2>
          <p>
            ParkWatch presents GraphSAGE as the main AI forecasting layer. The fixed
            scores are retained as transparent operational features and fallback
            rankings, but the forecast tab and patrol planner prefer the trained graph
            forecast whenever it is available:
          </p>
          <pre className="formula-block">{`Provided violation records
-> grid-cell hotspot graph
-> node features from volume, time, station, junction, validation, and neighbor context
-> GraphSAGE neighborhood aggregation
-> predicted violations and forecast priority
-> Mappls road ETA/distance matrix for selected stops
-> A* patrol sequence with haversine fallback
-> traffic-delay exposure estimate for selected hotspots`}</pre>
        </article>

        <article className="method-section wide">
          <h2>Interpretation Note</h2>
          <p>
            ParkWatch uses provided parking violation records for planning intelligence.
            Mappls road-aware routing estimates patrol travel time and road distance for
            selected enforcement stops. Traffic-delay exposure is a planning estimate
            based on Mappls/OSM route deltas and hotspot pressure, not a measured public
            delay total. Verified minutes saved and exact congestion-reduction claims
            still require traffic-flow validation.
          </p>
        </article>
      </section>
    </main>
  );
}
