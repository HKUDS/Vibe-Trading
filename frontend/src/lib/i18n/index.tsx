import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react";
import en from "./en";
import zh from "./zh";
import zhHant from "./zh-Hant";
import ja from "./ja";
import fr from "./fr";
import ko from "./ko";
import es from "./es";
import ar from "./ar";
import pt from "./pt";
import de from "./de";
import ru from "./ru";

const LOCALES = ["en", "zh", "zh-Hant", "ja", "fr", "ko", "es", "ar", "pt", "de", "ru"] as const;
type Locale = (typeof LOCALES)[number];

const messagesMap: Record<Locale, Record<string, string>> = {
  en, zh, "zh-Hant": zhHant, ja, fr, ko, es, ar, pt, de, ru,
};

const LABELS: Record<Locale, string> = {
  en: "English",
  zh: "简体中文",
  "zh-Hant": "繁體中文",
  ja: "日本語",
  fr: "Français",
  ko: "한국어",
  es: "Español",
  ar: "العربية",
  pt: "Português",
  de: "Deutsch",
  ru: "Русский",
};

function detectLocale(): Locale {
  const stored = localStorage.getItem("vibe-locale");
  if (stored && LOCALES.includes(stored as Locale)) return stored as Locale;
  const lang = navigator.language || "";
  if (lang.startsWith("zh-Hant") || lang.startsWith("zh-HK") || lang.startsWith("zh-TW")) return "zh-Hant";
  if (lang.startsWith("zh")) return "zh";
  if (lang.startsWith("ja")) return "ja";
  if (lang.startsWith("fr")) return "fr";
  if (lang.startsWith("ko")) return "ko";
  if (lang.startsWith("es")) return "es";
  if (lang.startsWith("ar")) return "ar";
  if (lang.startsWith("pt")) return "pt";
  if (lang.startsWith("de")) return "de";
  if (lang.startsWith("ru")) return "ru";
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
