#!/usr/bin/env python3
"""Every translatable string on the wiki has a Chinese version, and no more.

English is the HTML itself; Chinese lives in ``wiki/locales/zh.json`` and is
applied by ``site.js`` through ``data-i18n``, ``data-i18n-html``,
``data-i18n-attr`` and ``data-href-zh``. This fails when:

* a key used on a page (hand-written, a partial, or a page the Alpha Library
  generator renders) has no Chinese value — the reader would see English in
  the middle of a Chinese page;
* ``zh.json`` holds a key nothing uses — a translation that silently stopped
  applying after someone renamed its key;
* a ``data-href-zh`` link points at a file that does not exist;
* a generated Alpha Library page is not marked language-neutral or not in
  the ``alpha`` section — it would stay English for a Chinese reader and
  highlight no header item (``sync_site_chrome.py`` checks the hand-written
  pages the same way).

The generator's templates are rendered from a one-alpha-per-zoo manifest, so
their keys are checked the way they ship (zoo ids are substituted into keys).
The docs are checked separately by ``check_docs_parity.mjs``.

Usage:
    python wiki/scripts/check_i18n.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
WIKI = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import build_alpha_library as alpha  # noqa: E402
from sync_site_chrome import pages  # noqa: E402

KEY_ATTR_RE = re.compile(r'data-i18n(?:-html)?="([^"]+)"')
ATTR_LIST_RE = re.compile(r'data-i18n-attr="([^"]+)"')
HREF_ZH_RE = re.compile(r'data-href-zh="([^"]+)"')


def generated_pages() -> list[str]:
    """Render one zoo page and one alpha page for every known zoo.

    Returns:
        The rendered HTML strings.
    """
    env = alpha._build_env()
    rendered = []
    for zoo_id in alpha._ZOO_DISPLAY:
        sample = {
            "id": f"{zoo_id}_001",
            "module_path": f"src.factors.zoo.{zoo_id}.alpha_001",
            "meta": {"theme": ["momentum"], "universe": ["equity_cn"], "frequency": ["1d"],
                     "formula_latex": "rank(x)", "notes": "note", "decay_horizon": 1,
                     "min_warmup_bars": 1, "requires_sector": False, "columns_required": ["close"]},
        }
        zoo = {"zoo_id": zoo_id, "alphas": [sample]}
        rendered.append(alpha.render_zoo_page(env, zoo))
        rendered.append(alpha.render_alpha_page(env, sample, zoo))
    return rendered


def main() -> int:
    """Compare the keys the pages use with the keys zh.json defines.

    Returns:
        Process exit code.
    """
    zh = json.loads((WIKI / "locales" / "zh.json").read_text(encoding="utf-8"))
    sources = {path.relative_to(WIKI).as_posix(): path.read_text(encoding="utf-8") for path in pages()}
    sources.update({f"partials/{p.name}": p.read_text(encoding="utf-8") for p in (WIKI / "partials").glob("*.html")})
    generated = {f"<generated #{i}>": html for i, html in enumerate(generated_pages())}
    sources.update(generated)

    used: dict[str, str] = {}
    problems = []
    for name, html in generated.items():
        html_tag = re.search(r"<html\b[^>]*>", html)
        body_tag = re.search(r"<body\b[^>]*>", html)
        if not html_tag or "data-lang-neutral" not in html_tag.group(0):
            problems.append(f"{name}: generated page lacks <html data-lang-neutral>")
        if not body_tag or 'data-section="alpha"' not in body_tag.group(0):
            problems.append(f'{name}: generated page lacks <body data-section="alpha">')
    for name, text in sources.items():
        for key in KEY_ATTR_RE.findall(text):
            used.setdefault(key, name)
        for spec in ATTR_LIST_RE.findall(text):
            for pair in spec.split(","):
                attr, _, key = pair.partition("=")
                if not attr.strip() or not key.strip():
                    problems.append(f"{name}: malformed data-i18n-attr {spec!r}")
                    continue
                used.setdefault(key.strip(), name)
        for href in HREF_ZH_RE.findall(text):
            if not (WIKI / href.lstrip("/")).is_file():
                problems.append(f"{name}: data-href-zh points at missing {href}")

    for key, where in sorted(used.items()):
        value = zh.get(key)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{where}: no Chinese for {key!r}")
    for key in sorted(set(zh) - set(used)):
        problems.append(f"locales/zh.json: {key!r} is used by no page")

    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print(f"i18n ok: {len(used)} keys, {len(sources)} sources")
    return 0


if __name__ == "__main__":
    sys.exit(main())
