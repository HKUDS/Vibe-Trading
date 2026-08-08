import { ChildProcess, spawn } from "node:child_process";
import {
  createWriteStream,
  existsSync,
  mkdirSync,
  readFileSync,
  WriteStream,
} from "node:fs";
import { createServer } from "node:net";
import path from "node:path";
import {
  DesktopMessages,
  formatDesktopMessage,
} from "./locales";

type BackendManagerOptions = {
  appPath: string;
  resourcesPath: string;
  allowSourceDiscovery: boolean;
  logDirectory: string;
  apiAuthKey: string;
  messages: DesktopMessages;
  credentialEnvironment?: NodeJS.ProcessEnv;
  onStatus: (message: string) => void;
  onUnexpectedExit: (message: string) => void;
};

export type ResolvedBackend = {
  executable: string;
  prefixArguments: string[];
  includeServeCommand: boolean;
};

export type BackendResolutionOptions = {
  appPath: string;
  resourcesPath: string;
  moduleDirectory?: string;
  allowSourceDiscovery: boolean;
  executableOverride?: string;
  pathEnvironment?: string;
};

type WatchdogMessage = {
  type: string;
  pid?: number;
  code?: number | null;
  signal?: NodeJS.Signals | null;
  message?: string;
  reason?: string;
};

export class BackendManager {
  private watchdog: ChildProcess | undefined;
  private watchdogError: Error | undefined;
  private backendPid: number | undefined;
  private baseUrl: string | undefined;
  private stopping = false;
  private logStream: WriteStream | undefined;
  private readonly recentOutput: string[] = [];

  constructor(private readonly options: BackendManagerOptions) {}

  async start(): Promise<string> {
    if (this.watchdog) throw new Error(this.options.messages.backendAlreadyRunning);
    this.stopping = false;
    this.watchdogError = undefined;
    const resolved = resolveBackend({
      appPath: this.options.appPath,
      resourcesPath: this.options.resourcesPath,
      moduleDirectory: __dirname,
      allowSourceDiscovery: this.options.allowSourceDiscovery,
      executableOverride: process.env.VIBE_TRADING_EXECUTABLE,
      pathEnvironment: process.env.PATH,
    });
    if (!resolved) throw new Error(this.options.messages.backendNotFound);
    const executable = resolved.executable;
    const port = await findFreePort(this.options.messages.portUnavailable);
    this.baseUrl = `http://127.0.0.1:${port}/`;
    mkdirSync(this.options.logDirectory, { recursive: true });
    const day = new Date().toISOString().slice(0, 10).replaceAll("-", "");
    this.logStream = createWriteStream(path.join(this.options.logDirectory, `desktop-${day}.log`), {
      flags: "a",
      encoding: "utf8",
    });
    this.writeLog(`\n[${new Date().toISOString()}] Starting ${executable} on 127.0.0.1:${port}`);

    const backendArguments = [
      ...resolved.prefixArguments,
      ...(resolved.includeServeCommand ? ["serve"] : []),
      "--host", "127.0.0.1", "--port", String(port),
    ];
    const gtkBin = path.join(path.dirname(executable), "gtk", "bin");
    const childEnvironment: NodeJS.ProcessEnv = {
      ...process.env,
      ...this.options.credentialEnvironment,
      API_AUTH_KEY: this.options.apiAuthKey,
      VIBE_TRADING_DESKTOP_SECURE_CREDENTIALS: "1",
      PYTHONUTF8: "1",
      PYTHONUNBUFFERED: "1",
      ELECTRON_RUN_AS_NODE: "1",
      VIBE_TRADING_DESKTOP_PARENT_PID: String(process.pid),
      VIBE_TRADING_DESKTOP_BACKEND_EXECUTABLE: executable,
      VIBE_TRADING_DESKTOP_BACKEND_ARGUMENTS: Buffer.from(
        JSON.stringify(backendArguments),
        "utf8",
      ).toString("base64url"),
      VIBE_TRADING_DESKTOP_BACKEND_CWD: path.dirname(executable),
    };
    if (existsSync(gtkBin)) {
      childEnvironment.PATH = `${gtkBin}${path.delimiter}${process.env.PATH ?? ""}`;
      childEnvironment.WEASYPRINT_DLL_DIRECTORIES = gtkBin;
    }

    const watchdogPath = path.join(__dirname, "backend-watchdog.js");
    const watchdog = spawn(process.execPath, [watchdogPath], {
      // In a packaged app __dirname is inside app.asar. Electron's fs layer can
      // read that path, but Windows cannot use an ASAR path as a process cwd.
      cwd: this.options.resourcesPath,
      windowsHide: true,
      env: childEnvironment,
      stdio: ["ignore", "pipe", "pipe", "ipc"],
    });
    this.watchdog = watchdog;
    watchdog.stdout?.on("data", (chunk: Buffer) => this.capture("OUT", chunk));
    watchdog.stderr?.on("data", (chunk: Buffer) => this.capture("ERR", chunk));
    watchdog.on("message", (message: WatchdogMessage) => this.handleWatchdogMessage(message));
    watchdog.once("error", (error) => {
      this.watchdogError = error;
      this.writeLog(`[WATCHDOG] ${error.stack ?? error.message}`);
    });
    watchdog.once("exit", (code, signal) => {
      this.writeLog(`[WATCHDOG] exited code=${String(code)} signal=${String(signal)}`);
      this.backendPid = undefined;
      if (!this.stopping) {
        this.options.onUnexpectedExit(formatDesktopMessage(
          this.options.messages.backendUnexpectedExit,
          { code: code ?? signal ?? "unknown" },
        ));
      }
    });

    this.options.onStatus(formatDesktopMessage(this.options.messages.backendStarting, { port }));
    await this.waitUntilHealthy();
    this.options.onStatus(formatDesktopMessage(this.options.messages.backendReady, { port }));
    return this.baseUrl;
  }

  async stop(): Promise<void> {
    const watchdog = this.watchdog;
    if (!watchdog) return;
    this.stopping = true;
    if (isRunning(watchdog) && this.baseUrl) {
      try {
        await fetch(new URL("system/shutdown", this.baseUrl), {
          method: "POST",
          headers: { Authorization: `Bearer ${this.options.apiAuthKey}` },
          signal: AbortSignal.timeout(2_000),
        });
      } catch (error) {
        this.writeLog(`[SHUTDOWN] graceful request failed: ${errorText(error)}`);
      }
    }

    if (isRunning(watchdog)) {
      await Promise.race([waitForExit(watchdog), delay(3_000)]);
    }
    if (isRunning(watchdog)) {
      this.writeLog(`[SHUTDOWN] asking watchdog to terminate backend pid=${String(this.backendPid)}`);
      try {
        watchdog.send({ type: "terminate-backend" });
      } catch (error) {
        this.writeLog(`[SHUTDOWN] watchdog IPC failed: ${errorText(error)}`);
      }
      await Promise.race([waitForExit(watchdog), delay(5_000)]);
    }
    if (isRunning(watchdog) && watchdog.pid) {
      this.writeLog(`[SHUTDOWN] terminating watchdog tree pid=${watchdog.pid}`);
      await runTaskkill(watchdog.pid);
    }

    this.watchdog = undefined;
    this.watchdogError = undefined;
    this.backendPid = undefined;
    this.baseUrl = undefined;
    await new Promise<void>((resolve) => this.logStream?.end(resolve) ?? resolve());
    this.logStream = undefined;
  }

  get url(): string | undefined {
    return this.baseUrl;
  }

  get processId(): number | undefined {
    return this.backendPid;
  }

  private handleWatchdogMessage(message: WatchdogMessage): void {
    switch (message?.type) {
      case "backend-started":
        if (typeof message.pid === "number") {
          this.backendPid = message.pid;
          this.writeLog(`[WATCHDOG] backend started pid=${message.pid}`);
        }
        break;
      case "backend-error":
        this.writeLog(`[WATCHDOG] backend error: ${message.message ?? "unknown"}`);
        break;
      case "backend-exited":
        this.writeLog(
          `[WATCHDOG] backend exited code=${String(message.code)} signal=${String(message.signal)}`,
        );
        break;
      case "watchdog-terminating":
        this.writeLog(`[WATCHDOG] terminating backend reason=${message.reason ?? "unknown"}`);
        break;
      default:
        break;
    }
  }

  private async waitUntilHealthy(): Promise<void> {
    if (!this.watchdog || !this.baseUrl) throw new Error(this.options.messages.backendNotStarted);
    const deadline = Date.now() + 180_000;
    while (Date.now() < deadline) {
      if (this.watchdogError) throw this.watchdogError;
      if (!isRunning(this.watchdog)) {
        throw new Error(formatDesktopMessage(this.options.messages.backendExitedEarly, {
          code: this.watchdog.exitCode ?? this.watchdog.signalCode ?? "unknown",
          details: this.tail(),
        }));
      }
      try {
        const response = await fetch(new URL("health", this.baseUrl), {
          headers: { Authorization: `Bearer ${this.options.apiAuthKey}` },
          signal: AbortSignal.timeout(2_000),
        });
        if (response.ok) return;
      } catch {
        // The loopback socket is not accepting connections yet.
      }
      await delay(100);
    }
    throw new Error(formatDesktopMessage(this.options.messages.backendHealthTimeout, {
      details: this.tail(),
    }));
  }

  private capture(stream: "OUT" | "ERR", chunk: Buffer): void {
    for (const line of chunk.toString("utf8").split(/\r?\n/u)) {
      if (!line.trim()) continue;
      const formatted = `[${new Date().toISOString()}] [${stream}] ${line}`;
      this.recentOutput.push(formatted);
      if (this.recentOutput.length > 80) this.recentOutput.shift();
      this.writeLog(formatted);
    }
  }

  private tail(): string {
    return this.recentOutput.slice(-20).join("\n");
  }

  private writeLog(message: string): void {
    this.logStream?.write(`${message}\n`);
  }

}

const sourceProjectName = "vibe-trading-ai";

export function resolveBackend(options: BackendResolutionOptions): ResolvedBackend | undefined {
  const configured = options.executableOverride;
  if (configured && existsSync(configured)) return commandBackend(configured);

  for (const root of trustedPackagedRoots(options.appPath, options.resourcesPath)) {
    const resolved = resolvePackagedBackend(root);
    if (resolved) return resolved;
  }

  if (options.allowSourceDiscovery) {
    const sourceRoots = new Set<string>();
    for (const start of [options.appPath, options.moduleDirectory]) {
      if (!start) continue;
      const sourceRoot = findMarkedSourceRoot(start);
      if (sourceRoot) sourceRoots.add(sourceRoot);
    }
    for (const sourceRoot of sourceRoots) {
      const candidate = path.join(sourceRoot, ".venv", "Scripts", "vibe-trading.exe");
      if (existsSync(candidate)) return commandBackend(candidate);
    }
  }

  for (const rawEntry of (options.pathEnvironment ?? "").split(path.delimiter)) {
    const entry = rawEntry.replaceAll('"', "").trim();
    if (!entry) continue;
    const candidate = path.join(entry, "vibe-trading.exe");
    if (existsSync(candidate)) return commandBackend(candidate);
  }
  return undefined;
}

function trustedPackagedRoots(appPath: string, resourcesPath: string): string[] {
  return [...new Set([
    path.resolve(appPath),
    path.resolve(resourcesPath),
    path.resolve(resourcesPath, "app"),
    path.resolve(resourcesPath, "resources"),
  ])];
}

function resolvePackagedBackend(root: string): ResolvedBackend | undefined {
  for (const candidate of [
    path.join(root, "backend", "python.exe"),
    path.join(root, "runtime", "backend", "python.exe"),
  ]) {
    if (existsSync(candidate)) {
      return {
        executable: path.resolve(candidate),
        prefixArguments: [
          "-c",
          "import api_server; raise SystemExit(api_server.serve_main())",
        ],
        includeServeCommand: false,
      };
    }
  }
  for (const candidate of [
    path.join(root, "backend", "Scripts", "vibe-trading.exe"),
    path.join(root, "runtime", "Scripts", "vibe-trading.exe"),
  ]) {
    if (existsSync(candidate)) return commandBackend(candidate);
  }
  return undefined;
}

function findMarkedSourceRoot(start: string): string | undefined {
  let current = path.resolve(start);
  while (true) {
    const parent = path.dirname(current);
    if (parent === current) return undefined;
    if (isVibeTradingProject(path.join(current, "pyproject.toml"))) return current;
    current = parent;
  }
}

function isVibeTradingProject(markerPath: string): boolean {
  if (!existsSync(markerPath)) return false;
  try {
    let inProjectSection = false;
    for (const rawLine of readFileSync(markerPath, "utf8").split(/\r?\n/u)) {
      const line = rawLine.trim();
      if (/^\[[^\]]+\]$/u.test(line)) {
        inProjectSection = line === "[project]";
        continue;
      }
      if (!inProjectSection) continue;
      const name = /^name\s*=\s*(["'])([^"']+)\1(?:\s*#.*)?$/u.exec(line)?.[2];
      if (name) return name === sourceProjectName;
    }
  } catch {
    return false;
  }
  return false;
}

function commandBackend(executable: string): ResolvedBackend {
  return {
    executable: path.resolve(executable),
    prefixArguments: [],
    includeServeCommand: true,
  };
}

function findFreePort(errorMessage: string): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.unref();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        server.close();
        reject(new Error(errorMessage));
        return;
      }
      const port = address.port;
      server.close((error) => (error ? reject(error) : resolve(port)));
    });
  });
}

function isRunning(child: ChildProcess): boolean {
  return child.exitCode === null && child.signalCode === null;
}

function waitForExit(child: ChildProcess): Promise<void> {
  if (!isRunning(child)) return Promise.resolve();
  return new Promise((resolve) => child.once("exit", () => resolve()));
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function runTaskkill(pid: number): Promise<void> {
  if (process.platform !== "win32") {
    try {
      process.kill(pid, "SIGKILL");
    } catch {
      // The watchdog has already exited.
    }
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    const killer = spawn("taskkill.exe", ["/PID", String(pid), "/T", "/F"], {
      windowsHide: true,
      stdio: "ignore",
    });
    killer.once("exit", () => resolve());
    killer.once("error", () => resolve());
  });
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
