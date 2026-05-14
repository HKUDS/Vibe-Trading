# Vibe-Trading Wiki

Static source for `https://vibetrading.wiki`.

## Local preview

```bash
cd wiki
python3 -m http.server 8088
```

Open `http://localhost:8088/home/` for the landing page and `http://localhost:8088/docs/` for the docs app.

Direct docs URLs such as `/docs/latest/getting-started/vibe-trading-overview` are handled by Cloudflare Pages via `_redirects`. The simple Python preview server does not apply those rewrite rules, so use `/docs/` as the local entry point.

## Cloudflare Pages

- Project root: `wiki`
- Build command: leave empty
- Output directory: `.`
- Custom domain: `vibetrading.wiki`

The site is intentionally static. No server, database, or build step is required.
