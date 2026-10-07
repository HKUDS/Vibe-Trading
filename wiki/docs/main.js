import { initSite, setPageLang, storedLang } from "/site.js?v=20260929e";
import {
  DOCS_DEFAULT_LANG,
  DOCS_DEFAULT_PAGE,
  DOCS_LANGUAGES,
  DOCS_UI,
  DOCS_VERSIONS
} from "/docs/content.js?v=20260929e";

const SITE = "https://vibetrading.wiki";

function stripTags(html) {
  return String(html).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
}

const pagesByLang = Object.fromEntries(
  Object.entries(DOCS_LANGUAGES).map(([lang, { structure }]) => [
    lang,
    structure.flatMap((group) =>
      group.pages.map((page) => ({
        ...page,
        group: group.label,
        searchText: [
          page.title,
          page.description,
          page.lead,
          ...page.sections.map((section) => `${section.title} ${stripTags(section.body)}`)
        ].join(" ").toLowerCase()
      }))
    )
  ])
);


function slugify(text) {
  return String(text)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function langForSegment(segment) {
  const match = Object.entries(DOCS_LANGUAGES).find(([, meta]) => meta.segment === segment);
  return match ? match[0] : DOCS_DEFAULT_LANG;
}

// The URL decides the language: /docs/zh/… is Chinese, /docs/latest/… (or an
// old version number) English. Only a URL that names no language — /docs/
// itself — falls back to the reader's stored choice, English by default.
function routeParts() {
  const normalized = location.pathname.replace(/\/+$/, "");
  const match = normalized.match(/^\/docs\/([^/]+)\/(.+)$/);
  if (!match) {
    const bare = normalized.match(/^\/docs\/([^/]+)$/);
    const lang = bare && bare[1] !== "index.html" ? langForSegment(bare[1]) : storedLang();
    return { lang, pageId: DOCS_DEFAULT_PAGE, canonical: false };
  }
  const lang = langForSegment(match[1]);
  return { lang, pageId: match[2], canonical: match[1] === DOCS_LANGUAGES[lang].segment };
}

function canonicalPath(pageId, lang) {
  return `/docs/${DOCS_LANGUAGES[lang].segment}/${pageId}`;
}

function resolvePage(pageId, lang) {
  const pages = pagesByLang[lang];
  return pages.find((page) => page.id === pageId) || pages.find((page) => page.id === DOCS_DEFAULT_PAGE);
}


function setAlternate(hreflang, href) {
  let link = document.querySelector(`link[rel='alternate'][hreflang='${hreflang}']`);
  if (!link) {
    link = document.createElement("link");
    link.rel = "alternate";
    link.hreflang = hreflang;
    document.head.appendChild(link);
  }
  link.href = href;
}

function setMeta(page, lang) {
  const ui = DOCS_UI[lang];
  const title = `${page.title} - ${ui.siteTitle}`;
  const description = page.description || page.lead;
  document.title = title;
  document.querySelector('meta[name="description"]')?.setAttribute("content", description);
  document.querySelector('meta[property="og:title"]')?.setAttribute("content", title);
  document.querySelector('meta[property="og:description"]')?.setAttribute("content", description);
  document.querySelector('meta[property="og:site_name"]')?.setAttribute("content", ui.siteTitle);
  const canonical = `${SITE}${canonicalPath(page.id, lang)}`;
  document.querySelector('meta[property="og:url"]')?.setAttribute("content", canonical);
  document.querySelector("link[rel='canonical']")?.setAttribute("href", canonical);
  for (const [code, meta] of Object.entries(DOCS_LANGUAGES)) {
    setAlternate(meta.htmlLang, `${SITE}${canonicalPath(page.id, code)}`);
  }
  setAlternate("x-default", `${SITE}${canonicalPath(page.id, DOCS_DEFAULT_LANG)}`);
}

function applyChrome(lang) {
  const ui = DOCS_UI[lang];
  document.querySelectorAll("[data-ui]").forEach((el) => {
    const value = ui[el.getAttribute("data-ui")];
    if (typeof value === "string") el.textContent = value;
  });
  document.getElementById("docs-search")?.setAttribute("placeholder", ui.searchPlaceholder);
  document.querySelector(".docs-sidebar")?.setAttribute("aria-label", ui.navLabel);
  document.querySelector(".docs-outline")?.setAttribute("aria-label", ui.onThisPage);

  const select = document.getElementById("version-select");
  if (select) {
    select.innerHTML = DOCS_VERSIONS.map((item) =>
      `<option value="${item.name}">${item.label[lang] || item.name}</option>`
    ).join("");
  }
}

function navLink(page, currentId) {
  const active = page.id === currentId ? "is-active" : "";
  return `<a class="${active}" data-doc-link="${page.id}">
    <span>${page.title}</span>
    <small>${page.description}</small>
  </a>`;
}

function renderNav(currentId, lang, filter = "") {
  const nav = document.getElementById("docs-nav");
  if (!nav) return;
  const q = filter.trim().toLowerCase();
  const pages = pagesByLang[lang];
  const groups = DOCS_LANGUAGES[lang].structure.map((group) => {
    const matches = pages.filter((page) => page.group === group.label && (!q || page.searchText.includes(q)));
    if (!matches.length) return "";
    return `<section>
      <h2>${group.label}</h2>
      ${matches.map((page) => navLink(page, currentId)).join("")}
    </section>`;
  }).join("");
  nav.innerHTML = groups || `<p class="empty-state">${DOCS_UI[lang].noMatch}</p>`;
}

function renderOutline(page) {
  const outline = document.getElementById("docs-outline");
  if (!outline) return;
  outline.innerHTML = page.sections.map((section) =>
    `<a href="#${section.id || slugify(section.title)}">${section.title}</a>`
  ).join("");
}

function renderArticle(page, lang) {
  const article = document.getElementById("docs-article");
  if (!article) return;

  const ui = DOCS_UI[lang];
  const pages = pagesByLang[lang];
  const index = pages.findIndex((candidate) => candidate.id === page.id);
  const previous = index > 0 ? pages[index - 1] : null;
  const next = index < pages.length - 1 ? pages[index + 1] : null;

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
      ${previous ? `<a data-doc-link="${previous.id}"><span>${ui.previous}</span><strong>${previous.title}</strong></a>` : "<span></span>"}
      ${next ? `<a data-doc-link="${next.id}"><span>${ui.next}</span><strong>${next.title}</strong></a>` : "<span></span>"}
    </footer>
  `;
}

function navigate(path) {
  history.pushState({}, "", path);
  renderCurrent();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function bindDocLinks(lang, root = document) {
  root.querySelectorAll("[data-doc-link]").forEach((link) => {
    const pageId = link.getAttribute("data-doc-link");
    if (!pageId) return;
    link.setAttribute("href", canonicalPath(pageId, lang));
    link.onclick = (event) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1) return;
      event.preventDefault();
      navigate(canonicalPath(pageId, lang));
    };
  });
}

function renderCurrent() {
  const { lang, pageId, canonical } = routeParts();
  const page = resolvePage(pageId, lang);

  if (!canonical || page.id !== pageId) {
    history.replaceState({}, "", canonicalPath(page.id, lang) + location.hash);
  }

  current = { lang, pageId: page.id };
  setPageLang(lang);
  setMeta(page, lang);
  applyChrome(lang);
  renderNav(page.id, lang, document.getElementById("docs-search")?.value || "");
  renderArticle(page, lang);
  renderOutline(page);
  bindDocLinks(lang);
  document.getElementById("docs-article")?.focus({ preventScroll: true });
}

function initSearch() {
  const search = document.getElementById("docs-search");
  if (!search) return;
  search.addEventListener("input", () => {
    const { lang, pageId } = routeParts();
    renderNav(resolvePage(pageId, lang).id, lang, search.value);
    bindDocLinks(lang, document.getElementById("docs-nav") || document);
  });
}

let current = { lang: DOCS_DEFAULT_LANG, pageId: DOCS_DEFAULT_PAGE };

window.addEventListener("popstate", renderCurrent);

initSite({ onToggle: (lang) => navigate(canonicalPath(current.pageId, lang)) });
initSearch();
renderCurrent();
// The sections are rendered after load, so the browser could not scroll to
// a #section in the URL on its own.
if (location.hash) document.getElementById(decodeURIComponent(location.hash.slice(1)))?.scrollIntoView();
