#!/usr/bin/env bash

set -Eeuo pipefail

readonly APP_DIR="/opt/trading-projects/code/Vibe-Trading"
readonly SERVICE_NAME="vibe-trading"
readonly HEALTH_URL="http://127.0.0.1:8899/"

cd "$APP_DIR"

if [[ "$(git branch --show-current)" != "personal" ]]; then
    echo "Deployment aborted: $APP_DIR must be on the personal branch." >&2
    exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
    echo "Deployment aborted: $APP_DIR/.venv is missing." >&2
    exit 1
fi

if [[ ! -f agent/.env ]]; then
    echo "Deployment aborted: $APP_DIR/agent/.env is missing." >&2
    exit 1
fi

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    echo "Deployment aborted: Node.js and npm are required." >&2
    exit 1
fi

echo "Installing Python dependencies for $(git rev-parse --short HEAD)..."
.venv/bin/python -m pip install \
    --index-url https://pypi.org/simple \
    --timeout 120 \
    --retries 5 \
    -e .

echo "Installing frontend dependencies..."
npm --prefix frontend ci \
    --prefer-offline \
    --no-audit \
    --no-fund

echo "Building frontend..."
npm --prefix frontend run build

echo "Restarting $SERVICE_NAME..."
sudo systemctl restart "$SERVICE_NAME"

for attempt in $(seq 1 45); do
    if curl --fail --silent --show-error \
        --output /dev/null \
        --max-time 5 \
        "$HEALTH_URL"; then
        echo "Deployment healthy at $(git rev-parse --short HEAD)."
        exit 0
    fi

    echo "Waiting for $SERVICE_NAME ($attempt/45)..."
    sleep 2
done

echo "Deployment failed: health check did not pass." >&2
sudo systemctl status "$SERVICE_NAME" --no-pager >&2 || true
sudo journalctl -u "$SERVICE_NAME" -n 100 --no-pager >&2 || true
exit 1
