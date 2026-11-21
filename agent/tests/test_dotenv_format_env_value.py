"""Unit tests for ``src.config.dotenv._format_env_value``.

``_format_env_value`` is the single place that turns a Settings-supplied
string into a dotenv ``KEY=value`` line body. Two invariants matter for
correctness/security: a newline or carriage return must never reach the
written file (that would let a value inject a bogus extra ``KEY=`` line or
comment into ``.env``), and a value that needs quoting (because it contains
whitespace or ``#``) must have its own backslashes and double quotes escaped
in the right order so the quoted line parses back to the original value.
"""

from __future__ import annotations

import pytest

from src.config.dotenv import _format_env_value


def test_format_env_value_empty_string_returns_empty():
    assert _format_env_value("") == ""


def test_format_env_value_whitespace_only_returns_empty():
    assert _format_env_value("   ") == ""


def test_format_env_value_simple_value_is_unquoted():
    assert _format_env_value("sk-plain-token") == "sk-plain-token"


def test_format_env_value_strips_surrounding_whitespace():
    assert _format_env_value("  plain  ") == "plain"


def test_format_env_value_quotes_value_containing_space():
    assert _format_env_value("has space") == '"has space"'


def test_format_env_value_quotes_value_containing_hash_without_space():
    # No whitespace, but '#' alone must still trigger quoting or a later
    # unquoted read would treat everything after '#' as a comment.
    assert _format_env_value("value#tail") == '"value#tail"'


def test_format_env_value_escapes_quotes_and_backslashes_in_order():
    # Backslashes must be escaped first, then quotes, so unescaping the
    # written line recovers exactly the original backslash-quote sequence.
    value = 'back\\slash and "quote" here'
    formatted = _format_env_value(value)
    assert formatted == '"back\\\\slash and \\"quote\\" here"'


@pytest.mark.parametrize("bad_value", ["line1\nline2", "line1\rline2", "a\n"])
def test_format_env_value_rejects_embedded_newlines(bad_value):
    with pytest.raises(ValueError):
        _format_env_value(bad_value)
