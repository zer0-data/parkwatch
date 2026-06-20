# ParkWatch: Our Hackathon Prototype Brief

## What We Built

We built ParkWatch as an AI-powered parking enforcement intelligence prototype for Bengaluru. Our goal is to help traffic teams move from reactive patrols to targeted, evidence-led action against illegal parking pressure near intersections, commercial areas, transit zones, and other repeated obstruction points.

ParkWatch turns the provided parking violation records into a working command dashboard: hotspot detection, graph-based forecasting, A*-optimized patrol sequencing, scenario planning, report export, and an analyst copilot.

## Why It Matters

Illegal on-street parking is hard to manage because teams often know the problem exists but do not have a clear way to rank where to act first. ParkWatch gives enforcement teams a practical workflow:

1. Detect repeated parking pressure zones.
2. Forecast where violation pressure is likely to remain high.
3. Prioritize zones by enforcement value.
4. Generate an A*-optimized patrol sequence.
5. Export a field-ready action plan.

This makes the prototype useful for both strategic planning and day-to-day deployment.

## Product Highlights

- **Hotspot Intelligence:** We aggregate violation records into grid cells and rank zones using obstruction risk, recurrence, severity, junction share, validation support, and nearby-cell activity.
- **GraphSAGE Forecasting:** We integrate a trained GraphSAGE forecast artifact so the system can prioritize future observed violation pressure, not just historical hotspots.
- **A* Patrol Planner:** We select top forecast-priority zones and run A* over the coordinate hotspot graph using haversine distance as the heuristic. Leaflet visualizes the numbered stop sequence and route line.
- **Scenario Impact Engine:** We model obstruction-exposure coverage under targeted enforcement scenarios so decision-makers can compare action plans.
- **Analyst Copilot:** We added a backend-only HF-powered analyst popup with a local analyst generator fallback, so judges can ask questions about the selected hotspot, forecast, deployment priority, or product pitch.
- **Exportable Outputs:** Patrol plans, priority zones, scenario tables, and compiled reports can be downloaded for review or field planning.

## What Makes It Scalable

The architecture separates offline data processing, API serving, and frontend decision support:

- FastAPI serves precomputed analytics and model outputs.
- Next.js renders a responsive dashboard with Leaflet maps and product workflows.
- Docker Compose runs backend, frontend, and nginx together for deployment.
- GraphSAGE is optional at runtime: if the trained forecast artifact exists, ParkWatch uses it; otherwise it falls back to the baseline forecast.

This means the prototype can start with the provided dataset and later add richer data sources if allowed by the challenge or by a deployment partner.

## How We Present The A* Planner

Our A* planner is intentionally practical for this prototype. It is not claiming road-network shortest-path routing. It runs on selected enforcement hotspot coordinates and uses haversine distance as a geographic heuristic. That gives us a credible, explainable patrol sequence today, while leaving room to add road-network routing later if road graph or travel-time data is available.

## Our Demo Story

In the demo, we would show a judge this flow:

1. Open the ParkWatch command dashboard.
2. Filter by police station, violation type, peak day, or peak hour.
3. Inspect the top hotspot and its evidence.
4. Switch to Forecast to show GraphSAGE forecast priority.
5. Open Patrol Planner to generate the A*-optimized enforcement sequence.
6. Export the patrol CSV or compiled report.
7. Ask the analyst copilot for a concise deployment explanation.

The result is a product-like workflow rather than just a model notebook.

## Interpretation Note

ParkWatch uses the provided parking violation records for planning intelligence. The current prototype focuses on enforcement priority, obstruction exposure, and future observed violation pressure. Road-speed, measured-delay, or exact congestion-reduction claims would require additional traffic-flow or road-network data.
