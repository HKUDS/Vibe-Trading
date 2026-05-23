#!/bin/bash
# Server initialization script for Alibaba Cloud Linux 3
# Run once on a fresh server

set -euo pipefail

echo "=== Vibe-Trading Copy — Server Setup ==="
echo "OS: Alibaba Cloud Linux 3 (OpenAnolis)"
echo ""

# ─── Update system ──────────────────────────────────────────────────
echo "[1/6] Updating system packages..."
sudo yum update -y

# ─── Install Docker ─────────────────────────────────────────────────
echo "[2/6] Installing Docker..."
if ! command -v docker &> /dev/null; then
    sudo yum install -y docker
    sudo systemctl start docker
    sudo systemctl enable docker
    echo "Docker installed"
else
    echo "Docker already installed"
fi

# ─── Install Docker Compose ─────────────────────────────────────────
echo "[3/6] Installing Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
        -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    echo "Docker Compose installed"
else
    echo "Docker Compose already installed"
fi

# ─── Install Git ────────────────────────────────────────────────────
echo "[4/6] Installing Git..."
if ! command -v git &> /dev/null; then
    sudo yum install -y git
fi

# ─── Install Node.js (for building frontend) ────────────────────────
echo "[5/6] Installing Node.js 20..."
if ! command -v node &> /dev/null; then
    curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
    sudo yum install -y nodejs
    echo "Node.js installed: $(node --version)"
else
    echo "Node.js already installed: $(node --version)"
fi

# ─── Create app directory ───────────────────────────────────────────
echo "[6/6] Creating app directory..."
APP_DIR="/opt/vibe-trading"
sudo mkdir -p "$APP_DIR"
sudo chown "$(whoami):$(whoami)" "$APP_DIR"

echo ""
echo "=== Setup Complete ==="
echo "App directory: $APP_DIR"
echo ""
echo "Next steps:"
echo "  1. Clone your fork: cd $APP_DIR && git clone https://github.com/Seven-zzy/Vibe-Trading.git ."
echo "  2. Configure environment: cp .env.example .env && nano .env"
echo "  3. Deploy: ./scripts/deploy.sh"
