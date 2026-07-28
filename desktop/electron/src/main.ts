import { randomBytes } from "node:crypto";
import path from "node:path";
import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  Menu,
  nativeTheme,
  shell,
} from "electron";
import { BackendManager } from "./backend-manager";

let mainWindow: BrowserWindow | undefined;
let backend: BackendManager | undefined;
let bootPromise: Promise<void> | undefined;
let quitting = false;
const apiAuthKey = randomBytes(32).toString("base64url");
const productName = "Vibe-Trading Desktop (Unofficial Community Build)";

app.setName(productName);
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });
  void app.whenReady().then(ready).catch((error) => {
    dialog.showErrorBox("Vibe-Trading Desktop 启动失败", errorText(error));
  });
}

async function ready(): Promise<void> {
  nativeTheme.themeSource = "dark";
  app.setAppLogsPath();
  createWindow();
  registerIpc();
  createMenu();
  await showLoadingPage();
  void boot();
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 960,
    minHeight: 640,
    show: false,
    backgroundColor: "#0b0f14",
    title: productName,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      devTools: !app.isPackaged,
      partition: "persist:vibe-trading-desktop",
    },
  });
  const rendererSession = mainWindow.webContents.session;
  rendererSession.setPermissionCheckHandler(() => false);
  rendererSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));
  rendererSession.webRequest.onBeforeSendHeaders(
    { urls: ["http://127.0.0.1/*"] },
    (details, callback) => {
      const backendOrigin = backend?.url ? new URL(backend.url).origin : undefined;
      const requestOrigin = safeOrigin(details.url);
      if (backendOrigin && requestOrigin === backendOrigin) {
        details.requestHeaders.Authorization = `Bearer ${apiAuthKey}`;
      }
      callback({ requestHeaders: details.requestHeaders });
    },
  );
  mainWindow.once("ready-to-show", () => mainWindow?.show());
  mainWindow.on("close", (event) => {
    if (quitting) return;
    event.preventDefault();
    void shutdownAndQuit();
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (isSafeExternalUrl(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  mainWindow.webContents.on("will-navigate", (event, url) => {
    const currentOrigin = backend?.url ? new URL(backend.url).origin : undefined;
    if (currentOrigin && safeOrigin(url) === currentOrigin) return;
    event.preventDefault();
    if (isSafeExternalUrl(url)) void shell.openExternal(url);
  });
}

function registerIpc(): void {
  ipcMain.on("desktop:retry", (event) => {
    assertMainWindowSender(event.sender);
    void boot();
  });
  ipcMain.on("desktop:open-logs", (event) => {
    assertMainWindowSender(event.sender);
    void shell.openPath(app.getPath("logs"));
  });
  ipcMain.handle("desktop:restart-backend", async (event) => {
    assertMainWindowSender(event.sender);
    await boot();
    return true;
  });
}

async function showLoadingPage(): Promise<void> {
  if (!mainWindow) return;
  await mainWindow.loadFile(path.join(__dirname, "loading.html"));
}

function boot(): Promise<void> {
  if (bootPromise) return bootPromise;
  bootPromise = bootInternal().finally(() => { bootPromise = undefined; });
  return bootPromise;
}

async function bootInternal(): Promise<void> {
  if (!mainWindow) return;
  await backend?.stop();
  if (!mainWindow.webContents.getURL().startsWith("file:")) await showLoadingPage();

  backend = new BackendManager({
    appPath: app.getAppPath(),
    resourcesPath: process.resourcesPath,
    logDirectory: app.getPath("logs"),
    apiAuthKey,
    onStatus: (message) => mainWindow?.webContents.send("desktop:status", message),
    onUnexpectedExit: (message) => {
      if (!quitting) void reportBootError(message);
    },
  });

  try {
    const url = await backend.start();
    await mainWindow.loadURL(url);
  } catch (error) {
    await backend.stop();
    await reportBootError(errorText(error));
  }
}

async function reportBootError(message: string): Promise<void> {
  if (!mainWindow) return;
  if (!mainWindow.webContents.getURL().startsWith("file:")) await showLoadingPage();
  mainWindow.webContents.send("desktop:error", message);
}

function createMenu(): void {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    {
      label: "应用",
      submenu: [
        { label: "重启本地服务", click: () => void boot() },
        { label: "打开日志文件夹", click: () => void shell.openPath(app.getPath("logs")) },
        { type: "separator" },
        { role: "quit", label: "退出" },
      ],
    },
    {
      label: "视图",
      submenu: [
        { role: "reload", label: "刷新" },
        ...(!app.isPackaged ? [{ role: "toggleDevTools" as const, label: "开发者工具" }] : []),
        { type: "separator" },
        { role: "resetZoom", label: "实际大小" },
        { role: "zoomIn", label: "放大" },
        { role: "zoomOut", label: "缩小" },
        { role: "togglefullscreen", label: "全屏" },
      ],
    },
  ]));
}

function assertMainWindowSender(sender: Electron.WebContents): void {
  if (sender !== mainWindow?.webContents) throw new Error("Desktop request rejected");
}

async function shutdownAndQuit(): Promise<void> {
  if (quitting) return;
  quitting = true;
  mainWindow?.webContents.send("desktop:status", "正在关闭本地服务…");
  await backend?.stop();
  app.quit();
}

function isSafeExternalUrl(rawUrl: string): boolean {
  try {
    const protocol = new URL(rawUrl).protocol;
    return protocol === "https:" || protocol === "http:";
  } catch {
    return false;
  }
}

function safeOrigin(rawUrl: string): string | undefined {
  try {
    return new URL(rawUrl).origin;
  } catch {
    return undefined;
  }
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") void shutdownAndQuit();
});

process.on("uncaughtException", (error) => {
  dialog.showErrorBox("Vibe-Trading Desktop", error.stack ?? error.message);
});
