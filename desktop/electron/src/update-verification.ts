import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { createReadStream } from "node:fs";
import path from "node:path";

export type AuthenticodeInspection = {
  status: string;
  artifactSha256?: string;
  signerSubject?: string;
  productVersion?: string;
  certificateSha256?: string;
};

export type UpdateCandidate = {
  artifactPath: string;
  version: string;
  expectedSha256: string;
};

export type UpdateVerificationPolicy = {
  currentVersion: string;
  allowedPublisherCertificateSha256: readonly string[];
};

export type UpdateRejectionCode =
  | "invalid-verification-policy"
  | "invalid-release-metadata"
  | "version-not-newer"
  | "artifact-inspection-failed"
  | "artifact-hash-mismatch"
  | "artifact-changed-during-verification"
  | "artifact-version-mismatch"
  | "artifact-unsigned"
  | "artifact-signature-invalid"
  | "publisher-not-allowed";

export type UpdateVerificationResult =
  | {
      accepted: true;
      version: string;
      sha256: string;
      signerSubject?: string;
      certificateSha256: string;
    }
  | {
      accepted: false;
      code: UpdateRejectionCode;
      detail: string;
    };

type SignatureInspector = (artifactPath: string) => AuthenticodeInspection;

export async function verifyWindowsUpdateCandidate(
  candidate: UpdateCandidate,
  policy: UpdateVerificationPolicy,
  inspectSignature: SignatureInspector = inspectAuthenticodeSignature,
): Promise<UpdateVerificationResult> {
  const expectedHash = normalizeSha256(candidate.expectedSha256);
  const normalizedPublishers = policy.allowedPublisherCertificateSha256.map(normalizeSha256);
  if (normalizedPublishers.length === 0 || normalizedPublishers.some((value) => !value)) {
    return reject(
      "invalid-verification-policy",
      "Every publisher entry must be a complete SHA-256 certificate fingerprint.",
    );
  }
  const allowedPublishers = normalizedPublishers as string[];
  if (!expectedHash || !parseSemanticVersion(candidate.version)) {
    return reject(
      "invalid-release-metadata",
      "The candidate version or SHA-256 digest is malformed.",
    );
  }
  if (!parseSemanticVersion(policy.currentVersion)) {
    return reject("invalid-verification-policy", "The installed version is malformed.");
  }
  if (compareSemanticVersions(candidate.version, policy.currentVersion) <= 0) {
    return reject(
      "version-not-newer",
      `Candidate ${candidate.version} is not newer than ${policy.currentVersion}.`,
    );
  }

  let actualHash: string;
  try {
    actualHash = await sha256(candidate.artifactPath);
  } catch (error) {
    return reject("artifact-inspection-failed", `The artifact could not be read: ${errorText(error)}`);
  }
  if (actualHash !== expectedHash) {
    return reject("artifact-hash-mismatch", "The artifact SHA-256 digest does not match release metadata.");
  }

  let signature: AuthenticodeInspection;
  try {
    signature = inspectSignature(candidate.artifactPath);
  } catch (error) {
    return reject(
      "artifact-inspection-failed",
      `Authenticode inspection failed: ${errorText(error)}`,
    );
  }
  if (signature.status === "NotSigned") {
    return reject("artifact-unsigned", "The update artifact has no Authenticode signature.");
  }
  if (signature.status !== "Valid") {
    return reject(
      "artifact-signature-invalid",
      `Authenticode reported status '${signature.status || "Unknown"}'.`,
    );
  }

  const certificateSha256 = normalizeSha256(signature.certificateSha256);
  if (!certificateSha256 || !allowedPublishers.includes(certificateSha256)) {
    return reject(
      "publisher-not-allowed",
      "The signer certificate is not in the configured publisher allowlist.",
    );
  }

  // Bind the advertised version to the signed PE resource, not just feed text.
  if (signature.productVersion !== candidate.version) {
    return reject("artifact-version-mismatch", "The signed installer version does not match the release.");
  }

  const inspectedArtifactSha256 = normalizeSha256(signature.artifactSha256);
  if (!inspectedArtifactSha256 || inspectedArtifactSha256 !== actualHash) {
    return reject(
      "artifact-changed-during-verification",
      "Authenticode inspection did not cover the same artifact bytes as the release digest.",
    );
  }

  let confirmedHash: string;
  try {
    confirmedHash = await sha256(candidate.artifactPath);
  } catch (error) {
    return reject(
      "artifact-inspection-failed",
      `The artifact could not be confirmed after signature inspection: ${errorText(error)}`,
    );
  }
  if (confirmedHash !== actualHash) {
    return reject(
      "artifact-changed-during-verification",
      "The update artifact changed while its signature was being verified.",
    );
  }

  return {
    accepted: true,
    version: candidate.version,
    sha256: confirmedHash,
    signerSubject: signature.signerSubject,
    certificateSha256,
  };
}

export async function assertVerifiedUpdateArtifactUnchanged(
  artifactPath: string,
  expectedSha256: string,
): Promise<void> {
  const expectedHash = normalizeSha256(expectedSha256);
  if (!expectedHash) throw new Error("The verified artifact SHA-256 is malformed");
  let actualHash: string;
  try {
    actualHash = await sha256(artifactPath);
  } catch (error) {
    throw new Error(`The verified update artifact could not be read: ${errorText(error)}`);
  }
  if (actualHash !== expectedHash) {
    throw new Error("The verified update artifact changed before installer launch");
  }
}

export function inspectAuthenticodeSignature(artifactPath: string): AuthenticodeInspection {
  if (process.platform !== "win32") {
    return { status: "UnsupportedPlatform" };
  }
  const result = spawnSync(
    resolveSignaturePowerShell(),
    [
      "-NoProfile",
      "-NonInteractive",
      "-Command",
      [
        "$artifactPath = [System.IO.Path]::GetFullPath($env:VIBE_UPDATE_ARTIFACT_PATH)",
        "$stream = [System.IO.File]::Open($artifactPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)",
        "try {",
        "  $artifactHasher = [System.Security.Cryptography.SHA256]::Create()",
        "  try {",
        "    $artifactBytes = $artifactHasher.ComputeHash($stream)",
        "    $artifactFingerprint = ([System.BitConverter]::ToString($artifactBytes)).Replace('-', '').ToLowerInvariant()",
        "  } finally { $artifactHasher.Dispose() }",
        "  $signature = Get-AuthenticodeSignature -LiteralPath $artifactPath",
        "  $certificateFingerprint = $null",
        "  if ($signature.SignerCertificate) {",
        "    $certificateHasher = [System.Security.Cryptography.SHA256]::Create()",
        "    try {",
        "      $certificateBytes = $certificateHasher.ComputeHash($signature.SignerCertificate.RawData)",
        "      $certificateFingerprint = ([System.BitConverter]::ToString($certificateBytes)).Replace('-', '').ToLowerInvariant()",
        "    } finally { $certificateHasher.Dispose() }",
        "  }",
        "  @{ productVersion = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($artifactPath).ProductVersion; status = $signature.Status.ToString(); artifactSha256 = $artifactFingerprint; signerSubject = $signature.SignerCertificate.Subject; certificateSha256 = $certificateFingerprint } | ConvertTo-Json -Compress",
        "} finally { $stream.Dispose() }",
      ].join("\n"),
    ],
    {
      env: { ...process.env, VIBE_UPDATE_ARTIFACT_PATH: path.resolve(artifactPath) },
      encoding: "utf8",
      windowsHide: true,
      timeout: 15_000,
      maxBuffer: 1_048_576,
    },
  );
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(result.stderr.trim() || result.stdout.trim() || "Authenticode inspection failed");
  }
  const parsed: unknown = JSON.parse(result.stdout.trim());
  if (!parsed || typeof parsed !== "object" || typeof (parsed as Record<string, unknown>).status !== "string") {
    throw new Error("Authenticode inspection returned an invalid payload");
  }
  const payload = parsed as Record<string, unknown>;
  return {
    status: payload.status as string,
    productVersion: typeof payload.productVersion === "string" ? payload.productVersion : undefined,
    artifactSha256: typeof payload.artifactSha256 === "string"
      ? payload.artifactSha256
      : undefined,
    signerSubject: typeof payload.signerSubject === "string" ? payload.signerSubject : undefined,
    certificateSha256: typeof payload.certificateSha256 === "string"
      ? payload.certificateSha256
      : undefined,
  };
}

export function compareSemanticVersions(left: string, right: string): number {
  const leftVersion = parseSemanticVersion(left);
  const rightVersion = parseSemanticVersion(right);
  if (!leftVersion || !rightVersion) throw new Error("Cannot compare malformed semantic versions");
  for (let index = 0; index < 3; index += 1) {
    const difference = leftVersion.core[index] - rightVersion.core[index];
    if (difference !== 0) return Math.sign(difference);
  }
  if (!leftVersion.prerelease.length && !rightVersion.prerelease.length) return 0;
  if (!leftVersion.prerelease.length) return 1;
  if (!rightVersion.prerelease.length) return -1;
  const length = Math.max(leftVersion.prerelease.length, rightVersion.prerelease.length);
  for (let index = 0; index < length; index += 1) {
    const leftPart = leftVersion.prerelease[index];
    const rightPart = rightVersion.prerelease[index];
    if (leftPart === undefined) return -1;
    if (rightPart === undefined) return 1;
    if (leftPart === rightPart) continue;
    const leftNumeric = /^\d+$/u.test(leftPart);
    const rightNumeric = /^\d+$/u.test(rightPart);
    if (leftNumeric && rightNumeric) {
      if (leftPart.length !== rightPart.length) return leftPart.length < rightPart.length ? -1 : 1;
      return leftPart < rightPart ? -1 : 1;
    }
    if (leftNumeric !== rightNumeric) return leftNumeric ? -1 : 1;
    return leftPart < rightPart ? -1 : 1;
  }
  return 0;
}

function parseSemanticVersion(value: string): { core: [number, number, number]; prerelease: string[] } | undefined {
  const match = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/u.exec(value);
  if (!match) return undefined;
  const core = [Number(match[1]), Number(match[2]), Number(match[3])] as [number, number, number];
  if (!core.every(Number.isSafeInteger)) return undefined;
  const prerelease = match[4]?.split(".") ?? [];
  if (prerelease.some((part) => /^\d+$/u.test(part) && part.length > 1 && part.startsWith("0"))) {
    return undefined;
  }
  return {
    core,
    prerelease,
  };
}

function normalizeSha256(value: string | undefined): string | undefined {
  const normalized = value?.replaceAll(":", "").trim().toLowerCase();
  return normalized && /^[a-f0-9]{64}$/u.test(normalized) ? normalized : undefined;
}

function resolveSignaturePowerShell(): string {
  const candidates = [
    process.env.ProgramFiles
      ? path.join(process.env.ProgramFiles, "PowerShell", "7", "pwsh.exe")
      : undefined,
    "pwsh.exe",
    "powershell.exe",
  ].filter((candidate): candidate is string => Boolean(candidate));
  for (const candidate of new Set(candidates)) {
    const probe = spawnSync(
      candidate,
      ["-NoProfile", "-NonInteractive", "-Command", "Get-Command Get-AuthenticodeSignature -ErrorAction Stop | Out-Null"],
      {
        encoding: "utf8",
        windowsHide: true,
        timeout: 5_000,
        maxBuffer: 262_144,
      },
    );
    if (!probe.error && probe.status === 0) return candidate;
  }
  throw new Error("No PowerShell host can inspect Authenticode signatures");
}

async function sha256(file: string): Promise<string> {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(file)) hash.update(chunk);
  return hash.digest("hex");
}

function reject(code: UpdateRejectionCode, detail: string): UpdateVerificationResult {
  return { accepted: false, code, detail };
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
