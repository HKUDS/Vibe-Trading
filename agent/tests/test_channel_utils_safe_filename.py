"""Coverage for safe_filename, the sanitizer applied to attachment/media
filenames pulled from untrusted IM channel payloads (Dingtalk, Discord,
Email, Feishu, Matrix, Napcat, Signal, Slack) before they are joined onto a
download directory. It had no direct or indirect test anywhere in the suite
before this file.
"""

from __future__ import annotations

from src.channels.utils import safe_filename


class TestSafeFilename:
    def test_plain_name_is_unchanged(self) -> None:
        assert safe_filename("report.pdf") == "report.pdf"

    def test_path_separators_are_replaced_preventing_traversal(self) -> None:
        """A naive implementation that only strips '/' (POSIX) but not '\\'
        would let a Windows-style traversal payload through untouched.
        """
        assert safe_filename("../../etc/passwd") == ".._.._etc_passwd"
        assert safe_filename("..\\..\\windows\\system32") == ".._.._windows_system32"

    def test_other_unsafe_characters_are_replaced(self) -> None:
        assert safe_filename('bad:name*file?"<x>|.txt') == "bad_name_file___x__.txt"

    def test_surrounding_whitespace_is_stripped(self) -> None:
        assert safe_filename("  name.txt  ") == "name.txt"

    def test_empty_string_stays_empty(self) -> None:
        assert safe_filename("") == ""
