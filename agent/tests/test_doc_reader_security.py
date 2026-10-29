"""Security regression tests for document and broker-file path boundaries."""

from __future__ import annotations

import json

import pytest

from src.tools.doc_reader_tool import DocReaderTool, read_document
from src.tools.path_utils import safe_document_path, safe_user_path


@pytest.fixture(autouse=True)
def clear_allowed_roots(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start each test with only the built-in import roots."""
    monkeypatch.delenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", raising=False)


def _read_json(result: str) -> dict:
    """Parse a document-reader JSON envelope."""
    return json.loads(result)


def test_read_document_rejects_system_paths() -> None:
    result = _read_json(read_document("/etc/passwd"))

    assert result["status"] == "error"
    assert "outside allowed document roots" in result["error"]


def test_safe_user_path_rejects_root_home_credentials() -> None:
    with pytest.raises(ValueError, match="outside allowed user-file roots"):
        safe_user_path("/root/.aws/credentials")


def test_read_document_allows_configured_import_root(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = tmp_path / "note.txt"
    doc.write_text("VT_DOC_OK", encoding="utf-8")
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))

    result = _read_json(read_document(str(doc)))

    assert result["status"] == "ok"
    assert result["text"] == "VT_DOC_OK"
    assert safe_document_path(str(doc)) == doc.resolve()


@pytest.mark.parametrize("arguments", [{}, {"file_path": ""}, {"file_path": None}])
def test_missing_document_path_names_the_required_argument(arguments) -> None:
    result = _read_json(DocReaderTool().execute(**arguments))
    assert result["status"] == "error"
    assert "file_path is required" in result["error"]


def test_uploaded_handle_uses_upload_root_even_when_a_run_dir_is_supplied(tmp_path, monkeypatch) -> None:
    from src.config.paths import get_uploads_dir

    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    doc = get_uploads_dir() / "report.txt"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("UPLOADED_REPORT", encoding="utf-8")
    result = _read_json(DocReaderTool().execute(file_path="uploads/report.txt", run_dir=str(tmp_path / "runs/r1")))
    assert result["status"] == "ok"
    assert result["text"] == "UPLOADED_REPORT"
