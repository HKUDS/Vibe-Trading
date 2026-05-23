import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react";
import en from "./en";
import zh from "./zh";
import zhHant from "./zh-Hant";
import ja from "./ja";
import ko from "./ko";

const LOCALES = ["en", "zh", "zh-Hant", "ja", "ko"] as const;
type Locale = (typeof LOCALES)[number];

const messagesMap: Record<Locale, Record<string, string>> = {
  en, zh, "zh-Hant": zhHant, ja, ko,
};

const LABELS: Record<Locale, string> = {
  en: "English",
  zh: "简体中文",
  "zh-Hant": "繁體中文",
  ja: "日本語",
  ko: "한국어",
};

function detectLocale(): Locale {
  const stored = localStorage.getItem("vibe-locale");
  if (stored && LOCALES.includes(stored as Locale)) return stored as Locale;
  const lang = navigator.language || "";
  if (lang.startsWith("zh-Hant") || lang.startsWith("zh-HK") || lang.startsWith("zh-TW")) return "zh-Hant";
  if (lang.startsWith("zh")) return "zh";
  if (lang.startsWith("ja")) return "ja";
  if (lang.startsWith("ko")) return "ko";
  return "en";
}

interface I18nCtxValue {
  t: Record<string, string>;
  locale: Locale;
  setLocale: (l: Locale) => void;
  locales: readonly Locale[];
  labels: Record<Locale, string>;
}

const I18nCtx = createContext<I18nCtxValue>({
  t: en,
  locale: "en",
  setLocale: () => {},
  locales: LOCALES,
  labels: LABELS,
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(detectLocale);

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    localStorage.setItem("vibe-locale", l);
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale.startsWith("zh") ? "zh-CN" : locale;
  }, [locale]);

  const val = { t: messagesMap[locale], locale, setLocale, locales: LOCALES, labels: LABELS };

  return <I18nCtx.Provider value={val}>{children}</I18nCtx.Provider>;
}

export function useI18n() {
  return useContext(I18nCtx);
}
