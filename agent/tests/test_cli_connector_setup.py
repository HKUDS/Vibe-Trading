from __future__ import annotations

from cli import _legacy
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
    args = _legacy._build_parser().parse_args(
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
    monkeypatch.setattr(_legacy.Prompt, "ask", lambda *args, **kwargs: next(answers))

    result = _legacy.cmd_connector_setup(
        "okx-live-sdk-readonly",
        connection_id="main-okx",
        label="Main OKX",
    )

    assert result == _legacy.EXIT_SUCCESS
    assert credentials.load("main-okx", ("api_key", "api_secret", "passphrase")) == {
        "api_key": "key-value",
        "api_secret": "secret-value",
        "passphrase": "passphrase-value",
    }
    registry = (tmp_path / "connections.json").read_text(encoding="utf-8")
    assert "key-value" not in registry
    assert "secret-value" not in registry
    assert "passphrase-value" not in registry
