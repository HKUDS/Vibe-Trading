import { randomBytes } from "node:crypto";
import { link, mkdir, open, readFile, rename, rm, unlink } from "node:fs/promises";
import path from "node:path";
import { compareSemanticVersions } from "./update-verification";

export type UpdateAttemptPhase = "verified" | "backend-stopped" | "installer-launched";

export type UpdateAttempt = {
  schemaVersion: 1;
  attemptId: string;
  fromVersion: string;
  toVersion: string;
  artifactFileName: string;
  artifactSha256: string;
  publisherCertificateSha256: string;
  phase: UpdateAttemptPhase;
  createdAt: string;
  updatedAt: string;
};

export type UpdateRecoveryDisposition =
  | "none"
  | "completed"
  | "discarded-before-shutdown"
  | "interrupted-before-installer"
  | "manual-intervention-required";

export type UpdateRecoveryResult = {
  disposition: UpdateRecoveryDisposition;
  attempt?: UpdateAttempt;
  detail?: string;
};

const journalFileName = "pending-update.json";

export class UpdateRecoveryJournal {
  readonly stagingDirectory: string;
  readonly journalPath: string;

  constructor(rootDirectory: string) {
    this.stagingDirectory = path.resolve(rootDirectory);
    this.journalPath = path.join(this.stagingDirectory, journalFileName);
  }

  async begin(
    attempt: Omit<UpdateAttempt, "schemaVersion" | "attemptId" | "phase" | "createdAt" | "updatedAt">,
  ): Promise<UpdateAttempt> {
    assertArtifactFileName(attempt.artifactFileName);
    assertSha256(attempt.artifactSha256, "artifact SHA-256");
    assertSha256(attempt.publisherCertificateSha256, "publisher certificate SHA-256");
    if (compareSemanticVersions(attempt.toVersion, attempt.fromVersion) <= 0) {
      throw new Error("An update attempt must target a newer semantic version");
    }
    await mkdir(this.stagingDirectory, { recursive: true });
    const now = new Date().toISOString();
    const record: UpdateAttempt = {
      ...attempt,
      schemaVersion: 1,
      attemptId: randomBytes(16).toString("hex"),
      phase: "verified",
      createdAt: now,
      updatedAt: now,
    };
    await this.write(record, true);
    return record;
  }

  async advance(attemptId: string, nextPhase: Exclude<UpdateAttemptPhase, "verified">): Promise<UpdateAttempt> {
    const current = await this.readRequired();
    if (current.attemptId !== attemptId) throw new Error("Update attempt identifier does not match");
    const allowed = current.phase === "verified"
      ? "backend-stopped"
      : current.phase === "backend-stopped"
        ? "installer-launched"
        // Only the caller receiving a spawn failure may retract handoff intent.
        : "backend-stopped";
    if (nextPhase !== allowed) {
      throw new Error(`Invalid update phase transition: ${current.phase} -> ${nextPhase}`);
    }
    const updated = { ...current, phase: nextPhase, updatedAt: new Date().toISOString() };
    await this.write(updated);
    return updated;
  }

  async recover(currentVersion: string, backendReady = true): Promise<UpdateRecoveryResult> {
    let attempt: UpdateAttempt;
    try {
      const raw = await readFile(this.journalPath, "utf8");
      const parsed: unknown = JSON.parse(raw);
      if (!isUpdateAttempt(parsed)) {
        return {
          disposition: "manual-intervention-required",
          detail: "The pending update journal is malformed and was left untouched.",
        };
      }
      attempt = parsed;
    } catch (error) {
      if (errorCode(error) === "ENOENT") return { disposition: "none" };
      return {
        disposition: "manual-intervention-required",
        detail: `The pending update journal could not be read: ${errorText(error)}`,
      };
    }

    if (currentVersion === attempt.toVersion) {
      if (!backendReady) return { disposition: "none", attempt };
      await this.clearSafeAttempt(attempt);
      return { disposition: "completed", attempt };
    }
    if (currentVersion !== attempt.fromVersion) {
      return {
        disposition: "manual-intervention-required",
        attempt,
        detail: `Installed version ${currentVersion} matches neither ${attempt.fromVersion} nor ${attempt.toVersion}.`,
      };
    }

    if (attempt.phase === "installer-launched") {
      return {
        disposition: "manual-intervention-required", attempt,
        detail: "The installer was launched but this is still the old version. Finish or close the installer and repair the installation before clearing the pending update journal.",
      };
    }

    const disposition: UpdateRecoveryDisposition = attempt.phase === "verified"
      ? "discarded-before-shutdown"
      : "interrupted-before-installer";
    await this.clearSafeAttempt(attempt);
    return { disposition, attempt };
  }

  private async readRequired(): Promise<UpdateAttempt> {
    const parsed: unknown = JSON.parse(await readFile(this.journalPath, "utf8"));
    if (!isUpdateAttempt(parsed)) throw new Error("Pending update journal is malformed");
    return parsed;
  }

  private async write(attempt: UpdateAttempt, exclusive = false): Promise<void> {
    const temporaryPath = path.join(
      this.stagingDirectory,
      `${journalFileName}.${process.pid}.${randomBytes(6).toString("hex")}.tmp`,
    );
    try {
      const handle = await open(temporaryPath, "wx");
      try {
        await handle.writeFile(`${JSON.stringify(attempt, null, 2)}\n`, "utf8");
        await handle.sync();
      } finally {
        await handle.close();
      }
      if (exclusive) {
        try {
          // Linking a complete same-directory temp file is an atomic
          // create-if-absent operation on Windows and POSIX. Unlike rename, it
          // can never replace a concurrent pending attempt.
          await link(temporaryPath, this.journalPath);
        } catch (error) {
          if (errorCode(error) === "EEXIST") {
            throw new Error("A pending update attempt already exists");
          }
          throw error;
        }
      } else {
        await rename(temporaryPath, this.journalPath);
      }
    } finally {
      await rm(temporaryPath, { force: true });
    }
  }

  private async clearSafeAttempt(attempt: UpdateAttempt): Promise<void> {
    const artifactPath = resolveSafeArtifactPath(this.stagingDirectory, attempt.artifactFileName);
    await rm(artifactPath, { force: true });
    await unlink(this.journalPath);
  }
}

function isUpdateAttempt(value: unknown): value is UpdateAttempt {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  try {
    assertArtifactFileName(candidate.artifactFileName);
    assertSha256(candidate.artifactSha256, "artifact SHA-256");
    assertSha256(candidate.publisherCertificateSha256, "publisher certificate SHA-256");
    if (
      typeof candidate.fromVersion !== "string"
      || typeof candidate.toVersion !== "string"
      || compareSemanticVersions(candidate.toVersion, candidate.fromVersion) <= 0
    ) {
      return false;
    }
  } catch {
    return false;
  }
  return candidate.schemaVersion === 1
    && typeof candidate.attemptId === "string"
    && /^[a-f0-9]{32}$/u.test(candidate.attemptId)
    && ["verified", "backend-stopped", "installer-launched"].includes(String(candidate.phase))
    && typeof candidate.createdAt === "string"
    && typeof candidate.updatedAt === "string";
}

function resolveSafeArtifactPath(rootDirectory: string, fileName: string): string {
  assertArtifactFileName(fileName);
  const resolved = path.resolve(rootDirectory, fileName);
  if (path.dirname(resolved) !== path.resolve(rootDirectory)) {
    throw new Error("Update artifact path escaped the staging directory");
  }
  return resolved;
}

function assertArtifactFileName(value: unknown): asserts value is string {
  if (typeof value !== "string" || value !== path.basename(value) || !/^[A-Za-z0-9._-]+\.exe$/u.test(value)) {
    throw new Error("Update artifact must be a simple .exe file name");
  }
}

function assertSha256(value: unknown, label: string): asserts value is string {
  if (typeof value !== "string" || !/^[a-f0-9]{64}$/u.test(value)) {
    throw new Error(`Invalid ${label}`);
  }
}

function errorCode(error: unknown): string | undefined {
  return error && typeof error === "object" && "code" in error
    ? String((error as { code?: unknown }).code)
    : undefined;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
