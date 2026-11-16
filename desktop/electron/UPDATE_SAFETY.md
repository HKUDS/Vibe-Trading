# Signed Desktop updates

## Status

Settings now provides an explicit **Check for updates** action and, for a
configured packaged Windows build, **Update and restart**. There are no background
installs. Web uses the CLI's read-only PyPI check and shows instructions for the
server's installation type; it never runs pip inside a live server or container.

Desktop reuses `update-verification.ts`, `update-recovery.ts` and the owned-backend
shutdown boundary. The release channel remains **unconfigured** in this checkout:
no publisher certificate or release endpoint has been invented. Developer builds
and unsupported platforms show manual distributor instructions.

The existing 0.3.0 build has no update entry. Users must install the first
update-capable build through their original distributor; it cannot add an update
button to an already installed older binary.

`BackendManager.stopForUpdate()` is the required handoff boundary. It returns
only after the exact owned backend PID, watchdog PID, and loopback listener are
gone. Listener evidence uses a TCP connection probe rather than HTTP health, so
a process that accepts connections but stops answering HTTP remains open. A
failed handoff retains the exact identifiers and log stream for a later cleanup
retry. It never terminates `python.exe` by image name.

## Verification order

The caller must supply the installed version, candidate version, expected
SHA-256 digest, and an allowlist containing at least one publisher certificate
SHA-256 fingerprint. The policy fails closed when the allowlist is empty.

Checks run in this order:

1. policy and release metadata are well formed;
2. the candidate semantic version is strictly newer;
3. the local file digest matches the expected SHA-256;
4. PowerShell opens the artifact with a lock that permits readers but denies
   writers and deletion, hashes those locked bytes, and inspects Authenticode;
5. the locked digest matches the initial and expected digests;
6. Windows reports a `Valid` Authenticode signature;
7. the SHA-256 hash of the signer certificate's raw bytes is allowlisted;
8. the signed PE ProductVersion matches the advertised candidate version;
9. the file digest is confirmed again after the locked inspection.

The launch path calls
`assertVerifiedUpdateArtifactUnchanged()` immediately before starting the
installer. Verification and PowerShell discovery are both timeout-bounded. The
pre-launch assertion is mandatory even though the artifact was already checked:
no result object makes a mutable path permanently trustworthy.

The installed package owns `desktopUpdates.feedUrl` and
`desktopUpdates.allowedPublisherCertificateSha256` in `package.json`. The HTTPS
feed supplies `{ "version": "...", "url": "https://.../installer.exe", "sha256": "..." }`.
It cannot replace the publisher pins. Every redirect must stay HTTPS; metadata
and installer downloads have size and time limits. The exact reviewed release
is checked again before download. No installation URL comes from the renderer.

## Rejection matrix

| Scenario | Verification evidence | Stable result code | Required behavior |
| --- | --- | --- | --- |
| Tampered artifact | Local SHA-256 differs from release metadata | `artifact-hash-mismatch` | Do not launch; discard/quarantine the staged file |
| Unsigned artifact | Authenticode status is `NotSigned` | `artifact-unsigned` | Do not launch, even when the digest matches |
| Invalid or damaged signature | Authenticode status is not `Valid` or `NotSigned` | `artifact-signature-invalid` | Do not launch; record the Windows status for diagnostics |
| Wrong publisher | Signature is valid but certificate SHA-256 is not allowlisted | `publisher-not-allowed` | Do not launch; never trust the subject name alone |
| Signed version differs from feed | PE ProductVersion differs | `artifact-version-mismatch` | Reject before stopping the backend |
| Equal or downgraded version | Candidate is not strictly newer | `version-not-newer` | Do not download or launch |
| Missing publisher policy | Certificate allowlist is empty | `invalid-verification-policy` | Keep the updater disabled |
| Malformed version or digest | Release metadata is not valid | `invalid-release-metadata` | Reject before signature inspection |
| File or Authenticode inspection failure | Artifact cannot be read or Windows inspection fails | `artifact-inspection-failed` | Reject without launching |
| Artifact replaced during inspection | Locked Authenticode digest or post-inspection digest differs | `artifact-changed-during-verification` | Reject and require a fresh staged artifact |

The unsigned automated test uses injected Authenticode observations so every
branch is deterministic. The later signed end-to-end run must repeat the first
five rows with real Authenticode artifacts and the agreed publisher identity.

## Recovery journal

The updater advances only through these durable phases:

```text
verified -> backend-stopped -> installer-launched
```

- `verified`: the staged candidate passed the complete verification policy.
- `backend-stopped`: `stopForUpdate()` confirmed no owned PID or listener.
- `installer-launched`: handoff intent is durable before spawning the installer.
  It may be running even if the previous process never recorded an acknowledgement.
  Only an explicit spawn failure retracts it to `backend-stopped`, allowing
  normal cleanup and backend restart; an interrupted/unknown handoff still
  requires manual resolution.

On the next application start, the journal is checked before starting Python.
An uncertain installer handoff blocks an old backend from starting under file
replacement. Completion is recorded only after the target backend is healthy:

| Installed version | Last phase | Recovery result |
| --- | --- | --- |
| Target version | Any | Mark complete; remove journal and staged candidate |
| Original version | `verified` | Discard staged candidate; no shutdown occurred |
| Original version | `backend-stopped` | Treat as interrupted before installer; discard and require fresh verification |
| Original version | `installer-launched` | Preserve journal/artifact; finish or close the installer and repair the installation before clearing the journal |
| Any third version | Any | Leave journal and artifact untouched; require manual intervention |
| Malformed journal | Unknown | Leave it untouched; require manual intervention |

The journal stores a simple `.exe` file name inside its dedicated staging
directory. Malformed or traversal paths are never followed for deletion. A
begin operation fsyncs a complete same-directory temporary file and publishes
it with an atomic hard-link create-if-absent operation. Concurrent begins can
therefore never overwrite one another. Later phase writes retain the
same-directory rename path.

Verified and pre-installer attempts can return to a clean retry state. An
installer handoff on the old version requires manual resolution because the
absence of a version change does not prove that the installer has exited. It does **not** claim rollback of a partially
modified installation. That remains part of the real signed NSIS interruption
test required by #1016.

## Automated checks

From `desktop/electron`:

```powershell
npm run test:update-safety
npm run smoke:lifecycle
npm run smoke:parent-death
```

The lifecycle tests start an unrelated Python sentinel before stopping the
desktop-owned backend. The sentinel must still be alive after graceful and
forced-parent-death cleanup, while the owned Python PID and listener must be
gone. The update-safety test also holds open a TCP listener that never answers
HTTP, proves shutdown fails closed while retaining the exact identifiers, then
closes the listener and proves a second cleanup attempt succeeds. It races two
journal begins and requires exactly one durable winner, and mutates an artifact
during and after verification to exercise both integrity gates.

## Remaining enablement gates

- maintainer-owned Authenticode identity and certificate lifecycle;
- maintainer-owned release feed and authenticated metadata policy;
- real signed `0.3.0 -> 0.3.1` clean-Windows upgrade;
- preserved settings and `safeStorage` credential validation;
- real interrupted NSIS recovery validation;
- the rejection matrix repeated with real signed and tampered artifacts.

Do not distribute an update-enabled build until these release checks pass.
The local source implementation and injected-signature tests are not evidence
of a successful signed Windows installation.

## Publishing the feed

1. Keep the existing `appId`, `productName`, installation account and data paths.
2. Configure the HTTPS feed URL and trusted signing-certificate SHA-256 pins in
   `package.json` **before building the first update-capable release**.
3. Build with the existing signing variables and
   `VIBE_TRADING_DESKTOP_UPDATE_ARTIFACT_URL` set to the intended HTTPS installer URL.
   `npm run installer:win:signed` verifies signatures, publisher and signed version,
   then writes `release/desktop-update.json` beside `SHA256SUMS.txt`.
4. Publish the immutable installer first, then the generated manifest at the feed
   URL. Packaging never uploads either. Keep old pins until every installed build
   can trust a new signing certificate.

## Data preservation

The installer replaces the application and bundled backend. The updater never
rewrites `.env`, credentials, sessions or workspace files, and NSIS explicitly
keeps application data on uninstall. The secure store remains
`userData/credentials.v1.json`, with the same OS user and application identity;
the backend keeps the same runtime root, including any `VIBE_TRADING_HOME` override.
The updater refuses relative runtime overrides and data directories resolving
inside the program directory. Keep user data outside program files; do not
relocate data as part of an update.

A failed download or verification leaves the backend running. A failed handoff
cleans only its own staged artifact and restarts the existing backend. Once the
installer launches, Desktop exits and lets NSIS replace and reopen the app.
The next successful backend startup reconciles the journal. It does not restore
an old copy over newer user data or promise rollback after a partial NSIS failure.
Finish active work first; existing session checkpoints handle interrupted replies.

## Local validation (2026-11-14)

- Old source `dbff8165f` and the new source ran in separate processes against an
  isolated profile. Old encrypted credentials decrypted in a new native macOS
  Electron process; config and encrypted file bytes remained identical.
- The old API created a session. Old storage code persisted history, reasoning,
  tool trail and a partial-response checkpoint. The new API read the completed
  history unchanged and recovered the checkpoint as an interrupted reply.
- The actual Desktop main/preload IPC ran in a native Electron development host,
  reading the old encrypted credential and sessions. It correctly reported Desktop
  0.3.1 and the unsupported/unconfigured-channel guidance, separately from the
  Python backend version. This did not execute an NSIS installer.
- A real PyPI request and Web Settings click reported the running version and
  source-install guidance. These are live local checks, **not a Windows installer
  upgrade**. Signed Windows replacement, UAC, relaunch and interrupted NSIS still
  require the actual publisher artifacts and a Windows environment.

## Focused review after Desktop isolation (2026-11-14)

The Mac DMG/icon/startup experiment remains on `codex/macos-desktop-experiment`;
this branch keeps the existing Windows update transport and Web version checks.
Unreadable credential ciphertext now fails before dotenv migration, preserving
both copies for recovery. No plaintext fallback or new credential format was
introduced. The installation/data path guard also resolves existing symlink or
junction parents when a data subdirectory does not exist yet.

The real old-to-new credential/configuration/session fixture is reused for
validation. Signed Windows installer replacement remains unverified on this Mac;
the release feed and publisher pins remain unconfigured. Local checks do not
claim an enabled public automatic-update channel.

Verified in this review: 177 Python checks passed (7 optional cases skipped),
the 2 Web update-card cases passed, and TypeScript/update-safety checks passed.
Real Electron read the old credential fixture without changing ciphertext or
configuration bytes; a live current API retained saved messages, reasoning,
tool trails and interrupted-attempt recovery. A hidden native Electron run
through the actual main/preload entry showed the pending-installer error,
retained the journal/artifact and did not start a backend. No new Mac UI or
packaging feature was brought back for these checks.

Follow-up recovery review: initial credential decryption failure exits the host
so a repaired/unlocked store can be relaunched without an orphan single-instance
lock. Decryption failure during backend restart uses the existing visible error
and retry path. A native main/preload/backend run verified that recovery leaves
configuration and ciphertext unchanged and starts a new backend. The compiled
installer handoff also recovered from a real OS spawn rejection (EACCES), with
release/signature transport simulated; signed Windows acceptance is still open.
