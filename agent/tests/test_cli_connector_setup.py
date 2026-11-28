from __future__ import annotations

import cli.commands.common as _cmd_common
import cli.commands.connectors as _cmd_connectors
import cli.commands.execution as _cmd_execution
import cli.commands.parser as _cmd_parser

from src.trading.connections import ConnectionStore
from src.trading.credentials import CredentialStore


class _MemoryCredentials:
    def __init__(self):
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str):
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str):
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str):
        self.values.pop((service_name, username), None)


def test_connector_setup_parser_exposes_a_safe_local_onboarding_command():
    args = _cmd_parser.build_parser().parse_args(
        [
            "connector",
            "setup",
            "okx-live-sdk-readonly",
            "--connection-id",
            "main-okx",
            "--label",
            "Main OKX",
            "--skip-check",
        ]
    )

    assert args.connector_command == "setup"
    assert args.connection_id == "main-okx"
    assert args.label == "Main OKX"
    assert args.skip_check is True


def test_connector_setup_prompts_locally_and_never_writes_secrets_to_registry(
    tmp_path,
    monkeypatch,
):
    from src.trading import connections, service

    credentials = CredentialStore(_MemoryCredentials())
    store = ConnectionStore(tmp_path / "connections.json", credential_store=credentials)
    monkeypatch.setattr(connections, "ConnectionStore", lambda: store)
    monkeypatch.setattr(service, "check_connection", lambda *args, **kwargs: {"status": "ok"})
    answers = iter(("key-value", "secret-value", "passphrase-value"))
    monkeypatch.setattr(_cmd_common.Prompt, "ask", lambda *args, **kwargs: next(answers))

    result = _cmd_connectors.cmd_connector_setup(
        "okx-live-sdk-readonly",
        connection_id="main-okx",
        label="Main OKX",
    )

    assert result == _cmd_common.EXIT_SUCCESS
    assert credentials.load("main-okx", ("api_key", "api_secret", "passphrase")) == {
        "api_key": "key-value",
        "api_secret": "secret-value",
        "passphrase": "passphrase-value",
    }
    registry = (tmp_path / "connections.json").read_text(encoding="utf-8")
    assert "key-value" not in registry
    assert "secret-value" not in registry
    assert "passphrase-value" not in registry


def test_connector_setup_saves_the_endpoint_used_by_the_agent_read_path(tmp_path, monkeypatch):
    from src.trading import connections
    from src.tools import trading_connector_tool

    store = ConnectionStore(tmp_path / "connections.json", credential_store=CredentialStore(_MemoryCredentials()))
    monkeypatch.setattr(connections, "ConnectionStore", lambda: store)
    args = _cmd_parser.build_parser().parse_args(
        [
            "connector",
            "setup",
            "ibkr-paper-local",
            "--connection-id",
            "gateway",
            "--host",
            "localhost",
            "--port",
            "4002",
            "--skip-check",
        ]
    )
    monkeypatch.setattr(_cmd_execution, "_ensure_cli_env", lambda: None)
    assert _cmd_connectors._dispatch_connector(args) == _cmd_common.EXIT_SUCCESS
    assert store.get("gateway").endpoint == {"host": "localhost", "port": 4002}
    seen = []

    def read_account(config):
        seen.append((config.host, config.port, config.readonly))
        return {"status": "ok", "account": {}}

    monkeypatch.setattr("src.trading.connectors.ibkr.local.get_account_snapshot", read_account)
    trading_connector_tool.TradingAccountTool().execute(connection="ibkr-paper-local", connection_id="gateway")
    assert seen == [("localhost", 4002, True)]
