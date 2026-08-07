"""Phase 2 refresh-surface contract for ``refresh_strategy_evidence`` (#969).

Covers the agent tool in ``src.tools.strategy_discovery_tool``: the strict
envelope on the ok path (fixture run dirs in the REAL engine artifact schema,
reused from ``test_strategy_discovery_harness`` — no second schema), the
exactly-one-source rule, both manifest shapes (object with ``runs`` + bare
array), manifest failure envelopes, per-entry validation, and the D7 path
containment rule (offending entries skipped with the stable
``path-outside-allowed-roots:`` token while the rest still process).

The store is isolated per test through the
``VIBE_TRADING_STRATEGY_DISCOVERY_DB_PATH`` env override (the conftest
resets the cached EnvConfig around every test); the runtime runs root is
redirected via ``VIBE_TRADING_HOME``.

Atomicity failure-injection is NOT duplicated here — Unit 1 pins it in
``test_strategy_discovery_hard_gates.py::TestAtomicRebuild``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

try:
    from src.strategy_discovery.evidence_store import EvidenceStore
    from src.tools import strategy_discovery_tool as sdt

    from tests.test_strategy_discovery_harness import (
        ALL_TRADE_DAYS,
        _write_run_fixture,
    )

    REFRESH_AVAILABLE = True
except ImportError:
    EvidenceStore = None
    sdt = None
    REFRESH_AVAILABLE = False

requires_refresh = pytest.mark.skipif(
    not REFRESH_AVAILABLE,
    reason="waiting on refresh_strategy_evidence tool (issue #969 Phase 2)",
)

TOOL_NAME = "refresh_strategy_evidence"
SKIP_TOKEN = "path-outside-allowed-roots"


def _strict_json_loads(text: str) -> dict:
    def _reject(constant):
        raise ValueError(f"non-strict constant {constant!r} in tool output")

    payload = json.loads(text, parse_constant=_reject)
    assert isinstance(
        payload, dict
    ), f"tool output must be a JSON object, got {type(payload)}"
    return payload


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the runtime root and the evidence DB into tmp_path."""
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    monkeypatch.setenv(
        "VIBE_TRADING_STRATEGY_DISCOVERY_DB_PATH", str(tmp_path / "evidence.db")
    )
    monkeypatch.delenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", raising=False)
    return tmp_path


@pytest.fixture
def runs_root(isolated_home: Path) -> Path:
    """The runtime runs root (inside the allowed roots by construction)."""
    root = isolated_home / "runs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _tool() -> "sdt.RefreshStrategyEvidenceTool":
    return sdt.RefreshStrategyEvidenceTool()


def _write_manifest(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _store() -> "EvidenceStore":
    return EvidenceStore()


@requires_refresh
class TestToolIdentity:
    def test_tool_metadata(self) -> None:
        tool = _tool()
        assert tool.name == TOOL_NAME
        assert tool.is_readonly is False, "the refresh tool is a WRITE tool"
        assert tool.repeatable is True
        assert tool.parameters["properties"].keys() == {"manifest_path", "runs"}
        assert tool.parameters.get("required", []) == []


@requires_refresh
class TestEnvelopeOkPath:
    def test_manifest_object_form(self, runs_root: Path) -> None:
        run_dir = _write_run_fixture(runs_root)
        manifest = _write_manifest(
            runs_root.parent / "manifest.json",
            {"runs": [{"strategy_id": "sdm:refreshed", "run_dir": str(run_dir)}]},
        )

        payload = _strict_json_loads(_tool().execute(manifest_path=str(manifest)))

        assert payload["status"] == "ok"
        assert payload["runs"] == 1
        assert payload["strategies"] == 1
        assert payload["rows"] > 0
        assert payload["skipped"] == []
        rows = _store().get_rows()
        assert rows, "evidence rows must land in the default store"
        assert {row.strategy_id for row in rows} == {"sdm:refreshed"}
        assert sum(row.trades_in_regime for row in rows) == len(ALL_TRADE_DAYS)

    def test_manifest_bare_array_form(self, runs_root: Path) -> None:
        run_dir = _write_run_fixture(runs_root)
        manifest = _write_manifest(
            runs_root.parent / "manifest.json",
            [{"strategy_id": "sdm:bare_array", "run_dir": str(run_dir)}],
        )

        payload = _strict_json_loads(_tool().execute(manifest_path=str(manifest)))

        assert payload["status"] == "ok"
        assert payload["strategies"] == 1
        assert payload["rows"] > 0

    def test_inline_runs_parameter(self, runs_root: Path) -> None:
        run_dir = _write_run_fixture(runs_root)

        payload = _strict_json_loads(
            _tool().execute(
                runs=[{"strategy_id": "sdm:inline", "run_dir": str(run_dir)}]
            )
        )

        assert payload["status"] == "ok"
        assert payload["strategies"] == 1
        assert payload["rows"] > 0
        assert {row.strategy_id for row in _store().get_rows()} == {"sdm:inline"}

    def test_position_size_is_forwarded(self, runs_root: Path) -> None:
        run_dir = _write_run_fixture(runs_root)

        payload = _strict_json_loads(
            _tool().execute(
                runs=[
                    {
                        "strategy_id": "sdm:sized",
                        "run_dir": str(run_dir),
                        "position_size": 2500.0,
                    }
                ]
            )
        )

        assert payload["status"] == "ok"
        rows = _store().get_rows()
        assert rows
        assert all(row.position_size == 2500.0 for row in rows)

    def test_gated_run_reports_hard_gate_token(self, runs_root: Path) -> None:
        run_dir = _write_run_fixture(runs_root)
        (run_dir / "state.json").unlink()

        payload = _strict_json_loads(
            _tool().execute(
                runs=[{"strategy_id": "sdm:gated", "run_dir": str(run_dir)}]
            )
        )

        assert payload["status"] == "ok"
        assert payload["rows"] == 0
        assert len(payload["skipped"]) == 1
        assert payload["skipped"][0]["reason"].startswith("hard-gate:")


@requires_refresh
class TestExactlyOneSource:
    def test_neither_parameter_is_an_error(self) -> None:
        payload = _strict_json_loads(_tool().execute())
        assert payload["status"] == "error"
        assert "exactly one" in payload["error"]

    def test_both_parameters_is_an_error(self, runs_root: Path) -> None:
        manifest = _write_manifest(runs_root.parent / "manifest.json", {"runs": []})
        payload = _strict_json_loads(
            _tool().execute(manifest_path=str(manifest), runs=[])
        )
        assert payload["status"] == "error"
        assert "exactly one" in payload["error"]

    def test_runs_must_be_an_array(self) -> None:
        payload = _strict_json_loads(_tool().execute(runs={"strategy_id": "x"}))
        assert payload["status"] == "error"
        assert "array" in payload["error"]

    def test_overlong_manifest_path_is_rejected(self) -> None:
        payload = _strict_json_loads(_tool().execute(manifest_path="m" * 501))
        assert payload["status"] == "error"
        assert "too long" in payload["error"].lower()


@requires_refresh
class TestManifestFailures:
    def test_missing_manifest_file(self, isolated_home: Path) -> None:
        payload = _strict_json_loads(
            _tool().execute(manifest_path=str(isolated_home / "absent.json"))
        )
        assert payload["status"] == "error"
        assert "missing or unreadable" in payload["error"]

    def test_invalid_json_manifest(self, isolated_home: Path) -> None:
        bad = isolated_home / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        payload = _strict_json_loads(_tool().execute(manifest_path=str(bad)))
        assert payload["status"] == "error"
        assert "not valid JSON" in payload["error"]

    @pytest.mark.parametrize(
        "payload_factory",
        [
            lambda: {"strategies": []},  # object without a runs array
            lambda: {"runs": "not-a-list"},  # runs present but wrong type
            lambda: "just a string",  # neither object nor array
        ],
        ids=["no-runs-key", "runs-not-list", "bare-string"],
    )
    def test_wrong_manifest_shape(self, isolated_home: Path, payload_factory) -> None:
        manifest = _write_manifest(isolated_home / "shape.json", payload_factory())
        payload = _strict_json_loads(_tool().execute(manifest_path=str(manifest)))
        assert payload["status"] == "error"
        assert (
            "'runs' array" in payload["error"] or "bare JSON array" in payload["error"]
        )


@requires_refresh
class TestPathContainment:
    def test_outside_entry_skipped_with_stable_token_rest_process(
        self, runs_root: Path, isolated_home: Path
    ) -> None:
        inside = _write_run_fixture(runs_root)
        outside = _write_run_fixture(isolated_home / "elsewhere")

        payload = _strict_json_loads(
            _tool().execute(
                runs=[
                    {"strategy_id": "sdm:outside", "run_dir": str(outside)},
                    {"strategy_id": "sdm:inside", "run_dir": str(inside)},
                ]
            )
        )

        assert payload["status"] == "ok"
        assert payload["runs"] == 2
        assert payload["strategies"] == 1, "the inside entry still processes"
        assert payload["rows"] > 0
        assert {row.strategy_id for row in _store().get_rows()} == {"sdm:inside"}
        assert len(payload["skipped"]) == 1
        skip = payload["skipped"][0]
        assert skip["run_dir"] == str(outside)
        assert skip["reason"].startswith(f"{SKIP_TOKEN}:")
        assert str(outside) in skip["reason"]

    def test_configured_allowed_run_root_is_accepted(
        self, isolated_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        extra_root = tmp_path / "extra-roots" / "research"
        extra_root.mkdir(parents=True)
        run_dir = _write_run_fixture(extra_root)
        monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(extra_root))

        payload = _strict_json_loads(
            _tool().execute(
                runs=[{"strategy_id": "sdm:extra_root", "run_dir": str(run_dir)}]
            )
        )

        assert payload["status"] == "ok"
        assert payload["skipped"] == []
        assert payload["rows"] > 0

    def test_symlink_escape_is_contained(
        self, runs_root: Path, isolated_home: Path
    ) -> None:
        outside = _write_run_fixture(isolated_home / "elsewhere")
        link = runs_root / "sneaky_link"
        try:
            link.symlink_to(outside)
        except OSError:
            pytest.skip("symlinks unavailable on this platform")

        payload = _strict_json_loads(
            _tool().execute(runs=[{"strategy_id": "sdm:sneaky", "run_dir": str(link)}])
        )

        assert payload["rows"] == 0
        assert payload["skipped"][0]["reason"].startswith(f"{SKIP_TOKEN}:")


@requires_refresh
class TestEntryValidation:
    def test_invalid_entries_skipped_with_reasons(self, runs_root: Path) -> None:
        valid = _write_run_fixture(runs_root)
        payload = _strict_json_loads(
            _tool().execute(
                runs=[
                    {"run_dir": str(valid)},  # missing strategy_id
                    {"strategy_id": "   ", "run_dir": str(valid)},  # blank id
                    {"strategy_id": "a" * 501, "run_dir": str(valid)},  # too long
                    {"strategy_id": "sdm:no_dir"},  # missing run_dir
                    "not-an-object",
                    {
                        "strategy_id": "sdm:valid",
                        "run_dir": str(valid),
                    },
                ]
            )
        )

        assert payload["status"] == "ok"
        assert payload["runs"] == 6
        assert payload["strategies"] == 1
        assert payload["rows"] > 0
        reasons = [entry["reason"] for entry in payload["skipped"]]
        assert len(reasons) == 5
        assert reasons.count("missing strategy_id or run_dir") == 3
        assert any("too long" in reason for reason in reasons)
        assert any("not an object" in reason for reason in reasons)

    def test_all_entries_invalid_leaves_store_untouched(
        self, runs_root: Path, isolated_home: Path
    ) -> None:
        # A rebuild is a full statement of the evidence — but entries refused
        # at the validation boundary never reach the rebuild, so a fully
        # invalid manifest must NOT clear the existing cache.
        from src.strategy_discovery.models import EvidenceRow

        store = _store()
        store.upsert_rows(
            [
                EvidenceRow(
                    strategy_id="alpha_zoo:prior",
                    regime="bear_market",
                    trades_in_regime=12,
                    date_ranges=("2018-01 to 2018-12",),
                    last_verified="2026-08-01",
                )
            ]
        )
        outside = _write_run_fixture(isolated_home / "elsewhere")

        payload = _strict_json_loads(
            _tool().execute(
                runs=[{"strategy_id": "sdm:outside", "run_dir": str(outside)}]
            )
        )

        assert payload["status"] == "ok"
        assert payload["rows"] == 0
        assert len(payload["skipped"]) == 1
        assert _store().row_count() == 1, "prior rows survive an all-invalid refresh"


@requires_refresh
class TestRegistryDiscovery:
    def test_auto_discovered_and_executable_through_registry(
        self, runs_root: Path
    ) -> None:
        from src.tools import build_registry

        registry = build_registry()
        assert TOOL_NAME in registry.tool_names
        tool = registry.get(TOOL_NAME)
        assert tool is not None
        assert tool.is_readonly is False

        run_dir = _write_run_fixture(runs_root)
        result = registry.execute(
            TOOL_NAME,
            {"runs": [{"strategy_id": "sdm:via_registry", "run_dir": str(run_dir)}]},
        )
        payload = _strict_json_loads(result)
        assert payload["status"] == "ok"
        assert payload["rows"] > 0
