"""Tests for atomic Longbridge credential resolution."""

from __future__ import annotations

import json

import pytest

from src.config.accessor import reset_env_config
from src.trading.connectors.longbridge.credentials import (
    LongbridgeCredentialError,
    LongbridgeCredentials,
    require_longbridge_credentials,
    resolve_longbridge_credentials,
)

_CREDENTIAL_FIELDS = ("app_key", "app_secret", "access_token")
_ENV_NAMES = {
    "app_key": "LONGBRIDGE_APP_KEY",
    "app_secret": "LONGBRIDGE_APP_SECRET",
    "access_token": "LONGBRIDGE_ACCESS_TOKEN",
}


def _clear_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_name in _ENV_NAMES.values():
        monkeypatch.delenv(env_name, raising=False)


def _set_environment(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    _clear_environment(monkeypatch)
    for field, value in values.items():
        monkeypatch.setenv(_ENV_NAMES[field], value)
    reset_env_config()


def _write_runtime_file(tmp_path, values: dict[str, str]) -> None:
    (tmp_path / "longbridge.json").write_text(json.dumps(values), encoding="utf-8")


def test_complete_environment_is_selected(monkeypatch, tmp_path):
    values = {
        "app_key": "environment-key",
        "app_secret": "environment-secret",
        "access_token": "environment-token",
    }
    _set_environment(monkeypatch, values)

    resolution = resolve_longbridge_credentials(tmp_path)

    assert resolution.credentials == LongbridgeCredentials(**values)
    assert resolution.source == "environment"
    assert resolution.missing_fields == ()
    assert resolution.conflict_fields == ()
    assert require_longbridge_credentials(tmp_path) == LongbridgeCredentials(**values)


def test_complete_runtime_file_is_fallback(monkeypatch, tmp_path):
    _clear_environment(monkeypatch)
    values = {
        "app_key": "file-key",
        "app_secret": "file-secret",
        "access_token": "file-token",
    }
    _write_runtime_file(tmp_path, values)

    resolution = resolve_longbridge_credentials(tmp_path)

    assert resolution.credentials == LongbridgeCredentials(**values)
    assert resolution.source == "runtime_file"
    assert resolution.missing_fields == ()
    assert resolution.conflict_fields == ()


def test_equal_complete_sources_are_allowed(monkeypatch, tmp_path):
    values = {
        "app_key": "shared-key",
        "app_secret": "shared-secret",
        "access_token": "shared-token",
    }
    _set_environment(monkeypatch, values)
    _write_runtime_file(tmp_path, values)

    resolution = resolve_longbridge_credentials(tmp_path)

    assert resolution.credentials == LongbridgeCredentials(**values)
    assert resolution.source == "environment"
    assert resolution.missing_fields == ()
    assert resolution.conflict_fields == ()


def test_different_complete_sources_fail_closed(monkeypatch, tmp_path):
    _set_environment(
        monkeypatch,
        {
            "app_key": "environment-key",
            "app_secret": "environment-secret",
            "access_token": "environment-token",
        },
    )
    _write_runtime_file(
        tmp_path,
        {
            "app_key": "file-key",
            "app_secret": "file-secret",
            "access_token": "file-token",
        },
    )

    resolution = resolve_longbridge_credentials(tmp_path)

    assert resolution.credentials is None
    assert resolution.source is None
    assert resolution.missing_fields == ()
    assert resolution.conflict_fields == _CREDENTIAL_FIELDS
    with pytest.raises(LongbridgeCredentialError) as exc_info:
        require_longbridge_credentials(tmp_path)
    assert exc_info.value.code == "credentials_conflict"
    assert exc_info.value.fields == _CREDENTIAL_FIELDS


def test_partial_environment_is_not_mixed_with_file(monkeypatch, tmp_path):
    _set_environment(monkeypatch, {"app_key": "environment-key"})
    _write_runtime_file(
        tmp_path,
        {
            "app_key": "file-key",
            "app_secret": "file-secret",
            "access_token": "file-token",
        },
    )

    resolution = resolve_longbridge_credentials(tmp_path)

    assert resolution.credentials is None
    assert resolution.source == "environment"
    assert resolution.missing_fields == ("app_secret", "access_token")
    assert resolution.conflict_fields == ()
    with pytest.raises(LongbridgeCredentialError) as exc_info:
        require_longbridge_credentials(tmp_path)
    assert exc_info.value.code == "credentials_partial"
    assert exc_info.value.fields == ("app_secret", "access_token")


def test_diagnostics_never_contain_secret_values(monkeypatch, tmp_path):
    _clear_environment(monkeypatch)

    with pytest.raises(LongbridgeCredentialError) as missing_exc:
        require_longbridge_credentials(tmp_path)
    assert missing_exc.value.code == "credentials_missing"
    assert missing_exc.value.fields == _CREDENTIAL_FIELDS

    environment_values = {
        "app_key": "diagnostic-environment-key",
        "app_secret": "diagnostic-environment-secret",
        "access_token": "diagnostic-environment-token",
    }
    file_values = {
        "app_key": "diagnostic-file-key",
        "app_secret": "diagnostic-file-secret",
        "access_token": "diagnostic-file-token",
    }
    _set_environment(monkeypatch, environment_values)
    _write_runtime_file(tmp_path, file_values)

    resolution = resolve_longbridge_credentials(tmp_path)
    with pytest.raises(LongbridgeCredentialError) as conflict_exc:
        require_longbridge_credentials(tmp_path)

    diagnostics = (repr(resolution), str(conflict_exc.value), repr(conflict_exc.value))
    for secret_value in (*environment_values.values(), *file_values.values()):
        assert all(secret_value not in diagnostic for diagnostic in diagnostics)


def _assert_invalid_runtime_file_is_redaction_safe(tmp_path, secret_value: str) -> None:
    for operation in (
        lambda: resolve_longbridge_credentials(tmp_path),
        lambda: require_longbridge_credentials(tmp_path),
    ):
        try:
            result = operation()
        except Exception as exc:  # The contract requires this specific safe exception.
            assert type(exc) is LongbridgeCredentialError
            assert exc.code == "credentials_partial"
            assert exc.fields == _CREDENTIAL_FIELDS
            assert secret_value not in str(exc)
            assert secret_value not in repr(exc)
        else:
            assert result.credentials is None
            assert result.source == "runtime_file"
            assert result.missing_fields == _CREDENTIAL_FIELDS
            assert result.conflict_fields == ()
            assert secret_value not in repr(result)


def test_malformed_runtime_file_uses_safe_structured_error(monkeypatch, tmp_path):
    _clear_environment(monkeypatch)
    secret_value = "malformed-runtime-secret"
    (tmp_path / "longbridge.json").write_text(
        '{"app_secret": "' + secret_value + '",', encoding="utf-8"
    )

    _assert_invalid_runtime_file_is_redaction_safe(tmp_path, secret_value)


def test_unreadable_runtime_file_uses_safe_structured_error(monkeypatch, tmp_path):
    _clear_environment(monkeypatch)
    (tmp_path / "longbridge.json").mkdir()

    _assert_invalid_runtime_file_is_redaction_safe(tmp_path, "longbridge.json")


def test_invalid_encoding_runtime_file_uses_safe_structured_error(
    monkeypatch, tmp_path
):
    _clear_environment(monkeypatch)
    secret_value = "invalid-encoding-runtime-secret"
    (tmp_path / "longbridge.json").write_bytes(
        b'{"app_secret": "' + secret_value.encode() + b'\xff"}'
    )

    _assert_invalid_runtime_file_is_redaction_safe(tmp_path, secret_value)


def test_partial_runtime_file_with_empty_environment(monkeypatch, tmp_path):
    _clear_environment(monkeypatch)
    _write_runtime_file(tmp_path, {"app_key": "partial-runtime-key"})

    resolution = resolve_longbridge_credentials(tmp_path)

    assert resolution.credentials is None
    assert resolution.source == "runtime_file"
    assert resolution.missing_fields == ("app_secret", "access_token")
    assert resolution.conflict_fields == ()
    with pytest.raises(LongbridgeCredentialError) as exc_info:
        require_longbridge_credentials(tmp_path)
    assert exc_info.value.code == "credentials_partial"
    assert exc_info.value.fields == ("app_secret", "access_token")


@pytest.mark.parametrize(
    "runtime_values",
    [
        pytest.param({}, id="empty-object"),
        pytest.param(
            {"app_key": "", "app_secret": "  ", "access_token": "\t\n"},
            id="all-blank-values",
        ),
    ],
)
def test_valid_zero_runtime_source_is_missing(monkeypatch, tmp_path, runtime_values):
    _clear_environment(monkeypatch)
    _write_runtime_file(tmp_path, runtime_values)

    resolution = resolve_longbridge_credentials(tmp_path)

    assert resolution.credentials is None
    assert resolution.source is None
    assert resolution.missing_fields == _CREDENTIAL_FIELDS
    assert resolution.conflict_fields == ()
    with pytest.raises(LongbridgeCredentialError) as exc_info:
        require_longbridge_credentials(tmp_path)
    assert exc_info.value.code == "credentials_missing"
    assert exc_info.value.fields == _CREDENTIAL_FIELDS
