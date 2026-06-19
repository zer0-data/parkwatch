#!/bin/bash
# ============================================================
#  ParkWatch — One-Shot Docker Compose Deployment Script
#  Usage: ./start.sh
# ============================================================

set -euo pipefail

# ── Colours ─────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✔${NC}  $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
err()  { echo -e "${RED}✖${NC}  $*"; }
info() { echo -e "${CYAN}→${NC}  $*"; }
hr()   { echo -e "${CYAN}────────────────────────────────────────────${NC}"; }

# ── Banner ──────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}  🚗  ParkWatch — Docker Compose Deployment${NC}"
hr
echo ""

# ── 0. Locate script root ────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE}")" && pwd)"
cd "$SCRIPT_DIR"
info "Working directory: $SCRIPT_DIR"
echo ""

# ── 1. Prerequisite checks ───────────────────────────────────
hr
echo -e "${BOLD}Step 1 — Checking prerequisites${NC}"
hr

# Docker
if ! command -v docker &>/dev/null; then
  err "Docker is not installed."
  echo "    Install it from: https://docs.docker.com/engine/install/"
  exit 1
fi
ok "Docker: $(docker --version | awk '{print $3}' | tr -d ',')"

# Docker Compose (v2 plugin or standalone v1)
if docker compose version &>/dev/null 2>&1; then
  COMPOSE_CMD="docker compose"
  ok "Docker Compose: $(docker compose version --short 2>/dev/null || docker compose version | grep -oP '[\d.]+')"
elif command -v docker-compose &>/dev/null; then
  COMPOSE_CMD="docker-compose"
  ok "Docker Compose (standalone): $(docker-compose --version | awk '{print $3}' | tr -d ',')"
else
  err "Docker Compose is not installed."
  echo "    Install it from: https://docs.docker.com/compose/install/"
  exit 1
fi

# Docker daemon running?
if ! docker info &>/dev/null 2>&1; then
  err "Docker daemon is not running. Start it with: sudo systemctl start docker"
  exit 1
fi
ok "Docker daemon is running"
echo ""

# ── 2. Verify data files ─────────────────────────────────────
hr
echo -e "${BOLD}Step 2 — Verifying data${NC}"
hr

# Look for a CSV in data/
CSV_FILE=""
for f in data/parking_violations.csv data/parking_violations_sample.csv; do
  if [ -f "$f" ]; then
    CSV_FILE="$f"
    break
  fi
done

if [ -z "$CSV_FILE" ]; then
  err "No parking violations CSV found in data/"
  echo "    Expected: data/parking_violations.csv"
  echo "    Please add your CSV file and re-run this script."
  exit 1
fi
ok "Found data file: $CSV_FILE"

# Check if processed JSON files exist
PROCESSED_DIR="backend/app/data/processed"
REQUIRED_FILES=("hotspots.json" "graph.json" "forecast.json" "temporal.json")
MISSING=0
for f in "${REQUIRED_FILES[@]}"; do
  if [ ! -f "$PROCESSED_DIR/$f" ]; then
    MISSING=1
    break
  fi
done

if [ "$MISSING" -eq 1 ]; then
  warn "Processed JSON files not found. Running preprocessing..."

  # Check Python
  if ! command -v python3 &>/dev/null; then
    err "python3 is required for preprocessing but is not installed."
    exit 1
  fi

  # Set up venv if not present
  if [ ! -d ".venv" ]; then
    info "Creating Python virtual environment..."
    python3 -m venv .venv
  fi

  source .venv/bin/activate
  info "Installing Python dependencies for preprocessing..."
  pip install --quiet -r backend/requirements.txt

  info "Running preprocessing script..."
  PYTHONPATH="$SCRIPT_DIR" python scripts/preprocess_official_csv.py

  deactivate
  ok "Preprocessing complete"
else
  ok "Processed data already present ($(ls "$PROCESSED_DIR"/*.json 2>/dev/null | wc -l) JSON files)"
fi
echo ""

# ── 3. Self-signed SSL cert (for nginx HTTPS) ────────────────
hr
echo -e "${BOLD}Step 3 — TLS certificate${NC}"
hr

SSL_DIR="ssl"
mkdir -p "$SSL_DIR"

if [ ! -f "$SSL_DIR/cert.pem" ] || [ ! -f "$SSL_DIR/key.pem" ]; then
  if command -v openssl &>/dev/null; then
    info "Generating self-signed TLS certificate (valid 365 days)..."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
      -keyout "$SSL_DIR/key.pem" \
      -out "$SSL_DIR/cert.pem" \
      -subj "/CN=parkwatch.local/O=ParkWatch/C=IN" \
      2>/dev/null
    ok "Self-signed certificate created in ssl/"
    warn "Browsers will show a security warning — this is expected for self-signed certs."
    warn "For production, replace ssl/cert.pem and ssl/key.pem with a real certificate."
  else
    warn "openssl not found — skipping TLS cert generation."
    warn "Nginx HTTPS will not work without a certificate."
    warn "Install openssl and re-run, or add ssl/cert.pem and ssl/key.pem manually."
  fi
else
  ok "TLS certificate already exists in ssl/"
fi
echo ""

# ── 4. Build & launch containers ────────────────────────────
hr
echo -e "${BOLD}Step 4 — Launching containers${NC}"
hr

info "Killing rogue host processes on port 8000 to prevent port conflicts..."
sudo fuser -k 8000/tcp || true

info "Bringing up docker stack..."
echo ""

$COMPOSE_CMD up -d

echo ""
ok "Containers launched"
echo ""

# ── 5. Wait for backend health check ────────────────────────
hr
echo -e "${BOLD}Step 5 — Waiting for services to become healthy${NC}"
hr

MAX_WAIT=120   # seconds
WAITED=0
INTERVAL=5

info "Polling backend health at http://localhost:8000/api/health ..."
while true; do
  if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
    ok "Backend is healthy!"
    break
  fi
  if [ "$WAITED" -ge "$MAX_WAIT" ]; then
    err "Backend did not become healthy within ${MAX_WAIT}s."
    echo "    Check logs with: $COMPOSE_CMD logs backend"
    exit 1
  fi
  echo -n "."
  sleep "$INTERVAL"
  WAITED=$((WAITED + INTERVAL))
done

info "Polling frontend at http://localhost:3000 ..."
WAITED=0
while true; do
  if curl -sf http://localhost:3000 > /dev/null 2>&1; then
    ok "Frontend is healthy!"
    break
  fi
  if [ "$WAITED" -ge "$MAX_WAIT" ]; then
    err "Frontend did not become healthy within ${MAX_WAIT}s."
    echo "    Check logs with: $COMPOSE_CMD logs frontend"
    exit 1
  fi
  echo -n "."
  sleep "$INTERVAL"
  WAITED=$((WAITED + INTERVAL))
done
echo ""

# ── 6. Final status summary ──────────────────────────────────
hr
echo -e "${BOLD}${GREEN}  🎉  ParkWatch is live!${NC}"
hr
echo ""
echo -e "  ${BOLD}Dashboard:${NC}   http://localhost/dashboard"
echo -e "  ${BOLD}API health:${NC}  http://localhost:8000/api/health"
if [ -f "$SSL_DIR/cert.pem" ]; then
  echo -e "  ${BOLD}HTTPS:${NC}       https://localhost/dashboard  (self-signed — accept browser warning)"
fi
echo ""
echo -e "${BOLD}  Container status:${NC}"
$COMPOSE_CMD ps
echo ""
echo -e "${BOLD}  Useful commands:${NC}"
echo "    View logs:        $COMPOSE_CMD logs -f"
echo "    View backend log: $COMPOSE_CMD logs -f backend"
echo "    Stop everything:  $COMPOSE_CMD down"
echo "    Rebuild & restart: bash start.sh"
echo ""
hr