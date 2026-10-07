import { DOCS_STRUCTURE as EN_STRUCTURE } from "/docs/content.en.js?v=20260929e";
import { DOCS_STRUCTURE as ZH_STRUCTURE } from "/docs/content.zh.js?v=20260929e";

// One content set per language; every version alias renders the latest.
export const DOCS_DEFAULT_VERSION = "0.1.16";
export const DOCS_LATEST_ALIAS = "latest";
export const DOCS_DEFAULT_PAGE = "getting-started/vibe-trading-overview";
export const DOCS_DEFAULT_LANG = "en";

// `segment` is the first path segment after /docs/: /docs/latest/<page> is
// English, /docs/zh/<page> is Chinese. Any other segment (an old version
// number) resolves to English.
export const DOCS_LANGUAGES = {
  en: { segment: DOCS_LATEST_ALIAS, htmlLang: "en", label: "English", structure: EN_STRUCTURE },
  zh: { segment: "zh", htmlLang: "zh-CN", label: "中文", structure: ZH_STRUCTURE }
};

export const DOCS_VERSIONS = [
  { name: DOCS_DEFAULT_VERSION, label: { en: `${DOCS_DEFAULT_VERSION} (latest)`, zh: `${DOCS_DEFAULT_VERSION}（最新）` } }
];

export const DOCS_UI = {
  en: {
    siteTitle: "Vibe-Trading Docs",
    search: "Search",
    searchPlaceholder: "Search docs",
    version: "Version",
    onThisPage: "On this page",
    previous: "Previous",
    next: "Next",
    noMatch: "No pages match that search.",
    navLabel: "Documentation navigation"
  },
  zh: {
    siteTitle: "Vibe-Trading 文档",
    search: "搜索",
    searchPlaceholder: "搜索文档",
    version: "版本",
    onThisPage: "本页内容",
    previous: "上一页",
    next: "下一页",
    noMatch: "没有匹配的页面。",
    navLabel: "文档导航"
  }
};
