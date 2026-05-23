#!/bin/bash
# One-click deployment script
# Run this after code changes to redeploy

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "=== Vibe-Trading Copy — Deploy ==="
echo "Time: $(date)"
echo ""

# ─── Pull latest code ───────────────────────────────────────────────
echo "[1/7] Pulling latest code..."
git pull origin main

# ─── Load environment ───────────────────────────────────────────────
echo "[2/7] Loading environment..."
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
    echo "Loaded .env"
else
    echo "WARNING: .env not found. Copy from .env.example and configure."
    exit 1
fi

# ─── Build frontend ─────────────────────────────────────────────────
echo "[3/7] Building frontend..."
cd frontend

# Install if node_modules missing
if [ ! -d node_modules ]; then
    echo "Installing frontend dependencies..."
    npm install -g pnpm
    pnpm install
fi

# Build for production
pnpm build
cd ..

echo "Frontend built: $(du -sh frontend/dist)"

# ─── Stop old containers ────────────────────────────────────────────
echo "[4/7] Stopping old containers..."
docker-compose -f docker-compose.prod.yml down --remove-orphans

# ─── Clean up dangling images ───────────────────────────────────────
echo "[5/7] Cleaning up old images..."
docker system prune -f

# ─── Build and start ────────────────────────────────────────────────
echo "[6/7] Building and starting services..."
docker-compose -f docker-compose.prod.yml up --build -d

# ─── Health check ───────────────────────────────────────────────────
echo "[7/7] Waiting for services..."
sleep 5

echo ""
echo "Checking backend health..."
if curl -sf http://localhost:80/health > /dev/null; then
    echo "  ✓ Backend is healthy"
else
    echo "  ✗ Backend not responding (may need more time)"
fi

echo ""
echo "=== Deploy Complete ==="
echo ""
echo "Your app should be accessible at:"
echo "  http://$(curl -s ifconfig.me)"
echo ""
echo "View logs:"
echo "  docker-compose -f docker-compose.prod.yml logs -f"
echo ""
echo "Check memory usage:"
echo "  docker stats --no-stream"
