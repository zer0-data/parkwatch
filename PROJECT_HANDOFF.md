# ParkWatch Project Summary

## One-Line Pitch

ParkWatch is an AI-powered parking enforcement intelligence prototype for Bengaluru traffic teams: GraphSAGE forecasts where illegal-parking pressure will appear, Mappls/OSM estimate road-aware patrol movement and traffic-delay exposure, and the dashboard turns that into targeted enforcement plans.

## Current Product Story

- Detect repeated illegal-parking hotspots from the provided parking violation records.
- Forecast next-week observed violation pressure with GraphSAGE when `forecast_graphsage.json` is available.
- Prioritize forecast-priority zones for targeted enforcement.
- Generate a Mappls road-aware A* patrol sequence, with haversine fallback if Mappls is unavailable.
- Estimate traffic-delay exposure by comparing Mappls traffic ETA with a road-baseline ETA around selected hotspots, then weighting by forecast pressure, obstruction risk, peak-window evidence, and road context.
- Export CSVs and compiled reports for judges or field-planning review.

## Important Claim Boundaries

Use:

- AI-powered parking enforcement intelligence
- forecast-priority zones
- road-aware A* patrol sequence
- estimated traffic-delay exposure
- parking-attributed delay proxy
- modeled obstruction-exposure reduction

Avoid:

- measured congestion reduction
- measured public delay reduction
- verified minutes saved
- exact congestion-reduction percentage

## Core Stack

- Backend: FastAPI, Pydantic, HTTPX, precomputed JSON artifacts.
- Frontend: Next.js, React, TypeScript, Leaflet, Recharts, Material UI.
- ML/artifacts: Python preprocessing, GraphSAGE forecast artifact support, baseline forecast fallback.
- Maps/routing: Mappls REST APIs for road-aware ETA/distance and route geometry; OSM/Leaflet fallback visualization; OSRM fallback for corridor baselines where needed.
- Deployment: Docker Compose with backend, frontend, and nginx. Cloudflare quick tunnel can point at `localhost:3000`.

## Environment

Do not commit real secrets. Local `.env` is ignored.

Expected optional values:

```text
HF_TOKEN=
HF_MODEL=
HF_TIMEOUT_SECONDS=8
MAPPLS_REST_KEY=
MAPPLS_TIMEOUT_SECONDS=8
MAPPLS_BASE_URL=https://apis.mappls.com/advancedmaps/v1
```

Mappls REST calls are backend-only. The real key should stay in `.env`, not in frontend code or docs.

## Key Files

- `backend/app/main.py`: FastAPI routes, including Mappls patrol and delay-exposure APIs.
- `backend/app/services/precomputed_store.py`: Loads and caches processed dataset artifacts.
- `backend/app/services/mappls.py`: Mappls/OSM/haversine routing and delay-exposure service wrapper.
- `backend/app/models.py`: API response/request models.
- `frontend/app/components/patrol-planner.tsx`: Road-aware A* patrol planner UI.
- `frontend/app/components/impact-scenario-panel.tsx`: Traffic-delay exposure scenario UI.
- `frontend/app/components/compiled-report-panel.tsx`: Judge/report summary export.
- `frontend/app/lib/delay-candidates.ts`: Builds GraphSAGE-first delay exposure candidates.
- `frontend/app/methodology/page.tsx`: AI Engine page.
- `frontend/app/explainer/page.tsx`: Demo walkthrough.
- `README.md`: Product pitch, stack, setup, hosting, and verification docs.

## Verification Commands

Run from repo root unless noted:

```powershell
python -m compileall backend\app scripts
.\.venv\Scripts\python.exe scripts\smoke_test_mappls.py
cd frontend
npm.cmd run typecheck
npm.cmd run build
```

Docker:

```powershell
docker compose up -d --build backend frontend nginx
docker compose ps
Invoke-RestMethod http://127.0.0.1:8001/api/health
```

## Current Notes

- Dashboard first-load performance was improved by limiting the initial hotspot payload and caching summary/station aggregates.
- Backend store preload was added at FastAPI startup so the first visitor should not pay the JSON loading cost after the container is healthy.
- If Docker rebuild is interrupted, rerun `docker compose up -d --build backend frontend nginx` before assuming the hosted container has the latest source.
- A quick Cloudflare tunnel only stays live while `cloudflared` and the laptop remain running. For always-on hosting, use a persistent cloud service.
