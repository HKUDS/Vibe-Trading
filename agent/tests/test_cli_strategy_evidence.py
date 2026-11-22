'CLI contract for ``vibe-trading strategy-evidence refresh`` (#969 Phase 2).\n\nDriven through ``cli.commands.dispatch.main`` so the argparse wiring is exercised, not\njust the handler (same invocation style as ``test_playbooks_surface.py``).\nThe refresh runs the SAME core as the agent tool\n(``refresh_strategy_evidence_core`` over the default ``EvidenceStore()``\nresolution) — no second spec-parsing code path.\n\nFixture run dirs use the REAL engine artifact schema, reused from\n``test_strategy_discovery_harness``. The runtime root and the evidence DB are\nredirected into ``tmp_path`` via ``VIBE_TRADING_HOME`` and the\n``VIBE_TRADING_STRATEGY_DISCOVERY_DB_PATH`` override (the conftest resets the\ncached EnvConfig around every test).\n'

from __future__ import annotations

import cli.commands.dispatch as _cmd_dispatch

import json
from pathlib import Path
from typing import List

import pytest

try:
    from src.strategy_discovery.evidence_store import EvidenceStore

    from tests.test_strategy_discovery_harness import (
        ALL_TRADE_DAYS,
        _write_run_fixture,
    )

    CLI_AVAILABLE = True
except ImportError:
    EvidenceStore = None
    CLI_AVAILABLE = False

requires_cli = pytest.mark.skipif(
    not CLI_AVAILABLE,
    reason="waiting on strategy-evidence refresh surface (issue #969 Phase 2)",
)


def _run_cli(argv: List[str]) -> int:
    """Drive the real argparse dispatcher, returning its exit code."""

    return int(_cmd_dispatch.main(argv))


def _flat(text: str) -> str:
    # Rich soft-wraps console output at the terminal width, and the wrap
    # point is runner-dependent (CI hit mid-phrase wraps that broke literal
    # substring assertions); collapse all whitespace before matching.
    return " ".join(text.split())


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the runtime root and the evidence DB into tmp_path."""
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    monkeypatch.setenv(
        "VIBE_TRADING_STRATEGY_DISCOVERY_DB_PATH", str(tmp_path / "evidence.db")
    )
    monkeypatch.delenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", raising=False)
    return tmp_path


@pytest.fixture
def run_dir(home: Path) -> Path:
    """A healthy fixture run inside the runtime runs root (allowed by D7)."""
    runs_root = home / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    return _write_run_fixture(runs_root)


def _write_manifest(home: Path, payload) -> Path:
    manifest = home / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    return manifest


@requires_cli
class TestCliRefreshHappyPath:
    def test_manifest_refresh_writes_rows_and_summarizes(
        self, home: Path, run_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        manifest = _write_manifest(
            home, {"runs": [{"strategy_id": "sdm:cli", "run_dir": str(run_dir)}]}
        )

        code = _run_cli(["strategy-evidence", "refresh", "--manifest", str(manifest)])

        out = capsys.readouterr().out
        assert code == 0
        assert "Refreshed strategy evidence" in _flat(out)
        rows = EvidenceStore().get_rows()
        assert rows, "the CLI refresh must write evidence rows to the default store"
        assert {row.strategy_id for row in rows} == {"sdm:cli"}
        assert sum(row.trades_in_regime for row in rows) == len(ALL_TRADE_DAYS)

    def test_json_flag_emits_machine_readable_envelope(
        self, home: Path, run_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        manifest = _write_manifest(
            home,
            [{"strategy_id": "sdm:cli_json", "run_dir": str(run_dir)}],
        )

        code = _run_cli(
            ["strategy-evidence", "refresh", "--manifest", str(manifest), "--json"]
        )

        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["status"] == "ok"
        assert payload["runs"] == 1
        assert payload["strategies"] == 1
        assert payload["rows"] > 0
        assert payload["skipped"] == []

    def test_skipped_entries_are_reported(
        self, home: Path, run_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        outside = _write_run_fixture(home / "elsewhere")
        manifest = _write_manifest(
            home,
            {
                "runs": [
                    {"strategy_id": "sdm:outside", "run_dir": str(outside)},
                    {"strategy_id": "sdm:inside", "run_dir": str(run_dir)},
                ]
            },
        )

        code = _run_cli(
            ["strategy-evidence", "refresh", "--manifest", str(manifest), "--json"]
        )

        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["strategies"] == 1
        assert len(payload["skipped"]) == 1
        assert payload["skipped"][0]["reason"].startswith("path-outside-allowed-roots:")


@requires_cli
class TestCliRefreshFailures:
    def test_missing_manifest_file_fails_with_clear_error(
        self, home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _run_cli(
            [
                "strategy-evidence",
                "refresh",
                "--manifest",
                str(home / "absent.json"),
            ]
        )

        out = capsys.readouterr().out
        assert code != 0
        assert "missing or unreadable" in _flat(out)

    def test_malformed_manifest_json_fails_with_clear_error(
        self, home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bad = home / "bad.json"
        bad.write_text("{not json", encoding="utf-8")

        code = _run_cli(["strategy-evidence", "refresh", "--manifest", str(bad)])

        out = capsys.readouterr().out
        assert code != 0
        assert "not valid JSON" in _flat(out)

    def test_wrong_manifest_shape_fails_with_clear_error(
        self, home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        manifest = _write_manifest(home, {"strategies": []})

        code = _run_cli(["strategy-evidence", "refresh", "--manifest", str(manifest)])

        out = capsys.readouterr().out
        assert code != 0
        assert "'runs' array" in _flat(out)

    def test_missing_manifest_flag_is_a_usage_error(self, home: Path) -> None:
        code = _run_cli(["strategy-evidence", "refresh"])
        assert code != 0
