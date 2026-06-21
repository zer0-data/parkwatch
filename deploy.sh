#!/bin/bash
# ParkWatch Deploy Script
# Quick deployment to various platforms

set -e

echo "🚀 ParkWatch Deployment Script"
echo "=============================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
DEPLOYMENT_TARGET=${1:-local}

case $DEPLOYMENT_TARGET in
  local)
    echo -e "${GREEN}✓${NC} Local Development Setup"
    
    # Create venv if not exists
    if [ ! -d ".venv" ]; then
      echo "Creating virtual environment..."
      python3 -m venv .venv
    fi
    
    source .venv/bin/activate
    echo "✓ Virtual environment activated"
    
    # Install dependencies
    echo "Installing backend dependencies..."
    pip install --quiet -r backend/requirements.txt
    pip install --quiet gunicorn
    
    echo "Installing frontend dependencies..."
    cd frontend
    npm install --silent
    cd ..
    
    # Preprocess data
    if [ ! -f "data/parking_violations.csv" ] && [ ! -f "data/parking_violations_sample.csv" ]; then
      echo -e "${YELLOW}⚠${NC} No CSV found in data/ directory"
      echo "To proceed, please add parking_violations.csv to data/"
      exit 1
    fi
    
    # Find the CSV
    CSV_FILE=$(find data/ -name "*.csv" -type f | head -1)
    echo "Processing data from: $CSV_FILE"
    python scripts/preprocess_official_csv.py
    
    echo ""
    echo -e "${GREEN}✓ Setup Complete!${NC}"
    echo ""
    echo "Start services in separate terminals:"
    echo "  Terminal 1 (Backend):  source .venv/bin/activate && PYTHONPATH=. python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000"
    echo "  Terminal 2 (Frontend): cd frontend && npm run dev"
    echo ""
    echo "Then visit: http://127.0.0.1:3000/dashboard"
    ;;

  docker)
    echo -e "${GREEN}✓${NC} Docker Compose Deployment"
    
    if ! command -v docker-compose &> /dev/null; then
      echo -e "${RED}✗${NC} docker-compose not found"
      exit 1
    fi
    
    echo "Building containers..."
    docker-compose build
    
    echo "Starting services..."
    docker-compose up -d
    
    echo ""
    sleep 3
    
    # Check health
    if curl -s http://localhost:8001/api/health > /dev/null; then
      echo -e "${GREEN}OK${NC} Backend healthy at http://localhost:8001"
    else
      echo -e "${RED}✗${NC} Backend not responding"
    fi
    
    echo -e "${GREEN}✓${NC} Frontend running at http://localhost:3000"
    echo ""
    echo "View logs: docker-compose logs -f"
    echo "Stop services: docker-compose down"
    ;;

  heroku)
    echo -e "${GREEN}✓${NC} Heroku Deployment"
    
    if ! command -v heroku &> /dev/null; then
      echo -e "${RED}✗${NC} Heroku CLI not found"
      echo "Install from: https://devcenter.heroku.com/articles/heroku-cli"
      exit 1
    fi
    
    APP_NAME=${2:-parkwatch-app}
    
    echo "Creating Heroku app: $APP_NAME"
    heroku create $APP_NAME 2>/dev/null || true
    
    echo "Adding buildpacks..."
    heroku buildpacks:add --index 1 heroku/python -a $APP_NAME 2>/dev/null || true
    heroku buildpacks:add --index 2 heroku/nodejs -a $APP_NAME 2>/dev/null || true
    
    echo "Deploying to Heroku..."
    git push heroku main
    
    echo ""
    echo -e "${GREEN}✓${NC} Deployment complete!"
    echo "View logs: heroku logs --tail -a $APP_NAME"
    echo "Visit: https://$APP_NAME.herokuapp.com"
    ;;

  aws)
    echo -e "${GREEN}✓${NC} AWS EC2 Deployment"
    
    if ! command -v aws &> /dev/null; then
      echo -e "${RED}✗${NC} AWS CLI not found"
      echo "Install from: https://aws.amazon.com/cli/"
      exit 1
    fi
    
    # Prompt for inputs
    read -p "EC2 Instance IP: " INSTANCE_IP
    read -p "SSH Key file: " SSH_KEY
    read -p "SSH User (ubuntu/ec2-user): " SSH_USER
    
    if [ -z "$INSTANCE_IP" ] || [ -z "$SSH_KEY" ]; then
      echo -e "${RED}✗${NC} Missing required parameters"
      exit 1
    fi
    
    echo "Connecting to EC2 instance..."
    
    # Copy files to EC2
    scp -i "$SSH_KEY" -r . "$SSH_USER@$INSTANCE_IP:/home/$SSH_USER/parkwatch/"
    
    # Run setup script on EC2
    ssh -i "$SSH_KEY" "$SSH_USER@$INSTANCE_IP" << 'EOF'
    cd /home/$SSH_USER/parkwatch
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r backend/requirements.txt
    pip install gunicorn
    python scripts/preprocess_official_csv.py
    
    # Install Node and npm
    curl -sL https://rpm.nodesource.com/setup_18.x | sudo bash -
    sudo yum install -y nodejs
    
    cd frontend && npm install && npm run build
    
    echo "Setup complete on EC2"
EOF
    
    echo -e "${GREEN}✓${NC} EC2 setup complete"
    echo "Next steps:"
    echo "1. SSH to instance: ssh -i $SSH_KEY $SSH_USER@$INSTANCE_IP"
    echo "2. Start backend: cd parkwatch && source .venv/bin/activate && gunicorn -w 4 -b 0.0.0.0:8000 backend.app.main:app"
    echo "3. Start frontend: cd parkwatch/frontend && npm run start"
    echo "4. Setup Nginx reverse proxy (see README.md)"
    ;;

  gcloud)
    echo -e "${GREEN}✓${NC} Google Cloud Run Deployment"
    
    if ! command -v gcloud &> /dev/null; then
      echo -e "${RED}✗${NC} Google Cloud SDK not found"
      echo "Install from: https://cloud.google.com/sdk/docs/install"
      exit 1
    fi
    
    read -p "GCP Project ID: " PROJECT_ID
    
    if [ -z "$PROJECT_ID" ]; then
      echo -e "${RED}✗${NC} Project ID required"
      exit 1
    fi
    
    gcloud config set project $PROJECT_ID
    
    echo "Building backend image..."
    gcloud builds submit --tag gcr.io/$PROJECT_ID/parkwatch-backend -f Dockerfile.backend
    
    echo "Building frontend image..."
    gcloud builds submit --tag gcr.io/$PROJECT_ID/parkwatch-frontend -f Dockerfile.frontend
    
    echo "Deploying backend..."
    gcloud run deploy parkwatch-backend \
      --image gcr.io/$PROJECT_ID/parkwatch-backend \
      --platform managed \
      --region us-central1 \
      --memory 2Gi \
      --timeout 3600 \
      --allow-unauthenticated
    
    echo "Deploying frontend..."
    gcloud run deploy parkwatch-frontend \
      --image gcr.io/$PROJECT_ID/parkwatch-frontend \
      --platform managed \
      --region us-central1 \
      --set-env-vars NEXT_PUBLIC_API_BASE_URL=https://parkwatch-backend-xxxxx.a.run.app \
      --allow-unauthenticated
    
    echo -e "${GREEN}✓${NC} Cloud Run deployment complete"
    ;;

  *)
    echo -e "${RED}✗${NC} Unknown deployment target: $DEPLOYMENT_TARGET"
    echo ""
    echo "Usage: ./deploy.sh [target] [options]"
    echo ""
    echo "Targets:"
    echo "  local              Local development setup"
    echo "  docker             Docker Compose (recommended)"
    echo "  heroku             Heroku deployment"
    echo "  aws                AWS EC2 deployment"
    echo "  gcloud             Google Cloud Run deployment"
    echo ""
    echo "Examples:"
    echo "  ./deploy.sh local"
    echo "  ./deploy.sh docker"
    echo "  ./deploy.sh heroku my-app-name"
    echo "  ./deploy.sh aws"
    exit 1
    ;;
esac

echo ""
echo "📚 For more info, see:"
echo "   - README.md for quick reference, deployment, and hosting instructions"
