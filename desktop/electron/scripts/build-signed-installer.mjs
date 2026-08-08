import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const electronRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const signaturePowerShell = resolveSignaturePowerShell();
const certificate = (process.env.WIN_CSC_LINK ?? process.env.CSC_LINK)?.trim();
const password = process.env.WIN_CSC_KEY_PASSWORD ?? process.env.CSC_KEY_PASSWORD;

if (!certificate || password === undefined) {
  throw new Error(
    "Signed packaging requires WIN_CSC_LINK/WIN_CSC_KEY_PASSWORD " +
      "(or their CSC_LINK/CSC_KEY_PASSWORD fallbacks). " +
      "Use installer:win:review for a local, non-publishable unsigned artifact.",
  );
}

const npmCli = process.env.npm_execpath;
if (!npmCli) {
  throw new Error("Signed packaging must be launched through npm.");
}
run(process.execPath, [npmCli, "run", "build"]);
run(process.execPath, [npmCli, "run", "prepare:electron"]);
run(
  process.execPath,
  [
    path.join(electronRoot, "node_modules", "electron-builder", "cli.js"),
    "--publish",
    "never",
    "--win",
    "nsis",
    "--config.win.forceCodeSigning=true",
  ],
  {
    env: {
      ...process.env,
      CSC_IDENTITY_AUTO_DISCOVERY: "true",
      ELECTRON_BUILDER_COMPRESSION_LEVEL: "7",
    },
  },
);

const releaseDirectory = path.join(electronRoot, "release");
const installers = (await readdir(releaseDirectory, { withFileTypes: true }))
  .filter(
    (entry) =>
      entry.isFile() &&
      /^Vibe-Trading-Desktop-Unofficial-.*-x64\.exe$/u.test(entry.name),
  )
  .map((entry) => path.join(releaseDirectory, entry.name));

if (installers.length !== 1) {
  throw new Error(`Expected one signed installer, found ${installers.length}.`);
}

const unpackedDirectory = path.join(releaseDirectory, "win-unpacked");
const applicationExecutables = (await readdir(unpackedDirectory, { withFileTypes: true }))
  .filter((entry) => entry.isFile() && entry.name.toLowerCase().endsWith(".exe"))
  .map((entry) => path.join(unpackedDirectory, entry.name));
if (applicationExecutables.length !== 1) {
  throw new Error(
    `Expected one top-level packaged application executable, found ${applicationExecutables.length}.`,
  );
}

for (const artifact of [...applicationExecutables, ...installers]) {
  console.log(`Authenticode signature verified: ${verifySignature(artifact)}`);
}
const installerHash = await sha256(installers[0]);
await writeFile(
  path.join(releaseDirectory, "SHA256SUMS.txt"),
  `${installerHash}  ${path.basename(installers[0])}\n`,
  "ascii",
);
console.log(`Signed installer ready: ${installers[0]}`);
console.log(`SHA-256: ${installerHash}`);

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: electronRoot,
    stdio: "inherit",
    ...options,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${path.basename(command)} exited with code ${result.status}`);
  }
}

function verifySignature(artifact) {
  const signatureCheck = spawnSync(
    signaturePowerShell,
    [
      "-NoProfile",
      "-NonInteractive",
      "-Command",
      [
        "$signature = Get-AuthenticodeSignature -LiteralPath $env:VIBE_SIGNED_ARTIFACT_PATH",
        "if ($signature.Status -ne 'Valid') {",
        "  throw \"Artifact signature is $($signature.Status): $($signature.StatusMessage)\"",
        "}",
        "$signature.SignerCertificate.Subject",
      ].join("; "),
    ],
    {
      cwd: electronRoot,
      env: {
        ...process.env,
        VIBE_SIGNED_ARTIFACT_PATH: artifact,
      },
      encoding: "utf8",
    },
  );
  if (signatureCheck.status !== 0) {
    throw new Error(signatureCheck.stderr.trim() || signatureCheck.stdout.trim());
  }
  return `${path.basename(artifact)} — ${signatureCheck.stdout.trim()}`;
}

function resolveSignaturePowerShell() {
  const candidates = [
    process.env.ProgramFiles
      ? path.join(process.env.ProgramFiles, "PowerShell", "7", "pwsh.exe")
      : undefined,
    "pwsh.exe",
    "powershell.exe",
  ].filter(Boolean);
  const failures = [];
  for (const candidate of new Set(candidates)) {
    const probe = spawnSync(
      candidate,
      [
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "Get-Command Get-AuthenticodeSignature -ErrorAction Stop | Out-Null",
      ],
      { encoding: "utf8", windowsHide: true },
    );
    if (!probe.error && probe.status === 0) return candidate;
    failures.push(`${candidate}: ${probe.error?.message ?? probe.stderr.trim()}`);
  }
  throw new Error(`No PowerShell host can load Get-AuthenticodeSignature.\n${failures.join("\n")}`);
}

async function sha256(file) {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(file)) hash.update(chunk);
  return hash.digest("hex");
}
