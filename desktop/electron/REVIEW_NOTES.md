# Desktop Shell Review Notes

## Upstream baseline

- Repository: `HKUDS/Vibe-Trading`
- Baseline commit: `715ea33b664a0eb55e413cbdef950e0bbb1ee7f3`
- Baseline version metadata: `0.1.12`
- Rebuilt directly from current upstream `main`; no `0.1.11` source overlay is
  included.

## File inventory

```text
.gitignore
desktop/electron/
  README.md
  REVIEW_NOTES.md
  THREAT_MODEL.md
  package.json
  package-lock.json
  tsconfig.json
  scripts/
    copy-static.mjs
    smoke-lifecycle.mjs
  src/
    backend-manager.ts
    loading.html
    main.ts
    preload.ts
```

No agent, provider, session, frontend, channel, packaging, credential-storage,
or updater file is changed.

## Dependency and license review

Commands:

```powershell
npm ci
npm ls --all --json
npm audit --json
npm sbom --sbom-format cyclonedx
```

Host result on 2026-07-28:

- 14 installed dependency packages;
- 0 known npm audit vulnerabilities;
- no production JavaScript dependencies;
- direct development dependencies: Electron 43.1.1, TypeScript 5.9.3, and
  `@types/node` 24.13.3.

Observed package licenses:

| License | Packages |
| --- | --- |
| MIT | `@electron/get`, `@types/node`, `debug`, `electron`, `env-paths`, `ms`, `progress`, `undici`, `undici-types` |
| ISC | `graceful-fs`, `semver` |
| Apache-2.0 | `sumchecker`, `typescript` |
| BSD-2-Clause | `@electron-internal/extract-zip` |

The CycloneDX JSON output is generated from the committed lock file for PR
review rather than hand-maintained. Electron's Chromium/Node third-party
notices become a packaging deliverable and are intentionally deferred.

## Validation ledger

Host development validation on Windows:

- [x] `npm ci`
- [x] `npm run build`
- [x] `npm audit` reports zero vulnerabilities
- [x] TypeScript strict compilation
- [x] current-upstream backend starts on a random `127.0.0.1` port
- [x] unauthenticated protected route returns HTTP 401
- [x] authenticated health and protected-route requests succeed
- [x] graceful shutdown stops the listener and leaves no owned Python process
- [ ] clean-Windows source startup from a restored VM snapshot
- [ ] forced child-process-tree cleanup scenario
- [ ] repeated startup/shutdown process-residue check
- [ ] missing-backend startup diagnostics

The unchecked clean-machine items must be completed and recorded in the pull
request before requesting final review.

## Unsigned-build limitations

This change is source-only and intentionally produces no installer. A later
packaging review must cover Authenticode signing, installer reputation, bundled
license notices, Python SBOM, update authenticity, and release ownership.
Nothing in this change creates or claims an HKUDS release channel.
