from __future__ import annotations

from pathlib import Path

import yaml


RULE_FILE = Path("security/semgrep/ags-python-injection.yml")


def test_custom_semgrep_rule_file_contains_required_bypass_detectors() -> None:
    rules = yaml.safe_load(RULE_FILE.read_text(encoding="utf-8"))
    ids = {rule["id"] for rule in rules["rules"]}

    assert "ags.builtins-getattr-dynamic-exec" in ids
    assert "ags.builtins-dict-exec" in ids
    assert "ags.dynamic-import-in-lambda-or-type" in ids


def test_custom_semgrep_rules_are_scoped_to_ags_risk_patterns() -> None:
    rules = yaml.safe_load(RULE_FILE.read_text(encoding="utf-8"))
    combined = "\n".join(str(rule) for rule in rules["rules"])

    assert "getattr" in combined
    assert "__dict__" in combined
    assert "__import__" in combined
    assert "builtins" in combined
