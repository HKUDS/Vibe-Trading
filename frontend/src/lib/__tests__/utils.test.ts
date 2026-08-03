import { cn } from "../utils";

describe("cn", () => {
  it("merges class names", () => {
    expect(cn("px-2", "py-1")).toBe("px-2 py-1");
  });

  it("deduplicates tailwind conflicts — last wins", () => {
    expect(cn("px-2", "px-4")).toBe("px-4");
  });

  it("handles conditional classes via clsx", () => {
    // Function param keeps the falsy branch non-constant so the intent is
    // legible to no-constant-binary-expression while still exercising clsx.
    const buildClass = (includeHidden: boolean) => cn("base", includeHidden && "hidden", "end");
    expect(buildClass(false)).toBe("base end");
    expect(buildClass(true)).toBe("base hidden end");
  });

  it("handles undefined and null inputs", () => {
    expect(cn("a", undefined, null, "b")).toBe("a b");
  });

  it("handles empty input", () => {
    expect(cn()).toBe("");
  });

  it("merges complex tailwind conflicts", () => {
    expect(cn("bg-red-500", "bg-blue-500")).toBe("bg-blue-500");
  });

  it("preserves non-conflicting classes from different groups", () => {
    expect(cn("text-red-500", "bg-blue-500")).toBe("text-red-500 bg-blue-500");
  });
});
