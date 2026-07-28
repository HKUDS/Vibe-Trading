import { ChildProcess, spawn } from "node:child_process";
import { createWriteStream, existsSync, mkdirSync, WriteStream } from "node:fs";
import { createServer } from "node:net";
import path from "node:path";

type BackendManagerOptions = {
  appPath: string;
  resourcesPath: string;
  logDirectory: string;
  apiAuthKey: string;
  onStatus: (message: string) => void;
  onUnexpectedExit: (message: string) => void;
};

type ResolvedBackend = {
  executable: string;
  prefixArguments: string[];
  includeServeCommand: boolean;
};

export class BackendManager {
  private child: ChildProcess | undefined;
  private baseUrl: string | undefined;
  private stopping = false;
  private logStream: WriteStream | undefined;
  private readonly recentOutput: string[] = [];

  constructor(private readonly options: BackendManagerOptions) {}

  async start(): Promise<string> {
    if (this.child) throw new Error("后端进程已经在运行。");
    this.stopping = false;
    const resolved = this.resolveBackend();
    const executable = resolved.executable;
    const port = await findFreePort();
    this.baseUrl = `http://127.0.0.1:${port}/`;
    mkdirSync(this.options.logDirectory, { recursive: true });
    const day = new Date().toISOString().slice(0, 10).replaceAll("-", "");
    this.logStream = createWriteStream(path.join(this.options.logDirectory, `desktop-${day}.log`), {
      flags: "a",
      encoding: "utf8",
    });
    this.writeLog(`\n[${new Date().toISOString()}] Starting ${executable} on 127.0.0.1:${port}`);

    const gtkBin = path.join(path.dirname(executable), "gtk", "bin");
    const childEnvironment: NodeJS.ProcessEnv = {
      ...process.env,
      API_AUTH_KEY: this.options.apiAuthKey,
      VIBE_TRADING_DESKTOP_FAST_START: "1",
      PYTHONUTF8: "1",
      PYTHONUNBUFFERED: "1",
    };
    if (existsSync(gtkBin)) {
      childEnvironment.PATH = `${gtkBin}${path.delimiter}${process.env.PATH ?? ""}`;
      childEnvironment.WEASYPRINT_DLL_DIRECTORIES = gtkBin;
    }

    const child = spawn(executable, [
      ...resolved.prefixArguments,
      ...(resolved.includeServeCommand ? ["serve"] : []),
      "--host", "127.0.0.1", "--port", String(port),
    ], {
      cwd: path.dirname(executable),
      windowsHide: true,
      env: childEnvironment,
      stdio: ["ignore", "pipe", "pipe"],
    });
    this.child = child;
    child.stdout?.on("data", (chunk: Buffer) => this.capture("OUT", chunk));
    child.stderr?.on("data", (chunk: Buffer) => this.capture("ERR", chunk));
    child.once("error", (error) => this.writeLog(`[PROCESS] ${error.stack ?? error.message}`));
    child.once("exit", (code, signal) => {
      this.writeLog(`[PROCESS] exited code=${String(code)} signal=${String(signal)}`);
      if (!this.stopping) {
        this.options.onUnexpectedExit(`Vibe-Trading 后端意外退出（代码 ${String(code)}）。`);
      }
    });

    this.options.onStatus(`后端已启动，正在等待健康检查 · ${port}`);
    await this.waitUntilHealthy();
    this.options.onStatus(`本地服务已就绪 · ${port}`);
    return this.baseUrl;
  }

  async stop(): Promise<void> {
    const child = this.child;
    if (!child) return;
    this.stopping = true;
    if (child.exitCode === null && this.baseUrl) {
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

    if (child.exitCode === null) {
      await Promise.race([waitForExit(child), delay(3_000)]);
    }
    if (child.exitCode === null && child.pid) {
      this.writeLog(`[SHUTDOWN] terminating process tree pid=${child.pid}`);
      if (process.platform === "win32") {
        await runTaskkill(child.pid);
      } else {
        child.kill("SIGTERM");
      }
    }

    this.child = undefined;
    this.baseUrl = undefined;
    await new Promise<void>((resolve) => this.logStream?.end(resolve) ?? resolve());
    this.logStream = undefined;
  }

  get url(): string | undefined {
    return this.baseUrl;
  }

  private async waitUntilHealthy(): Promise<void> {
    if (!this.child || !this.baseUrl) throw new Error("后端尚未启动。");
    const deadline = Date.now() + 180_000;
    while (Date.now() < deadline) {
      if (this.child.exitCode !== null) {
        throw new Error(`Vibe-Trading 后端提前退出（代码 ${this.child.exitCode}）。\n${this.tail()}`);
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
    throw new Error(`等待 Vibe-Trading 后端就绪超时。\n${this.tail()}`);
  }

  private capture(stream: "OUT" | "ERR", chunk: Buffer): void {
    for (const line of chunk.toString("utf8").split(/\r?\n/u)) {
      if (!line.trim()) continue;
      const formatted = `[${new Date().toLocaleTimeString("zh-CN", { hour12: false })}] [${stream}] ${line}`;
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

  private resolveBackend(): ResolvedBackend {
    const configured = process.env.VIBE_TRADING_EXECUTABLE;
    if (configured && existsSync(configured)) {
      return { executable: path.resolve(configured), prefixArguments: [], includeServeCommand: true };
    }

    const roots = new Set<string>([
      this.options.appPath,
      this.options.resourcesPath,
      __dirname,
      process.cwd(),
    ]);
    for (const initialRoot of [...roots]) {
      let current = path.resolve(initialRoot);
      for (let depth = 0; depth < 10; depth += 1) {
        roots.add(current);
        const parent = path.dirname(current);
        if (parent === current) break;
        current = parent;
      }
    }

    for (const root of roots) {
      for (const pythonCandidate of [
        path.join(root, "backend", "python.exe"),
        path.join(root, "runtime", "backend", "python.exe"),
      ]) {
        if (existsSync(pythonCandidate)) {
          return {
            executable: path.resolve(pythonCandidate),
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
        path.join(root, ".venv", "Scripts", "vibe-trading.exe"),
        path.join(root, "Vibe-Trading", ".venv", "Scripts", "vibe-trading.exe"),
      ]) {
        if (existsSync(candidate)) {
          return { executable: path.resolve(candidate), prefixArguments: [], includeServeCommand: true };
        }
      }
    }

    for (const entry of (process.env.PATH ?? "").split(path.delimiter)) {
      const candidate = path.join(entry.replaceAll('"', ""), "vibe-trading.exe");
      if (existsSync(candidate)) {
        return { executable: path.resolve(candidate), prefixArguments: [], includeServeCommand: true };
      }
    }
    throw new Error("找不到 vibe-trading.exe。请先安装后端，或设置 VIBE_TRADING_EXECUTABLE 环境变量。");
  }
}

function findFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.unref();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        server.close();
        reject(new Error("无法分配本地端口。"));
        return;
      }
      const port = address.port;
      server.close((error) => (error ? reject(error) : resolve(port)));
    });
  });
}

function waitForExit(child: ChildProcess): Promise<void> {
  return new Promise((resolve) => child.once("exit", () => resolve()));
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function runTaskkill(pid: number): Promise<void> {
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
