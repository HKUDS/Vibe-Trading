# Vibe-Trading Wiki

Static source for `https://vibetrading.wiki`.

## Local preview

```bash
cd wiki
python3 -m http.server 8088
```

Open `http://localhost:8088/home/` for the landing page and these wiki sections:

- `http://localhost:8088/docs/`
- `http://localhost:8088/tutorials/`
- `http://localhost:8088/alpha-library/`
- `http://localhost:8088/research-lab/`

Direct docs URLs such as `/docs/latest/getting-started/vibe-trading-overview` or `/docs/zh/…` are handled by Cloudflare Pages via `_redirects`. The simple Python preview server does not apply those rewrite rules, so use `/docs/` as the local entry point. Build the Alpha Library first (see below) or its zoo links fall through.

## One header, two languages

Every page shares one head block, header and footer, kept in `partials/` and
copied between `<!-- site-head|site-header|site-footer:start/end -->` markers:

```bash
python3 wiki/scripts/sync_site_chrome.py          # after editing a partial
python3 wiki/scripts/sync_site_chrome.py --check  # CI
```

The check also requires `<body data-section>` (it highlights the current
section in the header, CSS only), the language attributes below, and one
cache-busting `?v=` token everywhere — `_headers` lets browsers keep JS and
CSS for an hour, so a module bumped alone can meet a cached copy of what it
imports and leave the page blank. Bump the token with one replace across
`wiki/`.

**Language.** English by default, never guessed from the browser; the header
button switches the whole site and the choice is stored (`vibetrading-lang`).
`site.js` does the switching:

- A page whose URL names no language (`<html data-lang-neutral>`: home,
  tutorials and research-lab indexes, the Alpha Library and its generated
  pages, bare `/docs/`) is English HTML with `data-i18n` / `data-i18n-html` /
  `data-i18n-attr` / `data-href-zh` hooks; Chinese comes from
  `locales/zh.json`. `theme-init.js` hides such a page until the Chinese text
  is in, so it never flashes English.
- An article exists once per language (`<html data-page-lang="en|zh">` plus
  `<link rel="alternate" hreflang>` both ways): the tutorial
  (`vibe-trading-beginner.html` / `-zh.html`) and the research post. Opening
  one records its language; the button goes to the other file.
- The docs are one shell: English at `/docs/latest/<page>` from
  `docs/content.en.js`, Chinese at `/docs/zh/<page>` from
  `docs/content.zh.js`.

```bash
node wiki/scripts/check_docs_parity.mjs   # docs: same pages and sections in both languages
python3 wiki/scripts/check_i18n.py        # every data-i18n key has Chinese, no orphans (needs jinja2)
```

Counts on the pages (data sources, engines, skills, presets, MCP tools,
brokers, alphas) are measured from the code of the version in
`docs/content.js`; re-measure them for a new release rather than editing one
number.

## Alpha Library

`alpha-library/content/` and `manifest.json` are generated, not committed. The
deploy workflow builds them before uploading, and also redeploys when
`agent/src/factors/` changes:

```bash
vibe-trading alpha export-manifest --out wiki/alpha-library/manifest.json --force
python wiki/scripts/build_alpha_library.py --clean
```

## Cloudflare Pages

- Project root: `wiki`
- Build command: leave empty
- Output directory: `.`
- Custom domain: `vibetrading.wiki`

The pages are static and need no build step; the deploy workflow only
generates the Alpha Library (above). The only dynamic piece is a small
analytics layer in `functions/` (Cloudflare Pages Functions): `_middleware.js`
classifies each page request as AI-agent / bot / human by User-Agent and counts
it into a D1 database (`vibetrading-analytics`, binding `DB`), and
`api/stats.js` serves the footer's aggregate counts alongside public PyPI and
GitHub numbers. The counter is anonymous and first-party — no cookies, no
per-visitor identifier, no IP retention.
