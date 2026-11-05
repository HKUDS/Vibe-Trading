import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { JSDOM } from "jsdom";
import { DOCS_STRUCTURE as EN } from "../../wiki/docs/content.en.js";
import { DOCS_STRUCTURE as ZH } from "../../wiki/docs/content.zh.js";
import { buildDocMetadata, serializeStructuredData } from "../../wiki/docs/metadata.js";
import { loadPage, until, wiki } from "./dom.mjs";

const site = "https://vibetrading.wiki";
const pages = { en: EN.flatMap((g) => g.pages), zh: ZH.flatMap((g) => g.pages) };
const segments = { en: "latest", zh: "zh" };

test("every static document has its body, own metadata and reciprocal language links", () => {
  for (const [lang, entries] of Object.entries(pages)) {
    for (const page of entries) {
      const dom = new JSDOM(readFileSync(path.join(wiki, `docs/${segments[lang]}/${page.id}.html`), "utf8"));
      try {
        const document = dom.window.document;
        const canonical = `${site}/docs/${segments[lang]}/${page.id}`;
        assert.equal(document.querySelector("h1").textContent, page.title);
        assert.equal(document.documentElement.lang, lang === "en" ? "en" : "zh-CN");
        assert.equal(document.querySelector('link[rel="canonical"]').href, canonical);
        for (const section of page.sections) {
          const rendered = document.getElementById(section.id);
          assert.ok(rendered, `${canonical} is missing section ${section.id}`);
          const expected = JSDOM.fragment(section.body).textContent.replace(/\s+/g, " ").trim();
          assert.ok(rendered.textContent.replace(/\s+/g, " ").includes(expected));
        }
        const scripts = document.querySelectorAll('script[type="application/ld+json"]');
        assert.equal(scripts.length, 1);
        const data = JSON.parse(scripts[0].textContent);
        assert.equal(data.url, canonical);
        assert.equal(data.mainEntityOfPage["@id"], canonical);
        assert.equal(data.headline, page.title);
        assert.equal(data.inLanguage, document.documentElement.lang);
        for (const [code, segment] of [["en", "latest"], ["zh-CN", "zh"], ["x-default", "latest"]]) {
          assert.equal(document.querySelector(`link[hreflang="${code}"]`).href, `${site}/docs/${segment}/${page.id}`);
        }
      } finally {
        dom.window.close();
      }
    }
  }
});

test("sitemap has all docs, core pages and articles without duplicate or redirecting URLs", () => {
  const dom = new JSDOM(readFileSync(path.join(wiki, "sitemap.xml"), "utf8"), { contentType: "application/xml" });
  try {
    const urls = [...dom.window.document.querySelectorAll("url > loc")].map((e) => e.textContent);
    const articleCount = ["tutorials", "research-lab/posts"].reduce((count, directory) =>
      count + readdirSync(path.join(wiki, directory)).filter((name) => name.endsWith(".html") && name !== "index.html").length, 0);
    assert.equal(urls.length, pages.en.length + pages.zh.length + 4 + articleCount);
    assert.equal(new Set(urls).size, urls.length);
    assert.ok(urls.every((url) => url.startsWith(`${site}/`) && !url.endsWith(".html")));
    for (const [lang, entries] of Object.entries(pages)) {
      for (const page of entries) assert.ok(urls.includes(`${site}/docs/${segments[lang]}/${page.id}`));
    }
    for (const directory of ["home", "tutorials", "alpha-library", "research-lab"]) {
      assert.ok(urls.includes(`${site}/${directory}/`));
    }
  } finally {
    dom.window.close();
  }
});

function assertCurrentMetadata(window, pageId, lang) {
  const document = window.document;
  const page = pages[lang].find((p) => p.id === pageId);
  const canonical = `${site}/docs/${segments[lang]}/${pageId}`;
  const scripts = document.querySelectorAll('script[type="application/ld+json"]');
  assert.equal(scripts.length, 1, "navigation must replace metadata, not append claims");
  const data = JSON.parse(scripts[0].textContent);
  assert.equal(window.location.pathname, `/docs/${segments[lang]}/${pageId}`);
  assert.equal(document.querySelector("h1").textContent, page.title);
  assert.equal(document.querySelector('link[rel="canonical"]').href, canonical);
  assert.equal(document.querySelector('meta[property="og:url"]').content, canonical);
  assert.equal(data.url, canonical);
  assert.equal(data.mainEntityOfPage["@id"], canonical);
  assert.equal(data.headline, page.title);
  assert.equal(data.inLanguage, lang === "en" ? "en" : "zh-CN");
}

test("actual client router synchronizes JSON-LD on navigation, language changes and history", async () => {
  const dom = await loadPage("docs/latest/tools/alpha-zoo.html", "/docs/latest/tools/alpha-zoo");
  try {
    const window = dom.window;
    assertCurrentMetadata(window, "tools/alpha-zoo", "en");
    window.document.querySelector('a[data-doc-link="getting-started/quick-start"]').click();
    assertCurrentMetadata(window, "getting-started/quick-start", "en");
    window.document.getElementById("lang-toggle").click();
    await until(() => window.document.documentElement.lang === "zh-CN");
    assertCurrentMetadata(window, "getting-started/quick-start", "zh");
    window.history.back();
    await until(() => window.location.pathname === "/docs/latest/getting-started/quick-start");
    assertCurrentMetadata(window, "getting-started/quick-start", "en");
    window.history.back();
    await until(() => window.location.pathname === "/docs/latest/tools/alpha-zoo");
    assertCurrentMetadata(window, "tools/alpha-zoo", "en");
    window.history.forward();
    await until(() => window.location.pathname === "/docs/latest/getting-started/quick-start");
    assertCurrentMetadata(window, "getting-started/quick-start", "en");
  } finally {
    dom.window.close();
  }
});

test("the unrendered docs entry also creates one correct structured-data record", async () => {
  const dom = await loadPage("docs/index.html", "/docs/");
  try {
    assertCurrentMetadata(dom.window, "getting-started/vibe-trading-overview", "en");
  } finally {
    dom.window.close();
  }
});

test("404 title, metadata, explanation and recovery links translate and restore to English", async () => {
  const dom = await loadPage("404.html", "/missing-test-page", { entry: "main.js" });
  try {
    const document = dom.window.document;
    const marked = [...document.querySelectorAll("[data-i18n], [data-i18n-attr]")];
    const english = marked.map((element) => element.outerHTML);
    assert.equal(document.querySelector("h1").textContent, "This page does not exist");
    const locale = JSON.parse(readFileSync(path.join(wiki, "locales/zh.json"), "utf8"));
    document.getElementById("lang-toggle").click();
    await until(() => document.documentElement.lang === "zh-CN");
    for (const element of marked) {
      if (element.dataset.i18n) assert.equal(element.textContent, locale[element.dataset.i18n]);
      for (const pair of (element.dataset.i18nAttr || "").split(",").filter(Boolean)) {
        const [attr, key] = pair.split("=");
        assert.equal(element.getAttribute(attr), locale[key]);
      }
    }
    assert.equal(document.title, "页面未找到 | Vibe-Trading Wiki");
    assert.equal(document.querySelector('meta[name="robots"]').content, "noindex, follow");
    assert.deepEqual([...document.querySelectorAll("main a")].map((a) => a.getAttribute("href")),
      ["/home/", "/docs/", "/tutorials/", "/alpha-library/", "/research-lab/", "https://github.com/HKUDS/Vibe-Trading"]);
    document.getElementById("lang-toggle").click();
    await until(() => document.documentElement.lang === "en");
    for (const [index, element] of marked.entries()) {
      // The translator stores the originals in data attributes; compare rendered values.
      const original = JSDOM.fragment(english[index]).firstChild;
      if (element.dataset.i18n) assert.equal(element.textContent, original.textContent);
      for (const pair of (element.dataset.i18nAttr || "").split(",").filter(Boolean)) {
        const [attr] = pair.split("=");
        assert.equal(element.getAttribute(attr), original.getAttribute(attr));
      }
    }
  } finally {
    dom.window.close();
  }
});

test("404 honors an existing Chinese preference on first load", async () => {
  const dom = await loadPage("404.html", "/missing-test-page", { language: "zh", entry: "main.js" });
  try {
    await until(() => dom.window.document.documentElement.lang === "zh-CN");
    assert.equal(dom.window.document.querySelector("h1").textContent, "此页面不存在");
  } finally {
    dom.window.close();
  }
});

test("static JSON-LD serialization preserves text without terminating the script", () => {
  const metadata = buildDocMetadata({ id: "test", title: "</script><h1>wrong</h1>", lead: "test" },
    { segment: "latest", htmlLang: "en", siteTitle: "Docs" });
  const dom = new JSDOM(`<script type="application/ld+json">${serializeStructuredData(metadata.structuredData)}</script>`);
  try {
    assert.equal(dom.window.document.querySelectorAll("h1").length, 0);
    assert.deepEqual(JSON.parse(dom.window.document.querySelector("script").textContent), metadata.structuredData);
  } finally {
    dom.window.close();
  }
});
