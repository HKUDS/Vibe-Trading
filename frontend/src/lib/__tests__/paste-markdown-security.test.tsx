import { sanitizePastedMarkdown } from "../alphaGenesisSecurity";

describe("Alpha Genesis paste/Markdown security", () => {
  it("escapes HTML and neutralizes dangerous Markdown links", () => {
    const result = sanitizePastedMarkdown(
      '<img src=x onerror=alert(1)> [run](javascript:alert(1)) ![x](data:text/html;base64,abc)',
    );

    expect(result).not.toContain("<img");
    expect(result.toLowerCase()).not.toContain("javascript:");
    expect(result.toLowerCase()).not.toContain("data:text/html");
    expect(result).toContain("&lt;img");
    expect(result).toContain("\\[run\\]");
  });
});
