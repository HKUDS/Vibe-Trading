# Desktop Process-Boundary Threat Model

## Scope

This document covers the Electron main process, its sandboxed renderer, and the
single Vibe-Trading Python process started by the shell. The Windows packaging
layer additionally covers local credential encryption, migration, and
injection into that owned Python process. Auto-update, optional messaging
adapters, personal WeChat pairing, broker configuration, and release ownership
remain outside this change.

Dormant update-safety primitives are in scope only as a reviewable boundary:
they inspect a caller-supplied local artifact, apply a fail-closed policy, and
record/recover a staged attempt. No release feed, downloader, installer launch,
or default-enabled updater exists.

## Assets

- The per-launch API authentication secret.
- Local Vibe-Trading sessions, reports, configuration, and research data.
- Any credentials already present in the environment inherited by the Python
  process.
- LLM, Tushare, and Gildata credentials managed by the desktop host.
- The integrity of the executable selected as the backend.
- The ability to invoke authenticated local API routes.
- Future update publisher policy, release digest metadata, and the integrity of
  a staged installer.
- The pending-update journal used to distinguish completed and interrupted
  attempts.

## Trust boundaries

```text
Electron main process
  |-- owns random API secret
  |-- owns safeStorage encryption/decryption
  |-- selects backend executable and starts watchdog
  |-- injects Authorization on one loopback origin
  |
  +--> sandboxed renderer
  |      no Node.js, isolated context, deny-by-default permissions
  |      can use the authenticated local API through normal page requests
  |      can set or clear allowlisted credentials, but cannot read them
  |
  +--> backend parent-death watchdog
         |-- inherits the launch secret and decrypted credentials only to pass them to Python
         |-- exits without spawning Python if the parent is already gone
         |-- monitors Electron IPC disconnect and parent PID liveness
         +--> Python backend
                binds 127.0.0.1:<random-port>
                receives API_AUTH_KEY through its child environment
                receives decrypted credentials through its child environment
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
- The preload exposes status, error, retry, log-folder, backend-restart, and
  allowlisted credential-write operations. Credential values are never
  returned to the renderer.
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
- Graceful update handoff returns structured evidence for the exact owned
  backend PID, watchdog PID, and listener. The listener check probes TCP rather
  than HTTP responsiveness. It fails closed if any remains and retains the
  ownership state for a later cleanup retry.
- Graceful and parent-death tests each start an unrelated Python sentinel and
  verify that it remains alive; termination commands are always PID-scoped and
  never use an image name such as `python.exe`.

### Dormant update verification and recovery

- Candidate release and installed versions must be valid semantic versions,
  and the candidate must be strictly newer.
- The artifact SHA-256 must match caller-supplied release metadata before its
  signature is considered.
- The production Authenticode adapter holds a read-only Windows file lock that
  denies writers and deletion while it hashes and inspects the same artifact.
  Its locked digest and a post-inspection digest must both match release
  metadata.
- Windows Authenticode status must be `Valid`; unsigned and invalid signatures
  are rejected with stable codes.
- Publisher identity uses an explicit allowlist of SHA-256 hashes of signer
  certificate raw bytes. Subject display names alone are not trusted.
- No publisher is currently configured. An empty allowlist is itself a policy
  error, so these primitives cannot silently trust the first certificate seen.
- A pending-attempt journal is fsynced to a same-directory temporary file. Its
  first publication uses an atomic hard-link create-if-absent operation, so two
  concurrent begins cannot replace one another; later phase changes use the
  existing same-directory rename path. It records only a simple staged `.exe`
  file name, not an arbitrary deletion path.
- On the next launch, an attempt that still reports the old version discards
  the staged candidate and requires a fresh download and verification. A
  successful target version clears the journal. Any third version or malformed
  journal is left untouched for explicit operator intervention.
- The allowed phase order is `verified` -> `backend-stopped` ->
  `installer-launched`. A future updater must call the strict backend shutdown
  path before recording `backend-stopped`, and must re-hash the verified
  artifact immediately before installer launch.
- PowerShell host discovery and Authenticode inspection have hard timeouts; a
  hung host rejects the candidate rather than blocking Electron indefinitely.

### Credential storage

- Credential names are checked against a fixed allowlist in the Electron main
  process.
- Values are encrypted and decrypted only through Electron `safeStorage`.
- The on-disk JSON file contains only Base64-encoded ciphertext and the list of
  configured names.
- Writes use a same-directory temporary file followed by rename.
- Existing supported values in `~/.vibe-trading/.env`
  are migrated once; the corresponding plaintext field is removed after the
  encrypted store has been persisted.
- Decrypted values are injected only into the owned backend child environment.
- Desktop secure mode prevents settings API writes from copying injected
  secrets back into dotenv.
- The credential smoke test uses an isolated temporary profile and verifies
  migration, persistence, plaintext removal, allowlisting, replacement, and
  clearing.

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
- A compromised renderer can overwrite or clear an allowlisted credential even
  though it cannot retrieve the current value.
- `safeStorage` protects data at rest for the current Windows user; it does not
  protect against malware, a debugger, or another process already executing
  with equivalent user privileges.
- Migration cannot erase plaintext that may remain in backups, filesystem
  history, crash dumps, or external logs.
- The child inherits both the desktop process environment and decrypted
  credentials required by the backend.
- Forceful tree termination can interrupt in-progress local work after the
  graceful shutdown timeout.
- The verification policy receives its expected digest and certificate
  allowlist from a future trusted release configuration. Feed ownership and
  metadata authenticity are unresolved, so no runtime caller is wired today.
- Recovery proves safe journal and staged-file handling. It does not claim to
  roll back an installer that has already partially modified application files;
  the signed end-to-end NSIS test remains required.
- The review installer is deliberately unsigned and unpublished. This change
  does not provide a signing identity, installer reputation, update
  authenticity, or an official HKUDS release channel.

## Non-goals

- Protecting against a fully compromised Windows account or administrator.
- Enabling remote API access.
- Managing broker, exchange, or IM credentials.
- Exposing credential values back to the renderer.
- Publishing releases, choosing a signing identity, or updating the
  application.
