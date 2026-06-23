# ParkWatch

ParkWatch is an AI-powered parking enforcement intelligence prototype for Bengaluru traffic teams. We built it for the hackathon problem statement on illegal parking hotspots and parking-induced obstruction: instead of showing only raw violations, ParkWatch turns the provided parking violation records into a command dashboard for hotspot detection, GraphSAGE forecasting, Mappls road-aware A* patrol sequencing, estimated traffic-delay exposure, analyst explanations, and exportable action plans.

## Live Demo

Current hosted URL: `https://quick-lambda-donor-prior.trycloudflare.com`

Demo Video: `https://drive.google.com/file/d/1CgVTIzaoDWYEquHUsFABdVe7SFGC74H0/view?usp=sharing`

Recommended judge path after opening the link:

1. Open `/dashboard`.
2. Review top enforcement-priority hotspots.
3. Switch to `Forecast` and show the GraphSAGE model/source.
4. Open `Patrol Planner` and generate the Mappls road-aware A* stop sequence.
5. Open `Traffic Impact` to show estimated traffic-delay exposure.
6. Export the patrol CSV or compiled report.
7. Visit `/methodology` and `/explainer` for the product and AI-engine walkthrough.

## Product Pitch

Illegal on-street parking is operationally hard because teams often know the problem exists, but do not have a clear way to rank where to act first. ParkWatch gives enforcement teams a practical workflow:

1. Detect repeated illegal-parking pressure zones.
2. Forecast next-week observed violation pressure with GraphSAGE.
3. Prioritize zones for targeted enforcement.
4. Generate a Mappls road-aware A* patrol sequence over forecast-priority stops.
5. Estimate traffic-delay exposure using Mappls traffic ETA versus road-baseline ETA.
6. Export a field-ready action plan for review or deployment.

The product story is simple: ParkWatch helps traffic teams move from reactive patrols to targeted, evidence-led enforcement.

## What We Built

- Hotspot intelligence: aggregates official parking violation records into grid cells and builds a spatial hotspot graph.
- GraphSAGE forecast engine: prefers `forecast_graphsage.json` when present and ranks future observed violation pressure from hotspot and neighbor context.
- Mappls road-aware A* patrol planner: selects top forecast-priority zones and sequences them with Mappls ETA or road distance as the edge cost, with haversine fallback.
- Leaflet visualization: numbered patrol markers, road-following route geometry when available, stop details, coverage metrics, and CSV export.
- Traffic Delay Exposure Engine: compares Mappls traffic ETA with road-baseline ETA around selected hotspots, then weights the delay by GraphSAGE pressure and obstruction severity.
- Scenario impact engine: compares estimated delay exposure and modeled obstruction-exposure coverage under targeted enforcement assumptions.
- Analyst copilot: backend-powered analyst responses with a local analyst generator fallback.
- Reports and exports: forecast CSV, patrol CSV, hotspot action lists, scenario tables, and compiled report text.

## Hackathon Fit

ParkWatch addresses the problem statement direction: AI-driven parking intelligence that detects illegal parking hotspots and quantifies their operational impact for targeted enforcement. The current prototype uses only the provided parking violation records for core planning intelligence, which keeps the submission auditable for Problem Statements 1 and 2.

## AI Engine

### Hotspot Detection Engine

The offline pipeline reads the provided violation CSV, converts records into 0.001-degree grid cells, and builds an enforcement graph from repeated illegal-parking observations and nearby-cell relationships.

### GraphSAGE Forecast Engine

When `backend/app/data/processed/forecast_graphsage.json` exists, the backend serves that trained GraphSAGE forecast first. The model learns from each hotspot and its neighboring cells to rank likely next-week observed violation pressure. If the artifact is missing, ParkWatch falls back to the baseline forecast so the dashboard still works.

### A* Patrol Planner

The patrol planner uses forecast-priority locations as enforcement stops. When Mappls is configured, A* uses Mappls traffic ETA or road distance as the edge cost and renders returned route geometry. If Mappls is unavailable or quota-limited, ParkWatch falls back to the original haversine coordinate A* so the demo still works.

### Mappls Road Intelligence Layer

Mappls adds road-aware patrol distance, estimated patrol travel time, route geometry, reverse-geocoded stop labels, and nearby context for selected hotspots. OSM/Leaflet remains the resilient visualization fallback.

### Scenario Impact Engine

Scenario controls estimate how targeted enforcement choices change estimated traffic-delay exposure and modeled obstruction-exposure coverage across selected hotspots. These are planning heuristics, not measured traffic-flow outcomes.

### Traffic Delay Exposure Engine

For selected forecast-priority hotspots, ParkWatch compares Mappls traffic ETA with a road-baseline ETA on a short local corridor. The traffic delta is combined with GraphSAGE predicted violations, obstruction severity, peak-window evidence, and road-importance weighting. If Mappls traffic data is unavailable, the engine falls back to OSM/OSRM or a transparent haversine heuristic.

## Interpretation Note

ParkWatch uses provided parking violation records for planning intelligence and Mappls/OSM road intelligence for routing and estimated traffic-delay exposure. The delay figures are planning heuristics, not measured public delay or verified minutes saved.

## Tech Stack

- Backend: FastAPI, Uvicorn, Pydantic, HTTPX
- Frontend: Next.js, React, TypeScript, Leaflet, Recharts
- Maps and routing: Mappls REST APIs for road-aware patrol planning, Leaflet/OSM fallback visualization
- ML/offline scripts: Python preprocessing, GraphSAGE training/export scripts, forecast artifact support
- Runtime/deployment: Docker Compose with backend, frontend, and nginx
- Optional copilot: Hugging Face Inference Providers token read by the backend only

## Repository Structure

```text
backend/                  FastAPI app and precomputed-data loader
frontend/                 Next.js dashboard, maps, reports, planner, pages
scripts/                  Offline preprocessing and ML artifact scripts
data/                     Local official dataset storage, ignored by git
backend/app/data/processed/ Generated JSON artifacts, ignored by git
backend/app/data/cache/     Mappls response cache, ignored by git
docs/                     Deployment reference assets
docker-compose.yml        Local full-stack Docker runtime
Dockerfile.backend        Backend image
Dockerfile.frontend       Frontend image
nginx.docker.conf         Docker nginx reverse proxy
```

## Data And Artifacts

Core source data belongs in `data/` and is intentionally ignored by git. Generated backend JSON artifacts are written to `backend/app/data/processed/` and are also ignored by git.

Expected generated artifacts include:

- `hotspots.json`
- `graph.json`
- `graph_edges.json`
- `forecast.json`
- `forecast_graphsage.json` when a trained GraphSAGE forecast is available
- `temporal.json`
- `cell_timeseries.json`
- `weekly_timeseries.json`

## Local Setup Without Docker

Run these commands from the repository root unless noted.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
```

Generate or refresh the processed JSON artifacts:

```powershell
python scripts\preprocess_official_csv.py
```

Optional GraphSAGE artifact flow:

```powershell
python scripts\export_ml_artifacts.py
python scripts\train_graphsage.py
```

Start the backend:

```powershell
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Start the frontend in another terminal:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Open `http://127.0.0.1:3000/dashboard`.

## Local Setup With Docker

Build and start the full stack:

```powershell
docker compose up -d --build
```

Useful local URLs:

- Frontend: `http://127.0.0.1:3000`
- Dashboard: `http://127.0.0.1:3000/dashboard`
- Backend health: `http://127.0.0.1:8001/api/health`
- Backend API docs through the host port: `http://127.0.0.1:8001/docs`
- Nginx entrypoint: `http://127.0.0.1`

Check container status:

```powershell
docker compose ps
```

View logs:

```powershell
docker compose logs -f backend
docker compose logs -f frontend
```

## Updating The Running Cloudflare Demo

For a quick Cloudflare Tunnel such as:

```powershell
C:\tmp\cloudflared.exe tunnel --url http://localhost:3000
```

you do not need a new Cloudflare URL if the same `cloudflared` process stays open. The tunnel forwards whatever is currently running on `localhost:3000`.

For frontend code or page-copy changes, rebuild and restart only the frontend container:

```powershell
docker compose build frontend
docker compose up -d frontend nginx
```

For backend or API changes, rebuild and restart the backend too:

```powershell
docker compose up -d --build backend frontend nginx
```

Then refresh the Cloudflare URL in the browser. If the `cloudflared` terminal was closed, start a new tunnel and paste the new URL into the Live Demo placeholder above.

## Optional Copilot Setup

Copy the example environment file and add a backend-only Hugging Face token:

```powershell
Copy-Item .env.example .env
```

Example values:

```text
HF_TOKEN=hf_your_token_here
HF_MODEL=Qwen/Qwen2.5-7B-Instruct:cheapest
HF_TIMEOUT_SECONDS=8
MAPPLS_REST_KEY=your_mappls_rest_key_here
MAPPLS_TIMEOUT_SECONDS=8
```

Do not commit `.env` or expose tokens in frontend environment variables. Mappls REST calls go through the FastAPI backend and are cached under `backend/app/data/cache/` so repeated demos do not burn quota.

## Verification Commands

```powershell
python -m compileall backend\app scripts
cd frontend
npm.cmd run typecheck
npm.cmd run build
```

Docker verification:

```powershell
docker compose ps
Invoke-RestMethod http://127.0.0.1:8001/api/health
```

## Main API Endpoints

```text
GET /api/health
GET /api/summary
GET /api/hotspots?limit=100
GET /api/hotspots/{cell_id}
GET /api/stations
GET /api/graph/{cell_id}
GET /api/forecast?limit=100
POST /api/mappls/patrol-plan
POST /api/mappls/delay-exposure
GET /api/mappls/reverse-geocode?lat=12.97&lon=77.59
GET /api/mappls/nearby?lat=12.97&lon=77.59
GET /api/temporal/hourly
GET /api/temporal/weekday
GET /api/temporal/heatmap
GET /api/timeseries/{cell_id}
GET /api/timeseries/{cell_id}/weekly
POST /api/copilot
```

## Submission Notes

- Keep the demo link current in the Live Demo section.
- Keep `data/`, `backend/app/data/processed/`, and `.env` out of git unless the hosting strategy explicitly changes.
- The public product claim should stay focused on enforcement intelligence, forecast-priority zones, Mappls road-aware patrol planning, estimated traffic-delay exposure, and obstruction-exposure planning.
- Avoid claiming measured congestion reduction, measured delay reduction, or verified minutes saved.
