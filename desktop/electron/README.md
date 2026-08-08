# Vibe-Trading Desktop (Unofficial Community Build)

This directory contains an Electron host for the existing Vibe-Trading FastAPI
and React application. The Windows packaging layer can assemble an unsigned
NSIS review artifact or require and verify Authenticode signing for a
publishable installer. Both use an isolated Python runtime and encrypted
credential storage. This layer does not contain an updater, optional IM
adapters, personal WeChat pairing, or changes to the agent loop and provider
behavior.

## What the shell does

- Enforces a single desktop application instance.
- Starts one owned `vibe-trading serve` process through a parent-death
  watchdog.
- Selects a free loopback port and binds the backend to `127.0.0.1`.
- Generates a 256-bit authentication secret for each desktop process.
- Adds the secret to same-origin renderer requests without exposing its value
  to page JavaScript.
- Waits for the authenticated `/health` endpoint before loading the UI.
- Captures backend output in Electron's per-user log directory.
- Reports startup failures and exposes retry and log-folder actions.
- Requests authenticated graceful shutdown before asking the watchdog to
  terminate the owned Windows process tree as a fallback.
- Terminates the Python process tree if the Electron main process is killed
  without running JavaScript shutdown handlers.
- Localizes desktop-owned loading, status, error, dialog, and menu text in
  English, Simplified Chinese, Japanese, Korean, and Arabic, including RTL
  loading-page layout for Arabic.
- Prevents in-window navigation away from the local backend origin.

See [THREAT_MODEL.md](THREAT_MODEL.md) for the trust boundary and residual
risks. See [REVIEW_NOTES.md](REVIEW_NOTES.md) for the file inventory and
validation ledger. See [WINDOWS_PACKAGING.md](WINDOWS_PACKAGING.md) for the
packaging-specific boundary and build commands.

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

The Windows lifecycle suite used by CI can be run from the same directory:

```powershell
npm run smoke:lifecycle
```

It verifies localized message parity, graceful shutdown, authentication, and
the parent-death path by force-terminating only the Electron main PID before
checking that the Python process and loopback listener are gone.

Backend resolution is intentionally narrow. It checks an explicit
`VIBE_TRADING_EXECUTABLE` override first, then exact application/resource
locations used by packaged builds. In source mode only, it may use
`.venv\Scripts\vibe-trading.exe` from an ancestor containing this project's
`pyproject.toml` (`[project].name = "vibe-trading-ai"`). Its final fallback is
`vibe-trading.exe` on `PATH`; arbitrary ancestor directories and the drive root
are never searched for executables. To select an explicit development backend:

```powershell
$env:VIBE_TRADING_EXECUTABLE = "C:\path\to\vibe-trading.exe"
npm start
```

## Review scope

The desktop lifecycle shell and Windows packaging are kept as separate review
layers. The packaging layer adds Electron Builder, an unsigned NSIS review
artifact, a checksum-pinned CPython 3.12.10 base runtime, and `safeStorage`
credential migration.

It intentionally excludes:

- update checks or release-feed configuration;
- provider/model discovery and response metadata;
- optional IM adapters and personal WeChat pairing;
- broker-specific optional packages.

The desktop shell remains unofficial. No release or distribution ownership is
implied by this source directory.
