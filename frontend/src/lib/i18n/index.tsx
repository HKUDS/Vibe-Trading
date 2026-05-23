import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react";
import en from "./en";
import zh from "./zh";
import zhHant from "./zh-Hant";
import ja from "./ja";
import fr from "./fr";

const LOCALES = ["en", "zh", "zh-Hant", "ja", "fr"] as const;
type Locale = (typeof LOCALES)[number];

const messagesMap: Record<Locale, Record<string, string>> = { en, zh, "zh-Hant": zhHant, ja, fr };

const LABELS: Record<Locale, string> = {
  en: "EN",
  zh: "中文",
  "zh-Hant": "繁體",
  ja: "日本語",
  fr: "FR",
};

function detectLocale(): Locale {
  const stored = localStorage.getItem("vibe-locale");
  if (stored && LOCALES.includes(stored as Locale)) return stored as Locale;
  const lang = navigator.language || "";
  if (lang.startsWith("zh-Hant") || lang.startsWith("zh-HK") || lang.startsWith("zh-TW")) return "zh-Hant";
  if (lang.startsWith("zh")) return "zh";
  if (lang.startsWith("ja")) return "ja";
  if (lang.startsWith("fr")) return "fr";
  return "en";
}

interface I18nCtxValue {
  t: Record<string, string>;
  locale: Locale;
  setLocale: (l: Locale) => void;
  locales: readonly Locale[];
  localeLabel: (l: Locale) => string;
}

const I18nCtx = createContext<I18nCtxValue>({
  t: en,
  locale: "en",
  setLocale: () => {},
  locales: LOCALES,
  localeLabel: (l) => LABELS[l],
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

  const val = { t: messagesMap[locale], locale, setLocale, locales: LOCALES, localeLabel: (l: Locale) => LABELS[l] };

  return <I18nCtx.Provider value={val}>{children}</I18nCtx.Provider>;
}

export function useI18n() {
  return useContext(I18nCtx);
}
