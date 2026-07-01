import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import en from "./locales/en.json";
import zhCN from "./locales/zh-CN.json";
import ja from "./locales/ja.json";
import ko from "./locales/ko.json";
import ar from "./locales/ar.json";

// Language registry — keep in sync with the Layout switcher and README_xx.md.
// `dir` flags whether the language is right-to-left so the app can mirror the
// layout (sidebar on the right, etc.) when needed.
export const SUPPORTED_LANGUAGES = [
  { code: "en", label: "English", dir: "ltr" as const },
  { code: "zh-CN", label: "中文", dir: "ltr" as const },
  { code: "ja", label: "日本語", dir: "ltr" as const },
  { code: "ko", label: "한국어", dir: "ltr" as const },
  { code: "ar", label: "العربية", dir: "rtl" as const },
] as const;

export type SupportedLanguageCode = (typeof SUPPORTED_LANGUAGES)[number]["code"];

const RTL_CODES = new Set<SupportedLanguageCode>(
  SUPPORTED_LANGUAGES.filter((l) => l.dir === "rtl").map((l) => l.code),
);

export function isRtl(code: string): boolean {
  if (RTL_CODES.has(code as SupportedLanguageCode)) return true;
  // Handle regional variants: "ar-EG" → match "ar", "he-IL" → match "he" (if added).
  return [...RTL_CODES].some((rtl) => code.startsWith(rtl + "-"));
}

export function applyDocumentDirection(code: string): void {
  if (typeof document === "undefined") return;
  const dir = isRtl(code) ? "rtl" : "ltr";
  document.documentElement.setAttribute("dir", dir);
  document.documentElement.setAttribute("lang", code);
}

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      "zh-CN": { translation: zhCN },
      ja: { translation: ja },
      ko: { translation: ko },
      ar: { translation: ar },
    },
    // Default to English for everyone on first visit; only an explicit toggle
    // (persisted to localStorage) switches language. After a manual choice
    // the navigator value can act as a fallback when the saved language is
    // removed.
    fallbackLng: "en",
    supportedLngs: SUPPORTED_LANGUAGES.map((l) => l.code),
    // NOTE: Intentionally NOT using nonExplicitSupportedLngs — it strips
    // region codes from compound language keys like "zh-CN" which causes
    // isSupportedCode to reject them ("zh-CN" → "zh", not in supportedLngs).
    interpolation: { escapeValue: false },
    detection: {
      // In browsers the navigator.language gives the user's browser locale,
      // useful as a fallback when no explicit choice is saved. In Node.js
      // (SSR, tests) navigator.language reflects the *OS* locale which is
      // meaningless for a browser-only app — skip it there.
      order: typeof window !== "undefined"
        ? ["localStorage", "navigator"]
        : ["localStorage"],
      caches: ["localStorage"],
      lookupLocalStorage: "i18nextLng",
    },
  });

// Keep the <html dir/lang> attributes in sync with the active language so
// RTL languages (Arabic today, Hebrew if added later) render correctly
// without a page reload.
applyDocumentDirection(i18n.language || "en");
i18n.on("languageChanged", (lng) => applyDocumentDirection(lng));
// Re-apply after async detection resolves — the synchronous call above may
// fire before LanguageDetector finishes, causing a brief LTR flash for RTL
// users on first visit.
i18n.on("initialized", () => {
  if (i18n.language) applyDocumentDirection(i18n.language);
});

export default i18n;
