import { create } from "zustand";
import { persist } from "zustand/middleware";
import { setChartLocale } from "@/lib/chart-theme";

export type Locale = "en" | "zh" | "zh-tw";

interface LocaleState {
  locale: Locale;
  setLocale: (locale: string) => void;
}

export const useLocaleStore = create<LocaleState>()(
  persist(
    (set) => ({
      locale: (navigator.language || "").startsWith("zh") ? "zh" : "en",
      setLocale: (locale) => {
        const htmlLang = locale === "zh" ? "zh-CN" : locale === "zh-tw" ? "zh-TW" : "en";
        setChartLocale(htmlLang);
        set({ locale: locale as Locale });
      },
    }),
    {
      name: "vibe-trading-locale",
      onRehydrateStorage: () => (state) => {
        if (state) {
          const htmlLang = state.locale === "zh" ? "zh-CN" : state.locale === "zh-tw" ? "zh-TW" : "en";
          setChartLocale(htmlLang);
        }
      },
    },
  ),
);
