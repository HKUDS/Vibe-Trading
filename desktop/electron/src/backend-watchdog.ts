import { ChildProcess, spawn } from "node:child_process";

type WatchdogCommand = {
  type: "terminate-backend";
};

const parentPid = parseRequiredPid(process.env.VIBE_TRADING_DESKTOP_PARENT_PID, "parent");
const executable = requireEnvironment("VIBE_TRADING_DESKTOP_BACKEND_EXECUTABLE");
const backendCwd = requireEnvironment("VIBE_TRADING_DESKTOP_BACKEND_CWD");
const backendArguments = parseArguments(
  requireEnvironment("VIBE_TRADING_DESKTOP_BACKEND_ARGUMENTS"),
);

if (!isProcessAlive(parentPid)) process.exit(0);

const backendEnvironment = { ...process.env };
for (const key of [
  "ELECTRON_RUN_AS_NODE",
  "VIBE_TRADING_DESKTOP_PARENT_PID",
  "VIBE_TRADING_DESKTOP_BACKEND_EXECUTABLE",
  "VIBE_TRADING_DESKTOP_BACKEND_ARGUMENTS",
  "VIBE_TRADING_DESKTOP_BACKEND_CWD",
  "VIBE_TRADING_DESKTOP_ELECTRON_EXECUTABLE",
  "VIBE_TRADING_DESKTOP_LOCALE",
  "VIBE_TRADING_DESKTOP_PARENT_DEATH_SMOKE_FILE",
  "VIBE_TRADING_DESKTOP_TEST_USER_DATA",
]) {
  delete backendEnvironment[key];
}

const backend = spawn(executable, backendArguments, {
  cwd: backendCwd,
  windowsHide: true,
  env: backendEnvironment,
  stdio: ["ignore", "pipe", "pipe"],
});

backend.stdout?.pipe(process.stdout, { end: false });
backend.stderr?.pipe(process.stderr, { end: false });
process.stdout.on("error", () => undefined);
process.stderr.on("error", () => undefined);

let terminating = false;
let backendExited = false;
const parentMonitor = setInterval(() => {
  if (!isProcessAlive(parentPid)) void terminateBackend("parent-pid-exited");
}, 250);
parentMonitor.unref();

backend.once("spawn", () => {
  sendToParent({ type: "backend-started", pid: backend.pid });
  if (!process.connected || !isProcessAlive(parentPid)) {
    void terminateBackend("parent-unavailable-after-spawn");
  }
});

backend.once("error", (error) => {
  sendToParent({ type: "backend-error", message: error.message });
  clearInterval(parentMonitor);
  process.exit(1);
});

backend.once("exit", (code, signal) => {
  backendExited = true;
  clearInterval(parentMonitor);
  sendToParent({ type: "backend-exited", code, signal });
  if (!terminating) process.exit(code ?? 1);
});

process.on("disconnect", () => {
  void terminateBackend("ipc-disconnected");
});

process.on("message", (message: WatchdogCommand) => {
  if (message?.type === "terminate-backend") {
    void terminateBackend("parent-requested");
  }
});

process.on("SIGTERM", () => {
  void terminateBackend("watchdog-sigterm");
});

process.on("SIGINT", () => {
  void terminateBackend("watchdog-sigint");
});

async function terminateBackend(reason: string): Promise<void> {
  if (terminating) return;
  terminating = true;
  clearInterval(parentMonitor);
  sendToParent({ type: "watchdog-terminating", reason });

  if (!backendExited && backend.exitCode === null && backend.pid) {
    await terminateProcessTree(backend);
  }
  if (!backendExited) {
    await Promise.race([waitForExit(backend), delay(5_000)]);
  }
  process.exit(0);
}

async function terminateProcessTree(child: ChildProcess): Promise<void> {
  if (!child.pid) return;
  if (process.platform === "win32") {
    await new Promise<void>((resolve) => {
      const killer = spawn("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], {
        windowsHide: true,
        stdio: "ignore",
      });
      killer.once("exit", () => resolve());
      killer.once("error", () => resolve());
    });
    return;
  }
  child.kill("SIGKILL");
}

function sendToParent(message: unknown): void {
  if (!process.connected) return;
  try {
    process.send?.(message);
  } catch {
    // The Electron main process can disappear between the connected check and send.
  }
}

function isProcessAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function parseRequiredPid(rawValue: string | undefined, label: string): number {
  const value = Number(rawValue);
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new Error(`Invalid ${label} PID supplied to desktop backend watchdog`);
  }
  return value;
}

function parseArguments(encoded: string): string[] {
  const value: unknown = JSON.parse(Buffer.from(encoded, "base64url").toString("utf8"));
  if (!Array.isArray(value) || !value.every((item) => typeof item === "string")) {
    throw new Error("Invalid backend argument payload supplied to desktop backend watchdog");
  }
  return value;
}

function requireEnvironment(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Missing ${name} for desktop backend watchdog`);
  return value;
}

function waitForExit(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null) return Promise.resolve();
  return new Promise((resolve) => child.once("exit", () => resolve()));
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}
