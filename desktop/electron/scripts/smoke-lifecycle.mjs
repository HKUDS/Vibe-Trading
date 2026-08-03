import { randomBytes } from "node:crypto";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { BackendManager } from "../dist/backend-manager.js";
import { getDesktopMessages } from "../dist/locales.js";

const electronRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const logDirectory = await mkdtemp(path.join(os.tmpdir(), "vibe-trading-desktop-shell-"));
const statuses = [];
let unexpectedExit;
const apiAuthKey = randomBytes(32).toString("base64url");

const backend = new BackendManager({
  appPath: electronRoot,
  resourcesPath: electronRoot,
  logDirectory,
  apiAuthKey,
  messages: getDesktopMessages("en"),
  onStatus: (message) => statuses.push(message),
  onUnexpectedExit: (message) => {
    unexpectedExit = message;
  },
});

let url;
try {
  url = await backend.start();
  const parsed = new URL(url);
  if (parsed.hostname !== "127.0.0.1") {
    throw new Error(`Expected a loopback backend, received ${parsed.origin}`);
  }
  const health = await fetch(new URL("health", url), {
    headers: { Authorization: `Bearer ${apiAuthKey}` },
  });
  if (!health.ok) throw new Error(`Authenticated health returned HTTP ${health.status}`);
  const unauthorized = await fetch(new URL("sessions", url));
  if (unauthorized.status !== 401) {
    throw new Error(`Expected unauthenticated sessions request to return 401, received ${unauthorized.status}`);
  }
  const authorized = await fetch(new URL("sessions", url), {
    headers: { Authorization: `Bearer ${apiAuthKey}` },
  });
  if (!authorized.ok) {
    throw new Error(`Authenticated sessions request returned HTTP ${authorized.status}`);
  }
  if (unexpectedExit) throw new Error(unexpectedExit);
} finally {
  await backend.stop();
}

let stopped = false;
if (url) {
  try {
    await fetch(new URL("health", url), { signal: AbortSignal.timeout(1_000) });
  } catch {
    stopped = true;
  }
}
if (!stopped) throw new Error("Backend still accepted connections after shutdown");

console.log(JSON.stringify({
  backendOrigin: new URL(url).origin,
  statuses,
  logDirectory,
  authBoundaryVerified: true,
  shutdownVerified: stopped,
}, null, 2));
