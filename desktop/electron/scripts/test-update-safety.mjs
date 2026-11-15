import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { writeFileSync } from "node:fs";
import { access, mkdir, mkdtemp, readFile, symlink, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import os from "node:os";
import path from "node:path";

import { assertDataOutsideInstallation, checkDesktopUpdate, stageDesktopUpdate } from "../dist/update.js";
import { BackendManager } from "../dist/backend-manager.js";
import { getDesktopMessages } from "../dist/locales.js";
import { UpdateRecoveryJournal } from "../dist/update-recovery.js";
import {
  assertVerifiedUpdateArtifactUnchanged,
  compareSemanticVersions,
  inspectAuthenticodeSignature,
  verifyWindowsUpdateCandidate,
} from "../dist/update-verification.js";

const fixture = Buffer.from("vibe-trading-update-safety-fixture", "utf8");
const fixtureHash = createHash("sha256").update(fixture).digest("hex");
const publisher = "ab".repeat(32);
const otherPublisher = "cd".repeat(32);
const testRoot = await mkdtemp(path.join(os.tmpdir(), "vibe-update-safety-"));
assertDataOutsideInstallation(path.join(testRoot, "program"), [path.join(testRoot, "profile")]);
for (const directory of [path.join(testRoot, "program"), path.join(testRoot, "program", "sessions"), "relative-data"]) {
  assert.throws(() => assertDataOutsideInstallation(path.join(testRoot, "program"), [directory]));
}
await mkdir(path.join(testRoot, "program"));
await symlink(path.join(testRoot, "program"), path.join(testRoot, "profile-link"), "junction");
assert.throws(() => assertDataOutsideInstallation(path.join(testRoot, "program"), [
  path.join(testRoot, "profile-link", "not-created-yet", "sessions"),
]));
const artifactPath = path.join(testRoot, "candidate.exe");
await writeFile(artifactPath, fixture);

const candidate = { artifactPath, version: "0.3.1", expectedSha256: fixtureHash };
const policy = {
  currentVersion: "0.3.0",
  allowedPublisherCertificateSha256: [publisher],
};
const validSignature = () => ({
  status: "Valid",
  productVersion: candidate.version,
  artifactSha256: fixtureHash,
  signerSubject: "CN=Vibe-Trading Test Publisher",
  certificateSha256: publisher,
});

await expectRejection(candidate, policy, () => ({ ...validSignature(), productVersion: "0.2.9" }), "artifact-version-mismatch");

// Exercise the new feed/download boundary; signature and journal cases stay below.
const originalFetch = globalThis.fetch;
try {
  const release = { version: "0.3.1", url: "https://updates.example/installer.exe", sha256: fixtureHash };
  const feedPolicy = { feedUrl: "https://updates.example/latest.json", allowedPublisherCertificateSha256: [publisher] };
  globalThis.fetch = async () => Response.json(release);
  assert.deepEqual(await checkDesktopUpdate(feedPolicy), release);
  await assert.rejects(checkDesktopUpdate({ ...feedPolicy, allowedPublisherCertificateSha256: [] }), /not configured/u);
  let requests = 0;
  globalThis.fetch = async () => { requests++; return new Response(null, { status: 302, headers: { location: "http://insecure.example/file" } }); };
  await assert.rejects(checkDesktopUpdate(feedPolicy), /HTTPS/u);
  assert.equal(requests, 1, "an insecure redirect must not be followed");
  globalThis.fetch = async () => new Response("tampered download");
  const downloadDirectory = path.join(testRoot, "download");
  await assert.rejects(stageDesktopUpdate(release, feedPolicy, "0.3.0", downloadDirectory), /SHA-256/u);
  assert.deepEqual(await (await import("node:fs/promises")).readdir(downloadDirectory), []);
} finally {
  globalThis.fetch = originalFetch;
}

const accepted = await verifyWindowsUpdateCandidate(candidate, policy, validSignature);
assert.equal(accepted.accepted, true);
await assertVerifiedUpdateArtifactUnchanged(artifactPath, accepted.sha256);

await expectRejection(
  { ...candidate, expectedSha256: "00".repeat(32) },
  policy,
  validSignature,
  "artifact-hash-mismatch",
);
await expectRejection(candidate, policy, () => ({ status: "NotSigned" }), "artifact-unsigned");
await expectRejection(
  candidate,
  policy,
  () => ({ status: "HashMismatch", certificateSha256: publisher }),
  "artifact-signature-invalid",
);
await expectRejection(
  candidate,
  policy,
  () => ({ status: "Valid", certificateSha256: otherPublisher }),
  "publisher-not-allowed",
);
await expectRejection(
  { ...candidate, version: "0.2.9" },
  policy,
  validSignature,
  "version-not-newer",
);
await expectRejection(
  candidate,
  { ...policy, allowedPublisherCertificateSha256: [] },
  validSignature,
  "invalid-verification-policy",
);
await expectRejection(
  candidate,
  { ...policy, allowedPublisherCertificateSha256: [publisher, "malformed"] },
  validSignature,
  "invalid-verification-policy",
);
await expectRejection(
  { ...candidate, artifactPath: path.join(testRoot, "missing.exe") },
  policy,
  validSignature,
  "artifact-inspection-failed",
);
await expectRejection(
  candidate,
  policy,
  () => ({ ...validSignature(), artifactSha256: otherPublisher }),
  "artifact-changed-during-verification",
);

const mutationArtifactPath = path.join(testRoot, "mutation.exe");
await writeFile(mutationArtifactPath, fixture);
await expectRejection(
  { ...candidate, artifactPath: mutationArtifactPath },
  policy,
  (inspectedPath) => {
    writeFileSync(inspectedPath, Buffer.from("changed-during-signature-inspection", "utf8"));
    return validSignature();
  },
  "artifact-changed-during-verification",
);

await writeFile(artifactPath, Buffer.from("changed-after-verification", "utf8"));
await assert.rejects(
  () => assertVerifiedUpdateArtifactUnchanged(artifactPath, accepted.sha256),
  /changed before installer launch/u,
);
await writeFile(artifactPath, fixture);

assert.equal(compareSemanticVersions("0.3.1", "0.3.0"), 1);
assert.equal(compareSemanticVersions("0.3.1-beta.2", "0.3.1-beta.1"), 1);
assert.equal(compareSemanticVersions("0.3.1-beta.1", "0.3.1"), -1);
assert.equal(compareSemanticVersions("0.3.0+build.2", "0.3.0+build.1"), 0);
assert.throws(() => compareSemanticVersions("0.3.1-01", "0.3.0"));

let authenticodeAdapterVerified = false;
if (process.platform === "win32") {
  if (!process.env.SystemRoot) throw new Error("SystemRoot is required for the Authenticode adapter test");
  const signedSystemBinary = path.join(
    process.env.SystemRoot,
    "System32",
    "WindowsPowerShell",
    "v1.0",
    "powershell.exe",
  );
  const inspection = inspectAuthenticodeSignature(signedSystemBinary);
  assert.equal(inspection.status, "Valid");
  assert.match(inspection.certificateSha256 || "", /^[a-f0-9]{64}$/u);
  authenticodeAdapterVerified = true;
}

for (const scenario of [
  { phase: "verified", disposition: "discarded-before-shutdown" },
  { phase: "backend-stopped", disposition: "interrupted-before-installer" },
  { phase: "installer-launched", disposition: "manual-intervention-required" },
  { phase: "spawn-failed", disposition: "interrupted-before-installer" },
]) {
  const directory = await mkdtemp(path.join(testRoot, "recovery-"));
  const journal = new UpdateRecoveryJournal(directory);
  const stagedArtifact = path.join(directory, "update.exe");
  await writeFile(stagedArtifact, fixture);
  let attempt = await journal.begin(newAttempt("update.exe"));
  if (scenario.phase !== "verified") {
    attempt = await journal.advance(attempt.attemptId, "backend-stopped");
  }
  if (["installer-launched", "spawn-failed"].includes(scenario.phase)) {
    attempt = await journal.advance(attempt.attemptId, "installer-launched");
  }
  if (scenario.phase === "spawn-failed") await journal.advance(attempt.attemptId, "backend-stopped");
  const recovery = await journal.recover("0.3.0", false);
  assert.equal(recovery.disposition, scenario.disposition);
  assert.equal(await exists(stagedArtifact), scenario.phase === "installer-launched");
  assert.equal(await exists(journal.journalPath), scenario.phase === "installer-launched");
}

const completedDirectory = await mkdtemp(path.join(testRoot, "completed-"));
const completedJournal = new UpdateRecoveryJournal(completedDirectory);
await writeFile(path.join(completedDirectory, "update.exe"), fixture);
await completedJournal.begin(newAttempt("update.exe"));
assert.equal((await completedJournal.recover("0.3.1", false)).disposition, "none");
assert.equal(await exists(completedJournal.journalPath), true);
assert.equal((await completedJournal.recover("0.3.1")).disposition, "completed");

const mismatchDirectory = await mkdtemp(path.join(testRoot, "mismatch-"));
const mismatchJournal = new UpdateRecoveryJournal(mismatchDirectory);
const mismatchArtifact = path.join(mismatchDirectory, "update.exe");
await writeFile(mismatchArtifact, fixture);
await mismatchJournal.begin(newAttempt("update.exe"));
await assert.rejects(() => mismatchJournal.begin(newAttempt("other.exe")), /already exists/u);
assert.equal(
  (await mismatchJournal.recover("0.4.0")).disposition,
  "manual-intervention-required",
);
assert.equal(await exists(mismatchArtifact), true);
assert.equal(await exists(mismatchJournal.journalPath), true);

const concurrentDirectory = await mkdtemp(path.join(testRoot, "concurrent-"));
const concurrentJournal = new UpdateRecoveryJournal(concurrentDirectory);
const concurrentResults = await Promise.allSettled([
  concurrentJournal.begin(newAttempt("first.exe")),
  concurrentJournal.begin(newAttempt("second.exe")),
]);
const concurrentWinners = concurrentResults.filter((result) => result.status === "fulfilled");
const concurrentLosers = concurrentResults.filter((result) => result.status === "rejected");
assert.equal(concurrentWinners.length, 1);
assert.equal(concurrentLosers.length, 1);
assert.match(String(concurrentLosers[0].reason), /already exists/u);
const concurrentRecord = JSON.parse(await readFile(concurrentJournal.journalPath, "utf8"));
assert.equal(concurrentRecord.attemptId, concurrentWinners[0].value.attemptId);
assert.equal(concurrentRecord.artifactFileName, concurrentWinners[0].value.artifactFileName);

const traversalDirectory = await mkdtemp(path.join(testRoot, "traversal-"));
const traversalJournal = new UpdateRecoveryJournal(traversalDirectory);
const protectedFile = path.join(testRoot, "protected.exe");
await writeFile(protectedFile, fixture);
await writeFile(traversalJournal.journalPath, JSON.stringify({
  ...newAttempt("../protected.exe"),
  schemaVersion: 1,
  attemptId: "ef".repeat(16),
  phase: "verified",
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
}));
assert.equal(
  (await traversalJournal.recover("0.3.0")).disposition,
  "manual-intervention-required",
);
assert.equal((await readFile(protectedFile)).equals(fixture), true);

const hungListener = createServer(() => {
  // Accept TCP and deliberately never speak HTTP. Shutdown evidence must still
  // classify this port as open.
});
await listen(hungListener);
const hungAddress = hungListener.address();
if (!hungAddress || typeof hungAddress === "string") throw new Error("Expected a TCP listener address");
const hungBaseUrl = `http://127.0.0.1:${hungAddress.port}/`;
const retainedBackendPid = 2_147_483_646;
const retainedWatchdogPid = 2_147_483_647;
const retainedManager = new BackendManager({
  appPath: testRoot,
  resourcesPath: testRoot,
  allowSourceDiscovery: false,
  logDirectory: testRoot,
  apiAuthKey: "test-auth-key",
  messages: getDesktopMessages("en"),
  shutdownEvidenceTimeoutMilliseconds: 25,
  onStatus: () => {},
  onUnexpectedExit: () => {},
});
// TypeScript `private` fields compile to ordinary properties. This test seam
// models an already-exited watchdog whose exact identifiers must be retained
// while a stubborn listener survives.
retainedManager.watchdog = {
  pid: retainedWatchdogPid,
  exitCode: 0,
  signalCode: null,
};
retainedManager.backendPid = retainedBackendPid;
retainedManager.baseUrl = hungBaseUrl;
await assert.rejects(() => retainedManager.stopForUpdate(), /could not be verified/u);
assert.equal(retainedManager.url, hungBaseUrl);
assert.equal(retainedManager.processId, retainedBackendPid);
await close(hungListener);
const retriedEvidence = await retainedManager.stopForUpdate();
assert.deepEqual(retriedEvidence, {
  backendPid: retainedBackendPid,
  watchdogPid: retainedWatchdogPid,
  backendExited: true,
  watchdogExited: true,
  listenerClosed: true,
});
assert.equal(retainedManager.url, undefined);
assert.equal(retainedManager.processId, undefined);

console.log(JSON.stringify({
  verificationCases: ["accepted", "tampered", "unsigned", "invalid-signature", "wrong-publisher", "signed-version-mismatch", "downgraded", "mutation-during-verification", "mutation-before-launch"],
  recoveryPhases: ["verified", "backend-stopped", "installer-launched", "completed", "version-mismatch", "path-traversal", "concurrent-begin"],
  shutdownFailureRetryVerified: true,
  authenticodeAdapterVerified,
  releaseChannelConfigured: false,
}, null, 2));

async function expectRejection(candidateValue, policyValue, inspector, expectedCode) {
  const result = await verifyWindowsUpdateCandidate(candidateValue, policyValue, inspector);
  assert.equal(result.accepted, false);
  assert.equal(result.code, expectedCode);
}

function newAttempt(artifactFileName) {
  return {
    fromVersion: "0.3.0",
    toVersion: "0.3.1",
    artifactFileName,
    artifactSha256: fixtureHash,
    publisherCertificateSha256: publisher,
  };
}

async function exists(file) {
  try {
    await access(file);
    return true;
  } catch {
    return false;
  }
}

function listen(server) {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      resolve();
    });
  });
}

function close(server) {
  return new Promise((resolve, reject) => {
    server.close((error) => error ? reject(error) : resolve());
  });
}
