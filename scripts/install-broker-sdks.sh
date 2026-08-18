#!/bin/sh
# ---------------------------------------------------------------------------
# install-broker-sdks.sh — one-shot bootstrap for optional broker SDKs that
# are not part of the hash-pinned base requirements lock. Runs at container
# start (via docker-compose command override) so a fresh build picks them up
# without needing to modify the project's requirements.txt/lock files.
#
# Idempotent: skips install if the SDK is already importable.
# Runs as root inside the container (entrypoint is launched as root; the
# entrypoint itself drops to the `vibe` user before exec'ing the server).
# ---------------------------------------------------------------------------
set -eu

VENV=/opt/venv
PY="$VENV/bin/python"

require_sdk() {
    module="$1"
    pkg="$2"
    if "$PY" -c "import $module" >/dev/null 2>&1; then
        echo "[broker-sdks] $module already present, skipping $pkg"
    else
        echo "[broker-sdks] installing $pkg for $module"
        "$VENV/bin/pip" install --no-cache-dir "$pkg"
    fi
}

# Futu (moomoo) — needed for live-readonly profile + all extended read
# endpoints (get_rehab, get_capital_flow, get_history_deals, etc.). Pin to
# the same major version the SDK was installed against during initial
# bring-up (10.10.x); upgrades should be deliberate and re-tested.
require_sdk "futu" "futu-api==10.10.*"

# Add more brokers here as needed, e.g.:
#   require_sdk "ib_insync" "ib_insync"
#   require_sdk "tigeropen" "tigeropen"

echo "[broker-sdks] done"