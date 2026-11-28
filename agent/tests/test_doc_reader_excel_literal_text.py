"""Physical Excel text must not be reinterpreted as pandas missing-value markers."""

from src.tools.path_utils import FileRoots
from src.config.accessor import get_env_config


import json
import re

import pytest

from src.tools.doc_reader_tool import DocReaderTool

openpyxl = pytest.importorskip("openpyxl")
pytest.importorskip("pandas")


def read_workbook(tmp_path, monkeypatch, rows, second_sheet=False):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    path = tmp_path / "report.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Regions"
    sheet.append(["Value", "Label", "Count"])
    for row in rows:
        sheet.append(row)
    if second_sheet:
        workbook.create_sheet("Second").append(["Native second-sheet heading"])
    workbook.save(path)
    reopened = openpyxl.load_workbook(path)
    assert list(reopened["Regions"].values)[1:] == [tuple(row) for row in rows]
    reopened.close()
    return json.loads(DocReaderTool(roots=FileRoots.from_config(get_env_config().api)).execute(file_path=str(path)))


@pytest.mark.parametrize("literal", ["NA", "N/A", "NULL", "None", "null", "n/a"])
def test_native_literal_strings_survive_the_document_reader(
    tmp_path, monkeypatch, literal
):
    result = read_workbook(tmp_path, monkeypatch, [[literal, "Region marker", 42]])
    assert result["status"] == "ok", result
    assert re.search(
        r"^\s*" + re.escape(literal) + r"\s+Region marker\s+42\s*$",
        result["text"],
        re.M,
    )
    assert result["sheets"] == [{"name": "Regions", "rows": 1, "cols": 3}]


def test_real_blank_cells_keep_existing_nan_representation(tmp_path, monkeypatch):
    result = read_workbook(tmp_path, monkeypatch, [[None, "Ordinary", 42]])
    assert result["status"] == "ok"
    assert re.search(r"^\s*NaN\s+Ordinary\s+42\s*$", result["text"], re.M)


def test_ordinary_text_and_all_sheets_keep_their_contract(tmp_path, monkeypatch):
    result = read_workbook(
        tmp_path, monkeypatch, [["0012", "Ordinary", 42]], second_sheet=True
    )
    assert result["status"] == "ok"
    assert "0012" in result["text"] and "Native second-sheet heading" in result["text"]
    assert [s["name"] for s in result["sheets"]] == ["Regions", "Second"]
    assert result["text"].index("Regions") < result["text"].index("Second")


def test_existing_hundred_row_preview_is_unchanged(tmp_path, monkeypatch):
    rows = [[f"ROW-{i:03d}", "Ordinary", i] for i in range(101)]
    result = read_workbook(tmp_path, monkeypatch, rows)
    assert result["sheets"][0]["rows"] == 101
    assert "ROW-099" in result["text"] and "ROW-100" not in result["text"]
