"""Cookie and Set-Cookie header values are scrubbed from free-form text."""

from __future__ import annotations

import pytest

from src.tools.redaction import redact_text


@pytest.mark.parametrize("header", ["Cookie", "cookie", "Set-Cookie", "SET-COOKIE"])
def test_cookie_header_value_is_redacted(header: str) -> None:
    out = redact_text(f"{header}: sid=abc123; theme=dark; Path=/; HttpOnly")
    assert out == f"{header}: [redacted]"
    assert redact_text(out) == out


def test_only_the_header_line_is_redacted() -> None:
    out = redact_text("HTTP/1.1 200 OK\nSet-Cookie: sid=abc123; Secure\nContent-Type: text/html")
    assert out == "HTTP/1.1 200 OK\nSet-Cookie: [redacted]\nContent-Type: text/html"


@pytest.mark.parametrize("quote", ['"', "'"])
def test_quoted_curl_header_keeps_the_rest_of_the_command(quote: str) -> None:
    cmd = f"curl -H {quote}Cookie: sid=abc123; csrf=xyz{quote} https://example.com/api"
    out = redact_text(cmd)
    assert "abc123" not in out and "xyz" not in out
    assert out == f"curl -H {quote}Cookie: [redacted]{quote} https://example.com/api"


def test_prose_and_lookalikes_are_left_alone() -> None:
    text = "We use a cookie banner. my-cookie: x is not a header; cookies: 3"
    assert redact_text(text) == text
