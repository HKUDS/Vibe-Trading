const assert = require("node:assert/strict");
const { promises: fs } = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { app } = require("electron");
const { SecureCredentialStore } = require("../dist/secure-credentials.js");

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
    await fs.mkdir(configDirectory, { recursive: true });
    await fs.writeFile(
      path.join(configDirectory, ".env"),
      [
        "OPENAI_API_KEY=desktop-smoke-openai-secret",
        "MODELSCOPE_API_KEY=desktop-smoke-modelscope-secret",
        "TUSHARE_TOKEN='desktop-smoke-tushare-secret'",
        "ANTHROPIC_API_KEY=sk-xxx",
        "GILDATA_TOKEN=desktop-smoke-gildata-secret",
        "NON_SECRET_SETTING=preserved",
        "",
      ].join("\n"),
      "utf8",
    );

    const store = new SecureCredentialStore({ homeDirectory, userDataDirectory });
    await store.initialize();

    const initialEnvironment = store.environment();
    assert.equal(initialEnvironment.OPENAI_API_KEY, "desktop-smoke-openai-secret");
    assert.equal(
      initialEnvironment.MODELSCOPE_API_KEY,
      "desktop-smoke-modelscope-secret",
    );
    assert.equal(initialEnvironment.TUSHARE_TOKEN, "desktop-smoke-tushare-secret");
    assert.equal(initialEnvironment.GILDATA_TOKEN, "desktop-smoke-gildata-secret");
    assert.equal(initialEnvironment.ANTHROPIC_API_KEY, undefined);

    const status = store.status();
    assert.deepEqual(status.configured, [
      "GILDATA_TOKEN",
      "MODELSCOPE_API_KEY",
      "OPENAI_API_KEY",
      "TUSHARE_TOKEN",
    ]);
    assert.deepEqual(status.migrated, [
      "OPENAI_API_KEY",
      "MODELSCOPE_API_KEY",
      "TUSHARE_TOKEN",
      "GILDATA_TOKEN",
    ]);

    const encryptedFile = await fs.readFile(
      path.join(userDataDirectory, "credentials.v1.json"),
      "utf8",
    );
    for (const secret of Object.values(initialEnvironment)) {
      assert.ok(!encryptedFile.includes(secret), "encrypted file contains a plaintext secret");
    }

    const migratedDotenv = await fs.readFile(path.join(configDirectory, ".env"), "utf8");
    assert.match(migratedDotenv, /OPENAI_API_KEY is stored by Vibe-Trading Desktop/u);
    assert.match(migratedDotenv, /MODELSCOPE_API_KEY is stored by Vibe-Trading Desktop/u);
    assert.match(migratedDotenv, /TUSHARE_TOKEN is stored by Vibe-Trading Desktop/u);
    assert.match(migratedDotenv, /ANTHROPIC_API_KEY=sk-xxx/u);
    assert.match(migratedDotenv, /NON_SECRET_SETTING=preserved/u);
    assert.ok(!migratedDotenv.includes("desktop-smoke-openai-secret"));
    assert.ok(!migratedDotenv.includes("desktop-smoke-modelscope-secret"));
    assert.ok(!migratedDotenv.includes("desktop-smoke-tushare-secret"));

    assert.ok(!migratedDotenv.includes("desktop-smoke-gildata-secret"));

    const reloadedStore = new SecureCredentialStore({ homeDirectory, userDataDirectory });
    await reloadedStore.initialize();
    assert.equal(
      reloadedStore.environment().OPENAI_API_KEY,
      "desktop-smoke-openai-secret",
    );
    assert.equal(
      reloadedStore.environment().MODELSCOPE_API_KEY,
      "desktop-smoke-modelscope-secret",
    );

    await store.set("OPENAI_API_KEY", "desktop-smoke-replacement");
    assert.equal(store.environment().OPENAI_API_KEY, "desktop-smoke-replacement");
    await store.set("OPENAI_API_KEY", null);
    assert.equal(store.environment().OPENAI_API_KEY, undefined);
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
