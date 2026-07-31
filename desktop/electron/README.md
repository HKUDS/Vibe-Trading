# Vibe-Trading Desktop (Unofficial Community Build)

This directory contains a source-only Electron host for the existing
Vibe-Trading FastAPI and React application. It does not contain an installer,
an embedded Python runtime, credential storage, an updater, or changes to the
agent, provider, session, frontend model UX, or messaging-channel code.

## What the shell does

- Enforces a single desktop application instance.
- Starts one owned `vibe-trading serve` process.
- Selects a free loopback port and binds the backend to `127.0.0.1`.
- Generates a 256-bit authentication secret for each desktop process.
- Adds the secret to same-origin renderer requests without exposing its value
  to page JavaScript.
- Waits for the authenticated `/health` endpoint before loading the UI.
- Captures backend output in Electron's per-user log directory.
- Reports startup failures and exposes retry and log-folder actions.
- Requests authenticated graceful shutdown before terminating the owned
  Windows process tree as a fallback.
- Prevents in-window navigation away from the local backend origin.

See [THREAT_MODEL.md](THREAT_MODEL.md) for the trust boundary and residual
risks. See [REVIEW_NOTES.md](REVIEW_NOTES.md) for the file inventory and
validation ledger.

## Run from source

From a complete Vibe-Trading checkout:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .

cd frontend
npm ci
npm run build

cd ..\desktop\electron
npm ci
npm start
```

The shell searches for a repository `.venv\Scripts\vibe-trading.exe` before
falling back to `vibe-trading.exe` on `PATH`. To select an explicit development
backend:

```powershell
$env:VIBE_TRADING_EXECUTABLE = "C:\path\to\vibe-trading.exe"
npm start
```

## Review scope

This first change intentionally excludes:

- Electron Builder, NSIS, release workflows, and embedded Python;
- `safeStorage`, credential migration, and settings UI changes;
- update checks or release-feed configuration;
- provider/model discovery and response metadata;
- optional IM adapters and personal WeChat pairing;
- changes outside `desktop/`, except the two generated-output entries in the
  repository `.gitignore`.

The desktop shell remains unofficial. No release or distribution ownership is
implied by this source directory.
