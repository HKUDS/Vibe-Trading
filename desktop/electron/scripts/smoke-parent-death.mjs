import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

if (process.platform !== "win32") {
  console.log("Parent-death smoke is Windows-specific; skipped on this platform.");
  process.exit(0);
}

const electronPath = process.env.VIBE_TRADING_DESKTOP_ELECTRON_EXECUTABLE
  || (await import("electron")).default;

const electronRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const testDirectory = await mkdtemp(path.join(os.tmpdir(), "vibe-desktop-parent-death-"));
const readyFile = path.join(testDirectory, "ready.json");
const userData = path.join(testDirectory, "user-data");
const output = [];
const electronMain = spawn(electronPath, [electronRoot, "--disable-gpu"], {
  cwd: electronRoot,
  windowsHide: true,
  env: {
    ...process.env,
    VIBE_TRADING_DESKTOP_LOCALE: "en",
    VIBE_TRADING_DESKTOP_PARENT_DEATH_SMOKE_FILE: readyFile,
    VIBE_TRADING_DESKTOP_TEST_USER_DATA: userData,
  },
  stdio: ["ignore", "pipe", "pipe"],
});
electronMain.stdout?.on("data", (chunk) => output.push(`[OUT] ${chunk.toString("utf8")}`));
electronMain.stderr?.on("data", (chunk) => output.push(`[ERR] ${chunk.toString("utf8")}`));

let ready;
try {
  ready = await waitForReadyFile(readyFile, 180_000, electronMain, output);
  assert.equal(ready.mainPid, electronMain.pid, "Spawned Electron PID did not match its main PID");
  assert.equal(typeof ready.backendPid, "number");
  assert.match(ready.backendOrigin, /^http:\/\/127\.0\.0\.1:\d+$/u);
  assert.equal(await listenerAcceptsConnections(ready.backendOrigin), true);
  assert.equal(isProcessAlive(ready.backendPid), true);

  await killOnlyProcess(ready.mainPid);
  await waitForCondition(
    () => !isProcessAlive(ready.backendPid),
    20_000,
    `Python backend PID ${ready.backendPid} survived Electron main termination`,
  );
  await waitForCondition(
    async () => !(await listenerAcceptsConnections(ready.backendOrigin)),
    20_000,
    `Backend listener ${ready.backendOrigin} survived Electron main termination`,
  );

  console.log(JSON.stringify({
    killedPid: ready.mainPid,
    killMode: "single-pid-only",
    backendPid: ready.backendPid,
    backendOrigin: ready.backendOrigin,
    backendExited: true,
    listenerClosed: true,
  }, null, 2));
} finally {
  if (electronMain.pid && isProcessAlive(electronMain.pid)) {
    await killOnlyProcess(electronMain.pid);
  }
  if (ready?.backendPid && isProcessAlive(ready.backendPid)) {
    await killProcessTree(ready.backendPid);
  }
}

async function waitForReadyFile(filePath, timeoutMs, child, capturedOutput) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`Electron main exited before readiness.\n${capturedOutput.join("")}`);
    }
    try {
      return JSON.parse(await readFile(filePath, "utf8"));
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
    await delay(100);
  }
  throw new Error(`Timed out waiting for Electron parent-death readiness.\n${capturedOutput.join("")}`);
}

async function listenerAcceptsConnections(origin) {
  try {
    await fetch(new URL("health", `${origin}/`), { signal: AbortSignal.timeout(1_000) });
    return true;
  } catch {
    return false;
  }
}

function isProcessAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function waitForCondition(predicate, timeoutMs, errorMessage) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await delay(100);
  }
  throw new Error(errorMessage);
}

function killOnlyProcess(pid) {
  return runTaskkill(["/PID", String(pid), "/F"]);
}

function killProcessTree(pid) {
  return runTaskkill(["/PID", String(pid), "/T", "/F"]);
}

function runTaskkill(arguments_) {
  return new Promise((resolve, reject) => {
    const killer = spawn("taskkill.exe", arguments_, { windowsHide: true, stdio: "ignore" });
    killer.once("error", reject);
    killer.once("exit", (code) => {
      if (code === 0 || code === 128) resolve();
      else reject(new Error(`taskkill exited with code ${String(code)}`));
    });
  });
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}
