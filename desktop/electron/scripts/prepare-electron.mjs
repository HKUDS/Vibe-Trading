import { createHash } from "node:crypto";
import { copyFile, mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { downloadArtifact } from "@electron/get";

const electronRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const electronPackage = JSON.parse(
  await readFile(path.join(electronRoot, "node_modules", "electron", "package.json"), "utf8"),
);
const checksums = JSON.parse(
  await readFile(path.join(electronRoot, "node_modules", "electron", "checksums.json"), "utf8"),
);
const version = electronPackage.version;
const archiveName = `electron-v${version}-win32-x64.zip`;
const expected = checksums[archiveName];
if (!expected) throw new Error(`Official checksum is missing for ${archiveName}`);

const targetDirectory = path.join(electronRoot, ".cache", "electron-dist");
const target = path.join(targetDirectory, archiveName);
await mkdir(targetDirectory, { recursive: true });

if (await sha256(target) !== expected) {
  let lastError;
  for (let attempt = 1; attempt <= 4; attempt += 1) {
    try {
      let lastReportedPercent = -10;
      const downloaded = await downloadArtifact({
        version,
        artifactName: "electron",
        platform: "win32",
        arch: "x64",
        downloadOptions: {
          signal: AbortSignal.timeout(180_000),
          getProgressCallback: async ({ percent }) => {
            const currentPercent = Math.min(100, Math.floor(percent * 10) * 10);
            if (currentPercent >= lastReportedPercent + 10) {
              lastReportedPercent = currentPercent;
              console.log(`Electron download attempt ${attempt}/4: ${currentPercent}%`);
            }
          },
        },
      });
      await copyFile(downloaded, target);
      lastError = undefined;
      break;
    } catch (error) {
      lastError = error;
      if (attempt < 4) {
        const delayMs = attempt * 2_000;
        console.warn(
          `Electron download attempt ${attempt}/4 failed; retrying in ${delayMs / 1_000}s`,
        );
        await new Promise((resolve) => setTimeout(resolve, delayMs));
      }
    }
  }
  if (lastError) throw lastError;
}

const actual = await sha256(target);
if (actual !== expected) {
  throw new Error(`Electron checksum mismatch: expected ${expected}, got ${actual}`);
}
console.log(`Electron archive ready and verified: ${target}`);

async function sha256(file) {
  try {
    return createHash("sha256").update(await readFile(file)).digest("hex");
  } catch (error) {
    if (error && error.code === "ENOENT") return undefined;
    throw error;
  }
}
