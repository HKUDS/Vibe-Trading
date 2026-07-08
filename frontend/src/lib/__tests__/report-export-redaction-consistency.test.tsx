import { redactAlphaGenesisReport } from "../alphaGenesisSecurity";

describe("Alpha Genesis report export redaction", () => {
  it("redacts nested secret-like keys without changing research evidence", () => {
    const report = {
      schema_version: "alpha_genesis_report.v1",
      decision: "research_only",
      data_snapshot_hash: "sha256:snapshot",
      metadata: {
        token: "secret-token",
        nested: { broker_password: "pw", harmless: "kept" },
      },
    };

    const result = redactAlphaGenesisReport(report);

    expect(result.decision).toBe("research_only");
    expect(result.data_snapshot_hash).toBe("sha256:snapshot");
    expect(result.metadata.token).toBe("[redacted]");
    expect(result.metadata.nested.broker_password).toBe("[redacted]");
    expect(result.metadata.nested.harmless).toBe("kept");
  });
});
