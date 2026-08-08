import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("vibeDesktop", {
  isDesktop: true,
  onStatus: (callback: (message: string) => void) => {
    ipcRenderer.on("desktop:status", (_event, message: string) => callback(message));
  },
  onError: (callback: (message: string) => void) => {
    ipcRenderer.on("desktop:error", (_event, message: string) => callback(message));
  },
  retry: () => ipcRenderer.send("desktop:retry"),
  openLogs: () => ipcRenderer.send("desktop:open-logs"),
  restartBackend: () => ipcRenderer.invoke("desktop:restart-backend") as Promise<boolean>,
});
