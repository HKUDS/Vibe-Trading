// wiki/scripts/gen_sitemap.mjs — generate wiki/sitemap.xml from the pages the
// site actually publishes. Source of truth is the filesystem plus
// docs/content.{en,zh}.js, so the sitemap cannot drift from what a crawler can
// fetch.
//
// Usage: node scripts/gen_sitemap.mjs [--lastmod YYYY-MM-DD] [--out sitemap.xml]
// Run from wiki/ (`cd wiki && node scripts/gen_sitemap.mjs`).
import { writeFileSync, readdirSync, existsSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { DOCS_STRUCTURE as EN } from "../docs/content.en.js";
import { DOCS_STRUCTURE as ZH } from "../docs/content.zh.js";

const SITE = "https://vibetrading.wiki";
const args = process.argv.slice(2);
const getArg = (name, fallback) => {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};

function gitDate(path, fallback) {
  try {
    return (
      execFileSync("git", ["log", "-1", "--format=%cs", "--", path], {
        encoding: "utf8",
      }).trim() || fallback
    );
  } catch {
    return fallback;
  }
}

const today = new Date().toISOString().slice(0, 10);
const defaultLastmod = getArg("--lastmod", "");
const lastmodFor = (path) => defaultLastmod || gitDate(path, today);
const out = getArg("--out", "sitemap.xml");

const enIds = EN.flatMap((g) => g.pages.map((p) => p.id));
const zhIds = ZH.flatMap((g) => g.pages.map((p) => p.id));
if (enIds.join("|") !== zhIds.join("|")) {
  console.error("content.en.js / content.zh.js page ids diverge; refusing to write sitemap");
  process.exit(1);
}

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const urls = [];
const push = (loc, lastmod, extra = "", priority = "") =>
  urls.push(
    `  <url>\n    <loc>${esc(loc)}</loc>\n    <lastmod>${lastmod}</lastmod>\n` +
      (priority ? `    <priority>${priority}</priority>\n` : "") +
      extra +
      `  </url>`,
  );

// Core pages: one URL each; language is a client-side toggle, no separate URL.
for (const [path, priority] of [
  ["/home/", "1.0"],
  ["/tutorials/", "0.7"],
  ["/alpha-library/", "0.7"],
  ["/research-lab/", "0.6"],
]) {
  push(`${SITE}${path}`, lastmodFor(`${path.slice(1)}index.html`), "", priority);
}

// Editorial articles: every hand-written page under tutorials/ and
// research-lab/posts/ exists once per language, paired by the -zh suffix.
// Their canonical form keeps the .html extension (see each page's <link>).
const articles = [];
for (const dir of ["tutorials", "research-lab/posts"]) {
  if (!existsSync(dir)) continue;
  for (const name of readdirSync(dir).sort()) {
    if (!name.endsWith(".html") || name === "index.html") continue;
    articles.push({ dir, name, zh: name.endsWith("-zh.html") });
  }
}
const articlePairs = new Map();
for (const a of articles) {
  const base = a.zh ? a.name.replace(/-zh\.html$/, ".html") : a.name;
  const key = `${a.dir}/${base}`;
  const entry = articlePairs.get(key) || { dir: a.dir, base };
  if (a.zh) entry.zh = a.name;
  else entry.en = a.name;
  articlePairs.set(key, entry);
}
for (const { dir, base, en } of articlePairs.values()) {
  // Cloudflare Pages 308-redirects ``.html`` to the extensionless URL, so the
  // sitemap lists the final form; listing the redirecting form would submit a
  // URL that answers 308.
  const enPath = `${dir}/${base}`;
  const enClean = `${SITE}/${enPath.replace(/\.html$/, "")}`;
  const zhName = base.replace(/\.html$/, "-zh.html");
  const zhExists = existsSync(`${dir}/${zhName}`);
  const zhClean = `${SITE}/${dir}/${zhName.replace(/\.html$/, "")}`;
  const extra = zhExists
    ? `    <xhtml:link rel="alternate" hreflang="en" href="${enClean}"/>\n` +
      `    <xhtml:link rel="alternate" hreflang="zh-CN" href="${zhClean}"/>\n` +
      `    <xhtml:link rel="alternate" hreflang="x-default" href="${enClean}"/>\n`
    : "";
  push(enClean, lastmodFor(enPath), extra);
  if (zhExists) push(zhClean, lastmodFor(`${dir}/${zhName}`), extra);
}

// Docs pages: every page exists in both languages; emit reciprocal hreflang.
const docsLastmod = lastmodFor("docs/content.en.js");
for (const id of enIds) {
  const en = `${SITE}/docs/latest/${id}`;
  const zh = `${SITE}/docs/zh/${id}`;
  for (const loc of [en, zh]) {
    push(
      loc,
      docsLastmod,
      `    <xhtml:link rel="alternate" hreflang="en" href="${en}"/>\n` +
        `    <xhtml:link rel="alternate" hreflang="zh-CN" href="${zh}"/>\n` +
        `    <xhtml:link rel="alternate" hreflang="x-default" href="${en}"/>\n`,
    );
  }
}

const xml =
  `<?xml version="1.0" encoding="UTF-8"?>\n` +
  `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n` +
  urls.join("\n") +
  `\n</urlset>\n`;

writeFileSync(out, xml);
console.error(`wrote ${out}: ${urls.length} URLs`);
