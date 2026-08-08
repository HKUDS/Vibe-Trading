import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const electronRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const signaturePowerShell = resolveSignaturePowerShell();
const unsignedEnvironment = { ...process.env };
for (const name of [
  "CSC_LINK",
  "CSC_KEY_PASSWORD",
  "WIN_CSC_LINK",
  "WIN_CSC_KEY_PASSWORD",
  "AZURE_TENANT_ID",
  "AZURE_CLIENT_ID",
  "AZURE_CLIENT_SECRET",
]) {
  delete unsignedEnvironment[name];
}
unsignedEnvironment.CSC_IDENTITY_AUTO_DISCOVERY = "false";
unsignedEnvironment.ELECTRON_BUILDER_COMPRESSION_LEVEL = "7";

run(
  process.execPath,
  [
    path.join(electronRoot, "node_modules", "electron-builder", "cli.js"),
    "--publish",
    "never",
    "--win",
    "nsis",
  ],
  { env: unsignedEnvironment },
);

const releaseDirectory = path.join(electronRoot, "release");
const installers = (await readdir(releaseDirectory, { withFileTypes: true }))
  .filter(
    (entry) =>
      entry.isFile() &&
      /^Vibe-Trading-Desktop-Unofficial-.*-x64\.exe$/u.test(entry.name),
  )
  .map((entry) => path.join(releaseDirectory, entry.name));
const unpackedDirectory = path.join(releaseDirectory, "win-unpacked");
const applicationExecutables = (await readdir(unpackedDirectory, { withFileTypes: true }))
  .filter((entry) => entry.isFile() && entry.name.toLowerCase().endsWith(".exe"))
  .map((entry) => path.join(unpackedDirectory, entry.name));

if (installers.length !== 1 || applicationExecutables.length !== 1) {
  throw new Error(
    `Expected one installer and one top-level application executable; found ` +
      `${installers.length} and ${applicationExecutables.length}.`,
  );
}

for (const artifact of [...applicationExecutables, ...installers]) {
  const status = signatureStatus(artifact);
  if (status !== "NotSigned") {
    throw new Error(
      `Review artifact unexpectedly has Authenticode status '${status}': ${artifact}`,
    );
  }
  console.log(`Unsigned review boundary verified: ${path.basename(artifact)}`);
}

const installerHash = await sha256(installers[0]);
await writeFile(
  path.join(releaseDirectory, "SHA256SUMS.txt"),
  `${installerHash}  ${path.basename(installers[0])}\n`,
  "ascii",
);
console.log(`Unsigned review installer ready; do not publish: ${installers[0]}`);
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

function signatureStatus(artifact) {
  const result = spawnSync(
    signaturePowerShell,
    [
      "-NoProfile",
      "-NonInteractive",
      "-Command",
      "(Get-AuthenticodeSignature -LiteralPath $env:VIBE_REVIEW_ARTIFACT_PATH).Status",
    ],
    {
      cwd: electronRoot,
      env: {
        ...process.env,
        VIBE_REVIEW_ARTIFACT_PATH: artifact,
      },
      encoding: "utf8",
    },
  );
  if (result.status !== 0) {
    throw new Error(result.stderr.trim() || result.stdout.trim());
  }
  return result.stdout.trim();
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
