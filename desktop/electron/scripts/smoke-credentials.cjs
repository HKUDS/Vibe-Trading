const assert = require("node:assert/strict");
const { promises: fs } = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { app } = require("electron");
const { SecureCredentialStore } = require("../dist/secure-credentials.js");
const providers = require("../../../agent/src/providers/llm_providers.json");

void app.whenReady().then(run).catch(async (error) => {
  console.error(error);
  app.exit(1);
});

async function run() {
  const temporaryRoot = await fs.mkdtemp(
    path.join(os.tmpdir(), "vibe-trading-credentials-"),
  );
  const homeDirectory = path.join(temporaryRoot, "home");
  const userDataDirectory = path.join(temporaryRoot, "user-data");
  const configDirectory = path.join(homeDirectory, ".vibe-trading");
  let exitCode = 0;

  try {
    assert.deepEqual(require("../dist/llm_providers.json"), providers);
    const names = [...new Set(providers.flatMap((p) => p.api_key_env ? [p.api_key_env] : [])),
      "TUSHARE_TOKEN", "GILDATA_TOKEN"].filter((name) => name !== "ANTHROPIC_API_KEY");
    const expected = Object.fromEntries(names.map((name) => [name, `desktop-smoke-${name}-secret`]));
    await fs.mkdir(configDirectory, { recursive: true });
    await fs.writeFile(
      path.join(configDirectory, ".env"),
      [
        ...names.map((name) => `${name}='${expected[name]}'`),
        "ANTHROPIC_API_KEY=sk-xxx",
        "NON_SECRET_SETTING=preserved",
        "",
      ].join("\n"),
      "utf8",
    );

    const store = new SecureCredentialStore({ homeDirectory, userDataDirectory });
    await store.initialize();

    const initialEnvironment = store.environment();
    assert.deepEqual(initialEnvironment, expected);

    const status = store.status();
    assert.deepEqual(status.configured, [...names].sort());
    assert.deepEqual(status.migrated, names);

    const encryptedFile = await fs.readFile(
      path.join(userDataDirectory, "credentials.v1.json"),
      "utf8",
    );
    const migratedDotenv = await fs.readFile(path.join(configDirectory, ".env"), "utf8");
    for (const [name, secret] of Object.entries(expected)) {
      assert.ok(!encryptedFile.includes(secret), "encrypted file contains a plaintext secret");
      assert.ok(!migratedDotenv.includes(secret), "dotenv contains a migrated secret");
      assert.ok(migratedDotenv.includes(`# ${name} is stored by Vibe-Trading Desktop`));
    }
    assert.match(migratedDotenv, /ANTHROPIC_API_KEY=sk-xxx/u);
    assert.match(migratedDotenv, /NON_SECRET_SETTING=preserved/u);
    // A stale dotenv must not overwrite an existing encrypted credential.
    await fs.appendFile(path.join(configDirectory, ".env"), "OPENAI_API_KEY=stale-secret\n");
    const reloadedStore = new SecureCredentialStore({ homeDirectory, userDataDirectory });
    await reloadedStore.initialize();
    assert.deepEqual(reloadedStore.environment(), expected);
    assert.deepEqual(reloadedStore.status().migrated, []);
    assert.ok(!(await fs.readFile(path.join(configDirectory, ".env"), "utf8")).includes("stale-secret"));

    const credentialPath = path.join(userDataDirectory, "credentials.v1.json");
    const original = await fs.readFile(credentialPath);
    const dotenvPath = path.join(configDirectory, ".env");
    await fs.appendFile(dotenvPath, "OPENAI_API_KEY=migration-backup\n");
    const before = await fs.readFile(dotenvPath);
    const corrupt = JSON.stringify({ version: 1, values: { OPENAI_API_KEY: "corrupt" } });
    await fs.writeFile(credentialPath, corrupt);
    await assert.rejects(new SecureCredentialStore({ homeDirectory, userDataDirectory }).initialize());
    assert.deepEqual(await fs.readFile(dotenvPath), before);
    assert.equal(await fs.readFile(credentialPath, "utf8"), corrupt);
    await fs.writeFile(credentialPath, original);

    for (const name of names) {
      await store.set(name, "desktop-smoke-replacement");
      assert.equal(store.environment()[name], "desktop-smoke-replacement");
      await store.set(name, null);
      assert.equal(store.environment()[name], undefined);
    }
    await assert.rejects(
      store.set("UNSUPPORTED_SECRET", "not-allowed"),
      /This credential key is not supported\./u,
    );

    console.log(
      JSON.stringify({
        encryptionAvailable: status.available,
        migrationVerified: true,
        persistenceVerified: true,
        plaintextRemovalVerified: true,
        allowlistVerified: true,
        clearVerified: true,
      }, null, 2),
    );
  } catch (error) {
    console.error(error);
    exitCode = 1;
  } finally {
    await fs.rm(temporaryRoot, { recursive: true, force: true });
  }
  app.exit(exitCode);
}
