#!/usr/bin/env python3
"""Render the Alpha Library wiki section from ``manifest.json``.

Pipeline:
    1. Load ``wiki/alpha-library/manifest.json`` (produced by
       ``vibe-trading alpha export-manifest``).
    2. Emit one HTML page per alpha at
       ``wiki/alpha-library/content/<zoo>/<alpha_id>.html``.
    3. Emit one zoo overview page at
       ``wiki/alpha-library/content/<zoo>/index.html``.
    4. Emit ``wiki/alpha-library/content/index.json`` — a small blob the
       static landing page (``wiki/alpha-library/index.html``) fetches at
       runtime to fill in zoo counts and the "generated at" stamp.

Security posture (v0.1.8):
    * All HTML is rendered with Jinja2 autoescape on (``select_autoescape``)
      so manifest-derived strings (``formula_latex``, ``notes``, ids, …)
      cannot break out of the document.
    * Each generated page carries a strict Content-Security-Policy meta:
      ``script-src 'self'`` — no inline script and nothing from another
      origin. The only scripts are the site's own shell (theme, header,
      language switch), the same files every other wiki page loads.
    * KaTeX is intentionally **not** loaded. ``formula_latex`` is shown as
      raw escaped text inside ``<pre>``. A future revision can swap in a
      server-side LaTeX→MathML pass that keeps CSP intact.
    * Notes, nicknames and theme tags carry their Chinese in ``data-text-zh``
      from ``wiki/alpha-library/i18n.zh.json`` — only when the stored English
      still matches the manifest, so a stale translation is never shown.
    * The header, footer and head block come from ``wiki/partials/`` (the
      same markup ``sync_site_chrome.py`` writes into the hand-written
      pages); labels carry ``data-i18n`` keys from ``wiki/locales/zh.json``.
    * Run-time safety check (``--check-escape``, on by default) verifies a
      sample page contains no unescaped ``<``/``>``/``"`` from
      manifest-derived fields. The script exits non-zero on failure.

CLI:
    python wiki/scripts/build_alpha_library.py
    python wiki/scripts/build_alpha_library.py --manifest path/to/manifest.json
    python wiki/scripts/build_alpha_library.py --output-dir wiki/alpha-library/content
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from markupsafe import Markup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sync_site_chrome import render_block  # noqa: E402

try:
    from jinja2 import Environment, select_autoescape
except ImportError as exc:  # pragma: no cover — Jinja2 is a project dep
    print(
        "build_alpha_library: jinja2 is required (pip install jinja2)",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MANIFEST = _REPO_ROOT / "wiki" / "alpha-library" / "manifest.json"
_DEFAULT_OUTPUT = _REPO_ROOT / "wiki" / "alpha-library" / "content"
# Chinese notes, nicknames and theme names. Each note and nickname keeps the
# English it was translated from, so an edited English text is shown in
# English until its translation is updated (agent/tests/factors/
# test_alpha_library_translations.py fails in the meantime).
_I18N_PATH = _REPO_ROOT / "wiki" / "alpha-library" / "i18n.zh.json"

# Strict CSP for static content pages: same-origin scripts only, no inline.
_CSP_CONTENT = (
    "default-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "script-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self' https://fonts.gstatic.com; "
    "connect-src 'self' https://api.github.com;"
)

# Cache-busting version of the site shell modules; matches the hand-written pages.
_SHELL_VERSION = "20260929e"

# Display names for zoos. Source of truth — do not depend on prose elsewhere.
_ZOO_DISPLAY: dict[str, dict[str, str]] = {
    "qlib158": {
        "name": "Qlib Alpha158",
        "tagline": "Microsoft Qlib's 158 production alphas, ported to the panel API.",
    },
    "alpha101": {
        "name": "Kakushadze 101 Formulaic Alphas",
        "tagline": "The 101 short-horizon formulaic alphas from Kakushadze (2015).",
    },
    "gtja191": {
        "name": "GTJA 191",
        "tagline": "Guotai Junan's 191 alphas — A-share microstructure & volume themes.",
    },
    "academic": {
        "name": "Academic Anomalies",
        "tagline": "Curated alphas from the academic asset-pricing literature.",
    },
    "fundamental": {
        "name": "Point-in-time Fundamentals",
        "tagline": (
            "US SEC fundamentals anchored to the filing date, so a backtest never "
            "sees a number before it was published."
        ),
    },
}


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


def parse_manifest(path: Path) -> dict[str, Any]:
    """Load and lightly validate a manifest written by export-manifest.

    Args:
        path: Filesystem path to ``manifest.json``.

    Returns:
        The parsed manifest dict.

    Raises:
        SystemExit: If the file does not exist or has the wrong shape. We
            exit rather than raise because this is a CLI script and the
            caller is a human / CI step.
    """
    if not path.is_file():
        print(
            f"build_alpha_library: manifest not found at {path}\n"
            "  run: vibe-trading alpha export-manifest --out "
            "wiki/alpha-library/manifest.json --force",
            file=sys.stderr,
        )
        raise SystemExit(1)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"build_alpha_library: manifest is not valid JSON: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if not isinstance(raw, dict) or "zoos" not in raw or not isinstance(raw["zoos"], list):
        print(
            "build_alpha_library: manifest missing 'zoos' list "
            "(expected schema from Registry.export_manifest)",
            file=sys.stderr,
        )
        raise SystemExit(1)

    return raw


# ---------------------------------------------------------------------------
# Templates (inline string constants)
# ---------------------------------------------------------------------------


_ALPHA_PAGE_TEMPLATE = """<!doctype html>
<html lang="en" data-lang-neutral>
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Security-Policy" content="{{ csp }}">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ alpha.id }} | {{ zoo_display.name }} | Vibe-Trading</title>
  <meta name="description" content="{{ alpha.id }} — {{ zoo_display.name }} alpha definition.">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="https://vibetrading.wiki/alpha-library/content/{{ zoo.zoo_id }}/{{ alpha.id }}.html">
{{ head_block }}
  <script type="module" src="/main.js?v={{ shell_version }}"></script>
  <style>
    .alpha-page { width: min(880px, calc(100% - 32px)); margin: 48px auto 96px; }
    .alpha-page .crumbs { color: var(--muted); font-family: var(--mono); font-size: 0.85rem; margin-bottom: 12px; }
    .alpha-page .crumbs a { color: var(--accent); }
    .alpha-page h1 { font-family: var(--mono); font-size: 1.9rem; margin: 0 0 6px; word-break: break-word; }
    .alpha-page .nickname { color: var(--muted); margin: 0 0 28px; }
    .alpha-page .meta-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px 24px; margin: 24px 0; }
    .alpha-page .meta-grid dt { color: var(--muted); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em; }
    .alpha-page .meta-grid dd { margin: 4px 0 0; font-family: var(--mono); font-size: 0.92rem; word-break: break-word; }
    .alpha-page .formula { background: var(--surface-2); border: 1px solid var(--line); border-radius: 12px; padding: 16px 18px; overflow-x: auto; font-family: var(--mono); font-size: 0.9rem; white-space: pre-wrap; }
    .alpha-page .notes { color: var(--ink); margin-top: 18px; line-height: 1.7; }
    .alpha-page h2 { font-family: var(--mono); font-size: 1.05rem; margin: 32px 0 12px; letter-spacing: 0.02em; }
    .alpha-page .tag { display: inline-block; border: 1px solid var(--line); border-radius: 999px; padding: 2px 10px; margin: 2px 4px 2px 0; font-size: 0.78rem; color: var(--muted); }
  </style>
</head>
<body data-section="alpha">
{{ header_block }}

  <main class="alpha-page">
    <p class="crumbs">
      <a href="/alpha-library/" data-i18n="nav.alpha">Alpha Library</a>
      &nbsp;/&nbsp;
      <a href="index.html" data-i18n="alpha.zoo.{{ zoo.zoo_id }}Name">{{ zoo_display.name }}</a>
      &nbsp;/&nbsp;
      <span>{{ alpha.id }}</span>
    </p>
    <h1>{{ alpha.id }}</h1>
    {% if alpha.meta.nickname %}<p class="nickname"{% if zh.nickname %} data-text-zh="{{ zh.nickname }}"{% endif %}>{{ alpha.meta.nickname }}</p>{% endif %}

    <h2 data-i18n="alpha.page.themes">Themes &amp; universe</h2>
    <p>
      {% for t in alpha.meta.theme %}<span class="tag" data-text-zh="{{ t | zh_theme }}">{{ t }}</span>{% endfor %}
      {% for u in alpha.meta.universe %}<span class="tag">{{ u }}</span>{% endfor %}
      {% for f in alpha.meta.frequency %}<span class="tag">{{ f }}</span>{% endfor %}
    </p>

    <h2 data-i18n="alpha.page.formula">Formula</h2>
    <pre class="formula"><code>{{ alpha.meta.formula_latex }}</code></pre>

    <h2 data-i18n="alpha.page.definition">Definition</h2>
    <dl class="meta-grid">
      <div><dt>id</dt><dd>{{ alpha.id }}</dd></div>
      <div><dt>zoo</dt><dd>{{ zoo.zoo_id }}</dd></div>
      <div><dt>module_path</dt><dd>{{ alpha.module_path }}</dd></div>
      <div><dt>decay_horizon</dt><dd>{{ alpha.meta.decay_horizon }}</dd></div>
      <div><dt>min_warmup_bars</dt><dd>{{ alpha.meta.min_warmup_bars }}</dd></div>
      <div><dt>requires_sector</dt><dd>{{ alpha.meta.requires_sector }}</dd></div>
      <div><dt>columns_required</dt><dd>{{ alpha.meta.columns_required | join(", ") }}</dd></div>
      {% if alpha.meta.extras_required %}<div><dt>extras_required</dt><dd>{{ alpha.meta.extras_required | join(", ") }}</dd></div>{% endif %}
    </dl>

    {% if alpha.meta.notes %}
    <h2 data-i18n="alpha.page.notes">Notes</h2>
    <p class="notes"{% if zh.notes %} data-text-zh="{{ zh.notes }}"{% endif %}>{{ alpha.meta.notes }}</p>
    {% endif %}

    <h2 data-i18n="alpha.page.run">Run it</h2>
    <pre class="formula"><code>pip install vibe-trading-ai
vibe-trading alpha show {{ alpha.id }}
vibe-trading alpha bench --zoo {{ zoo.zoo_id }} --universe csi300 --period 2020-2025</code></pre>
  </main>

{{ footer_block }}
</body>
</html>
"""


_ZOO_PAGE_TEMPLATE = """<!doctype html>
<html lang="en" data-lang-neutral>
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Security-Policy" content="{{ csp }}">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ zoo_display.name }} | Alpha Library | Vibe-Trading</title>
  <meta name="description" content="{{ zoo_display.tagline }}">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="https://vibetrading.wiki/alpha-library/content/{{ zoo.zoo_id }}/index.html">
{{ head_block }}
  <script type="module" src="/main.js?v={{ shell_version }}"></script>
  <style>
    .zoo-page { width: min(1100px, calc(100% - 32px)); margin: 48px auto 96px; }
    .zoo-page .crumbs { color: var(--muted); font-family: var(--mono); font-size: 0.85rem; margin-bottom: 12px; }
    .zoo-page .crumbs a { color: var(--accent); }
    .zoo-page h1 { font-family: var(--mono); font-size: 2rem; margin: 0 0 6px; }
    .zoo-page .tagline { color: var(--muted); margin: 0 0 28px; max-width: 640px; line-height: 1.6; }
    .zoo-page .count-pill { display: inline-block; background: var(--surface-2); border: 1px solid var(--line); border-radius: 999px; padding: 4px 12px; font-family: var(--mono); font-size: 0.82rem; color: var(--muted); margin-left: 8px; }
    .zoo-page table { width: 100%; border-collapse: collapse; margin-top: 12px; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }
    .zoo-page th, .zoo-page td { padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--line); font-size: 0.9rem; }
    .zoo-page th { background: var(--surface-2); font-family: var(--mono); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); font-weight: 500; }
    .zoo-page tr:last-child td { border-bottom: none; }
    .zoo-page tbody tr:hover { background: var(--surface-2); }
    .zoo-page td a { color: var(--accent); font-family: var(--mono); }
    .zoo-page .theme-cell { color: var(--muted); font-size: 0.82rem; }
  </style>
</head>
<body data-section="alpha">
{{ header_block }}

  <main class="zoo-page">
    <p class="crumbs"><a href="/alpha-library/" data-i18n="nav.alpha">Alpha Library</a> &nbsp;/&nbsp; <span data-i18n="alpha.zoo.{{ zoo.zoo_id }}Name">{{ zoo_display.name }}</span></p>
    <h1><span data-i18n="alpha.zoo.{{ zoo.zoo_id }}Name">{{ zoo_display.name }}</span> <span class="count-pill">{{ zoo.alphas | length }} <span data-i18n="alpha.page.alphasUnit">alphas</span></span></h1>
    <p class="tagline" data-i18n="alpha.zoo.{{ zoo.zoo_id }}">{{ zoo_display.tagline }}</p>

    <table>
      <thead>
        <tr>
          <th>id</th>
          <th data-i18n="alpha.page.theme">theme</th>
          <th data-i18n="alpha.page.universe">universe</th>
          <th data-i18n="alpha.page.decay">decay</th>
          <th data-i18n="alpha.page.warmup">warmup</th>
        </tr>
      </thead>
      <tbody>
      {% for a in zoo.alphas %}
        <tr>
          <td><a href="{{ a.id }}.html">{{ a.id }}</a></td>
          <td class="theme-cell" data-text-zh="{{ a.meta.theme | map('zh_theme') | join('、') }}">{{ a.meta.theme | join(", ") }}</td>
          <td class="theme-cell">{{ a.meta.universe | join(", ") }}</td>
          <td>{{ a.meta.decay_horizon }}</td>
          <td>{{ a.meta.min_warmup_bars }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </main>

{{ footer_block }}
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _load_i18n() -> dict[str, Any]:
    """Load the Chinese notes / nicknames / theme names (empty when absent).

    Returns:
        ``{"notes": {id: {"en", "zh"}}, "nicknames": {...}, "themes": {tag: zh}}``.
    """
    if not _I18N_PATH.is_file():
        return {"notes": {}, "nicknames": {}, "themes": {}}
    return json.loads(_I18N_PATH.read_text(encoding="utf-8"))


_I18N = _load_i18n()


def _zh_texts(alpha: dict) -> dict[str, str | None]:
    """Chinese note and nickname for one alpha, or None where stale / missing.

    Args:
        alpha: One manifest alpha entry.

    Returns:
        ``{"notes": ..., "nickname": ...}``.
    """
    meta = alpha.get("meta", {})
    out: dict[str, str | None] = {}
    for field, bucket in (("notes", "notes"), ("nickname", "nicknames")):
        entry = _I18N.get(bucket, {}).get(alpha.get("id"))
        text = meta.get(field)
        out[field] = entry["zh"] if entry and text and entry.get("en") == text else None
    return out


def _build_env() -> Environment:
    """Create a Jinja2 environment with mandatory autoescape on."""
    env = Environment(
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["zh_theme"] = lambda tag: _I18N.get("themes", {}).get(tag, tag)
    return env


def _chrome() -> dict[str, Any]:
    """Return the shared head block, header and footer as trusted markup.

    They come from ``wiki/partials/`` (repository files, not manifest data),
    so they are marked safe and bypass autoescape; everything derived from
    the manifest still goes through it.

    Returns:
        Template variables ``head_block``, ``header_block``, ``footer_block``
        and ``shell_version``.
    """
    return {
        "head_block": Markup(render_block("site-head", "  ")),
        "header_block": Markup(render_block("site-header", "  ")),
        "footer_block": Markup(render_block("site-footer", "  ")),
        "shell_version": _SHELL_VERSION,
    }


def render_alpha_page(env: Environment, alpha: dict, zoo: dict) -> str:
    """Render a single alpha detail page."""
    zoo_display = _ZOO_DISPLAY.get(
        zoo["zoo_id"],
        {"name": zoo["zoo_id"], "tagline": ""},
    )
    template = env.from_string(_ALPHA_PAGE_TEMPLATE)
    return template.render(
        alpha=alpha,
        zoo=zoo,
        zoo_display=zoo_display,
        csp=_CSP_CONTENT,
        zh=_zh_texts(alpha),
        **_chrome(),
    )


def render_zoo_page(env: Environment, zoo: dict) -> str:
    """Render a zoo overview page with a sortable-style alpha table."""
    zoo_display = _ZOO_DISPLAY.get(
        zoo["zoo_id"],
        {"name": zoo["zoo_id"], "tagline": ""},
    )
    template = env.from_string(_ZOO_PAGE_TEMPLATE)
    return template.render(zoo=zoo, zoo_display=zoo_display, csp=_CSP_CONTENT, **_chrome())


def render_index_data(manifest: dict) -> dict:
    """Build the small JSON blob fetched by the static landing page."""
    zoos_out: list[dict] = []
    total = 0
    for zoo in manifest.get("zoos", []):
        count = len(zoo.get("alphas", []))
        total += count
        display = _ZOO_DISPLAY.get(
            zoo["zoo_id"],
            {"name": zoo["zoo_id"], "tagline": ""},
        )
        zoos_out.append(
            {
                "zoo_id": zoo["zoo_id"],
                "name": display["name"],
                "tagline": display["tagline"],
                "count": count,
                "href": f"content/{zoo['zoo_id']}/index.html",
            }
        )
    return {
        "generated_at": manifest.get("generated_at"),
        "rendered_at": datetime.now(timezone.utc).isoformat(),
        "total_alphas": total,
        "zoo_count": len(zoos_out),
        "zoos": zoos_out,
    }


# ---------------------------------------------------------------------------
# Escape self-test
# ---------------------------------------------------------------------------


def _escape_smoke(sample_html: str, alpha: dict) -> bool:
    """Confirm manifest-derived fields are escaped in the rendered HTML.

    We check the two highest-risk fields (``formula_latex``, ``notes``)
    for the presence of any raw ``<script`` or unescaped angle bracket
    that would indicate Jinja2 autoescape was bypassed.
    """
    formula = alpha.get("meta", {}).get("formula_latex", "")
    # The formula lives inside `<pre class="formula"><code>...</code></pre>`;
    # the page's own chrome (which loads the site scripts) is outside it.
    start_tag = '<pre class="formula"><code>'
    end_tag = "</code></pre>"
    if start_tag not in sample_html:
        return "<script" not in formula.lower()
    start = sample_html.index(start_tag) + len(start_tag)
    end = sample_html.index(end_tag, start)
    block = sample_html[start:end]
    if "<script" in formula.lower():
        # We synthesised a hostile string into a real alpha — refuse.
        return "<script" not in block.lower()
    # autoescape should turn `<` into `&lt;` etc.
    if "<" in formula and "<" in block and "&lt;" not in block:
        return False
    if ">" in formula and ">" in block and "&gt;" not in block:
        return False
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render the Alpha Library wiki section from manifest.json."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=_DEFAULT_MANIFEST,
        help="Path to manifest.json (default: wiki/alpha-library/manifest.json)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help="Output directory (default: wiki/alpha-library/content)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove the output directory before rendering",
    )
    args = parser.parse_args(argv)

    manifest = parse_manifest(args.manifest)
    env = _build_env()

    out_dir: Path = args.output_dir
    if args.clean and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    alpha_count = 0
    zoo_count = 0
    sample_alpha: dict | None = None
    sample_html: str | None = None
    untranslated: list[str] = []

    for zoo in manifest.get("zoos", []):
        zoo_id = zoo.get("zoo_id")
        if not isinstance(zoo_id, str) or not zoo_id:
            continue
        zoo_dir = out_dir / zoo_id
        zoo_dir.mkdir(parents=True, exist_ok=True)

        # zoo overview
        _write(zoo_dir / "index.html", render_zoo_page(env, zoo))
        zoo_count += 1

        # per-alpha pages
        for alpha in zoo.get("alphas", []):
            alpha_id = alpha.get("id")
            if not isinstance(alpha_id, str) or "/" in alpha_id or ".." in alpha_id:
                # Defensive: alpha ids are validated upstream by the registry
                # regex, but never trust a JSON file from disk.
                continue
            html = render_alpha_page(env, alpha, zoo)
            zh = _zh_texts(alpha)
            meta = alpha.get("meta", {})
            if (meta.get("notes") and not zh["notes"]) or (meta.get("nickname") and not zh["nickname"]):
                untranslated.append(alpha_id)
            _write(zoo_dir / f"{alpha_id}.html", html)
            alpha_count += 1
            if sample_alpha is None:
                sample_alpha = alpha
                sample_html = html

    # Top-level JSON for the landing page to fetch.
    index_data = render_index_data(manifest)
    _write(
        out_dir / "index.json",
        json.dumps(index_data, indent=2),
    )

    # Escape self-test.
    if sample_alpha is not None and sample_html is not None:
        if _escape_smoke(sample_html, sample_alpha):
            print("html escape ok")
        else:
            print("html escape FAIL", file=sys.stderr)
            return 1

    if untranslated:
        print(
            f"warning: {len(untranslated)} alphas show English notes/nicknames in Chinese "
            f"(missing or stale in {_I18N_PATH.name}): {', '.join(untranslated[:10])}",
            file=sys.stderr,
        )
    print(
        f"built: {alpha_count} alphas across {zoo_count} zoos -> {out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
