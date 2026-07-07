"""Phase 0.5 readiness checks for the IRR-AGL environment contract."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pydantic


REPO_ROOT = Path(__file__).resolve().parents[3]
INVENTORY_SCRIPT = REPO_ROOT / "agent" / "scripts" / "dump_tool_inventory.py"
VALID_MODES = {"off", "observe", "warn", "enforce"}


def _expand_config_path(raw: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(raw))).resolve(strict=False)


def _default_artifact_root() -> Path:
    return (Path.home() / ".vibe-trading" / "artifacts").resolve(strict=False)


def _default_ledger_path() -> Path:
    return (Path.home() / ".vibe-trading" / "research-ledger" / "ledger.sqlite").resolve(strict=False)


def _parse_mode(raw: str | None, *, default: str = "observe") -> str:
    value = (raw or default).strip().lower()
    if value not in VALID_MODES:
        raise ValueError(f"unsupported IRR-AGL mode: {raw!r}")
    return value


def _load_inventory_module():
    spec = importlib.util.spec_from_file_location("dump_tool_inventory", INVENTORY_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pydantic_major_version_is_2() -> None:
    assert int(pydantic.VERSION.split(".", 1)[0]) == 2


def test_scipy_is_importable() -> None:
    scipy_spec = importlib.util.find_spec("scipy")

    assert scipy_spec is not None


def test_default_artifact_root_resolves_under_user_home() -> None:
    artifact_root = _default_artifact_root()

    artifact_root.relative_to(Path.home().resolve(strict=False))
    assert artifact_root.name == "artifacts"
    assert artifact_root.parent.name == ".vibe-trading"


def test_artifact_root_override_can_resolve_outside_user_home(tmp_path: Path, monkeypatch) -> None:
    override = tmp_path / "custom-artifacts"
    monkeypatch.setenv("VIBE_TRADING_ARTIFACT_ROOT", str(override))

    resolved = _expand_config_path(os.environ["VIBE_TRADING_ARTIFACT_ROOT"])

    assert resolved == override.resolve(strict=False)


def test_default_ledger_path_resolves_under_user_home() -> None:
    ledger_path = _default_ledger_path()

    ledger_path.relative_to(Path.home().resolve(strict=False))
    assert ledger_path.name == "ledger.sqlite"
    assert ledger_path.parent.name == "research-ledger"
    assert ledger_path.parent.parent.name == ".vibe-trading"


def test_ledger_path_override_can_resolve_outside_user_home(tmp_path: Path, monkeypatch) -> None:
    override = tmp_path / "research-ledger" / "ledger.sqlite"
    monkeypatch.setenv("VIBE_TRADING_RESEARCH_LEDGER_PATH", str(override))

    resolved = _expand_config_path(os.environ["VIBE_TRADING_RESEARCH_LEDGER_PATH"])

    assert resolved == override.resolve(strict=False)


def test_platform_path_expansion_smoke(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_TEST_HOME", str(tmp_path))
    raw = (
        r"%VIBE_TRADING_TEST_HOME%\artifacts"
        if os.name == "nt"
        else "$VIBE_TRADING_TEST_HOME/artifacts"
    )

    resolved = _expand_config_path(raw)

    assert resolved == (tmp_path / "artifacts").resolve(strict=False)


def test_reliability_and_governance_feature_modes_accept_baseline_values() -> None:
    for env_name in ("VIBE_TRADING_RELIABILITY_MODE", "VIBE_TRADING_GOVERNANCE_MODE"):
        for mode in ("off", "observe", "warn", "enforce"):
            assert _parse_mode(mode) == mode
            assert _parse_mode(mode.upper()) == mode


def test_current_cli_package_is_discoverable() -> None:
    cli_spec = importlib.util.find_spec("cli")
    cli_main_spec = importlib.util.find_spec("cli.main")

    assert cli_spec is not None
    assert cli_main_spec is not None


def test_dump_tool_inventory_output_has_stable_required_fields() -> None:
    module = _load_inventory_module()

    rows = module.build_tool_inventory()

    assert rows
    assert [row["name"] for row in rows] == sorted(row["name"] for row in rows)

    required_fields = {
        "name",
        "module",
        "class_name",
        "is_readonly",
        "repeatable",
        "surface_guess",
        "risk_guess",
    }
    allowed_risks = {"R0_READ", "R1_WRITE_LOCAL", "R2_NETWORK", "R3_TRADE_READ", "R4_TRADE_WRITE", "R5_SHELL"}
    allowed_surfaces = {"filesystem", "live_connector", "local_cli", "local_research", "mcp", "network_data"}

    for row in rows:
        assert required_fields <= row.keys()
        assert isinstance(row["name"], str) and row["name"]
        assert isinstance(row["module"], str) and row["module"]
        assert isinstance(row["class_name"], str) and row["class_name"]
        assert isinstance(row["is_readonly"], bool)
        assert isinstance(row["repeatable"], bool)
        assert row["surface_guess"] in allowed_surfaces
        assert row["risk_guess"] in allowed_risks
