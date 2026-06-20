# ParkWatch

ParkWatch is a full-stack project for exploring parking-violation hotspots and
obstruction risk patterns from the official parking violation dataset.

## Structure

- `backend/`: FastAPI backend.
- `frontend/`: React/Next.js frontend.
- `scripts/`: Offline preprocessing utilities.
- `docs/`: Project notes and local reference material.
- `data/`: Local official dataset storage. This directory is ignored by git.

## Core Data Constraint

Only the official parking violation dataset in `data/` may be used. Do not use
OSM, weather, traffic APIs, or external datasets. ParkWatch outputs must describe
the computed score as an obstruction or congestion-risk proxy, not measured
congestion.

See `docs/methodology_compliance.md` for the full system overview, fields used,
score formula, confidence labels, limitations, and compliance boundary. ParkWatch
must not claim actual measured congestion reduction, minutes saved, delay avoided,
or travel-time improvement from the current official CSV alone.

## Production-Style Local Setup

Run commands from the repository root unless a step says otherwise.

Create and activate a Python virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Install backend dependencies:

```powershell
python -m pip install -r backend/requirements.txt
```

Generate the precomputed backend JSON files from the single official CSV in
`data/`:

```powershell
python scripts/preprocess_official_csv.py
```

Run backend checks:

```powershell
python scripts/smoke_test_backend.py
```

Start the FastAPI backend:

```powershell
python -m uvicorn backend.app.main:app --reload
```

Install frontend dependencies:

```powershell
cd frontend
npm.cmd install
```

Run frontend checks:

```powershell
npm.cmd run typecheck
npm.cmd run build
```

Start the frontend development server:

```powershell
npm.cmd run dev
```

The frontend expects the backend at `http://127.0.0.1:8000` by default. Set
`NEXT_PUBLIC_API_BASE_URL` to point at a different FastAPI host.

Optional HF copilot setup:

```powershell
Copy-Item .env.example .env
# Add a Hugging Face fine-grained/read token with Inference Providers access:
# HF_TOKEN=hf_...
# Optional demo model tested with Hugging Face Inference Providers:
# HF_MODEL=Qwen/Qwen2.5-7B-Instruct:cheapest
```

The copilot token is read only by the FastAPI backend. Do not commit `.env` or
paste tokens into frontend environment variables.

For a production-style frontend start after `npm.cmd run build`:

```powershell
npm.cmd run start
```

## Preprocessing

Run the offline preprocessing pipeline against the single official CSV in
`data/`:

```powershell
python scripts/preprocess_official_csv.py
```

Generated backend JSON files are written to `backend/app/data/processed/` and
are ignored by git.

## Backend Checks

Run the backend smoke test after preprocessing:

```powershell
python scripts/smoke_test_backend.py
```
