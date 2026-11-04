from cli import _legacy


def test_data_parser_accepts_status() -> None:
    parser = _legacy._build_parser()

    status = parser.parse_args(["data", "status"])
    assert status.command == "data"
    assert status.data_command == "status"
