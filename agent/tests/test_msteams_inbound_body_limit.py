"""Security regression tests for the MSTeams inbound webhook body bound."""

from __future__ import annotations

import pytest

from src.channels.msteams import (
    MSTEAMS_MAX_INBOUND_BODY_BYTES,
    msteams_validate_content_length,
)


@pytest.mark.parametrize("raw", ["0", None])
def test_absent_or_zero_length_is_accepted(raw: str | None) -> None:
    """An absent or zero body is valid; the handler substitutes ``{}``."""
    length, error = msteams_validate_content_length(raw)

    assert error is None
    assert length == 0


def test_ordinary_activity_size_is_accepted() -> None:
    length, error = msteams_validate_content_length("4096")

    assert error is None
    assert length == 4096


def test_limit_boundary_is_inclusive() -> None:
    length, error = msteams_validate_content_length(str(MSTEAMS_MAX_INBOUND_BODY_BYTES))

    assert error is None
    assert length == MSTEAMS_MAX_INBOUND_BODY_BYTES


def test_oversized_declared_length_is_rejected_before_read() -> None:
    """A hostile Content-Length must not drive an unbounded allocation."""
    _length, error = msteams_validate_content_length(
        str(MSTEAMS_MAX_INBOUND_BODY_BYTES + 1)
    )

    assert error == 413


def test_absurd_declared_length_is_rejected() -> None:
    _length, error = msteams_validate_content_length("10000000000")

    assert error == 413


@pytest.mark.parametrize("raw", ["-1", "abc", "1.5", "0x10", " ", ""])
def test_malformed_length_is_rejected(raw: str) -> None:
    _length, error = msteams_validate_content_length(raw)

    assert error == 400
