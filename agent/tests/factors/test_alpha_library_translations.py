"""The Alpha Library's Chinese notes, nicknames and theme names match the registry.

The wiki shows every alpha's ``notes`` and ``nickname`` in Chinese from
``wiki/alpha-library/i18n.zh.json``. Each entry keeps the English it was
translated from, and the page generator only uses a translation whose English
still equals the registry's, so an edited note silently falls back to English.
These tests make that visible: a new alpha with a note but no translation, an
edited note whose translation is now stale, a translation for an alpha that no
longer exists, or a theme tag with no Chinese name all fail here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.factors.registry import Registry

STORE = Path(__file__).resolve().parents[3] / "wiki" / "alpha-library" / "i18n.zh.json"


@pytest.fixture(scope="module")
def registry_meta() -> dict[str, dict]:
    manifest = Registry().export_manifest()
    return {a["id"]: a["meta"] for zoo in manifest["zoos"] for a in zoo["alphas"]}


@pytest.fixture(scope="module")
def store() -> dict:
    return json.loads(STORE.read_text(encoding="utf-8"))


@pytest.mark.parametrize(("field", "bucket"), [("notes", "notes"), ("nickname", "nicknames")])
def test_every_english_text_has_a_current_chinese_version(
    registry_meta: dict[str, dict], store: dict, field: str, bucket: str
) -> None:
    english = {aid: meta[field] for aid, meta in registry_meta.items() if (meta.get(field) or "").strip()}
    translated = store[bucket]

    assert not sorted(set(english) - set(translated)), "untranslated: add them to i18n.zh.json"
    assert not sorted(set(translated) - set(english)), "translations for alphas that have no such text any more"
    stale = sorted(aid for aid, text in english.items() if translated[aid]["en"] != text)
    assert not stale, f"English changed since translation, update 'en' and 'zh': {stale}"
    assert all(entry["zh"].strip() and entry["zh"] != entry["en"] for entry in translated.values())


def test_every_theme_tag_has_a_chinese_name(registry_meta: dict[str, dict], store: dict) -> None:
    used = {tag for meta in registry_meta.values() for tag in meta.get("theme") or []}

    assert used <= set(store["themes"]), sorted(used - set(store["themes"]))
