# Windows packaging review notes

This layer is stacked on the desktop lifecycle shell and adds only:

- an NSIS x64 installer;
- a checksum-pinned CPython 3.12.10 embedded runtime;
- the existing production frontend and the upstream hash-locked base Python
  dependencies;
- the verified native DLL subset required for WeasyPrint PDF output;
- Electron `safeStorage` for LLM, Tushare, and QVeris credentials.

## Deliberate exclusions

- No updater or release feed is included.
- No optional IM/channel extra is installed.
- Personal WeChat/Weixin QR pairing is not included.
- No broker-specific optional dependency is installed.
- The review workflow produces an unsigned artifact only; it does not publish a release.

Users can install an optional adapter later from a source/developer environment.
The desktop runtime does not expose a package installer UI in this change.

## Build

From a complete checkout of the current upstream source:

```powershell
cd frontend
npm ci
npm run build

cd ..\desktop\electron
npm ci
npm run smoke:credentials
npm run runtime:win -- -Clean
npm run smoke:lifecycle
npm run installer:win:review
```

The installer and checksum are written under `desktop/electron/release/`.
The `installer:win:review` artifact is deliberately unsigned and must never be
published to users. The command strips all supported signing credentials,
disables certificate auto-discovery, and fails unless both the application
executable and installer report `NotSigned`. Both review and signed builds use
Electron Builder's supported compression-level override at level 7 to bound
build time without changing installed build-tool code.
Python dependencies are installed from
`desktop/electron/requirements-windows-lock.txt` with `--require-hashes`; the
checked-out Vibe-Trading package is then installed with `--no-deps` so
packaging cannot silently resolve versions outside that lock.

The repository-root lock is generated for the upstream Linux environment and
contains platform-specific dependencies such as `uvloop`. It cannot be reused
for the Windows runtime. Regenerate the Windows lock only on Windows with
Python 3.12, from the base requirements (not an optional IM extra):

```powershell
python -m pip install pip-tools
python -m piptools compile --generate-hashes --allow-unsafe --resolver=backtracking --output-file=desktop/electron/requirements-windows-lock.txt agent/requirements.txt
```

## Credential boundary

The renderer can request a write only for an allowlisted credential name.
Encryption and decryption happen in the Electron main process. On Windows,
Electron `safeStorage` uses the operating-system encryption facility for the
current user. Decrypted values are injected only into the child backend
environment and are not returned to the renderer.

On first startup, supported secrets in `~/.vibe-trading/.env` and the QVeris
API key in `~/.vibe-trading/qveris.json` are migrated into encrypted storage.
The plaintext fields are then removed. Backend settings writes in desktop
secure mode explicitly blank known credential fields instead of writing the
injected values back to dotenv.

## Unsigned limitation

Local and pull-request artifacts are unsigned. Windows SmartScreen may warn
when they are launched. Code signing and release ownership remain with the
community publisher unless HKUDS explicitly takes them over later.

There is intentionally no generic `installer:win` command. A publishable build
must use:

```powershell
$env:WIN_CSC_LINK = 'C:\secure-location\publisher-certificate.pfx'
$env:WIN_CSC_KEY_PASSWORD = '<provided outside source control>'
npm run installer:win:signed
```

The signed command fails closed when either signing input is missing and then
enables Electron Builder's `forceCodeSigning` gate. It then verifies that
Windows reports both the packaged application executable and the resulting
installer's Authenticode status as `Valid`. The certificate and password must
come from CI secrets or an equivalent external secret store; they must never
be committed. The generic `CSC_LINK` and `CSC_KEY_PASSWORD` names remain
supported as fallbacks. This PR does not add a release workflow or upload an
artifact.

## Dependency-audit note

`npm audit --omit=dev` reports zero production dependency vulnerabilities.
Electron Builder is a build-time-only development dependency and its current
transitive tree reports high-severity audit findings in glob/minimatch-related
tooling. Those packages are not copied into the packaged application, but the
review workflow still treats the lockfile as trusted build input. This should
be re-audited whenever Electron Builder publishes a repaired dependency tree.

## CI build-host note

The packaging job is pinned to GitHub's clean `windows-2022` image. The
checksum-pinned GTK runtime installer used solely to extract WeasyPrint's
native DLL subset exits with an access violation on the Server 2025 runner,
although the extracted runtime and packaged application work on current
Windows 10/11 hosts. Moving that native dependency to a newer, directly
extractable upstream archive is a follow-up; silently dropping PDF support or
accepting an unverified binary is not.

## Local validation record

Windows host validation on 2026-08-08 against the current upstream
`vibe-trading-ai` 0.1.13 source:

- [x] all 183 installed third-party Python distributions exactly match the
  committed Windows lock; the checked-out `vibe-trading-ai` package is the only
  additional distribution;
- [x] `pip check` confirms that the locked runtime satisfies the checked-out
  project dependency metadata;
- [x] embedded Python reports version 3.12.10;
- [x] backend, CLI, and WeasyPrint PDF imports succeed;
- [x] DingTalk, Discord, Telegram, Neonize/WeChat, and QR-code modules are
  absent;
- [x] authenticated random-port startup and graceful shutdown succeed with no
  residual embedded Python process;
- [x] the exact packaged application loads the current production frontend and
  embedded backend, then removes the Python child and loopback listener when
  only the Electron main PID is force-terminated;
- [x] safeStorage migration, plaintext removal, allowlisting, replacement, and
  clearing succeed against an isolated temporary Windows profile;
- [ ] the exact current branch's packaged application loads the frontend and
  backend on a clean Windows VM and closes its owned process tree cleanly;
- [x] the generated installer is reported as `NotSigned` by Windows
  Authenticode inspection;
- [x] the unsigned review installer is 324.3 MiB and its generated
  `SHA256SUMS.txt` matches an independent SHA-256 calculation
  (`173f353fcb8517e9caaf3c715222d619c010bc615823df5e2ee414ace297783b`).

The assembled backend is 804.9 MiB before installer compression. An earlier
prototype passed the isolated-profile startup/shutdown check, but that result
predates the current-main rebuild and is deliberately not credited above. A
clean Windows VM re-run remains a release/review gate; this host record is not
a substitute for that independent environment check.
