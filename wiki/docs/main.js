import { initTheme } from "/theme.js";
import {
  DOCS_DEFAULT_PAGE,
  DOCS_DEFAULT_VERSION,
  DOCS_LATEST_ALIAS,
  DOCS_STRUCTURE,
  DOCS_VERSIONS
} from "/docs/content.js";

const REPO = "HKUDS/Vibe-Trading";
const API = `https://api.github.com/repos/${REPO}`;
const STARS_CACHE_KEY = "vibetrading-github-stars";
const STARS_TTL_MS = 12 * 60 * 60 * 1000;

const allPages = DOCS_STRUCTURE.flatMap((group) =>
  group.pages.map((page) => ({ ...page, group: group.label }))
);

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
  if (cached && Date.now() - cached.at < STARS_TTL_MS) return;

  fetch(API, { headers: { Accept: "application/vnd.github+json" } })
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

function slugify(text) {
  return String(text)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function routeParts() {
  const normalized = location.pathname.replace(/\/+$/, "");
  if (!normalized || normalized === "/docs" || normalized === "/docs/index.html") {
    return { version: DOCS_LATEST_ALIAS, pageId: DOCS_DEFAULT_PAGE };
  }
  const match = normalized.match(/^\/docs\/([^/]+)\/(.+)$/);
  if (!match) return { version: DOCS_LATEST_ALIAS, pageId: DOCS_DEFAULT_PAGE };
  return { version: match[1], pageId: match[2] || DOCS_DEFAULT_PAGE };
}

function canonicalPath(pageId, version = DOCS_LATEST_ALIAS) {
  return `/docs/${version}/${pageId}`;
}

function resolvePage(pageId) {
  return allPages.find((page) => page.id === pageId) || allPages.find((page) => page.id === DOCS_DEFAULT_PAGE);
}

function setMeta(page, version) {
  document.title = `${page.title} - Vibe-Trading Docs`;
  const description = page.description || page.lead || "Vibe-Trading documentation.";
  document.querySelector('meta[name="description"]')?.setAttribute("content", description);
  document.querySelector('meta[property="og:title"]')?.setAttribute("content", `${page.title} - Vibe-Trading Docs`);
  document.querySelector('meta[property="og:description"]')?.setAttribute("content", description);
  const canonical = `https://vibetrading.wiki${canonicalPath(page.id, version)}`;
  document.querySelector('meta[property="og:url"]')?.setAttribute("content", canonical);
  document.querySelector("link[rel='canonical']")?.setAttribute("href", canonical);
}

function navLink(page, currentId) {
  const active = page.id === currentId ? "is-active" : "";
  return `<a class="${active}" href="${canonicalPath(page.id)}" data-doc-link="${page.id}">
    <span>${page.title}</span>
    <small>${page.description}</small>
  </a>`;
}

function renderNav(currentId, filter = "") {
  const nav = document.getElementById("docs-nav");
  if (!nav) return;
  const q = filter.trim().toLowerCase();
  const groups = DOCS_STRUCTURE.map((group) => {
    const pages = group.pages.filter((page) => {
      if (!q) return true;
      return `${page.title} ${page.description} ${page.lead}`.toLowerCase().includes(q);
    });
    if (!pages.length) return "";
    return `<section>
      <h2>${group.label}</h2>
      ${pages.map((page) => navLink(page, currentId)).join("")}
    </section>`;
  }).join("");
  nav.innerHTML = groups || `<p class="empty-state">No pages match that search.</p>`;
}

function renderOutline(page) {
  const outline = document.getElementById("docs-outline");
  if (!outline) return;
  outline.innerHTML = page.sections.map((section) =>
    `<a href="#${section.id || slugify(section.title)}">${section.title}</a>`
  ).join("");
}

function renderArticle(page, version) {
  const article = document.getElementById("docs-article");
  if (!article) return;

  const index = allPages.findIndex((candidate) => candidate.id === page.id);
  const previous = index > 0 ? allPages[index - 1] : null;
  const next = index < allPages.length - 1 ? allPages[index + 1] : null;

  article.innerHTML = `
    <header class="doc-hero">
      <p class="eyebrow">${page.group}</p>
      <h1>${page.title}</h1>
      <p>${page.lead}</p>
    </header>
    ${page.sections.map((section) => `
      <section id="${section.id || slugify(section.title)}" class="doc-section">
        <h2>${section.title}</h2>
        ${section.body}
      </section>
    `).join("")}
    <footer class="doc-footer">
      ${previous ? `<a href="${canonicalPath(previous.id, version)}" data-doc-link="${previous.id}"><span>Previous</span><strong>${previous.title}</strong></a>` : "<span></span>"}
      ${next ? `<a href="${canonicalPath(next.id, version)}" data-doc-link="${next.id}"><span>Next</span><strong>${next.title}</strong></a>` : "<span></span>"}
    </footer>
  `;
}

function renderVersionSelect(version) {
  const select = document.getElementById("version-select");
  if (!select) return;
  select.innerHTML = DOCS_VERSIONS.map((item) =>
    `<option value="${item.name}" ${item.name === DOCS_DEFAULT_VERSION ? "selected" : ""}>${item.label}</option>`
  ).join("");
  select.addEventListener("change", () => {
    const { pageId } = routeParts();
    navigate(canonicalPath(pageId, DOCS_LATEST_ALIAS));
  });
}

function navigate(path) {
  history.pushState({}, "", path);
  renderCurrent();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function bindDocLinks(root = document) {
  root.querySelectorAll("[data-doc-link]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const pageId = link.getAttribute("data-doc-link");
      if (!pageId) return;
      navigate(canonicalPath(pageId));
    });
  });
}

function renderCurrent() {
  const { version, pageId } = routeParts();
  const resolvedVersion = version === DOCS_LATEST_ALIAS ? DOCS_LATEST_ALIAS : DOCS_DEFAULT_VERSION;
  const page = resolvePage(pageId);

  if (location.pathname === "/docs" || location.pathname === "/docs/" || location.pathname === "/docs/index.html") {
    history.replaceState({}, "", canonicalPath(page.id, DOCS_LATEST_ALIAS));
  }

  setMeta(page, resolvedVersion);
  renderNav(page.id, document.getElementById("docs-search")?.value || "");
  renderArticle(page, resolvedVersion);
  renderOutline(page);
  bindDocLinks(document);
  document.getElementById("docs-article")?.focus({ preventScroll: true });
}

function initSearch() {
  const search = document.getElementById("docs-search");
  if (!search) return;
  search.addEventListener("input", () => {
    const { pageId } = routeParts();
    renderNav(resolvePage(pageId).id, search.value);
    bindDocLinks(document.getElementById("docs-nav") || document);
  });
}

function initHeaderScroll() {
  const header = document.getElementById("site-header");
  if (!header) return;
  const sync = () => header.classList.toggle("is-scrolled", window.scrollY > 10);
  sync();
  window.addEventListener("scroll", sync, { passive: true });
}

window.addEventListener("popstate", renderCurrent);

initTheme();
initStars();
renderVersionSelect(DOCS_DEFAULT_VERSION);
initSearch();
initHeaderScroll();
renderCurrent();
