import { initTheme } from "./theme.js";

const REPO = "HKUDS/Vibe-Trading";
const API = `https://api.github.com/repos/${REPO}`;
const STARS_CACHE_KEY = "vibetrading-github-stars";
const STARS_TTL_MS = 12 * 60 * 60 * 1000;

function formatStarCount(n) {
  if (typeof n !== "number" || !Number.isFinite(n) || n < 0) return "--";
  if (n < 1000) return String(Math.round(n));
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(1)}m`;
}

function readStarsCache() {
  try {
    const raw = localStorage.getItem(STARS_CACHE_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw);
    if (typeof value.count !== "number" || typeof value.at !== "number") return null;
    return value;
  } catch {
    return null;
  }
}

function writeStarsCache(count) {
  try {
    localStorage.setItem(STARS_CACHE_KEY, JSON.stringify({ count, at: Date.now() }));
  } catch {
    /* private mode */
  }
}

function initStars() {
  const el = document.getElementById("star-count");
  if (!el) return;
  const cached = readStarsCache();
  if (cached) el.textContent = formatStarCount(cached.count);
  if (cached && Date.now() - cached.at < STARS_TTL_MS) return;

  fetch(API, { headers: { Accept: "application/vnd.github+json" } })
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
    .then((data) => {
      if (typeof data.stargazers_count !== "number") return;
      writeStarsCache(data.stargazers_count);
      el.textContent = formatStarCount(data.stargazers_count);
    })
    .catch(() => {
      if (!cached) el.textContent = "--";
    });
}

function initInstallTabs() {
  const tabs = Array.from(document.querySelectorAll("[data-tab]"));
  if (!tabs.length) return;

  for (const tab of tabs) {
    tab.addEventListener("click", () => {
      const key = tab.getAttribute("data-tab");
      for (const item of tabs) {
        const selected = item === tab;
        item.setAttribute("aria-selected", String(selected));
        const panelId = item.getAttribute("aria-controls");
        if (panelId) {
          const panel = document.getElementById(panelId);
          if (panel) panel.hidden = !selected;
        }
      }
      if (key) {
        try {
          localStorage.setItem("vibetrading-install-tab", key);
        } catch {
          /* ignore */
        }
      }
    });
  }

  try {
    const saved = localStorage.getItem("vibetrading-install-tab");
    const selected = tabs.find((tab) => tab.getAttribute("data-tab") === saved);
    if (selected) selected.click();
  } catch {
    /* ignore */
  }
}

async function applyLocale() {
  try {
    const response = await fetch("/locales/en.json");
    if (!response.ok) return;
    const messages = await response.json();
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      if (key && messages[key] != null) el.textContent = messages[key];
    });
    document.querySelectorAll("[data-i18n-html]").forEach((el) => {
      const key = el.getAttribute("data-i18n-html");
      if (key && messages[key] != null) el.innerHTML = messages[key];
    });
  } catch {
    /* static fallback text is already in the HTML */
  }
}

function initHeaderScroll() {
  const header = document.getElementById("site-header");
  if (!header) return;
  const sync = () => header.classList.toggle("is-scrolled", window.scrollY > 10);
  sync();
  window.addEventListener("scroll", sync, { passive: true });
}

initTheme();
initStars();
initInstallTabs();
initHeaderScroll();
applyLocale();
