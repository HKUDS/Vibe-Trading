"""Tests for the run-artifact reader tool.

Covers the contract of ``src.tools.run_artifact_tool``: manifest-driven
resolution (friendly aliases with and without a run card, manifest-listed
relative paths, tampered-manifest refusal), traversal rejection, CSV
coercion, offset paging, first+last-pinned downsampling, meta/JSON
envelopes including the manifest sha256, column projection, and the
byte-budget shrink loop.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from src.tools import run_artifact_tool
from src.tools.run_artifact_tool import RunArtifactTool, read_run_artifact

EQUITY_ROWS = 3821
EQUITY_COLUMNS = ["date", "equity", "cash", "drawdown"]
ROWS_ENVELOPE_KEYS = {
    "path",
    "artifact",
    "run_dir",
    "columns",
    "rows",
    "total_rows",
    "offset",
    "returned_rows",
    "truncated",
    "downsample",
    "next_offset",
}


def _expected_row(i: int) -> list:
    """Return the coerced form of equity.csv data row ``i``."""
    return [f"day{i:05d}", 100000 + i * 1.5, 1000 + i, None]


def _make_run(root: Path, rows: int = EQUITY_ROWS) -> Path:
    """Create a run directory carrying a programmatically generated equity.csv."""
    run_dir = root / "run"
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    with (run_dir / "artifacts" / "equity.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(EQUITY_COLUMNS)
        for i in range(rows):
            writer.writerow([f"day{i:05d}", 100000 + i * 1.5, 1000 + i, ""])
    return run_dir


@pytest.fixture()
def run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return a run directory inside a tmp_path-scoped allowed run root."""
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    return _make_run(tmp_path)


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    """Write a small CSV artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _manifest_entry(run_dir: Path, relative: str) -> dict:
    """Build a run_card manifest entry for a file on disk (run_card 1.0 shape)."""
    path = run_dir / relative
    return {
        "path": relative,
        "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _write_run_card(run_dir: Path, entries: list[dict]) -> None:
    """Write a run_card.json carrying the given artifacts manifest."""
    (run_dir / "run_card.json").write_text(
        json.dumps({"schema_version": "1.0", "artifacts": entries}),
        encoding="utf-8",
    )


# --------------------------------------------------------------------------
# (a) downsample
# --------------------------------------------------------------------------


def test_downsample_caps_points_and_pins_first_last(run_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(run_artifact_tool, "_BYTE_BUDGET", 120_000)
    env = json.loads(
        read_run_artifact(str(run_dir), "equity", format="downsample", max_rows=1000)
    )
    assert set(env) == ROWS_ENVELOPE_KEYS
    assert len(env["rows"]) <= 1000
    assert env["rows"][0] == _expected_row(0)
    assert env["rows"][-1] == _expected_row(EQUITY_ROWS - 1)
    ds = env["downsample"]
    assert ds == {
        "stride": 4,
        "pinned_last": True,
        "algorithm": "every-nth",
        "total_rows": EQUITY_ROWS,
    }
    assert env["total_rows"] == EQUITY_ROWS
    assert env["truncated"] is False
    assert env["next_offset"] is None


def test_downsample_returns_everything_when_total_fits(run_dir: Path) -> None:
    _write_csv(run_dir / "artifacts" / "trades.csv", ["a"], [["1"], ["2"], ["3"]])
    env = json.loads(
        read_run_artifact(str(run_dir), "trades", format="downsample", max_rows=100)
    )
    assert env["rows"] == [[1], [2], [3]]
    assert env["downsample"]["stride"] == 1
    assert env["downsample"]["pinned_last"] is True


# --------------------------------------------------------------------------
# (b) offset paging walk
# --------------------------------------------------------------------------


def test_offset_paging_walk_is_lossless(run_dir: Path) -> None:
    gathered: list[list] = []
    offset = 0
    for _ in range(20):  # 3821 / 500 -> 8 pages; hard stop guards a loop bug
        env = json.loads(
            read_run_artifact(str(run_dir), "equity", offset=offset, max_rows=500)
        )
        assert env["offset"] == offset
        gathered.extend(env["rows"])
        if not env["truncated"]:
            assert env["next_offset"] is None
            break
        assert env["next_offset"] == offset + env["returned_rows"]
        offset = env["next_offset"]
    else:
        pytest.fail("paging walk did not terminate")
    assert len(gathered) == EQUITY_ROWS
    assert gathered == [_expected_row(i) for i in range(EQUITY_ROWS)]


def test_offset_past_end_returns_empty_page(run_dir: Path) -> None:
    env = json.loads(
        read_run_artifact(str(run_dir), "equity", offset=EQUITY_ROWS + 100)
    )
    assert env["rows"] == []
    assert env["returned_rows"] == 0
    assert env["truncated"] is False
    assert env["next_offset"] is None


def test_negative_offset_rejected(run_dir: Path) -> None:
    env = json.loads(read_run_artifact(str(run_dir), "equity", offset=-1))
    assert env["ok"] is False


def test_max_rows_clamped(run_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_artifact_tool, "_BYTE_BUDGET", 10_000_000)
    _write_csv(
        run_dir / "artifacts" / "trades.csv", ["n"], [[str(i)] for i in range(5200)]
    )
    tiny = json.loads(read_run_artifact(str(run_dir), "trades", max_rows=0))
    assert tiny["returned_rows"] == 1
    huge = json.loads(read_run_artifact(str(run_dir), "trades", max_rows=10**6))
    assert huge["returned_rows"] == 5000
    assert huge["truncated"] is True
    assert huge["next_offset"] == 5000


# --------------------------------------------------------------------------
# (c) traversal / alias whitelist / manifest gate
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "artifact",
    [
        "../../etc/passwd",
        "/etc/passwd",
        "ohlcv:../../x",
        "ohlcv:/abs",
        "ohlcv:",
        "ohlcv:.hidden",
        "equity.csv",
        "config",
        "",
    ],
)
def test_non_whitelisted_artifacts_rejected(run_dir: Path, artifact: str) -> None:
    env = json.loads(read_run_artifact(str(run_dir), artifact))
    assert env["ok"] is False
    assert set(env) == {"ok", "error", "hint"}
    assert env["hint"]


def test_run_dir_outside_allowed_roots_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    env = json.loads(read_run_artifact(str(tmp_path.parent / "elsewhere"), "equity"))
    assert env["ok"] is False
    assert "run roots" in env["error"]


def test_symlink_escape_rejected(run_dir: Path, tmp_path: Path) -> None:
    secret = tmp_path / "secret.csv"
    secret.write_text("a\n1\n", encoding="utf-8")
    (run_dir / "artifacts" / "trades.csv").symlink_to(secret)
    env = json.loads(read_run_artifact(str(run_dir), "trades"))
    assert env["ok"] is False


# --------------------------------------------------------------------------
# (c2) manifest-driven resolution
# --------------------------------------------------------------------------


def test_manifest_listed_json_artifact_resolves(run_dir: Path) -> None:
    payload = {"walk_forward": {"oos_sharpe": 0.9}}
    (run_dir / "artifacts" / "validation.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    _write_run_card(run_dir, [_manifest_entry(run_dir, "artifacts/validation.json")])
    env = json.loads(read_run_artifact(str(run_dir), "artifacts/validation.json"))
    assert set(env) == {"artifact", "run_dir", "json", "size_bytes"}
    assert env["artifact"] == "artifacts/validation.json"
    assert env["json"] == payload


def test_manifest_listed_csv_artifact_resolves(run_dir: Path) -> None:
    _write_csv(
        run_dir / "artifacts" / "rebalance_notes.csv",
        ["date", "note"],
        [["2024-01-02", "held"]],
    )
    entry = _manifest_entry(run_dir, "artifacts/rebalance_notes.csv")
    _write_run_card(run_dir, [entry])
    env = json.loads(read_run_artifact(str(run_dir), "artifacts/rebalance_notes.csv"))
    assert env["columns"] == ["date", "note"]
    assert env["rows"] == [["2024-01-02", "held"]]
    meta = json.loads(
        read_run_artifact(str(run_dir), "artifacts/rebalance_notes.csv", format="meta")
    )
    assert meta["sha256"] == entry["sha256"]
    assert meta["manifest_size_bytes"] == entry["size_bytes"]


def test_relative_path_not_in_manifest_refused(run_dir: Path) -> None:
    _write_csv(run_dir / "artifacts" / "extra.csv", ["a"], [["1"]])
    _write_run_card(run_dir, [])  # a card exists but lists nothing
    env = json.loads(read_run_artifact(str(run_dir), "artifacts/extra.csv"))
    assert env["ok"] is False
    assert set(env) == {"ok", "error", "hint"}
    assert "manifest" in env["hint"]


@pytest.mark.parametrize("tampered", ["../evil.csv", "..\\evil.csv"])
def test_tampered_manifest_escape_entries_refused(
    run_dir: Path, tmp_path: Path, tampered: str
) -> None:
    (tmp_path / "evil.csv").write_text(
        "a\n1\n", encoding="utf-8"
    )  # the escape target exists
    _write_run_card(
        run_dir, [{"path": tampered, "size_bytes": 4, "sha256": "deadbeef"}]
    )
    env = json.loads(read_run_artifact(str(run_dir), tampered))
    assert env["ok"] is False
    assert set(env) == {"ok", "error", "hint"}


def test_tampered_manifest_absolute_path_refused(run_dir: Path, tmp_path: Path) -> None:
    secret = tmp_path / "secret.csv"
    secret.write_text("a\n1\n", encoding="utf-8")
    _write_run_card(
        run_dir, [{"path": str(secret), "size_bytes": 4, "sha256": "deadbeef"}]
    )
    env = json.loads(read_run_artifact(str(run_dir), str(secret)))
    assert env["ok"] is False


def test_manifest_symlink_entry_escaping_run_dir_refused(
    run_dir: Path, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.csv"
    secret.write_text("a\n1\n", encoding="utf-8")
    (run_dir / "artifacts" / "link.csv").symlink_to(secret)
    _write_run_card(run_dir, [_manifest_entry(run_dir, "artifacts/link.csv")])
    env = json.loads(read_run_artifact(str(run_dir), "artifacts/link.csv"))
    assert env["ok"] is False


def test_manifest_listed_non_served_suffix_refused(run_dir: Path) -> None:
    (run_dir / "code").mkdir(parents=True, exist_ok=True)
    (run_dir / "code" / "signal_engine.py").write_text("print(1)\n", encoding="utf-8")
    _write_run_card(run_dir, [_manifest_entry(run_dir, "code/signal_engine.py")])
    env = json.loads(read_run_artifact(str(run_dir), "code/signal_engine.py"))
    assert env["ok"] is False
    assert "read_file" in env["hint"]


def test_aliases_work_without_run_card(run_dir: Path) -> None:
    assert not (run_dir / "run_card.json").exists()
    env = json.loads(read_run_artifact(str(run_dir), "equity", format="meta"))
    assert env["total_rows"] == EQUITY_ROWS
    assert "sha256" not in env and "manifest_size_bytes" not in env


def test_aliases_work_with_corrupt_run_card(run_dir: Path) -> None:
    (run_dir / "run_card.json").write_text("{oops not json", encoding="utf-8")
    env = json.loads(read_run_artifact(str(run_dir), "equity", format="meta"))
    assert env["total_rows"] == EQUITY_ROWS
    refused = json.loads(read_run_artifact(str(run_dir), "artifacts/equity.csv"))
    assert refused["ok"] is False
    assert "manifest" in refused["hint"]


def test_meta_exposes_manifest_sha256(run_dir: Path) -> None:
    entry = _manifest_entry(run_dir, "artifacts/equity.csv")
    _write_run_card(run_dir, [entry])
    env = json.loads(read_run_artifact(str(run_dir), "equity", format="meta"))
    assert env["sha256"] == entry["sha256"]
    assert env["manifest_size_bytes"] == entry["size_bytes"]
    assert env["size_bytes"] == (run_dir / "artifacts" / "equity.csv").stat().st_size


# --------------------------------------------------------------------------
# (d) structured output, no raw CSV
# --------------------------------------------------------------------------


def test_rows_are_structured_arrays_not_raw_csv(run_dir: Path) -> None:
    payload = read_run_artifact(str(run_dir), "equity", max_rows=50)
    assert "day00000,100000.0" not in payload  # no raw CSV line survives
    env = json.loads(payload)
    assert env["columns"] == EQUITY_COLUMNS
    for row in env["rows"]:
        assert isinstance(row, list)
        assert all(cell is None or isinstance(cell, (int, float, str)) for cell in row)
        assert all("\n" not in cell for cell in row if isinstance(cell, str))


# --------------------------------------------------------------------------
# (e) coercion
# --------------------------------------------------------------------------


def test_numeric_coercion(run_dir: Path) -> None:
    _write_csv(
        run_dir / "artifacts" / "metrics.csv",
        ["i", "f", "blank", "nan_col", "inf_col", "text"],
        [
            ["42", "3.14", "", "nan", "inf", "hello"],
            ["-7", "1e5", "   ", "NaN", "-inf", "1_000"],
            ["0", "2.0", "x", "Infinity", "-Infinity", "null"],
        ],
    )
    env = json.loads(read_run_artifact(str(run_dir), "metrics"))
    assert env["rows"][0] == [42, 3.14, None, None, None, "hello"]
    assert env["rows"][1] == [-7, 100000.0, None, None, None, "1_000"]
    assert env["rows"][2] == [0, 2.0, "x", None, None, "null"]


# --------------------------------------------------------------------------
# (f) meta
# --------------------------------------------------------------------------


def test_meta_format(run_dir: Path) -> None:
    env = json.loads(read_run_artifact(str(run_dir), "equity", format="meta"))
    assert set(env) == {"artifact", "run_dir", "path", "columns", "total_rows", "size_bytes"}
    assert env["artifact"] == "equity"
    assert env["columns"] == EQUITY_COLUMNS
    assert env["total_rows"] == EQUITY_ROWS
    assert env["size_bytes"] == (run_dir / "artifacts" / "equity.csv").stat().st_size


def test_unknown_format_rejected(run_dir: Path) -> None:
    env = json.loads(read_run_artifact(str(run_dir), "equity", format="yaml"))
    assert env["ok"] is False


# --------------------------------------------------------------------------
# (g) projection
# --------------------------------------------------------------------------


def test_columns_projection(run_dir: Path) -> None:
    env = json.loads(
        read_run_artifact(
            str(run_dir), "equity", columns=["equity", "date"], max_rows=10
        )
    )
    assert env["columns"] == ["equity", "date"]
    assert env["rows"][0] == [100000.0, "day00000"]
    assert all(len(row) == 2 for row in env["rows"])


def test_unknown_column_lists_valid_columns(run_dir: Path) -> None:
    env = json.loads(
        read_run_artifact(str(run_dir), "equity", columns=["equity", "nope"])
    )
    assert env["ok"] is False
    assert "nope" in env["error"]
    for column in EQUITY_COLUMNS:
        assert column in env["error"]


# --------------------------------------------------------------------------
# (h) byte budget
# --------------------------------------------------------------------------


def test_byte_budget_shrinks_rows_page_honestly(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_artifact_tool, "_BYTE_BUDGET", 3000)
    payload = read_run_artifact(str(run_dir), "equity", max_rows=1000)
    assert len(payload) <= 3000
    env = json.loads(payload)  # never broken JSON
    assert 0 < env["returned_rows"] < 1000
    assert env["returned_rows"] == len(env["rows"])
    assert env["truncated"] is True
    assert env["next_offset"] == env["offset"] + env["returned_rows"]
    assert env["rows"][0] == _expected_row(0)
    # The advertised resume point serves a valid next page.
    follow = json.loads(
        read_run_artifact(
            str(run_dir), "equity", offset=env["next_offset"], max_rows=1000
        )
    )
    assert follow["rows"][0] == _expected_row(env["next_offset"])


def test_byte_budget_restrides_downsample(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_artifact_tool, "_BYTE_BUDGET", 3000)
    payload = read_run_artifact(
        str(run_dir), "equity", format="downsample", max_rows=1000
    )
    assert len(payload) <= 3000
    env = json.loads(payload)
    assert env["returned_rows"] < 1000
    assert env["downsample"]["stride"] > 4  # re-striden, not silently truncated
    assert env["downsample"]["total_rows"] == EQUITY_ROWS
    assert env["rows"][0] == _expected_row(0)
    assert env["rows"][-1] == _expected_row(EQUITY_ROWS - 1)


def test_byte_budget_never_breaks_json_at_floor(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_artifact_tool, "_BYTE_BUDGET", 10)
    env = json.loads(read_run_artifact(str(run_dir), "equity", max_rows=100))
    assert env["ok"] is False
    assert "budget" in env["error"]


# --------------------------------------------------------------------------
# (i) ohlcv
# --------------------------------------------------------------------------


def test_ohlcv_code_maps_to_artifacts_file(run_dir: Path) -> None:
    _write_csv(
        run_dir / "artifacts" / "ohlcv_600519.SH.csv",
        ["date", "open", "close"],
        [["2024-01-02", "100.5", "101.25"]],
    )
    env = json.loads(read_run_artifact(str(run_dir), "ohlcv:600519.SH"))
    assert env["artifact"] == "ohlcv:600519.SH"
    assert env["columns"] == ["date", "open", "close"]
    assert env["rows"] == [["2024-01-02", 100.5, 101.25]]


# --------------------------------------------------------------------------
# (j) run_card / corrupt JSON
# --------------------------------------------------------------------------


def test_run_card_returns_parsed_json_regardless_of_format(run_dir: Path) -> None:
    card = {"run_id": "abc", "metrics": {"sharpe": 1.25}, "tags": ["x"]}
    (run_dir / "run_card.json").write_text(json.dumps(card), encoding="utf-8")
    for fmt in ("rows", "downsample", "meta"):
        env = json.loads(read_run_artifact(str(run_dir), "run_card", format=fmt))
        assert set(env) == {"artifact", "run_dir", "json", "size_bytes"}
        assert env["json"] == card
        assert env["size_bytes"] == (run_dir / "run_card.json").stat().st_size


def test_corrupt_run_card_rejected(run_dir: Path) -> None:
    (run_dir / "run_card.json").write_text("{oops not json", encoding="utf-8")
    env = json.loads(read_run_artifact(str(run_dir), "run_card"))
    assert env["ok"] is False
    assert set(env) == {"ok", "error", "hint"}


# --------------------------------------------------------------------------
# (k) missing file
# --------------------------------------------------------------------------


def test_missing_artifact_has_hint(run_dir: Path) -> None:
    env = json.loads(read_run_artifact(str(run_dir), "trades"))
    assert env["ok"] is False
    assert env["hint"]
    assert "not found" in env["error"]


def test_manifest_listed_but_missing_on_disk_has_hint(run_dir: Path) -> None:
    _write_run_card(
        run_dir,
        [{"path": "artifacts/validation.json", "size_bytes": 2, "sha256": "deadbeef"}],
    )
    env = json.loads(read_run_artifact(str(run_dir), "artifacts/validation.json"))
    assert env["ok"] is False
    assert "not found" in env["error"]


# --------------------------------------------------------------------------
# envelope hygiene + tool class
# --------------------------------------------------------------------------


def test_success_envelope_carries_no_ok_field(run_dir: Path) -> None:
    env = json.loads(read_run_artifact(str(run_dir), "equity", max_rows=5))
    assert "ok" not in env and "status" not in env
    assert set(env) == ROWS_ENVELOPE_KEYS
    assert env["downsample"] is None
    assert env["run_dir"] == str(run_dir)


def test_tool_class_contract(run_dir: Path) -> None:
    tool = RunArtifactTool()
    assert tool.name == "read_run_artifact"
    assert tool.is_readonly is True
    assert tool.repeatable is True
    assert tool.description
    assert "progress" not in tool.description
    schema = tool.to_openai_schema()
    props = schema["function"]["parameters"]["properties"]
    assert props["format"]["enum"] == ["rows", "downsample", "meta"]
    assert schema["function"]["parameters"]["required"] == ["run_dir", "artifact"]

    meta = json.loads(
        tool.execute(run_dir=str(run_dir), artifact="equity", format="meta")
    )
    assert meta["total_rows"] == EQUITY_ROWS
    default = json.loads(
        tool.execute(run_dir=str(run_dir), artifact="equity", max_rows=3)
    )
    assert set(default) == ROWS_ENVELOPE_KEYS
    assert default["returned_rows"] == 3


def test_default_page_survives_actual_agent_delivery_cap(run_dir):
    from src.config.limits import TOOL_RESULT_LIMIT, truncate_tool_result
    payload = read_run_artifact(str(run_dir), "equity")
    assert len(payload) <= TOOL_RESULT_LIMIT
    assert truncate_tool_result(payload) == payload
    first = json.loads(payload)
    assert first["path"] == str(run_dir / "artifacts/equity.csv")
    next_page = json.loads(read_run_artifact(str(run_dir), "equity", offset=first["next_offset"]))
    assert next_page["rows"][0] == _expected_row(first["returned_rows"])


def test_oversized_json_is_an_actionable_error(run_dir):
    from src.config.limits import TOOL_RESULT_LIMIT
    (run_dir / "run_card.json").write_text(json.dumps({"body": "x" * TOOL_RESULT_LIMIT}))
    payload = read_run_artifact(str(run_dir), "run_card")
    assert len(payload) <= TOOL_RESULT_LIMIT
    assert json.loads(payload)["ok"] is False


def test_oversized_row_requires_projection(run_dir):
    _write_csv(run_dir / "artifacts/trades.csv", ["code", "note"], [["000001", "x" * 20000]])
    assert json.loads(read_run_artifact(str(run_dir), "trades"))["ok"] is False
    projected = json.loads(read_run_artifact(str(run_dir), "trades", columns=["code"]))
    assert projected["rows"] == [["000001"]]


def test_shape_and_page_do_not_coerce_unselected_rows(run_dir, monkeypatch):
    original = run_artifact_tool._coerce_value
    count = 0
    def coercion(value):
        nonlocal count
        count += 1
        return original(value)
    monkeypatch.setattr(run_artifact_tool, "_coerce_value", coercion)
    read_run_artifact(str(run_dir), "equity", format="meta")
    assert count == 0
    read_run_artifact(str(run_dir), "equity", max_rows=3)
    assert count == 3 * len(EQUITY_COLUMNS)



def test_oversized_json_meta_reports_size_without_content(run_dir):
    from src.config.limits import TOOL_RESULT_LIMIT
    card = run_dir / "run_card.json"
    card.write_text(json.dumps({"body": "x" * TOOL_RESULT_LIMIT}))
    result = json.loads(read_run_artifact(str(run_dir), "run_card", format="meta"))
    assert result["size_bytes"] == card.stat().st_size
    assert result["content_omitted"] is True
    assert result["format"] == "json"
    assert "json" not in result
