import { randomBytes } from "node:crypto";
import { spawn } from "node:child_process";
import { rm } from "node:fs/promises";
import { appendFileSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import os from "node:os";
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
import {
  DesktopLocale,
  getDesktopMessages,
  getRendererLocale,
  resolveDesktopLocale,
} from "./locales";
import { SecureCredentialStore } from "./secure-credentials";
import { assertDataOutsideInstallation, checkDesktopUpdate, stageDesktopUpdate, DesktopRelease, DesktopUpdatePolicy } from "./update";
import { UpdateRecoveryJournal, UpdateRecoveryResult } from "./update-recovery";
import { assertVerifiedUpdateArtifactUnchanged, compareSemanticVersions } from "./update-verification";

let mainWindow: BrowserWindow | undefined;
let backend: BackendManager | undefined;
let bootPromise: Promise<void> | undefined;
let quitting = false;
let updateBusy = false;
let updateCandidate: DesktopRelease | undefined;
let updateRecovery: UpdateRecoveryResult | undefined;
let updateJournal: UpdateRecoveryJournal;
let updatePolicy: DesktopUpdatePolicy;
let desktopLocale: DesktopLocale = "en";
let desktopMessages = getDesktopMessages(desktopLocale);
const apiAuthKey = randomBytes(32).toString("base64url");
const productName = "Vibe-Trading Desktop (Unofficial Community Build)";
const testUserData = process.env.VIBE_TRADING_DESKTOP_TEST_USER_DATA;
let credentialStore: SecureCredentialStore | undefined;

if (testUserData) app.setPath("userData", path.resolve(testUserData));
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
    dialog.showErrorBox(desktopMessages.startupFailureTitle, errorText(error));
    app.quit();
  });
}

async function ready(): Promise<void> {
  desktopLocale = resolveDesktopLocale(
    process.env.VIBE_TRADING_DESKTOP_LOCALE ?? app.getLocale(),
  );
  desktopMessages = getDesktopMessages(desktopLocale);
  nativeTheme.themeSource = "dark";
  app.setAppLogsPath();
  updateJournal = new UpdateRecoveryJournal(path.join(app.getPath("userData"), "updates"));
  updatePolicy = JSON.parse(readFileSync(path.join(app.getAppPath(), "package.json"), "utf8")).desktopUpdates;
  credentialStore = new SecureCredentialStore({ messages: desktopMessages });
  await credentialStore.initialize();
  createWindow();
  registerIpc();
  createMenu();
  await showLoadingPage();
  void boot();
}

function createWindow(): void {
  const parentDeathSmoke = Boolean(process.env.VIBE_TRADING_DESKTOP_PARENT_DEATH_SMOKE_FILE);
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
  if (!parentDeathSmoke) {
    mainWindow.once("ready-to-show", () => mainWindow?.show());
  }
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
  ipcMain.handle("desktop:check-update", async (event) => {
    assertMainWindowSender(event.sender);
    if (updateBusy) throw new Error("An update is already in progress");
    updateCandidate = undefined;
    const method = process.platform !== "win32" || !app.isPackaged ? "desktop-manual"
      : !updatePolicy?.feedUrl ? "desktop-unconfigured" : "desktop";
    if (method === "desktop") updateCandidate = await checkDesktopUpdate(updatePolicy);
    return {
      current_version: app.getVersion(), latest_version: updateCandidate?.version ?? null,
      available: Boolean(updateCandidate && compareSemanticVersions(updateCandidate.version, app.getVersion()) > 0),
      method, recovery: updateRecovery?.disposition ?? "none",
    };
  });
  ipcMain.handle("desktop:install-update", async (event) => {
    assertMainWindowSender(event.sender);
    if (event.senderFrame !== mainWindow?.webContents.mainFrame) throw new Error("Desktop request rejected");
    await installUpdate();
  });
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
  ipcMain.handle("desktop:get-credential-status", (event) => {
    assertMainWindowSender(event.sender);
    return requireCredentialStore().status();
  });
  ipcMain.handle("desktop:set-credential", async (event, name: unknown, value: unknown) => {
    assertMainWindowSender(event.sender);
    if (typeof name !== "string" || (typeof value !== "string" && value !== null)) {
      throw new Error(desktopMessages.credentialRequestInvalid);
    }
    const store = requireCredentialStore();
    await store.set(name, value);
    return store.status();
  });
}

async function showLoadingPage(): Promise<void> {
  if (!mainWindow) return;
  const localePayload = Buffer.from(
    JSON.stringify(getRendererLocale(desktopLocale)),
    "utf8",
  ).toString("base64url");
  await mainWindow.loadFile(path.join(__dirname, "loading.html"), {
    query: { locale: localePayload },
  });
}

function boot(): Promise<void> {
  if (updateBusy) return Promise.resolve();
  if (bootPromise) return bootPromise;
  bootPromise = bootInternal().finally(() => { bootPromise = undefined; });
  return bootPromise;
}

async function bootInternal(): Promise<void> {
  if (!mainWindow) return;
  await backend?.stop();
  if (!mainWindow.webContents.getURL().startsWith("file:")) await showLoadingPage();

  // Do not start an old backend while a previously launched installer may
  // still be replacing its files. Completion requires a healthy new backend.
  const recovery = await updateJournal.recover(app.getVersion(), false).catch((error) => ({
    disposition: "manual-intervention-required" as const, detail: errorText(error),
  }));
  updateRecovery = recovery.disposition === "none" ? undefined : recovery;
  if (recovery.disposition === "manual-intervention-required") {
    await reportBootError(recovery.detail ?? "Resolve the pending update before restarting");
    return;
  }

  try {
    backend = new BackendManager({
      appPath: app.getAppPath(),
      resourcesPath: process.resourcesPath,
      allowSourceDiscovery: !app.isPackaged,
      logDirectory: app.getPath("logs"),
      apiAuthKey,
      messages: desktopMessages,
      credentialEnvironment: requireCredentialStore().environment(),
      onStatus: (message) => mainWindow?.webContents.send("desktop:status", message),
      onUnexpectedExit: (message) => {
        if (!quitting && !updateBusy) void reportBootError(message);
      },
    });
    const url = await backend.start();
    // A target version is only reported complete after its backend starts.
    updateRecovery ??= await updateJournal.recover(app.getVersion()).catch((error) => ({
      disposition: "manual-intervention-required" as const,
      detail: errorText(error),
    }));
    await mainWindow.loadURL(url);
    writeParentDeathSmokeRecord(url);
  } catch (error) {
    await backend?.stop();
    await reportBootError(errorText(error));
  }
}

function writeParentDeathSmokeRecord(url: string): void {
  const target = process.env.VIBE_TRADING_DESKTOP_PARENT_DEATH_SMOKE_FILE;
  if (!target) return;
  const backendPid = backend?.processId;
  if (!backendPid) throw new Error("Parent-death smoke test could not resolve the backend PID");
  writeFileSync(path.resolve(target), JSON.stringify({
    mainPid: process.pid,
    backendPid,
    backendOrigin: new URL(url).origin,
  }), { encoding: "utf8", flag: "wx" });
}

async function reportBootError(message: string): Promise<void> {
  if (!mainWindow) return;
  if (!mainWindow.webContents.getURL().startsWith("file:")) await showLoadingPage();
  mainWindow.webContents.send("desktop:error", message);
}

function createMenu(): void {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    {
      label: desktopMessages.menuApplication,
      submenu: [
        { label: desktopMessages.menuRestartService, click: () => void boot() },
        { label: desktopMessages.menuOpenLogs, click: () => void shell.openPath(app.getPath("logs")) },
        { type: "separator" },
        { role: "quit", label: desktopMessages.menuQuit },
      ],
    },
    {
      label: desktopMessages.menuView,
      submenu: [
        { role: "reload", label: desktopMessages.menuReload },
        ...(!app.isPackaged
          ? [{ role: "toggleDevTools" as const, label: desktopMessages.menuDeveloperTools }]
          : []),
        { type: "separator" },
        { role: "resetZoom", label: desktopMessages.menuActualSize },
        { role: "zoomIn", label: desktopMessages.menuZoomIn },
        { role: "zoomOut", label: desktopMessages.menuZoomOut },
        { role: "togglefullscreen", label: desktopMessages.menuFullscreen },
      ],
    },
  ]));
}

function assertMainWindowSender(sender: Electron.WebContents): void {
  if (sender !== mainWindow?.webContents) throw new Error("Desktop request rejected");
}

function requireCredentialStore(): SecureCredentialStore {
  if (!credentialStore) throw new Error(desktopMessages.credentialStoreUnavailable);
  return credentialStore;
}

async function shutdownAndQuit(): Promise<void> {
  if (quitting || updateBusy) return;
  quitting = true;
  mainWindow?.webContents.send("desktop:status", desktopMessages.closingService);
  await backend?.stop();
  app.quit();
}

async function installUpdate(): Promise<void> {
  if (updateBusy || bootPromise || !backend?.url || !updateCandidate
    || !app.isPackaged || process.platform !== "win32"
    || !updateRecovery || updateRecovery.disposition === "manual-intervention-required") {
    throw new Error("Check updates after the service is ready; resolve any pending recovery first");
  }
  updateBusy = true;
  let artifactPath: string | undefined;
  let attemptStarted = false;
  let stopped = false;
  let launched = false;
  try {
    assertDataOutsideInstallation(path.dirname(app.getPath("exe")), [
      app.getPath("userData"), path.join(os.homedir(), ".vibe-trading"),
      ...(process.env.VIBE_TRADING_HOME ? [process.env.VIBE_TRADING_HOME] : []),
    ]);
    // Check again before downloading, but never silently change the reviewed target.
    const release = await checkDesktopUpdate(updatePolicy);
    if (release.version !== updateCandidate.version || release.url !== updateCandidate.url
      || release.sha256 !== updateCandidate.sha256) {
      throw new Error("The release changed. Check updates and review it again");
    }
    const staged = await stageDesktopUpdate(release, updatePolicy, app.getVersion(), updateJournal.stagingDirectory);
    artifactPath = staged.artifactPath;
    const attempt = await updateJournal.begin({
      fromVersion: app.getVersion(), toVersion: staged.version,
      artifactFileName: path.basename(artifactPath), artifactSha256: staged.sha256,
      publisherCertificateSha256: staged.certificateSha256,
    });
    attemptStarted = true;
    stopped = true;
    await backend.stopForUpdate();
    await updateJournal.advance(attempt.attemptId, "backend-stopped");
    await assertVerifiedUpdateArtifactUnchanged(artifactPath, staged.sha256);
    // Persist handoff intent first: a crash after spawn must not look safe to retry.
    await updateJournal.advance(attempt.attemptId, "installer-launched");
    try {
      await new Promise<void>((resolve, reject) => {
        const child = spawn(artifactPath!, ["--updated", "/S", "--force-run"], {
          detached: true, stdio: "ignore", windowsHide: true,
        });
        child.once("error", reject);
        child.once("spawn", () => { launched = true; child.unref(); resolve(); });
      });
    } catch (error) {
      // A rejected spawn is proof no installer started. A crash is not.
      await updateJournal.advance(attempt.attemptId, "backend-stopped");
      throw error;
    }
  } catch (error) {
    appendFileSync(path.join(app.getPath("logs"), "updates.log"), `${new Date().toISOString()} ${errorText(error)}\n`);
    throw error;
  } finally {
    updateCandidate = undefined;
    if (launched) {
      // Even a journal write failure must not restart a backend under the installer.
      quitting = true;
      app.quit();
    } else {
      try {
        if (attemptStarted) updateRecovery = await updateJournal.recover(app.getVersion());
        else if (artifactPath) await rm(artifactPath, { force: true });
      } finally {
        updateBusy = false;
        if (stopped) await boot();
      }
    }
  }
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
  dialog.showErrorBox(productName, error.stack ?? error.message);
});
