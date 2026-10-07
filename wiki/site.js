// Shared shell for every wiki page: theme, GitHub stars, header shadow, the
// English / 中文 switch, and the footer traffic line on the home page.
//
// Language model: English is the HTML itself. Chinese comes from
// /locales/zh.json through data-i18n (text), data-i18n-html (markup),
// data-i18n-attr ("attr=key,attr=key") and data-href-zh (a link that has a
// Chinese counterpart); generated pages carry their own Chinese inline in
// data-text-zh (the Alpha Library's per-alpha notes). One stored choice,
// default English, never guessed from the browser.
//
// A page whose URL is language-neutral (<html data-lang-neutral>) renders the
// stored language. A page whose URL is language-specific (<html
// data-page-lang="en|zh">, or the docs, which pass pageLang) shows its own
// language and records it, so following a Chinese link keeps the rest of the
// site Chinese; its toggle goes to the counterpart page instead.

const LANG_KEY = "vibetrading-lang";
const LOCALE_VERSION = "20260929e";
const THEME_KEY = "vibetrading-theme";
const STARS_CACHE_KEY = "vibetrading-github-stars";
const STARS_TTL_MS = 12 * 60 * 60 * 1000;
const REPO_API = "https://api.github.com/repos/HKUDS/Vibe-Trading";
const HTML_LANG = { en: "en", zh: "zh-CN" };
const TOGGLE = {
  en: { label: "中文", lang: "zh-CN", aria: "切换到中文" },
  zh: { label: "English", lang: "en", aria: "Switch to English" }
};

let zhMessages = null;
let pageLang = null;
let toggleHandler = null;

export function storedLang() {
  try {
    return localStorage.getItem(LANG_KEY) === "zh" ? "zh" : "en";
  } catch {
    return "en";
  }
}

export function storeLang(lang) {
  try {
    localStorage.setItem(LANG_KEY, lang);
  } catch {
    /* private mode: the choice lasts for this page only */
  }
}

async function loadZh() {
  if (zhMessages) return zhMessages;
  const response = await fetch(`/locales/zh.json?v=${LOCALE_VERSION}`);
  if (!response.ok) throw new Error(`zh.json ${response.status}`);
  zhMessages = await response.json();
  return zhMessages;
}

function remember(el, key, value) {
  if (!(key in el.dataset)) el.dataset[key] = value;
  return el.dataset[key];
}

function translateElement(el, messages) {
  const text = el.getAttribute("data-i18n");
  if (text) {
    const original = remember(el, "i18nEn", el.textContent);
    el.textContent = messages?.[text] ?? original;
  }
  const html = el.getAttribute("data-i18n-html");
  if (html) {
    const original = remember(el, "i18nEnHtml", el.innerHTML);
    el.innerHTML = messages?.[html] ?? original;
  }
  const attrs = el.getAttribute("data-i18n-attr");
  if (attrs) {
    for (const pair of attrs.split(",")) {
      const [attr, key] = pair.split("=").map((part) => part.trim());
      if (!attr || !key) continue;
      const slot = `i18nEnAttr${attr.replace(/[^a-z]/gi, "")}`;
      const original = remember(el, slot, el.getAttribute(attr) ?? "");
      el.setAttribute(attr, messages?.[key] ?? original);
    }
  }
  const textZh = el.getAttribute("data-text-zh");
  if (textZh) {
    const original = remember(el, "i18nEnText", el.textContent);
    el.textContent = messages ? textZh : original;
  }
  const hrefZh = el.getAttribute("data-href-zh");
  if (hrefZh) {
    const original = remember(el, "i18nEnHref", el.getAttribute("href") ?? "");
    el.setAttribute("href", messages ? hrefZh : original);
  }
}

// Apply a language to every translatable element under `root`. English
// restores the text the HTML shipped with; a missing Chinese key falls back
// to English rather than blanking the element.
export async function translate(lang, root = document) {
  let messages = null;
  if (lang === "zh") {
    try {
      messages = await loadZh();
    } catch {
      messages = null;
    }
  }
  root.querySelectorAll("[data-i18n], [data-i18n-html], [data-i18n-attr], [data-href-zh], [data-text-zh]").forEach((el) => {
    translateElement(el, messages);
  });
  if (root === document) {
    document.documentElement.lang = HTML_LANG[messages ? "zh" : "en"];
    const title = document.querySelector("title[data-i18n]");
    if (title) document.title = title.textContent;
  }
  syncToggle(messages ? "zh" : "en");
  document.documentElement.removeAttribute("data-lang-pending");
}

function syncToggle(lang) {
  const button = document.getElementById("lang-toggle");
  if (!button) return;
  const target = TOGGLE[lang];
  button.textContent = target.label;
  button.setAttribute("lang", target.lang);
  button.setAttribute("aria-label", target.aria);
}

function counterpartHref(lang) {
  const link = document.querySelector(`link[rel="alternate"][hreflang="${HTML_LANG[lang]}"]`);
  return link ? link.getAttribute("href") : null;
}

function initLanguageToggle() {
  const button = document.getElementById("lang-toggle");
  if (!button) return;
  button.addEventListener("click", () => {
    const current = pageLang || storedLang();
    const next = current === "zh" ? "en" : "zh";
    storeLang(next);
    if (toggleHandler) {
      toggleHandler(next);
      return;
    }
    if (pageLang) {
      const href = counterpartHref(next);
      if (href) {
        location.href = href;
        return;
      }
    }
    translate(next);
  });
}

// Tell the shell which language the current URL is in (docs call this on
// every in-page navigation). Records it as the reader's choice.
export function setPageLang(lang) {
  pageLang = lang;
  storeLang(lang);
  return translate(lang);
}

function initTheme() {
  const button = document.getElementById("theme-toggle");
  if (!button) return;
  button.addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      /* ignore */
    }
  });
}

function formatStarCount(n) {
  if (typeof n !== "number" || !Number.isFinite(n) || n < 0) return "--";
  if (n < 1000) return String(Math.round(n));
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(1)}m`;
}

function initStars() {
  const el = document.getElementById("star-count");
  if (!el) return;
  let cached = null;
  try {
    cached = JSON.parse(localStorage.getItem(STARS_CACHE_KEY) || "null");
  } catch {
    cached = null;
  }
  if (cached && typeof cached.count === "number") el.textContent = formatStarCount(cached.count);
  if (cached && typeof cached.at === "number" && Date.now() - cached.at < STARS_TTL_MS) return;

  fetch(REPO_API, { headers: { Accept: "application/vnd.github+json" } })
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
    .then((data) => {
      if (typeof data.stargazers_count !== "number") return;
      try {
        localStorage.setItem(STARS_CACHE_KEY, JSON.stringify({ count: data.stargazers_count, at: Date.now() }));
      } catch {
        /* ignore */
      }
      el.textContent = formatStarCount(data.stargazers_count);
    })
    .catch(() => {
      if (!cached) el.textContent = "--";
    });
}

function initHeaderScroll() {
  const header = document.getElementById("site-header");
  if (!header) return;
  const sync = () => header.classList.toggle("is-scrolled", window.scrollY > 10);
  sync();
  window.addEventListener("scroll", sync, { passive: true });
}

function formatTrafficCount(n) {
  n = Number(n) || 0;
  if (n < 1000) return String(n);
  return `${(n / 1000).toFixed(n < 10000 ? 1 : 0)}`.replace(/\.0$/, "") + "K";
}

// Footer traffic line (AI agents vs humans counted by the Pages middleware,
// plus PyPI installs). Home page only: /api/stats queries pypistats live, so
// asking for it on every page would multiply upstream calls for no reader.
function initTraffic() {
  const block = document.getElementById("footer-traffic");
  if (!block || document.body.dataset.section !== "home") return;
  fetch("/api/stats")
    .then((r) => (r.ok ? r.json() : null))
    .then((stats) => {
      if (!stats) return;
      const set = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
      };
      if (stats.web) {
        set("vt-agents", formatTrafficCount(stats.web.agent));
        set("vt-humans", formatTrafficCount(stats.web.human));
      }
      if (stats.pypi) set("vt-installs", formatTrafficCount(stats.pypi.last_month));
      block.hidden = false;
    })
    .catch(() => {
      /* stats unavailable — the line stays hidden */
    });
}

// Start the shell. `onToggle(lang)` replaces the default switch behaviour
// (the docs route to the other language's URL themselves).
export function initSite({ onToggle } = {}) {
  toggleHandler = onToggle || null;
  initTheme();
  initStars();
  initHeaderScroll();
  initTraffic();
  initLanguageToggle();
  const declared = document.documentElement.dataset.pageLang;
  if (declared === "en" || declared === "zh") return setPageLang(declared);
  if (document.documentElement.hasAttribute("data-lang-neutral")) return translate(storedLang());
  return Promise.resolve();
}
