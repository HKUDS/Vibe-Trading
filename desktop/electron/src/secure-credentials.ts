import { app, safeStorage } from "electron";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import type { DesktopMessages } from "./locales";

type CredentialFile = {
  version: 1;
  values: Record<string, string>;
};

// Bundled from agent/src/providers/llm_providers.json by copy-static.mjs.
const providers: { api_key_env?: string | null }[] = require("./llm_providers.json");
const ENV_CREDENTIALS = new Set([
  ...providers.flatMap((provider) => provider.api_key_env ? [provider.api_key_env] : []),
  "TUSHARE_TOKEN",
  "GILDATA_TOKEN",
]);

const PLACEHOLDER_VALUES = new Set([
  "",
  "sk-or-v1-your-key-here",
  "sk-or-...here",
  "sk-xxx",
  "xxx",
  "gsk_xxx",
  "your-tushare-token",
  "your-gildata-token",
]);

export type CredentialStatus = {
  available: boolean;
  configured: string[];
  migrated: string[];
};

export type SecureCredentialStoreOptions = {
  userDataDirectory?: string;
  homeDirectory?: string;
  messages?: Pick<
    DesktopMessages,
    | "credentialEncryptionUnavailable"
    | "credentialFileUnsupported"
    | "credentialKeyUnsupported"
  >;
};

const defaultMessages: NonNullable<SecureCredentialStoreOptions["messages"]> = {
  credentialEncryptionUnavailable: "Credential encryption is unavailable for this Windows user session.",
  credentialFileUnsupported: "The desktop credential file format is not supported.",
  credentialKeyUnsupported: "This credential key is not supported.",
};

export class SecureCredentialStore {
  private readonly filePath: string;
  private readonly homeDirectory: string;
  private readonly messages: NonNullable<SecureCredentialStoreOptions["messages"]>;
  private values: Record<string, string> = {};
  private migrated: string[] = [];

  constructor(options: SecureCredentialStoreOptions = {}) {
    this.filePath = path.join(
      options.userDataDirectory ?? app.getPath("userData"),
      "credentials.v1.json",
    );
    this.homeDirectory = options.homeDirectory ?? os.homedir();
    this.messages = options.messages ?? defaultMessages;
  }

  async initialize(): Promise<void> {
    if (!safeStorage.isEncryptionAvailable()) {
      throw new Error(this.messages.credentialEncryptionUnavailable);
    }
    await this.load();
    // Verify existing ciphertext before removing any plaintext migration source.
    this.environment();
    await this.migrateDotenv(path.join(this.homeDirectory, ".vibe-trading", ".env"));
  }

  status(): CredentialStatus {
    return {
      available: safeStorage.isEncryptionAvailable(),
      configured: Object.keys(this.values).sort(),
      migrated: [...this.migrated],
    };
  }

  async set(name: string, value: string | null): Promise<void> {
    this.assertAllowed(name);
    const normalized = value?.trim() ?? "";
    if (!normalized) {
      delete this.values[name];
    } else {
      this.values[name] = safeStorage.encryptString(normalized).toString("base64");
    }
    await this.persist();
  }

  environment(): NodeJS.ProcessEnv {
    const output: NodeJS.ProcessEnv = {};
    for (const name of Object.keys(this.values)) {
      const value = this.decrypt(name);
      if (value) output[name] = value;
    }
    return output;
  }

  private decrypt(name: string): string {
    return safeStorage.decryptString(Buffer.from(this.values[name], "base64"));
  }

  private assertAllowed(name: string): void {
    if (!ENV_CREDENTIALS.has(name)) {
      throw new Error(this.messages.credentialKeyUnsupported);
    }
  }

  private async load(): Promise<void> {
    try {
      const parsed = JSON.parse(await fs.readFile(this.filePath, "utf8")) as CredentialFile;
      if (parsed.version !== 1 || !parsed.values || typeof parsed.values !== "object") {
        throw new Error(this.messages.credentialFileUnsupported);
      }
      this.values = Object.fromEntries(
        Object.entries(parsed.values).filter(
          ([name, value]) => ENV_CREDENTIALS.has(name) && typeof value === "string",
        ),
      );
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
  }

  private async persist(): Promise<void> {
    await fs.mkdir(path.dirname(this.filePath), { recursive: true });
    const temporary = `${this.filePath}.${process.pid}.tmp`;
    await fs.writeFile(
      temporary,
      `${JSON.stringify({ version: 1, values: this.values }, null, 2)}\n`,
      { encoding: "utf8", mode: 0o600 },
    );
    await fs.rename(temporary, this.filePath);
  }

  private async migrateDotenv(filePath: string): Promise<void> {
    let text: string;
    try {
      text = await fs.readFile(filePath, "utf8");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
      throw error;
    }

    let changed = false;
    const nextLines: string[] = [];
    for (const line of text.split(/\r?\n/u)) {
      const match = line.match(/^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*)\s*$/u);
      const name = match?.[1] ?? "";
      const value = unquote(match?.[2] ?? "");
      if (ENV_CREDENTIALS.has(name) && !PLACEHOLDER_VALUES.has(value.toLowerCase())) {
        if (!this.values[name]) {
          this.values[name] = safeStorage.encryptString(value).toString("base64");
          this.migrated.push(name);
        }
        nextLines.push(`# ${name} is stored by Vibe-Trading Desktop secure storage.`);
        changed = true;
      } else {
        nextLines.push(line);
      }
    }
    if (changed) {
      await this.persist();
      await atomicTextWrite(filePath, nextLines.join("\n"));
    }
  }

}

function unquote(value: string): string {
  const trimmed = value.trim();
  if (
    trimmed.length >= 2 &&
    ((trimmed.startsWith('"') && trimmed.endsWith('"')) ||
      (trimmed.startsWith("'") && trimmed.endsWith("'")))
  ) {
    return trimmed.slice(1, -1).trim();
  }
  return trimmed;
}

async function atomicTextWrite(filePath: string, content: string): Promise<void> {
  const temporary = `${filePath}.${process.pid}.tmp`;
  await fs.writeFile(temporary, content, { encoding: "utf8", mode: 0o600 });
  await fs.rename(temporary, filePath);
}
