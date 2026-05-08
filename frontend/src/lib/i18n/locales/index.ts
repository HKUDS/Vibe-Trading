import type { Messages } from "./en";

export type { Messages };

const loaders: Record<string, () => Promise<Messages>> = {
  en: () => import("./en").then((m) => m.messages),
  zh: () => import("./zh").then((m) => m.messages),
  "zh-tw": () => import("./zh-tw").then((m) => m.messages),
};


export async function loadMessages(locale: string): Promise<Messages> {
  const loader = loaders[locale];
  if (!loader) {
    console.warn(`[i18n] Locale "${locale}" not found, falling back to "en"`);
    return loaders.en();
  }
  return loader();
}
