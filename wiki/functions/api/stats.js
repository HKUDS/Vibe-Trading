// GET /api/stats — aggregate numbers for the wiki footer.
//
//   web  : all-time agent-vs-human page views to vibetrading.wiki, counted
//          server-side by _middleware.js into D1 (cumulative since launch).
//   pypi : install counts for `vibe-trading-ai` (pypistats public API), with a
//          last-good D1 cache so an occasional flaky/rate-limited upstream call
//          never blanks the footer.
//
// GitHub stars are intentionally NOT fetched here — the page already loads them
// client-side (main.js `initStars`), so adding them would only duplicate work
// and introduce a rate-limited call. Never throws to the client.

async function getPypi(env) {
  // 1) live pypistats; on success refresh the D1 last-good cache.
  try {
    const resp = await fetch(
      "https://pypistats.org/api/packages/vibe-trading-ai/recent",
      { headers: { "User-Agent": "vibetrading-wiki" } },
    );
    if (resp.ok) {
      const data = await resp.json();
      const value = {
        last_day: data?.data?.last_day ?? 0,
        last_week: data?.data?.last_week ?? 0,
        last_month: data?.data?.last_month ?? 0,
      };
      if (env.DB) {
        await env.DB.prepare(
          "INSERT INTO cache (key, value, updated) VALUES ('pypi', ?1, ?2) " +
            "ON CONFLICT(key) DO UPDATE SET value = ?1, updated = ?2",
        )
          .bind(JSON.stringify(value), new Date().toISOString())
          .run()
          .catch(() => {});
      }
      return value;
    }
  } catch {
    // fall through to cache
  }
  // 2) upstream failed — serve the last-good value if we have one.
  try {
    if (env.DB) {
      const row = await env.DB.prepare(
        "SELECT value FROM cache WHERE key = 'pypi'",
      ).first();
      if (row && row.value) return JSON.parse(row.value);
    }
  } catch {
    // no cache yet
  }
  return null;
}

export async function onRequest(context) {
  const { env } = context;
  const headers = {
    "Access-Control-Allow-Origin": "*",
    "Cache-Control": "public, max-age=60",
  };

  const web = { human: 0, agent: 0, bot: 0 };
  try {
    if (env.DB) {
      const { results } = await env.DB.prepare(
        "SELECT klass, SUM(n) AS total FROM visits GROUP BY klass",
      ).all();
      for (const row of results || []) {
        if (row.klass in web) web[row.klass] = Number(row.total) || 0;
      }
    }
  } catch {
    // leave zeros
  }

  const pypi = await getPypi(env);

  return Response.json(
    {
      web,
      pypi,
      note: "anonymous · first-party · aggregate sample",
      generated_at: new Date().toISOString(),
    },
    { headers },
  );
}
