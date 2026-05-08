import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useLocaleStore } from "@/stores/locale";
import { loadMessages } from "./locales";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyMessages = Record<string, any>;

interface I18nContextValue {
  t: AnyMessages;
  locale: string;
  setLocale: (l: string) => Promise<void>;
  isLoading: boolean;
}

const I18nCtx = createContext<I18nContextValue>({
  t: {} as AnyMessages,
  locale: "en",
  setLocale: async () => {},
  isLoading: true,
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const { locale, setLocale: setStoreLocale } = useLocaleStore();
  const [messages, setMessages] = useState<AnyMessages | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    loadMessages(locale).then((msgs) => {
      if (!cancelled) {
        setMessages(msgs);
        setIsLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, [locale]);

  const handleSetLocale = async (newLocale: string) => {
    if (newLocale === locale) return;
    if (isLoading) return;
    setIsLoading(true);
    const msgs = await loadMessages(newLocale);
    setMessages(msgs);
    setStoreLocale(newLocale);
    setIsLoading(false);
  };

  if (!messages) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  return (
    <I18nCtx.Provider value={{ t: messages, locale, setLocale: handleSetLocale, isLoading }}>
      {children}
    </I18nCtx.Provider>
  );
}


export function useI18n() { return useContext(I18nCtx); }
