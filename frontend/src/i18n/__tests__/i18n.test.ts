import en from "../locales/en.json";
import i18n, { SUPPORTED_LANGUAGES, isRtl } from "../index";

// ── helpers ────────────────────────────────────────────────────

/** Recursively collect every dot-separated key path from a nested object. */
function collectKeys(obj: Record<string, unknown>, prefix = ""): string[] {
  const keys: string[] = [];
  for (const [k, v] of Object.entries(obj)) {
    const full = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      keys.push(...collectKeys(v as Record<string, unknown>, full));
    } else {
      keys.push(full);
    }
  }
  return keys;
}

/** Check whether a dot-separated path exists in a nested object. */
function hasPath(obj: Record<string, unknown>, path: string): boolean {
  const parts = path.split(".");
  let current: unknown = obj;
  for (const part of parts) {
    if (current === null || current === undefined || typeof current !== "object") return false;
    if (!(part in (current as Record<string, unknown>))) return false;
    current = (current as Record<string, unknown>)[part];
  }
  // Terminal must be a leaf (not a branch object), matching collectKeys'
  // definition of a key. Without this, a locale that restructures a leaf
  // into a nested object (or vice-versa) passes silently.
  if (current !== null && typeof current === "object" && !Array.isArray(current)) return false;
  return true;
}

// ── locale parity ──────────────────────────────────────────────

const enKeys = collectKeys(en as unknown as Record<string, unknown>);

// Locale files are discovered from disk, never listed here. A hardcoded list
// is how a locale can ship with perfect key parity and still be covered by no
// parity test at all -- the list is a proxy for the locale set, and the two
// drift the moment someone adds a language without editing this file.
const localeModules = import.meta.glob<Record<string, unknown>>("../locales/*.json", {
  eager: true,
  import: "default",
});

const localeCodes = Object.keys(localeModules)
  .map((path) => path.slice(path.lastIndexOf("/") + 1, -".json".length))
  // The locales directory also holds its own tsconfig.json.
  .filter((code) => code !== "tsconfig");

const locales: Record<string, Record<string, unknown>> = Object.fromEntries(
  localeCodes
    .filter((code) => code !== "en")
    .map((code) => [code, localeModules[`../locales/${code}.json`]]),
);

describe("i18n locale parity", () => {
  it.each(Object.entries(locales))("%s has every key from en.json", (name, locale) => {
    const missing = enKeys.filter((key) => !hasPath(locale, key));
    expect(missing).toEqual([]);
  });

  it.each(Object.entries(locales))("%s has no extra keys beyond en.json", (name, locale) => {
    const localeKeys = collectKeys(locale);
    const extra = localeKeys.filter((key) => !hasPath(en as unknown as Record<string, unknown>, key));
    expect(extra).toEqual([]);
  });

  it("en.json has at least 100 keys (sanity check)", () => {
    expect(enKeys.length).toBeGreaterThanOrEqual(100);
  });

  it("the locale files on disk are exactly the registered languages", () => {
    // Both directions: a locale file nobody registered is unreachable in the
    // switcher, and a registered language with no file is a runtime import
    // failure. Either way the parity tests above would silently skip it.
    expect([...localeCodes].sort()).toEqual(
      SUPPORTED_LANGUAGES.map((language) => language.code).sort(),
    );
  });
});

// ── interpolation variable parity ──────────────────────────────

/** Recursively collect leaf string values keyed by their dot path. */
function collectStrings(
  obj: Record<string, unknown>,
  prefix = "",
): Record<string, string> {
  const result: Record<string, string> = {};
  for (const [k, v] of Object.entries(obj)) {
    const full = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      Object.assign(result, collectStrings(v as Record<string, unknown>, full));
    } else if (typeof v === "string") {
      result[full] = v;
    }
  }
  return result;
}

const VAR_RE = /\{\{(\w+)\}\}/g;
const enStrings = collectStrings(en as unknown as Record<string, unknown>);

describe("i18n interpolation parity", () => {
  it.each(Object.entries(locales))(
    "%s has the same {{variables}} as en.json in every string",
    (name, locale) => {
      const locStrings = collectStrings(locale);
      const mismatches: string[] = [];
      for (const [key, enVal] of Object.entries(enStrings)) {
        const locVal = locStrings[key];
        if (locVal === undefined) continue; // key-parity test covers missing keys
        const enVars = [...enVal.matchAll(VAR_RE)].map((m) => m[1]).sort();
        const locVars = [...locVal.matchAll(VAR_RE)].map((m) => m[1]).sort();
        if (enVars.join(",") !== locVars.join(",")) {
          mismatches.push(`${key}: en=[${enVars}] vs ${name}=[${locVars}]`);
        }
      }
      expect(mismatches).toEqual([]);
    },
  );
});

// ── utility functions ──────────────────────────────────────────

describe("i18n utilities", () => {
  it("isRtl returns true for Arabic", () => {
    expect(isRtl("ar")).toBe(true);
  });

  it("isRtl returns true for Arabic regional variants", () => {
    expect(isRtl("ar-EG")).toBe(true);
    expect(isRtl("ar-SA")).toBe(true);
  });

  it("isRtl returns false for LTR languages", () => {
    expect(isRtl("en")).toBe(false);
    expect(isRtl("zh-CN")).toBe(false);
    expect(isRtl("ja")).toBe(false);
    expect(isRtl("ko")).toBe(false);
  });

  it("isRtl returns false for LTR regional variants", () => {
    expect(isRtl("en-US")).toBe(false);
    expect(isRtl("ja-JP")).toBe(false);
  });

  it("isRtl returns false for unknown codes", () => {
    expect(isRtl("xx")).toBe(false);
    expect(isRtl("")).toBe(false);
  });

  it("SUPPORTED_LANGUAGES lists every locale in switcher order", () => {
    // The set is pinned against the locales directory above; this case pins
    // the order the switcher renders, and that "en" stays first so the
    // primary-match fallback in Layout resolves regional codes to it.
    const codes = SUPPORTED_LANGUAGES.map((l) => l.code);
    expect(codes).toEqual(["en", "zh-CN", "ja", "ko", "ar", "es", "de"]);
  });

  it("accepts zh-CN as an explicit supported language", async () => {
    await i18n.changeLanguage("zh-CN");

    expect(i18n.language).toBe("zh-CN");
    expect(i18n.languages).toContain("zh-CN");

    await i18n.changeLanguage("en");
  });
});
