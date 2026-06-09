// In-path traffic classifier for vibetrading.wiki (Cloudflare Pages Function).
//
// Runs on every request, server-side, and counts each HTML page load as
// "agent" (AI crawler / agent tool), "bot" (generic SEO/monitor crawler), or
// "human". Because it runs in the request path — not from page JavaScript — it
// also counts AI crawlers that never execute JS (GPTBot, ClaudeBot, …).
//
// Trust posture: first-party, aggregate-only. No per-visitor identifier, no
// cookie, no IP retention — three integers per day in D1. Bulletproof by
// construction: every path is wrapped so a counting failure can never break
// page serving (always returns next()).

const AI_AGENT = new RegExp(
  [
    "GPTBot", "ChatGPT-User", "OAI-SearchBot",
    "ClaudeBot", "Claude-User", "Claude-SearchBot", "anthropic-ai",
    "PerplexityBot", "Perplexity-User", "Google-Extended", "GoogleOther",
    "Bytespider", "CCBot", "cohere-ai", "Meta-ExternalAgent", "meta-externalagent",
    "Amazonbot", "Applebot-Extended", "YouBot", "Diffbot", "DuckAssistBot",
    "MistralAI", "Timpibot", "ImagesiftBot",
    "python-requests", "aiohttp", "\\bhttpx\\b", "Go-http-client", "node-fetch",
    "axios", "okhttp", "Scrapy", "\\bcurl\\b", "Wget",
    "HeadlessChrome", "Headless", "PhantomJS", "Playwright", "Puppeteer", "Selenium",
  ].join("|"),
  "i",
);

const GENERIC_BOT = new RegExp(
  [
    "Googlebot", "bingbot", "YandexBot", "DuckDuckBot", "Baiduspider",
    "AhrefsBot", "SemrushBot", "DotBot", "MJ12bot", "PetalBot",
    "UptimeRobot", "Pingdom", "StatusCake", "facebookexternalhit",
    "Twitterbot", "Slackbot", "Discordbot", "TelegramBot", "WhatsApp",
    "\\bbot\\b", "\\bcrawler\\b", "\\bspider\\b", "\\bslurp\\b",
  ].join("|"),
  "i",
);

function classify(ua) {
  if (!ua) return "bot"; // a real browser always sends a User-Agent
  if (AI_AGENT.test(ua)) return "agent";
  if (GENERIC_BOT.test(ua)) return "bot";
  return "human";
}

export async function onRequest(context) {
  const { request, env, next } = context;
  try {
    const url = new URL(request.url);
    const accept = request.headers.get("accept") || "";
    const isPageView =
      request.method === "GET" &&
      accept.includes("text/html") &&
      !url.pathname.startsWith("/api/");

    if (isPageView && env.DB) {
      const klass = classify(request.headers.get("user-agent") || "");
      const day = new Date().toISOString().slice(0, 10); // UTC YYYY-MM-DD
      context.waitUntil(
        env.DB.prepare(
          "INSERT INTO visits (day, klass, n) VALUES (?1, ?2, 1) " +
            "ON CONFLICT(day, klass) DO UPDATE SET n = n + 1",
        )
          .bind(day, klass)
          .run()
          .catch(() => {}),
      );
    }
  } catch {
    // Analytics must never break the page. Fall through to serving the asset.
  }
  return next();
}
