import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react";
import en from "./en";
import zh from "./zh";

type Locale = "en" | "zh";

const messagesMap: Record<Locale, Record<string, string>> = { en, zh };

function detectLocale(): Locale {
  const stored = localStorage.getItem("vibe-locale");
  if (stored === "en" || stored === "zh") return stored;
  if (navigator.language.startsWith("zh")) return "zh";
  return "en";
}

interface I18nCtxValue {
  t: Record<string, string>;
  locale: Locale;
  setLocale: (l: Locale) => void;
}

const I18nCtx = createContext<I18nCtxValue>({
  t: en,
  locale: "en",
  setLocale: () => {},
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(detectLocale);

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    localStorage.setItem("vibe-locale", l);
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
  }, [locale]);

  return (
    <I18nCtx.Provider value={{ t: messagesMap[locale], locale, setLocale }}>
      {children}
    </I18nCtx.Provider>
  );
}

export function useI18n() {
  return useContext(I18nCtx);
}
