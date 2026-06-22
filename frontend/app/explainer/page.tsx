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
    step: "Enrich with roads",
    title: "Add Mappls road intelligence",
    body:
      "For the selected patrol candidates, ParkWatch asks Mappls for road-aware distance, estimated patrol travel time, route geometry, reverse-geocoded labels, and nearby context."
  },
  {
    step: "Plan patrols",
    title: "Generate a road-aware A* patrol sequence",
    body:
      "The Patrol Planner runs A* with Mappls ETA or road distance as the edge cost, then visualizes the road-following sequence on Leaflet with OSM and haversine fallback."
  },
  {
    step: "Estimate impact",
    title: "Quantify traffic-delay exposure",
    body:
      "The Traffic Impact tab compares Mappls traffic ETA with road-baseline ETA around selected hotspots, then weights the delay by forecast pressure, obstruction risk, peak-window evidence, and road context."
  },
  {
    step: "Report outcomes",
    title: "Export action lists and scenario summaries",
    body:
      "CSV exports and compiled reports turn hotspot evidence, road-aware patrol routing, and estimated delay exposure into a shareable plan for review, field assignment, and prototype presentation."
  }
];

const signals = [
  "GraphSAGE forecast priority: lead AI signal for next-week observed violation pressure.",
  "Predicted violations: model output used to size enforcement pressure.",
  "Mappls road ETA: estimated patrol travel time between selected enforcement stops.",
  "Traffic-delay exposure: planning estimate that combines Mappls/OSM route deltas with GraphSAGE pressure and obstruction risk.",
  "Baseline hotspot score: transparent fallback and filtering signal.",
  "Patrol sequence: A* ordering across selected hotspots using road-aware costs where available.",
  "Impact scenario: estimated delay-exposure and obstruction-exposure change under targeted action."
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
            hotspot detection, AI forecasting, Mappls road-aware A* patrol sequencing,
            and exportable action plans.
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
            Mappls routing estimates patrol travel time and road distance for selected
            enforcement stops, while traffic-delay exposure is a planning heuristic
            based on road ETA deltas and hotspot pressure. Exact congestion-reduction
            or measured public delay-reduction claims still require traffic-flow
            validation.
          </p>
        </article>
      </section>
    </main>
  );
}
