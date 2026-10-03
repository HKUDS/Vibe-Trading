"""Tests for fred_macro_tool: availability gating, success + error envelopes.

All HTTP is mocked — no test ever reaches a live FRED endpoint. The tool imports
``throttled_get_json`` from :mod:`backtest.loaders._http` into its own namespace,
so we monkeypatch that name on the ``fred_macro_tool`` module.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Dict

from src.config.limits import TOOL_RESULT_LIMIT, truncate_tool_result
from src.tools import fred_macro_tool
from src.tools.fred_macro_tool import FredMacroTool


def _ok_payload() -> Dict[str, Any]:
    """Three ascending observations with one FRED missing-value gap (".")."""
    return {
        "observations": [
            {"date": "2024-01-01", "value": "100.0"},
            {"date": "2024-02-01", "value": "."},
            {"date": "2024-03-01", "value": "101.5"},
        ]
    }


# ---------------------------------------------------------------------------
# Availability / auth gating
# ---------------------------------------------------------------------------


class TestAvailability:
    """check_available reflects only the env key and never raises."""

    def test_unavailable_without_key(self, monkeypatch):
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        assert FredMacroTool.check_available() is False

    def test_available_with_key(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "tok_123")
        assert FredMacroTool.check_available() is True

    def test_metadata(self):
        assert FredMacroTool.name == "get_macro_series"
        assert FredMacroTool().is_readonly is True


# ---------------------------------------------------------------------------
# execute — success envelope
# ---------------------------------------------------------------------------


class TestExecuteSuccess:
    """execute parses observations into the success envelope."""

    def test_success_envelope(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "tok_123")
        captured: Dict[str, Any] = {}

        def fake_get_json(url, **kwargs):
            captured["url"] = url
            captured["params"] = kwargs.get("params")
            captured["host_key"] = kwargs.get("host_key")
            return _ok_payload()

        monkeypatch.setattr(fred_macro_tool, "throttled_get_json", fake_get_json)

        raw = FredMacroTool().execute(
            series_id="cpiaucsl",
            start_date="2024-01-01",
            end_date="2024-03-31",
        )
        out = json.loads(raw)

        assert out["ok"] is True
        assert out["market"] == "US"
        assert out["source"] == "fred"
        data = out["data"]
        assert data["series_id"] == "CPIAUCSL"  # upper-cased
        assert data["count"] == 3
        obs = data["observations"]
        assert obs[0] == {"date": "2024-01-01", "value": 100.0}
        assert obs[1] == {"date": "2024-02-01", "value": None}  # "." gap -> None
        assert obs[2] == {"date": "2024-03-01", "value": 101.5}

        # Request was routed through the throttled fred host bucket with auth +
        # date window params.
        assert captured["url"] == fred_macro_tool._OBSERVATIONS_URL
        assert captured["host_key"] == "fred"
        assert captured["params"]["series_id"] == "CPIAUCSL"
        assert captured["params"]["api_key"] == "tok_123"
        assert captured["params"]["file_type"] == "json"
        assert captured["params"]["observation_start"] == "2024-01-01"
        assert captured["params"]["observation_end"] == "2024-03-31"

    def test_limit_keeps_most_recent(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "tok_123")
        monkeypatch.setattr(
            fred_macro_tool, "throttled_get_json", lambda url, **kw: _ok_payload()
        )

        out = json.loads(FredMacroTool().execute(series_id="UNRATE", limit=1))
        assert out["data"]["count"] == 1
        assert out["data"]["observations"][0]["date"] == "2024-03-01"

    def test_omitted_dates_send_no_window_params(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "tok_123")
        captured: Dict[str, Any] = {}

        def fake_get_json(url, **kwargs):
            captured["params"] = kwargs.get("params")
            return _ok_payload()

        monkeypatch.setattr(fred_macro_tool, "throttled_get_json", fake_get_json)
        FredMacroTool().execute(series_id="DGS10")
        assert "observation_start" not in captured["params"]
        assert "observation_end" not in captured["params"]


# ---------------------------------------------------------------------------
# execute — error envelopes
# ---------------------------------------------------------------------------


class TestExecuteErrors:
    """execute returns a failure envelope and never raises."""

    def test_missing_key(self, monkeypatch):
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        out = json.loads(FredMacroTool().execute(series_id="CPIAUCSL"))
        assert out["ok"] is False
        assert "FRED_API_KEY" in out["error"]

    def test_missing_series_id(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "tok_123")
        out = json.loads(FredMacroTool().execute(series_id="   "))
        assert out["ok"] is False
        assert "series_id" in out["error"]

    def test_request_failure_becomes_error_envelope(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "tok_123")

        def boom(url, **kwargs):
            raise RuntimeError("429 rate limited")

        monkeypatch.setattr(fred_macro_tool, "throttled_get_json", boom)
        out = json.loads(FredMacroTool().execute(series_id="CPIAUCSL"))
        assert out["ok"] is False
        assert "fred observations request failed" in out["error"]
        assert "429" in out["error"]

    def test_empty_observations_becomes_error_envelope(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "tok_123")
        monkeypatch.setattr(
            fred_macro_tool, "throttled_get_json", lambda url, **kw: {"observations": []}
        )
        out = json.loads(FredMacroTool().execute(series_id="CPIAUCSL"))
        assert out["ok"] is False
        assert "no observations found" in out["error"]


# ---------------------------------------------------------------------------
# Pure-helper parsing tolerance
# ---------------------------------------------------------------------------


class TestParsing:
    """_parse_observations tolerates malformed bodies."""

    def test_non_dict_payload(self):
        assert fred_macro_tool._parse_observations(None) == []
        assert fred_macro_tool._parse_observations("error") == []

    def test_missing_observations_array(self):
        assert fred_macro_tool._parse_observations({"foo": 1}) == []

    def test_row_without_date_dropped(self):
        payload = {"observations": [{"value": "1.0"}, {"date": "2024-01-01", "value": "2.0"}]}
        rows = fred_macro_tool._parse_observations(payload)
        assert rows == [{"date": "2024-01-01", "value": 2.0}]


# ---------------------------------------------------------------------------
# Truncation reporting
# ---------------------------------------------------------------------------


def _long_payload(count: int) -> Dict[str, Any]:
    """``count`` ascending daily observations, oldest first, from 2000-01-01."""
    start = date(2000, 1, 1)
    return {
        "observations": [
            {"date": (start + timedelta(days=i)).isoformat(), "value": str(float(i))}
            for i in range(count)
        ]
    }


class TestTruncationReporting:
    """A capped series reports the cap instead of looking complete."""

    def _run(self, monkeypatch, count: int, **kwargs: Any) -> Dict[str, Any]:
        monkeypatch.setenv("FRED_API_KEY", "tok_123")
        monkeypatch.setattr(
            fred_macro_tool,
            "throttled_get_json",
            lambda url, **kw: _long_payload(count),
        )
        return json.loads(FredMacroTool().execute(series_id="UNRATE", **kwargs))

    def test_cap_is_reported(self, monkeypatch):
        available = 2_500
        out = self._run(monkeypatch, available)
        data = out["data"]

        assert data["count"] == fred_macro_tool._DEFAULT_LIMIT
        assert data["truncated"] is True
        assert data["observations_available"] == available
        assert data["limit"] == fred_macro_tool._DEFAULT_LIMIT
        assert str(fred_macro_tool._DEFAULT_LIMIT) in data["hint"]
        assert str(available) in data["hint"]
        # Below the ceiling the raise clause is offered, not just the window.
        assert "raise limit" in data["hint"]
        # The tail is kept: the window still ends on the newest observation and
        # starts exactly ``limit`` rows before it.
        newest = date(2000, 1, 1) + timedelta(days=available - 1)
        oldest = date(2000, 1, 1) + timedelta(
            days=available - fred_macro_tool._DEFAULT_LIMIT
        )
        assert data["observations"][-1]["date"] == newest.isoformat()
        assert data["observations"][0]["date"] == oldest.isoformat()

    def test_series_that_fits_is_not_marked_truncated(self, monkeypatch):
        out = self._run(monkeypatch, fred_macro_tool._DEFAULT_LIMIT)
        data = out["data"]

        assert data["truncated"] is False
        assert data["observations_available"] == data["count"]
        assert "hint" not in data

    def test_raised_limit_uncaps_the_series(self, monkeypatch):
        out = self._run(monkeypatch, 2_500, limit=2_500)
        data = out["data"]

        assert data["count"] == 2_500
        assert data["truncated"] is False
        # The limit is echoed as asked, not swapped for the default.
        assert data["limit"] == 2_500

    def test_limit_above_the_ceiling_reports_the_ceiling(self, monkeypatch):
        out = self._run(monkeypatch, 6_000, limit=fred_macro_tool._MAX_LIMIT + 5_000)
        data = out["data"]

        assert data["limit"] == fred_macro_tool._MAX_LIMIT
        assert data["count"] == fred_macro_tool._MAX_LIMIT
        assert data["truncated"] is True
        # No dead advice: a limit already at its ceiling cannot be raised.
        assert "raise limit" not in data["hint"]
        assert "narrow the date window" in data["hint"]

    def test_one_row_over_the_cap_is_reported(self, monkeypatch):
        # The boundary: one row over the cap is a cut, not a fit.
        out = self._run(monkeypatch, fred_macro_tool._DEFAULT_LIMIT + 1)
        data = out["data"]

        assert data["count"] == fred_macro_tool._DEFAULT_LIMIT
        assert data["observations_available"] == fred_macro_tool._DEFAULT_LIMIT + 1
        assert data["truncated"] is True

    def test_below_the_limit_the_request_is_echoed(self, monkeypatch):
        # The below-cap regime: the limit is echoed as asked and
        # observations_available is the parsed count, not the cap.
        out = self._run(monkeypatch, 3, limit=3_000)
        data = out["data"]

        assert data["observations_available"] == 3
        assert data["limit"] == 3_000
        assert data["truncated"] is False

    def test_hint_offers_the_raise_clause_below_the_ceiling(self, monkeypatch):
        # A cap below the tool's own ceiling offers both remedies, even when the
        # series is longer than the ceiling itself.
        out = self._run(monkeypatch, 6_000, limit=fred_macro_tool._DEFAULT_LIMIT)
        data = out["data"]

        assert data["observations_available"] == 6_000
        assert "raise limit" in data["hint"]
        assert "narrow the date window" in data["hint"]

    def test_cap_report_survives_the_tool_result_cap(self, monkeypatch):
        # The agent loop trims every tool result to TOOL_RESULT_LIMIT characters.
        # A cap report serialized behind the observation array is cut away in
        # exactly the long-series case it exists for.
        monkeypatch.setenv("FRED_API_KEY", "tok_123")
        monkeypatch.setattr(
            fred_macro_tool,
            "throttled_get_json",
            lambda url, **kw: _long_payload(2_500),
        )
        envelope = FredMacroTool().execute(series_id="UNRATE")
        delivered = truncate_tool_result(envelope)

        assert len(envelope) > TOOL_RESULT_LIMIT
        assert len(delivered) <= TOOL_RESULT_LIMIT
        for field in ("observations_available", "truncated", "limit", "hint"):
            assert f'"{field}"' in delivered
        # The observations are the part that gets cut.
        assert delivered.count('"date"') < fred_macro_tool._DEFAULT_LIMIT
