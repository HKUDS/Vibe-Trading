"""Contract tests for the optional Longbridge historical-data loader."""

from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from backtest.loaders import longbridge as loader_mod
from backtest.loaders.base import NoAvailableSourceError
from src.trading.connectors.longbridge import credentials as lb_credentials


def test_wide_date_range_never_truncates_silently() -> None:
    start = dt.date(2000, 1, 1)
    end = start + dt.timedelta(days=loader_mod._MAX_WINDOW_DAYS * loader_mod._MAX_WINDOWS)

    with pytest.raises(NoAvailableSourceError, match="exceeds.*window limit"):
        loader_mod._date_windows(start, end)


@pytest.mark.parametrize("interval", ["2D", "4h", "garbage"])
def test_unsupported_intervals_fail_instead_of_changing_fidelity(
    interval: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_openapi = SimpleNamespace(Period=SimpleNamespace(Day="day"))
    monkeypatch.setattr(loader_mod, "_require_longbridge", lambda: fake_openapi)

    with pytest.raises(NoAvailableSourceError, match="unsupported Longbridge interval"):
        loader_mod._to_longport_period(interval)


def test_normalize_frame_converts_intraday_timestamps_to_naive_utc() -> None:
    bars = [
        SimpleNamespace(
            timestamp=pd.Timestamp("2026-07-14 09:30:00", tz="Asia/Hong_Kong"),
            open=10,
            high=11,
            low=9,
            close=10.5,
            volume=100,
        )
    ]

    frame = loader_mod._normalize_frame(bars)

    assert frame.index.tz is None
    assert frame.index[0] == pd.Timestamp("2026-07-14 01:30:00")


def test_is_available_does_not_make_a_market_data_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("LONGBRIDGE_APP_KEY", "key")
    monkeypatch.setenv("LONGBRIDGE_APP_SECRET", "secret")
    monkeypatch.setenv("LONGBRIDGE_ACCESS_TOKEN", "token")
    monkeypatch.setattr(lb_credentials, "get_runtime_root", lambda: tmp_path)
    fake_openapi = SimpleNamespace()
    monkeypatch.setattr(loader_mod, "_require_longbridge", lambda: fake_openapi)

    assert loader_mod.LongbridgeLoader().is_available() is True


def test_is_available_contains_secret_bearing_sdk_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("LONGBRIDGE_APP_KEY", "availability-key")
    monkeypatch.setenv("LONGBRIDGE_APP_SECRET", "availability-secret")
    monkeypatch.setenv("LONGBRIDGE_ACCESS_TOKEN", "availability-token")
    monkeypatch.setattr(lb_credentials, "get_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(
        loader_mod,
        "_require_longbridge",
        lambda: (_ for _ in ()).throw(
            RuntimeError("SDK failure with access_token=availability-token")
        ),
    )

    assert loader_mod.LongbridgeLoader().is_available() is False


def test_fetch_rejects_missing_credentials_before_sdk_initialization(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.delenv("LONGBRIDGE_APP_KEY", raising=False)
    monkeypatch.delenv("LONGBRIDGE_APP_SECRET", raising=False)
    monkeypatch.delenv("LONGBRIDGE_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(lb_credentials, "get_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(
        loader_mod,
        "_require_longbridge",
        lambda: (_ for _ in ()).throw(AssertionError("SDK must not initialize")),
    )

    with pytest.raises(NoAvailableSourceError, match="credentials are not configured"):
        loader_mod.LongbridgeLoader().fetch(
            ["AAPL"], "2026-01-01", "2026-01-02"
        )


def test_loader_partial_environment_with_complete_file_fails_before_sdk(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    secrets = {
        "environment": "loader-partial-environment-key-21ac",
        "file_key": "loader-complete-file-key-32bd",
        "file_secret": "loader-complete-file-secret-43ce",
        "file_token": "loader-complete-file-token-54df",
    }
    monkeypatch.setenv("LONGBRIDGE_APP_KEY", secrets["environment"])
    monkeypatch.delenv("LONGBRIDGE_APP_SECRET", raising=False)
    monkeypatch.delenv("LONGBRIDGE_ACCESS_TOKEN", raising=False)
    (tmp_path / "longbridge.json").write_text(
        json.dumps(
            {
                "app_key": secrets["file_key"],
                "app_secret": secrets["file_secret"],
                "access_token": secrets["file_token"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(lb_credentials, "get_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(
        loader_mod,
        "_require_longbridge",
        lambda: (_ for _ in ()).throw(AssertionError("SDK must not initialize")),
    )

    loader = loader_mod.LongbridgeLoader()
    assert loader.is_available() is False
    with pytest.raises(NoAvailableSourceError) as exc_info:
        loader.fetch(["AAPL"], "2026-01-01", "2026-01-02")

    diagnostic = str(exc_info.value)
    assert "credentials_partial" in diagnostic
    assert "app_secret" in diagnostic and "access_token" in diagnostic
    assert all(value not in diagnostic for value in secrets.values())
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_loader_differing_complete_sources_fail_before_sdk(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    environment = {
        "app_key": "loader-conflict-environment-key-65e0",
        "app_secret": "loader-conflict-environment-secret-76f1",
        "access_token": "loader-conflict-environment-token-8702",
    }
    runtime_file = {
        "app_key": "loader-conflict-file-key-9813",
        "app_secret": "loader-conflict-file-secret-a924",
        "access_token": "loader-conflict-file-token-ba35",
    }
    monkeypatch.setenv("LONGBRIDGE_APP_KEY", environment["app_key"])
    monkeypatch.setenv("LONGBRIDGE_APP_SECRET", environment["app_secret"])
    monkeypatch.setenv("LONGBRIDGE_ACCESS_TOKEN", environment["access_token"])
    (tmp_path / "longbridge.json").write_text(json.dumps(runtime_file), encoding="utf-8")
    monkeypatch.setattr(lb_credentials, "get_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(
        loader_mod,
        "_require_longbridge",
        lambda: (_ for _ in ()).throw(AssertionError("SDK must not initialize")),
    )

    loader = loader_mod.LongbridgeLoader()
    assert loader.is_available() is False
    with pytest.raises(NoAvailableSourceError) as exc_info:
        loader.fetch(["AAPL"], "2026-01-01", "2026-01-02")

    diagnostic = str(exc_info.value)
    assert "credentials_conflict" in diagnostic
    assert all(field in diagnostic for field in ("app_key", "app_secret", "access_token"))
    assert all(
        value not in diagnostic
        for value in (*environment.values(), *runtime_file.values())
    )
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def _configured_loader() -> loader_mod.LongbridgeLoader:
    loader = loader_mod.LongbridgeLoader.__new__(loader_mod.LongbridgeLoader)
    loader._app_key = "key"
    loader._app_secret = "secret"
    loader._access_token = "token"
    return loader


def test_fetch_combines_all_windows_and_caches_complete_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[dt.date, dt.date]] = []
    cached: list[pd.DataFrame] = []

    class FakeQuoteContext:
        def __init__(self, config: object) -> None:
            assert config == ("key", "secret", "token")

        def history_candlesticks_by_date(
            self,
            symbol: str,
            period: str,
            adjust_type: str,
            *,
            start: dt.date,
            end: dt.date,
        ) -> list[SimpleNamespace]:
            assert symbol == "AAPL.US"
            assert period == "day"
            assert adjust_type == "none"
            calls.append((start, end))
            return [
                SimpleNamespace(
                    timestamp=pd.Timestamp(start),
                    open=10,
                    high=11,
                    low=9,
                    close=10.5,
                    volume=100,
                )
            ]

    fake_openapi = SimpleNamespace(
        Config=lambda *args: args,
        QuoteContext=FakeQuoteContext,
        Period=SimpleNamespace(Day="day"),
        AdjustType=SimpleNamespace(NoAdjust="none"),
    )
    monkeypatch.setattr(loader_mod, "_require_longbridge", lambda: fake_openapi)
    monkeypatch.setattr(loader_mod, "loader_cache_get", lambda **kwargs: None)
    monkeypatch.setattr(
        loader_mod,
        "loader_cache_put",
        lambda **kwargs: cached.append(kwargs["frame"].copy()),
    )

    result = _configured_loader().fetch(
        ["AAPL"], "2026-01-01", "2026-07-01", interval="1D"
    )

    assert calls == [
        (dt.date(2026, 1, 1), dt.date(2026, 6, 29)),
        (dt.date(2026, 6, 30), dt.date(2026, 7, 1)),
    ]
    assert list(result) == ["AAPL"]
    assert len(result["AAPL"]) == 2
    assert len(cached) == 1
    pd.testing.assert_frame_equal(cached[0], result["AAPL"])


def test_fetch_rejects_partial_history_when_a_window_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sdk-window-exception-credential-cb46"

    class SecretBearingSdkError(RuntimeError):
        pass

    class FakeQuoteContext:
        def __init__(self, config: object) -> None:
            pass

        def history_candlesticks_by_date(self, *args: object, **kwargs: object):
            if kwargs["start"] == dt.date(2026, 6, 30):
                raise SecretBearingSdkError(f"quota failed with credential={secret}")
            return [
                SimpleNamespace(
                    timestamp=pd.Timestamp(kwargs["start"]),
                    open=10,
                    high=11,
                    low=9,
                    close=10.5,
                    volume=100,
                )
            ]

    fake_openapi = SimpleNamespace(
        Config=lambda *args: args,
        QuoteContext=FakeQuoteContext,
        Period=SimpleNamespace(Day="day"),
        AdjustType=SimpleNamespace(NoAdjust="none"),
    )
    monkeypatch.setattr(loader_mod, "_require_longbridge", lambda: fake_openapi)
    monkeypatch.setattr(loader_mod, "loader_cache_get", lambda **kwargs: None)
    monkeypatch.setattr(
        loader_mod,
        "loader_cache_put",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not cache")),
    )

    with pytest.raises(NoAvailableSourceError) as exc_info:
        _configured_loader().fetch(
            ["AAPL"], "2026-01-01", "2026-07-01", interval="1D"
        )

    assert str(exc_info.value) == "Longbridge history request failed."
    assert secret not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_fetch_redacts_sdk_initialization_exception_and_drops_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sdk-init-exception-credential-dc57"

    class SecretBearingSdkError(RuntimeError):
        pass

    fake_openapi = SimpleNamespace(
        Config=lambda *args: (_ for _ in ()).throw(
            SecretBearingSdkError(f"invalid access_token={secret}")
        ),
        QuoteContext=lambda config: config,
    )
    monkeypatch.setattr(loader_mod, "_require_longbridge", lambda: fake_openapi)
    monkeypatch.setattr(loader_mod, "loader_cache_get", lambda **kwargs: None)

    with pytest.raises(NoAvailableSourceError) as exc_info:
        _configured_loader().fetch(["AAPL"], "2026-01-01", "2026-01-02")

    assert str(exc_info.value) == "Longbridge SDK initialization failed."
    assert secret not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


# --------------------------------------------------------------------------- #
# Call-counter / spy tests: _require_longbridge must never be reached in
# both is_available and fetch when credentials are partial or conflicting.
# --------------------------------------------------------------------------- #


def test_partial_credentials_never_call_require_longbridge(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """is_available and fetch both exit before calling _require_longbridge."""
    call_count = 0

    def counting_require():
        nonlocal call_count
        call_count += 1
        raise AssertionError("_require_longbridge must not be called")

    secrets = {
        "app_key": "spy-partial-env-key-e1f2",
    }
    monkeypatch.setenv("LONGBRIDGE_APP_KEY", secrets["app_key"])
    monkeypatch.delenv("LONGBRIDGE_APP_SECRET", raising=False)
    monkeypatch.delenv("LONGBRIDGE_ACCESS_TOKEN", raising=False)
    (tmp_path / "longbridge.json").write_text(
        json.dumps(
            {
                "app_key": "spy-partial-file-key-a3b4",
                "app_secret": "spy-partial-file-secret-c5d6",
                "access_token": "spy-partial-file-token-e7f8",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(lb_credentials, "get_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(loader_mod, "_require_longbridge", counting_require)

    loader = loader_mod.LongbridgeLoader()
    assert loader.is_available() is False
    with pytest.raises(NoAvailableSourceError):
        loader.fetch(["AAPL"], "2026-01-01", "2026-01-02")

    assert call_count == 0


def test_conflict_credentials_never_call_require_longbridge(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """is_available and fetch both exit before calling _require_longbridge."""
    call_count = 0

    def counting_require():
        nonlocal call_count
        call_count += 1
        raise AssertionError("_require_longbridge must not be called")

    env = {
        "app_key": "spy-conflict-env-key-g9h0",
        "app_secret": "spy-conflict-env-secret-i1j2",
        "access_token": "spy-conflict-env-token-k3l4",
    }
    file = {
        "app_key": "spy-conflict-file-key-m5n6",
        "app_secret": "spy-conflict-file-secret-o7p8",
        "access_token": "spy-conflict-file-token-q9r0",
    }
    monkeypatch.setenv("LONGBRIDGE_APP_KEY", env["app_key"])
    monkeypatch.setenv("LONGBRIDGE_APP_SECRET", env["app_secret"])
    monkeypatch.setenv("LONGBRIDGE_ACCESS_TOKEN", env["access_token"])
    (tmp_path / "longbridge.json").write_text(json.dumps(file), encoding="utf-8")
    monkeypatch.setattr(lb_credentials, "get_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(loader_mod, "_require_longbridge", counting_require)

    loader = loader_mod.LongbridgeLoader()
    assert loader.is_available() is False
    with pytest.raises(NoAvailableSourceError):
        loader.fetch(["AAPL"], "2026-01-01", "2026-01-02")

    assert call_count == 0
