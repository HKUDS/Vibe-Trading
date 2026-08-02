from __future__ import annotations

import pytest

from cli import _legacy


def test_data_parser_accepts_status_mode_and_usage() -> None:
    parser = _legacy._build_parser()

    status = parser.parse_args(["data", "status"])
    assert status.command == "data"
    assert status.data_command == "status"

    free = parser.parse_args(["data", "mode", "free"])
    assert free.command == "data"
    assert free.data_command == "mode"
    assert free.mode == "free"

    paid = parser.parse_args(
        [
            "data",
            "mode",
            "paid",
            "--budget",
            "30",
            "--key",
            "sk-test",
            "--url",
            "https://qveris.test/api/v1",
        ]
    )
    assert paid.mode == "paid"
    assert paid.budget == 30
    assert paid.key == "sk-test"
    assert paid.url == "https://qveris.test/api/v1"

    usage = parser.parse_args(["data", "usage"])
    assert usage.data_command == "usage"


def test_qveris_is_not_a_top_level_user_command() -> None:
    parser = _legacy._build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["qveris", "status"])
