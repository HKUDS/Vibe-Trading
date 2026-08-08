# Desktop Process-Boundary Threat Model

## Scope

This document covers the Electron main process, its sandboxed renderer, and the
single Vibe-Trading Python process started by the shell. Packaging, credential
storage, auto-update, optional messaging adapters, broker configuration, and
code signing are outside this change.

## Assets

- The per-launch API authentication secret.
- Local Vibe-Trading sessions, reports, configuration, and research data.
- Any credentials already present in the environment inherited by the Python
  process.
- The integrity of the executable selected as the backend.
- The ability to invoke authenticated local API routes.

## Trust boundaries

```text
Electron main process
  |-- owns random API secret
  |-- selects backend executable and starts watchdog
  |-- injects Authorization on one loopback origin
  |
  +--> sandboxed renderer
  |      no Node.js, isolated context, deny-by-default permissions
  |      can use the authenticated local API through normal page requests
  |
  +--> backend parent-death watchdog
         |-- inherits the launch secret only to pass it to Python
         |-- exits without spawning Python if the parent is already gone
         |-- monitors Electron IPC disconnect and parent PID liveness
         +--> Python backend
                binds 127.0.0.1:<random-port>
                receives API_AUTH_KEY through its child environment
```

The renderer is trusted to perform the same application actions as the web UI,
but it is not given the raw authentication secret. A renderer compromise can
still call authenticated API routes through the Electron session and is
therefore security-significant.

## Controls

### Loopback and authentication

- The backend is launched with `--host 127.0.0.1`.
- A free ephemeral port is selected for every backend start.
- The secret is 32 cryptographically random bytes encoded with Base64URL.
- The secret exists only in Electron main-process memory and the owned
  watchdog/Python child environments. It is not written to logs,
  configuration, or renderer storage.
- Electron adds `Authorization: Bearer <secret>` only when the request origin
  exactly matches the active backend origin.
- Health and shutdown requests are authenticated.
- A new desktop process receives a new secret, so any stale value is invalid
  after exit.

### Renderer

- `nodeIntegration` is disabled.
- `contextIsolation` and Chromium sandboxing are enabled.
- The preload exposes only status, error, retry, log-folder, and backend-restart
  operations.
- Browser permission checks and requests are denied by default.
- New windows are denied; safe HTTP(S) links are opened in the system browser.
- In-window navigation is restricted to the active local backend origin.
- Developer tools are unavailable when Electron reports a packaged build.
- Renderer traffic uses an isolated persistent Electron partition rather than
  the default browser session.

### Backend executable resolution

- `VIBE_TRADING_EXECUTABLE`, when it names an existing file, is an explicit
  operator override and takes precedence.
- Packaged-runtime discovery checks only exact paths anchored to Electron's
  application and resources directories, including fixed `app` and `resources`
  subtrees. It does not walk their ancestors.
- Source-mode discovery is disabled for packaged applications. During source
  development, an ancestor is accepted only when its `pyproject.toml` contains
  `[project].name = "vibe-trading-ai"`; only that marked root's
  `.venv\Scripts\vibe-trading.exe` is eligible.
- The final fallback checks non-empty `PATH` entries for `vibe-trading.exe`.
- No generic executable candidate is evaluated while walking ancestors, and
  the filesystem drive root is never treated as a source-project root.

### Process lifecycle

- Only one desktop application instance is allowed.
- Standard output and standard error are appended to a per-user Electron log.
- Startup waits for authenticated health success and reports early process exit
  with a bounded log tail.
- Electron starts a small watchdog before the Python backend. The watchdog
  verifies that the Electron main PID is alive before spawning Python.
- The watchdog retains an IPC channel to Electron and also polls the exact
  parent PID. An IPC disconnect or dead parent PID triggers Windows
  `taskkill /T /F` against the Python process tree without relying on an
  Electron JavaScript shutdown callback.
- Normal shutdown first calls the authenticated backend shutdown route. If the
  backend remains alive, Electron asks the watchdog to terminate it and finally
  retains process-tree termination as a bounded fallback.
- The automated parent-death smoke test terminates only the Electron main PID,
  then independently verifies that both the Python PID and loopback listener
  are gone.

## Residual risks

- Renderer script injection can exercise the authenticated API even though it
  cannot read the raw secret.
- A local administrator, debugger, or process with equivalent user privileges
  may inspect the Electron, watchdog, or Python process and its environment.
- Port discovery closes the probe socket before Python binds it. Another local
  process can win that race, causing startup failure; it does not receive the
  authentication secret.
- The development override `VIBE_TRADING_EXECUTABLE` trusts the explicitly
  selected executable. Users must not point it at untrusted code.
- The `PATH` fallback trusts the desktop process environment and normal Windows
  executable-path integrity. A process able to alter that environment can
  select the backend that receives the launch secret.
- The child inherits the desktop process environment. Secure credential
  isolation is deferred to the packaging/credential-storage review.
- Forceful tree termination can interrupt in-progress local work after the
  graceful shutdown timeout.
- This source-only change does not provide code signing, installer reputation,
  update authenticity, or an official HKUDS release channel.

## Non-goals

- Protecting against a fully compromised Windows account or administrator.
- Enabling remote API access.
- Managing broker, exchange, IM, or model-provider credentials.
- Installing or updating the application.
