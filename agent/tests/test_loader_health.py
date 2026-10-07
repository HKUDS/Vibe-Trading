"""Offline contracts for the separately scheduled public-source canary."""

from datetime import date, timedelta
import json
import logging
import subprocess

import pandas as pd
import pytest
import requests

from backtest import loader_health as health

TODAY = date(2026, 9, 28)


@pytest.fixture(autouse=True)
def _registered_loaders():
    """Register the real loaders before a test stubs one of them.

    Registration fires on first use and assigns into ``LOADER_REGISTRY``
    unconditionally, so a stub installed for a real source before that first
    use is silently replaced by the real loader and the test reaches the live
    network instead of the stub.
    """
    from backtest.loaders.registry import _ensure_registered

    _ensure_registered()


def frame(age=0):
    return pd.DataFrame(
        {"open": [10.0], "high": [12.0], "low": [9.0], "close": [11.0], "volume": [100.0]},
        index=pd.DatetimeIndex([TODAY - timedelta(days=age)]),
    )


def test_catalog_covers_every_public_network_loader():
    assert health.coverage_errors() == []


def test_new_loader_cannot_silently_disappear(monkeypatch):
    from backtest.loaders.registry import LOADER_REGISTRY

    monkeypatch.setitem(LOADER_REGISTRY, "new_public_source", type("Loader", (), {"requires_auth": False}))
    assert "unmapped:new_public_source" in health.coverage_errors()


@pytest.mark.parametrize("age,status", [(0, "healthy"), (14, "healthy"), (15, "stale"), (-1, "invalid")])
def test_freshness_bounds(age, status):
    assert health.check_frame(frame(age), TODAY)["status"] == status


@pytest.mark.parametrize(
    "change,reason",
    [
        (lambda f: f.iloc[:0], "empty_frame"),
        (lambda f: f.drop(columns="close"), "schema"),
        (lambda f: f.assign(close="11"), "numeric_columns"),
        (lambda f: f.assign(close=float("nan")), "nonfinite_values"),
        (lambda f: f.assign(high=5), "ohlc_order"),
        (lambda f: f.assign(volume=-1), "invalid_prices_or_volume"),
        (lambda f: f.reset_index(drop=True), "datetime_index"),
        (lambda f: pd.concat([f, f]), "index_order"),
    ],
)
def test_normalized_contract(change, reason):
    assert health.check_frame(change(frame()), TODAY)["reason"] == reason


def test_no_keys_operator_home_or_cache_in_child(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_TOKEN", "private-test-value")
    monkeypatch.setenv("OPENAI_API_KEY", "private-test-value")
    monkeypatch.setenv("VIBE_TRADING_DATA_CACHE", "1")
    monkeypatch.setenv("PYTHONPATH", "/operator/overrides")
    env = health.child_environment(str(tmp_path))
    assert "GITHUB_TOKEN" not in env and "OPENAI_API_KEY" not in env
    assert env["HOME"] == env["VIBE_TRADING_HOME"] == str(tmp_path)
    assert env["VIBE_TRADING_DATA_CACHE"] == "0"
    assert env["PYTHONPATH"] != "/operator/overrides"


def test_unavailable_endpoint_is_not_skipped(monkeypatch):
    from backtest.loaders.registry import LOADER_REGISTRY

    monkeypatch.setitem(
        LOADER_REGISTRY,
        "tencent",
        type(
            "Loader",
            (),
            {
                "requires_auth": False,
                "is_available": lambda self: False,
            },
        ),
    )
    assert health.probe("tencent", TODAY) == {
        "status": "unavailable",
        "reason": "availability_probe_failed",
        "attempts": 2,
    }


def test_network_error_is_sanitized_and_retried(monkeypatch):
    from backtest.loaders.registry import LOADER_REGISTRY

    calls = []

    def fetch(self, *args, **kwargs):
        calls.append(args)
        logging.getLogger("backtest.loaders.tencent_loader").warning("GET https://secret:token@internal.example failed")
        raise requests.exceptions.ConnectionError("https://secret:token@internal.example")

    monkeypatch.setitem(
        LOADER_REGISTRY,
        "tencent",
        type(
            "Loader",
            (),
            {
                "requires_auth": False,
                "is_available": lambda self: True,
                "fetch": fetch,
            },
        ),
    )
    result = health.probe("tencent", TODAY)
    assert result["status"] == "unreachable" and len(calls) == 2
    assert result["evidence"] == ["GET <url> failed"]
    assert "secret" not in json.dumps(result)


def test_child_deadline_is_failure(monkeypatch):
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 0.1
        raise subprocess.TimeoutExpired(args[0], 0.1)

    monkeypatch.setattr(health.subprocess, "run", timeout)
    assert health.run_source("tencent", TODAY, 0.1)["status"] == "timeout"


def test_real_child_is_killed_at_deadline():
    assert health.run_source("tencent", TODAY, 0.001)["status"] == "timeout"


@pytest.mark.parametrize(
    "status,coverage,exit_code",
    [
        ("healthy", [], 0),
        ("unavailable", [], 1),
        ("missing_dependency", [], 1),
        ("healthy", ["unmapped:new"], 1),
    ],
)
def test_lane_exit_and_report(monkeypatch, tmp_path, status, coverage, exit_code):
    output = tmp_path / "report.json"
    monkeypatch.setattr(health.sys, "argv", ["health", "--output", str(output)])
    monkeypatch.setattr(health, "CANARY_SYMBOLS", {"test": "TEST"})
    monkeypatch.setattr(health, "coverage_errors", lambda: coverage)
    monkeypatch.setattr(
        health, "run_source", lambda *args: {"source": "test", "status": status, "evidence": ["a loader warning"]}
    )
    assert health.main() == exit_code
    report = json.loads(output.read_text())
    assert report["coverage_errors"] == coverage
    assert report["sources"] == [{"source": "test", "status": status, "evidence": ["a loader warning"]}]


@pytest.mark.parametrize(
    "payload,status",
    [
        ('{"status":"healthy","rows":2}', "healthy"),
        ('{"status":"stale","reason":"last_bar_too_old"}', "stale"),
        ('{"status":"unavailable","reason":"availability_probe_failed"}', "unavailable"),
        ('{"status":"unreachable","reason":"network_error"}', "unreachable"),
        ('{"status":"missing_dependency","reason":"install_canary_dependencies"}', "missing_dependency"),
        ('{"status":"error","reason":"fetch_failed"}', "error"),
        ("not json", "error"),
        ("[]", "error"),
        ('{"status":"skip"}', "error"),
        (None, "error"),
    ],
)
def test_child_report_handling(monkeypatch, payload, status):
    from pathlib import Path

    def child(command, **kwargs):
        if payload is not None:
            Path(command[command.index("--output") + 1]).write_text(payload)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(health.subprocess, "run", child)
    assert health.run_source("tencent", TODAY, 1)["status"] == status


def test_second_attempt_recovers_without_fallback(monkeypatch):
    from backtest.loaders.registry import LOADER_REGISTRY

    calls = []

    def fetch(self, codes, start, end, *, interval):
        calls.append(codes)
        if len(calls) == 1:
            return {}
        return {"601398.SH": frame()}

    monkeypatch.setitem(
        LOADER_REGISTRY,
        "tencent",
        type(
            "Loader",
            (),
            {
                "requires_auth": False,
                "is_available": lambda self: True,
                "fetch": fetch,
            },
        ),
    )
    result = health.probe("tencent", TODAY)
    assert result["status"] == "healthy" and result["attempts"] == 2
    assert calls == [["601398.SH"], ["601398.SH"]]


def _stub_loader(monkeypatch, source, *, fetch):
    from backtest.loaders.registry import LOADER_REGISTRY

    monkeypatch.setitem(
        LOADER_REGISTRY,
        source,
        type("Loader", (), {"requires_auth": False, "is_available": lambda self: True, "fetch": fetch}),
    )


def test_empty_frame_carries_the_loaders_own_reason(monkeypatch):
    """A blocked source must not report as a bare broken loader (#1621 item 2)."""

    def fetch(self, codes, start, end, *, interval):
        logging.getLogger("backtest.loaders.stooq_loader").warning(
            "stooq is serving an anti-bot challenge page instead of CSV data; "
            "treating it as unavailable for the rest of this process."
        )
        return {}

    _stub_loader(monkeypatch, "stooq", fetch=fetch)
    result = health.probe("stooq", TODAY)
    assert result["status"] == "invalid" and result["reason"] == "empty_frame"
    assert result["evidence"] == [
        "stooq is serving an anti-bot challenge page instead of CSV data; "
        "treating it as unavailable for the rest of this process."
    ]


def test_loader_evidence_is_sanitized(monkeypatch):
    def fetch(self, codes, start, end, *, interval):
        logging.getLogger("backtest.loaders.stooq_loader").warning(
            "GET https://api.example.com/v3/klines failed for /home/runner/.cache/vibe "
            "with api_key=abc123 from \\\\fileserver\\share"
        )
        return {}

    _stub_loader(monkeypatch, "stooq", fetch=fetch)
    result = health.probe("stooq", TODAY)
    report = json.dumps(result)
    assert "evidence" not in result
    assert (
        "example.com" not in report
        and "abc123" not in report
        and "/home/" not in report
    )


def test_a_loader_that_logs_then_raises_still_reports_its_reason(monkeypatch):
    """The generic handler path must keep the row (and the reason) alive."""

    def fetch(self, codes, start, end, *, interval):
        logging.getLogger("backtest.loaders.tencent_loader").warning("tencent returned an unparsable body")
        raise ValueError("boom")

    _stub_loader(monkeypatch, "tencent", fetch=fetch)
    result = health.probe("tencent", TODAY)
    assert result["status"] == "error" and result["reason"] == "fetch_failed" and result["attempts"] == 2
    assert result["evidence"] == ["tencent returned an unparsable body"]


def test_sanitizer_keeps_market_slashes_but_omits_filesystem_paths():
    """Market symbols remain useful; filesystem paths are omitted, never partially redacted."""
    assert (
        health.sanitize_evidence(
            "CCXT failed for BTC-USDT: binance does not have market symbol BTC/USDT"
        )
        == "CCXT failed for BTC-USDT: binance does not have market symbol BTC<path>"
    )
    assert health.sanitize_evidence("cache file /tmp missing, refetching") is None
    assert health.sanitize_evidence("retry 2/3 failed") == "retry 2<path> failed"


def test_sanitizer_redacts_header_and_token_shaped_credentials():
    assert (
        health.sanitize_evidence("request rejected, Authorization: Bearer ghp_abcdef123456")
        == "request rejected, Authorization: <redacted>"
    )
    assert health.sanitize_evidence("x-api-key: abc123 rejected") == "<redacted> rejected"
    assert health.sanitize_evidence("api_key=abc123 in query") == "<redacted> in query"
    assert health.sanitize_evidence("token sk-abcdefghijklmnop rejected") == "token <redacted> rejected"


@pytest.mark.parametrize(
    "message,expected",
    [
        # The scheme arm used to stop at the label and leave its value in the
        # report artifact CI uploads.
        ("Authorization: Bearer token: S3CR3TVALUE", "Authorization: <redacted>"),
        ("Bearer password: hunter2", "<redacted>"),
    ],
)
def test_sanitizer_redacts_a_schemes_labelled_value(message, expected):
    assert health.sanitize_evidence(message) == expected


def test_sanitizer_does_not_strand_a_scheme_behind_a_keyword_label():
    """A keyword chain must not hide the scheme's value from the scheme arm."""
    cleaned = health.sanitize_evidence("password: token: Bearer S3CR3TVALUE")
    assert cleaned is not None and "S3CR3TVALUE" not in cleaned


def test_sanitizer_truncates_and_collapses_whitespace():
    assert len(health.sanitize_evidence("x" * 500)) == health.EVIDENCE_TEXT_LIMIT
    assert health.sanitize_evidence("two\n\tlines   here ") == "two lines here"


def test_sanitizer_drops_a_body_it_cannot_classify():
    assert health.sanitize_evidence(r"retry via proxy \ gateway") is None
    assert health.sanitize_evidence("fetch failed at http://") is None
    assert health.sanitize_evidence("   ") is None


def test_evidence_is_capped_and_deduplicated(monkeypatch):
    def fetch(self, codes, start, end, *, interval):
        logger = logging.getLogger("backtest.loaders.stooq_loader")
        for index in range(5):
            logger.warning("attempt %s failed", index)
        logger.warning("attempt 0 failed")
        return {}

    _stub_loader(monkeypatch, "stooq", fetch=fetch)
    evidence = health.probe("stooq", TODAY)["evidence"]
    assert evidence == ["attempt 0 failed", "attempt 1 failed", "attempt 2 failed"]
    assert len(evidence) == health.MAX_EVIDENCE


def test_healthy_probe_carries_no_evidence_even_when_the_loader_warns(monkeypatch):
    """A warning during a fetch that then succeeds is not a reason for the row."""

    def fetch(self, codes, start, end, *, interval):
        logging.getLogger("backtest.loaders.ccxt_loader").warning(
            "Unknown CCXT exchange binance, falling back to binance"
        )
        return {codes[0]: frame()}

    _stub_loader(monkeypatch, "stooq", fetch=fetch)
    result = health.probe("stooq", TODAY)
    assert result["status"] == "healthy" and result["attempts"] == 1
    assert "evidence" not in result


def test_another_loggers_warning_is_not_evidence(monkeypatch):
    """Guards the attach point: only this package's loaders may become evidence.

    A logger outside the `backtest.loaders` hierarchy bypasses the handler
    entirely, so this also fails if the handler is ever moved to the root
    logger without a working name filter.
    """

    def fetch(self, codes, start, end, *, interval):
        logging.getLogger("urllib3.connectionpool").warning("Retrying after connection break")
        return {}

    _stub_loader(monkeypatch, "stooq", fetch=fetch)
    assert "evidence" not in health.probe("stooq", TODAY)


def test_evidence_survives_the_parent_report(monkeypatch):
    """The parent copies the child's fields through, `evidence` included."""
    from pathlib import Path

    payload = (
        '{"status":"invalid","reason":"empty_frame","attempts":2,'
        '"evidence":["stooq is serving an anti-bot challenge page instead of CSV data"]}'
    )

    def child(command, **kwargs):
        Path(command[command.index("--output") + 1]).write_text(payload)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(health.subprocess, "run", child)
    assert health.run_source("stooq", TODAY, 1) == {
        "source": "stooq",
        "symbol": "AAPL.US",
        "status": "invalid",
        "reason": "empty_frame",
        "attempts": 2,
        "evidence": ["stooq is serving an anti-bot challenge page instead of CSV data"],
    }


@pytest.mark.parametrize(
    "warning",
    [
        '{"api_key": "synthetic-canary-credential"}',
        "{'token': 'synthetic-canary-credential'}",
        'password="synthetic canary credential" rejected',
        "password='synthetic canary credential' rejected",
        "Authorization: Basic synthetic-canary-credential",
        'password="synthetic canary credential',
        "password='synthetic canary credential",
        '{"api_key": "synthetic canary credential',
        "password=synthetic,canary-credential",
        "password=synthetic;canary-credential",
        "password=synthetic}canary-credential",
    ],
)
def test_sanitizer_handles_structured_and_quoted_credentials(warning):
    sanitized = health.sanitize_evidence(warning)
    assert sanitized is not None
    assert "synthetic" not in sanitized
    assert "credential" not in sanitized
    assert "<redacted>" in sanitized


@pytest.mark.parametrize(
    "path",
    [
        "/Users/Example User/private-key.pem",
        "/tmp/[private].pem",
        '"/Users/Example User/config.json"',
        r"C:\Users\Example User\config.json",
        r"\\fileserver\private share\config.json",
        "(/Users/Example User/private-key.pem)",
        "path:/Users/Example User/private-key.pem",
        "path[/Users/Example User/private-key.pem]",
        "C:/Users/Example User/private-key.pem",
    ],
)
def test_filesystem_warnings_are_omitted_in_full(path):
    assert health.sanitize_evidence(f"cache file {path} missing") is None


@pytest.mark.parametrize(
    "message",
    [
        '{"api_key": "synthetic-canary-credential"}',
        'password="synthetic canary credential',
        "password=synthetic,canary-credential",
    ],
)
def test_real_tencent_warning_path_redacts_a_structured_exception(monkeypatch, message):
    from backtest.loaders.tencent_loader import DataLoader

    def fetch_one(self, *args, **kwargs):
        raise ValueError(message)

    monkeypatch.setattr(DataLoader, "_fetch_one", fetch_one)
    monkeypatch.setattr(DataLoader, "is_available", lambda self: True)
    from backtest.loaders.registry import LOADER_REGISTRY

    monkeypatch.setitem(LOADER_REGISTRY, "tencent", DataLoader)
    result = health.probe("tencent", TODAY)
    assert result["status"] == "invalid"
    assert result["attempts"] == 2
    assert "synthetic" not in json.dumps(result)
    assert "<redacted>" in result["evidence"][0]
