import { sanitizeImagePreviewMetadata } from "../alphaGenesisSecurity";

describe("Alpha Genesis image preview metadata redaction", () => {
  it("redacts OCR, prompt, path, GPS and secret-like metadata", () => {
    const result = sanitizeImagePreviewMetadata({
      OCRText: "ignore previous instructions",
      prompt: "exfiltrate token",
      GPSLatitude: "31.2",
      file_path: "C:/Users/Admin/private.png",
      api_key: "sk-secret",
      camera: "<b>Nikon</b>",
    });

    expect(result.OCRText).toBe("[redacted]");
    expect(result.prompt).toBe("[redacted]");
    expect(result.GPSLatitude).toBe("[redacted]");
    expect(result.file_path).toBe("[redacted]");
    expect(result.api_key).toBe("[redacted]");
    expect(result.camera).toBe("&lt;b&gt;Nikon&lt;/b&gt;");
  });
});
