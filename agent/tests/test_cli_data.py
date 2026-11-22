
import cli.commands.parser as _cmd_parser


def test_data_parser_accepts_status() -> None:
    parser = _cmd_parser.build_parser()

    status = parser.parse_args(["data", "status"])
    assert status.command == "data"
    assert status.data_command == "status"
