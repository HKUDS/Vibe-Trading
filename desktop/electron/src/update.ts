import { createWriteStream, existsSync, realpathSync } from "node:fs";
import { mkdir, rm } from "node:fs/promises";
import path from "node:path";
import { pipeline } from "node:stream/promises";
import { randomBytes } from "node:crypto";
import {
  compareSemanticVersions,
  verifyWindowsUpdateCandidate,
} from "./update-verification";

export type DesktopUpdatePolicy = {
  feedUrl: string;
  allowedPublisherCertificateSha256: string[];
};
export type DesktopRelease = { version: string; url: string; sha256: string };

export function assertDataOutsideInstallation(installationDirectory: string, dataDirectories: string[]): void {
  const canonical = (directory: string): string => {
    const absolute = path.resolve(directory);
    if (existsSync(absolute)) return realpathSync(absolute);
    const parent = path.dirname(absolute);
    return parent === absolute ? absolute : path.join(canonical(parent), path.basename(absolute));
  };
  for (const directory of dataDirectories) {
    if (!path.isAbsolute(directory)) throw new Error("Use an absolute data directory before updating");
    const relative = path.relative(canonical(installationDirectory), canonical(directory));
    if (relative !== ".." && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative)) {
      throw new Error("User data is inside the program directory. Move it outside through the original setup before updating");
    }
  }
}

// Both the feed and publisher pins belong to the installed application. Neither
// the renderer nor downloaded metadata can supply a replacement trust policy.
export async function checkDesktopUpdate(policy: DesktopUpdatePolicy): Promise<DesktopRelease> {
  if (!policy.allowedPublisherCertificateSha256.length
    || policy.allowedPublisherCertificateSha256.some((pin) => !/^[a-f0-9]{64}$/iu.test(pin))) {
    throw new Error("Desktop update publisher certificates are not configured");
  }
  const response = await fetchHttps(policy.feedUrl, 15_000);
  const chunks: Uint8Array[] = [];
  for await (const chunk of boundedBody(response, 64 * 1024)) chunks.push(chunk);
  const release = JSON.parse(Buffer.concat(chunks).toString("utf8")) as DesktopRelease;
  if (!release || typeof release.version !== "string" || typeof release.sha256 !== "string"
    || !/^[a-f0-9]{64}$/iu.test(release.sha256)) throw new Error("Invalid desktop release metadata");
  compareSemanticVersions(release.version, release.version);
  requireHttps(release.url);
  return release;
}

export async function stageDesktopUpdate(
  release: DesktopRelease, policy: DesktopUpdatePolicy, currentVersion: string, directory: string,
) {
  if (compareSemanticVersions(release.version, currentVersion) <= 0) throw new Error("The update version is not newer");
  await mkdir(directory, { recursive: true });
  const artifactPath = path.join(directory, `update-${randomBytes(12).toString("hex")}.exe`);
  try {
    const response = await fetchHttps(release.url, 10 * 60_000);
    await pipeline(boundedBody(response, 2 * 1024 ** 3), createWriteStream(artifactPath, { flags: "wx" }));
    const verified = await verifyWindowsUpdateCandidate(
      { artifactPath, version: release.version, expectedSha256: release.sha256 },
      { currentVersion, allowedPublisherCertificateSha256: policy.allowedPublisherCertificateSha256 },
    );
    if (!verified.accepted) throw new Error(verified.detail);
    return { artifactPath, ...verified };
  } catch (error) {
    await rm(artifactPath, { force: true });
    throw error;
  }
}

function requireHttps(value: string): void {
  const url = new URL(value);
  if (url.protocol !== "https:" || url.username || url.password) {
    throw new Error("Desktop updates require an HTTPS URL without credentials");
  }
}

async function fetchHttps(url: string, timeout: number): Promise<Response> {
  // Validate every redirect before connecting (including CDN redirects).
  const signal = AbortSignal.timeout(timeout);
  for (let redirects = 0; redirects <= 5; redirects++) {
    requireHttps(url);
    const response = await fetch(url, { redirect: "manual", signal });
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      const location = response.headers.get("location");
      await response.body?.cancel();
      if (!location) throw new Error("Update redirect has no location");
      url = new URL(location, url).href;
      continue;
    }
    if (!response.ok) {
      await response.body?.cancel();
      throw new Error(`Update download failed (HTTP ${response.status})`);
    }
    return response;
  }
  throw new Error("Too many update redirects");
}

async function* boundedBody(response: Response, limit: number): AsyncGenerator<Uint8Array> {
  if (!response.body) throw new Error("Update response has no body");
  const reader = response.body.getReader();
  let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      size += value.byteLength;
      if (size > limit) throw new Error("Update download exceeds its size limit");
      yield value;
    }
  } finally {
    await reader.cancel();
    reader.releaseLock();
  }
}
