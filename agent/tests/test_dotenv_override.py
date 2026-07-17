"""Regression coverage for project dotenv precedence."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import src.providers.llm as llm
from src.config.accessor import reset_env_config
from src.config.env_schema import EnvConfig


@pytest.fixture
def fresh_dotenv(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm, "_dotenv_loaded", False)


def test_dotenv_override_defaults_to_project_env() -> None:
    assert EnvConfig().llm.vibe_trading_dotenv_override is True


def test_dotenv_override_can_preserve_shell_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fresh_dotenv: None,
) -> None:
    env = tmp_path / ".env"
    env.write_text("VT_TEST_TOKEN=from_dotenv\n", encoding="utf-8")
    monkeypatch.setattr(llm, "_ENV_CANDIDATES", [env])
    monkeypatch.setattr(llm, "_ENV_LABELS", ("<TEST_SLOT>",))
    monkeypatch.setenv("VT_TEST_TOKEN", "from_shell")
    monkeypatch.setenv("VIBE_TRADING_DOTENV_OVERRIDE", "0")
    reset_env_config()
    try:
        llm._ensure_dotenv()
        assert os.environ["VT_TEST_TOKEN"] == "from_shell"
    finally:
        reset_env_config()


def test_dotenv_override_replaces_stale_shell_value_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fresh_dotenv: None,
) -> None:
    env = tmp_path / ".env"
    env.write_text("VT_TEST_TOKEN=from_dotenv\n", encoding="utf-8")
    monkeypatch.setattr(llm, "_ENV_CANDIDATES", [env])
    monkeypatch.setattr(llm, "_ENV_LABELS", ("<TEST_SLOT>",))
    monkeypatch.setenv("VT_TEST_TOKEN", "from_shell")
    monkeypatch.delenv("VIBE_TRADING_DOTENV_OVERRIDE", raising=False)
    reset_env_config()
    try:
        llm._ensure_dotenv()
        assert os.environ["VT_TEST_TOKEN"] == "from_dotenv"
    finally:
        reset_env_config()
