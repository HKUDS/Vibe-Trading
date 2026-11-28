"""Real slide text remains visible when its shape is a group or native table."""

from src.tools.path_utils import FileRoots
from src.config.accessor import get_env_config


import json

import pytest

from src.tools.doc_reader_tool import DocReaderTool

pptx = pytest.importorskip("pptx")
Inches = pytest.importorskip("pptx.util").Inches


def textbox(shapes, text):
    box = shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
    box.text = text
    return box


def read_deck(tmp_path, monkeypatch, presentation, expected_tokens=()):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    path = tmp_path / "report.pptx"
    presentation.save(path)
    # Independently confirm these tokens are physically stored in the package.
    from zipfile import ZipFile
    from xml.etree import ElementTree

    with ZipFile(path) as package:
        stored = []
        for name in sorted(
            n
            for n in package.namelist()
            if n.startswith("ppt/slides/slide") and n.endswith(".xml")
        ):
            stored.extend(
                element.text
                for element in ElementTree.fromstring(package.read(name)).iter(
                    "{http://schemas.openxmlformats.org/drawingml/2006/main}t"
                )
                if element.text
            )
    assert stored == list(expected_tokens)
    return json.loads(DocReaderTool(roots=FileRoots.from_config(get_env_config().api)).execute(file_path=str(path)))


def test_nested_groups_keep_child_text_once_in_shape_order(tmp_path, monkeypatch):
    presentation = pptx.Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    textbox(slide.shapes, "Before group")
    group = slide.shapes.add_group_shape()
    textbox(group.shapes, "Group first")
    inner = group.shapes.add_group_shape()
    textbox(inner.shapes, "Nested label")
    textbox(group.shapes, "Group last")
    textbox(slide.shapes, "After group")
    result = read_deck(
        tmp_path,
        monkeypatch,
        presentation,
        ["Before group", "Group first", "Nested label", "Group last", "After group"],
    )
    assert result["status"] == "ok", result
    assert (
        result["text"]
        == "--- Slide 1 ---\nBefore group\nGroup first\nNested label\nGroup last\nAfter group"
    )
    assert result["text"].count("Nested label") == 1
    assert result["slides"] == 1


def test_native_table_cells_keep_row_and_shape_order(tmp_path, monkeypatch):
    presentation = pptx.Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    textbox(slide.shapes, "FY2023")
    table = slide.shapes.add_table(
        2, 2, Inches(1), Inches(2), Inches(5), Inches(1)
    ).table
    for row, values in enumerate([["Metric", "Value"], ["Revenue", "$42m"]]):
        for column, value in enumerate(values):
            table.cell(row, column).text = value
    textbox(slide.shapes, "Conclusion")
    result = read_deck(
        tmp_path,
        monkeypatch,
        presentation,
        ["FY2023", "Metric", "Value", "Revenue", "$42m", "Conclusion"],
    )
    assert (
        result["text"]
        == "--- Slide 1 ---\nFY2023\nMetric | Value\nRevenue | $42m\nConclusion"
    )


def test_merged_table_origin_is_read_once_without_spanned_text(tmp_path, monkeypatch):
    presentation = pptx.Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    table = slide.shapes.add_table(
        1, 3, Inches(1), Inches(2), Inches(5), Inches(1)
    ).table
    table.cell(0, 0).text = "Merged left"
    table.cell(0, 1).text = "Merged right"
    table.cell(0, 2).text = "Independent"
    table.cell(0, 0).merge(table.cell(0, 1))
    assert table.cell(0, 0).is_merge_origin and table.cell(0, 1).is_spanned
    result = read_deck(
        tmp_path,
        monkeypatch,
        presentation,
        ["Merged left", "Merged right", "Independent"],
    )
    assert result["text"] == "--- Slide 1 ---\nMerged left Merged right | Independent"
    assert (
        result["text"].count("Merged left") == result["text"].count("Merged right") == 1
    )


def test_plain_formatted_runs_and_paragraphs_keep_existing_text(tmp_path, monkeypatch):
    presentation = pptx.Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    box = textbox(slide.shapes, "")
    paragraph = box.text_frame.paragraphs[0]
    paragraph.add_run().text = " First "
    run = paragraph.add_run()
    run.text = " second "
    run.font.bold = True
    box.text_frame.add_paragraph().text = "Next paragraph"
    result = read_deck(
        tmp_path, monkeypatch, presentation, [" First ", " second ", "Next paragraph"]
    )
    assert result["text"] == "--- Slide 1 ---\nFirst  second\nNext paragraph"


def test_empty_group_and_table_add_no_fake_text(tmp_path, monkeypatch):
    presentation = pptx.Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_group_shape()
    slide.shapes.add_table(1, 2, Inches(1), Inches(2), Inches(5), Inches(1))
    result = read_deck(tmp_path, monkeypatch, presentation, [])
    assert result["text"] == "--- Slide 1 ---"
    assert result["slides"] == 1
