"""Tests for parsers.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from parsers import csv_to_records, is_path_allowed, load_yaml, read_text


EQUITY_CSV = """\
timestamp,equity
2024-01-01T00:00:00,10000.5
2024-01-02T00:00:00,10250.0
"""

TRADES_CSV = """\
entry_time,exit_time,side,pnl,trades
2024-01-01T08:00:00,2024-01-03T08:00:00,long,250.5,1
"""

YAML_CONTENT = """\
name: S1_test
symbol: BTC
timeframe_signal: 8h
"""


def test_csv_to_records_equity(tmp_path):
    f = tmp_path / "equity.csv"
    f.write_text(EQUITY_CSV, encoding="utf-8")
    rows = csv_to_records(f)
    assert len(rows) == 2
    assert rows[0]["timestamp"] == "2024-01-01T00:00:00"
    assert rows[0]["equity"] == 10000.5


def test_csv_to_records_integer_column(tmp_path):
    f = tmp_path / "trades.csv"
    f.write_text(TRADES_CSV, encoding="utf-8")
    rows = csv_to_records(f)
    assert len(rows) == 1
    assert rows[0]["trades"] == 1
    assert rows[0]["pnl"] == 250.5


def test_csv_to_records_empty_cell(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("a,b\n1,\n", encoding="utf-8")
    rows = csv_to_records(f)
    assert rows[0]["b"] is None


def test_load_yaml(tmp_path):
    f = tmp_path / "strategy.yaml"
    f.write_text(YAML_CONTENT, encoding="utf-8")
    data = load_yaml(f)
    assert data["name"] == "S1_test"
    assert data["symbol"] == "BTC"


def test_load_yaml_empty(tmp_path):
    f = tmp_path / "empty.yaml"
    f.write_text("", encoding="utf-8")
    assert load_yaml(f) == {}


def test_read_text(tmp_path):
    f = tmp_path / "report.md"
    f.write_text("# Title\nContent", encoding="utf-8")
    assert read_text(f).startswith("# Title")


def test_is_path_allowed_inside(tmp_path):
    allowed = tmp_path / "research"
    allowed.mkdir()
    target = allowed / "report.md"
    target.write_text("x", encoding="utf-8")
    assert is_path_allowed(target, tmp_path, ["research"]) is True


def test_is_path_allowed_outside(tmp_path):
    outside = tmp_path / "secret"
    outside.mkdir()
    target = outside / "creds.txt"
    target.write_text("x", encoding="utf-8")
    assert is_path_allowed(target, tmp_path, ["research"]) is False


def test_is_path_allowed_traversal(tmp_path):
    research = tmp_path / "research"
    research.mkdir()
    # Simulated traversal attempt: path resolves outside research/
    evil = research / ".." / "secret.txt"
    (tmp_path / "secret.txt").write_text("x", encoding="utf-8")
    assert is_path_allowed(evil, tmp_path, ["research"]) is False
