"""Attachment filenames must remain usable child paths."""

import pytest
from src.channels.utils import safe_filename


@pytest.mark.parametrize("name", ["report\x00.csv", "report\n.csv", ".", ".."])
def test_sanitized_attachment_can_be_written(tmp_path, name):
    target = tmp_path / safe_filename(name)
    target.write_bytes(b"attachment")
    assert target.parent == tmp_path
    assert target.name not in {".", ".."}
    assert not any(ord(char) < 32 for char in target.name)
    assert target.read_bytes() == b"attachment"


@pytest.mark.parametrize("name", ["report.csv", "财报.pdf", "a b.txt", ".hidden"])
def test_valid_attachment_name_is_preserved(tmp_path, name):
    assert safe_filename(name) == name
    path = tmp_path / safe_filename(name)
    path.write_bytes(b"ok")
    assert path.read_bytes() == b"ok"
