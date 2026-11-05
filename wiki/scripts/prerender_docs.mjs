// wiki/scripts/prerender_docs.mjs — static-render every docs URL so non-JS
// crawlers (GPTBot, ClaudeBot, PerplexityBot) get the real body, title,
// canonical and hreflang without executing /docs/main.js.
//
// Usage: node scripts/prerender_docs.mjs
// Output: docs/latest/<id>.html, docs/zh/<id>.html (34 files for 17 pages x 2 langs)
// The runtime client (docs/main.js) still hydrates and takes over navigation.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { DOCS_STRUCTURE as EN } from "../docs/content.en.js";
import { DOCS_STRUCTURE as ZH } from "../docs/content.zh.js";
import { DOCS_SITE as SITE, buildDocMetadata, serializeStructuredData } from "../docs/metadata.js";

const TEMPLATE = readFileSync(new URL("../docs/index.html", import.meta.url), "utf8");

const LANGS = {
  en: { segment: "latest", htmlLang: "en", siteTitle: "Vibe-Trading Docs", previous: "Previous", next: "Next", navLabel: "Documentation navigation", onThisPage: "On this page" },
  zh: { segment: "zh", htmlLang: "zh-CN", siteTitle: "Vibe-Trading 文档", previous: "上一页", next: "下一页", navLabel: "文档导航", onThisPage: "本页内容" },
};
const STRUCTURE = { en: EN, zh: ZH };

const slugify = (s) =>
  String(s).toLowerCase().replace(/[^a-z0-9\u4e00-\u9fa5]+/g, "-").replace(/^-|-$/g, "");
const esc = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const canonicalPath = (id, lang) => `/docs/${LANGS[lang].segment}/${id}`;

function articleHtml(page, lang, pages) {
  const idx = pages.findIndex((p) => p.id === page.id);
  const prev = idx > 0 ? pages[idx - 1] : null;
  const next = idx < pages.length - 1 ? pages[idx + 1] : null;
  const sections = page.sections
    .map(
      (s) =>
        `<section id="${esc(s.id || slugify(s.title))}" class="doc-section">\n<h2>${s.title}</h2>\n${s.body}\n</section>`,
    )
    .join("\n");
  const footer =
    `<footer class="doc-footer">` +
    (prev ? `<a href="${canonicalPath(prev.id, lang)}"><span>${LANGS[lang].previous}</span><strong>${prev.title}</strong></a>` : "<span></span>") +
    (next ? `<a href="${canonicalPath(next.id, lang)}"><span>${LANGS[lang].next}</span><strong>${next.title}</strong></a>` : "<span></span>") +
    `</footer>`;
  return (
    `<header class="doc-hero">\n<p class="eyebrow">${esc(page.group)}</p>\n<h1>${page.title}</h1>\n<p>${page.lead}</p>\n</header>\n` +
    sections +
    "\n" +
    footer
  );
}

function buildNav(pages, groups, currentId) {
  return groups
    .map((group) => {
      const items = pages
        .filter((p) => p.group === group.label)
        .map(
          (p) =>
            `<a class="${p.id === currentId ? "is-active" : ""}" href="${canonicalPath(p.id, p.lang)}"><span>${p.title}</span><small>${p.description}</small></a>`,
        )
        .join("\n");
      return `<section>\n<h2>${group.label}</h2>\n${items}\n</section>`;
    })
    .join("\n");
}

const files = [];
for (const [lang, structure] of Object.entries(STRUCTURE)) {
  const pages = structure.flatMap((g) => g.pages.map((p) => ({ ...p, group: g.label, lang })));
  for (const page of pages) {
    const { title, description, canonical, structuredData } = buildDocMetadata(page, LANGS[lang]);
    const en = `${SITE}${canonicalPath(page.id, "en")}`;
    const zh = `${SITE}${canonicalPath(page.id, "zh")}`;

    let html = TEMPLATE.replace(/^<html lang="[^"]*"/m, `<html lang="${LANGS[lang].htmlLang}"`);

    // --- head: per-URL title/description/OG/canonical/hreflang ---
    html = html
      .replace(/<title>[\s\S]*?<\/title>/, `<title>${esc(title)}</title>`)
      .replace(/(<meta name="description" content=")[^"]*(")/, `$1${esc(description)}$2`)
      .replace(/(<meta property="og:title" content=")[^"]*(")/, `$1${esc(title)}$2`)
      .replace(/(<meta property="og:description" content=")[^"]*(")/, `$1${esc(description)}$2`)
      .replace(/(<meta property="og:url" content=")[^"]*(")/, `$1${canonical}$2`)
      .replace(/(<link rel="canonical" href=")[^"]*(")/, `$1${canonical}$2`)
      .replace(
        /<link rel="alternate" hreflang="en" href="[^"]*">/,
        `<link rel="alternate" hreflang="en" href="${en}">`,
      )
      .replace(
        /<link rel="alternate" hreflang="zh-CN" href="[^"]*">/,
        `<link rel="alternate" hreflang="zh-CN" href="${zh}">`,
      )
      .replace(
        /<link rel="alternate" hreflang="x-default" href="[^"]*">/,
        `<link rel="alternate" hreflang="x-default" href="${en}">`,
      );

    // --- body: sidebar nav, article, outline ---
    html = html
      .replace(/<nav id="docs-nav"><\/nav>/, `<nav id="docs-nav">\n${buildNav(pages, structure, page.id)}\n</nav>`)
      .replace(
        /<article class="docs-article" id="docs-article" tabindex="-1"><\/article>/,
        `<article class="docs-article" id="docs-article" tabindex="-1">\n${articleHtml(page, lang, pages)}\n</article>`,
      )
      .replace(
        /<nav id="docs-outline"><\/nav>/,
        `<nav id="docs-outline">\n${page.sections
          .map((s) => `<a href="#${esc(s.id || slugify(s.title))}">${s.title}</a>`)
          .join("\n")}\n</nav>`,
      )
      .replace(
        /<\/head>/,
        `<script id="docs-structured-data" type="application/ld+json">${serializeStructuredData(structuredData)}</script>\n</head>`,
      );

    const out = join("docs", LANGS[lang].segment, `${page.id}.html`);
    mkdirSync(dirname(out), { recursive: true });
    writeFileSync(out, html);
    files.push(out);
  }
}

console.error(`prerendered ${files.length} docs pages`);
