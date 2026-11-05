import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const wiki = fileURLToPath(new URL("../../wiki/", import.meta.url));
const require = createRequire(import.meta.url);
let server;
let state;
let base;

before(async () => {
  const reservation = net.createServer();
  reservation.listen(0, "127.0.0.1");
  await once(reservation, "listening");
  const port = reservation.address().port;
  await new Promise((resolve) => reservation.close(resolve));
  base = `http://127.0.0.1:${port}`;
  state = mkdtempSync(path.join(os.tmpdir(), "vibe-wiki-pages-test-"));
  server = spawn(process.execPath, [require.resolve("wrangler/bin/wrangler.js"),
    "pages", "dev", ".", "--ip", "127.0.0.1", "--port", String(port), "--persist-to", state], {
    cwd: wiki,
    env: { ...process.env, WRANGLER_SEND_METRICS: "false" },
    stdio: ["ignore", "pipe", "pipe"],
    detached: process.platform !== "win32",
  });
  await new Promise((resolve, reject) => {
    let output = "";
    const timer = setTimeout(() => reject(new Error(`Pages startup timed out:\n${output}`)), 40000);
    function log(data) {
      output = (output + data).slice(-20000);
      if (output.includes(`Ready on ${base}`)) {
        clearTimeout(timer);
        resolve();
      }
    }
    server.stdout.on("data", log);
    server.stderr.on("data", log);
    server.once("error", (error) => { clearTimeout(timer); reject(error); });
    server.once("exit", (code) => { clearTimeout(timer); reject(new Error(`Pages exited ${code}:\n${output}`)); });
  });
}, { timeout: 45000 });

after(async () => {
  if (server && server.exitCode === null && server.signalCode === null) {
    const stopped = once(server, "exit");
    if (process.platform === "win32") server.kill();
    else process.kill(-server.pid, "SIGTERM");
    let timer;
    await Promise.race([stopped, new Promise((resolve) => { timer = setTimeout(resolve, 5000); })]);
    clearTimeout(timer);
    if (server.exitCode === null && server.signalCode === null) {
      if (process.platform === "win32") server.kill("SIGKILL");
      else process.kill(-server.pid, "SIGKILL");
      await stopped;
    }
  }
  if (state) rmSync(state, { recursive: true, force: true });
});

function request(route) {
  return fetch(base + route, { redirect: "manual", headers: { "User-Agent": "GPTBot/1.2", Accept: "text/html" }, signal: AbortSignal.timeout(10000) });
}

test("Pages serves actual crawler files with their declared MIME types", async () => {
  const robots = await request("/robots.txt");
  assert.equal(robots.status, 200);
  assert.match(robots.headers.get("content-type"), /^text\/plain/);
  assert.match(await robots.text(), /Sitemap: https:\/\/vibetrading.wiki\/sitemap.xml/);
  const sitemap = await request("/sitemap.xml");
  assert.equal(sitemap.status, 200);
  assert.match(sitemap.headers.get("content-type"), /^application\/xml/);
});

test("every sitemap URL is directly reachable without JavaScript or redirects", async () => {
  const dom = new JSDOM(readFileSync(path.join(wiki, "sitemap.xml"), "utf8"), { contentType: "application/xml" });
  const routes = [...dom.window.document.querySelectorAll("url > loc")].map((element) => new URL(element.textContent).pathname);
  dom.window.close();
  for (const route of routes) {
    const response = await request(route);
    assert.equal(response.status, 200, route);
    if (route.startsWith("/docs/")) {
      const html = await response.text();
      assert.match(html, /<h1>[^<]+<\/h1>/, route);
      assert.ok(html.includes(`href="https://vibetrading.wiki${route}"`), route);
    } else await response.body.cancel();
  }
});

test("English and Chinese version roots redirect to the correct overview", async () => {
  for (const segment of ["latest", "zh"]) {
    for (const suffix of ["", "/"]) {
      const response = await request(`/docs/${segment}${suffix}`);
      assert.equal(response.status, 302);
      assert.equal(response.headers.get("location"), `/docs/${segment}/getting-started/vibe-trading-overview`);
    }
  }
});

test("old version deep links preserve their document through a permanent redirect", async () => {
  const response = await request("/docs/0.1.7/tools/alpha-zoo");
  assert.equal(response.status, 301);
  assert.equal(response.headers.get("location"), "/docs/latest/tools/alpha-zoo");
});

test("missing routes return a genuine non-indexable 404 while the docs shell still loads", async () => {
  for (const route of ["/missing-crawl-check", "/docs/latest/missing-crawl-check"]) {
    const response = await request(route);
    assert.equal(response.status, 404);
    const html = await response.text();
    assert.match(html, /name="robots" content="noindex, follow"/);
    assert.match(html, /data-i18n="notFound.heading"/);
  }
  assert.equal((await request("/docs/")).status, 200);
});
