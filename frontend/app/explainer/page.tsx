const workflow = [
  {
    step: "Detect hotspots",
    title: "Find repeated illegal-parking pressure zones",
    body:
      "ParkWatch groups official parking violation records into grid cells and builds a spatial hotspot graph from repeated observations, station context, junction signals, and nearby-cell activity."
  },
  {
    step: "Forecast pressure",
    title: "Let GraphSAGE rank next-week pressure",
    body:
      "The forecast view prefers the trained GraphSAGE artifact, showing likely future observed violations, forecast priority, model name, and source file behind the ranking."
  },
  {
    step: "Prioritize action",
    title: "Turn forecast-priority zones into action",
    body:
      "Baseline hotspot scores stay available for filtering and fallback, while GraphSAGE forecast priority drives the patrol candidates when the trained forecast is present."
  },
  {
    step: "Plan patrols",
    title: "Generate an A*-optimized patrol sequence",
    body:
      "The Patrol Planner selects forecast-priority zones and runs A* on their coordinate graph using haversine distance as the heuristic, then visualizes the sequence on Leaflet."
  },
  {
    step: "Report outcomes",
    title: "Export action lists and scenario summaries",
    body:
      "CSV exports and compiled reports turn dashboard evidence into a shareable plan for review, field assignment, and prototype presentation."
  }
];

const signals = [
  "GraphSAGE forecast priority: lead AI signal for next-week observed violation pressure.",
  "Predicted violations: model output used to size enforcement pressure.",
  "Baseline hotspot score: transparent fallback and filtering signal.",
  "Patrol sequence: A* ordering across selected hotspot coordinates.",
  "Impact scenario: modeled obstruction-exposure coverage for targeted action."
];

export default function ExplainerPage() {
  return (
    <main className="page-shell explainer-page">
      <section className="hero-band">
        <div>
          <p className="eyebrow">Demo workflow</p>
          <h1>How ParkWatch turns violations into enforcement intelligence.</h1>
          <p>
            ParkWatch helps traffic teams move from raw parking violation records to
            hotspot detection, AI forecasting, A*-based patrol sequencing, and exportable
            action plans.
          </p>
        </div>
      </section>

      <section className="explainer-grid" aria-label="ParkWatch workflow">
        {workflow.map((item) => (
          <article className="panel explainer-card" key={item.step}>
            <p className="eyebrow">{item.step}</p>
            <h2>{item.title}</h2>
            <p>{item.body}</p>
          </article>
        ))}
      </section>

      <section className="claim-grid" aria-label="Operational interpretation">
        <article className="panel">
          <p className="eyebrow">Operational signals</p>
          <h2>What to look for</h2>
          <ul className="method-list">
            {signals.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </article>
        <article className="panel">
          <p className="eyebrow">Interpretation note</p>
          <h2>How to present it</h2>
          <p>
            ParkWatch uses provided parking violation records for planning intelligence.
            The A* planner runs on a coordinate hotspot graph, not a road-network graph.
            Road-speed, measured-delay, and exact congestion-reduction claims require
            additional traffic data.
          </p>
        </article>
      </section>
    </main>
  );
}
