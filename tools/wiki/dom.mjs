import { readFileSync } from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

export const wiki = fileURLToPath(new URL("../../wiki/", import.meta.url));

// Execute the shipped modules, with only external network requests replaced.
export async function loadPage(filename, url, { language = "en", entry = "docs/main.js" } = {}) {
  const dom = new JSDOM(readFileSync(path.join(wiki, filename), "utf8"), {
    url: `http://127.0.0.1${url}`, runScripts: "outside-only", pretendToBeVisual: true,
  });
  dom.window.scrollTo = () => {};
  dom.window.localStorage.setItem("vibetrading-lang", language);
  dom.window.fetch = async (target) => ({
    ok: true,
    json: async () => String(target).startsWith("/locales/")
      ? JSON.parse(readFileSync(path.join(wiki, "locales/zh.json"), "utf8")) : {},
  });
  const context = dom.getInternalVMContext();
  const cache = new Map();
  async function load(file) {
    if (cache.has(file)) return cache.get(file);
    const module = new vm.SourceTextModule(readFileSync(file, "utf8"), { context, identifier: file });
    cache.set(file, module);
    await module.link((specifier, parent) => {
      const clean = specifier.split("?")[0];
      return load(clean.startsWith("/") ? path.join(wiki, clean) : path.resolve(path.dirname(parent.identifier), clean));
    });
    return module;
  }
  try {
    const module = await load(path.join(wiki, entry));
    await module.evaluate();
    return dom;
  } catch (error) {
    dom.window.close();
    throw error;
  }
}

export async function until(predicate) {
  const deadline = Date.now() + 2000;
  while (!predicate()) {
    if (Date.now() >= deadline) throw new Error("page did not reach the expected state");
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}
