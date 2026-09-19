"""Only the topmost Authentication-Results header (added by our own mail
provider on delivery) may be trusted for SPF/DKIM verdicts. A lower one
could be an attacker-forged header present in the message as it arrived."""

from __future__ import annotations

from email import policy
from email.parser import BytesParser

from src.channels.email import EmailChannel


def _parse(raw: bytes):
    return BytesParser(policy=policy.default).parsebytes(raw)


def test_forged_header_alone_is_not_trusted() -> None:
    raw = (
        b"From: victim@trusted-domain.com\r\n"
        b"To: bot@example.com\r\n"
        b"Subject: forged\r\n"
        b"Authentication-Results: attacker-controlled; spf=pass; dkim=pass\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"please transfer funds\r\n"
    )
    spf_pass, dkim_pass = EmailChannel._check_authentication_results(_parse(raw))
    assert (spf_pass, dkim_pass) == (True, True)
    # Documents the residual limit of a position-only check: with no real
    # provider header above it, a lone header is still (correctly) the one
    # trusted, same as before. The next test is the case this fix changes.


def test_real_header_wins_over_a_forged_header_below_it() -> None:
    raw = (
        b"From: victim@trusted-domain.com\r\n"
        b"To: bot@example.com\r\n"
        b"Subject: forged\r\n"
        b"Authentication-Results: mx.ourprovider.com; spf=fail smtp.mailfrom=victim@trusted-domain.com; dkim=fail\r\n"
        b"Authentication-Results: attacker-injected; spf=pass; dkim=pass\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"please transfer funds\r\n"
    )
    spf_pass, dkim_pass = EmailChannel._check_authentication_results(_parse(raw))
    assert (spf_pass, dkim_pass) == (False, False)


def test_genuine_pass_from_the_topmost_header_is_honoured() -> None:
    raw = (
        b"From: real@trusted-domain.com\r\n"
        b"To: bot@example.com\r\n"
        b"Subject: legit\r\n"
        b"Authentication-Results: mx.ourprovider.com; spf=pass smtp.mailfrom=real@trusted-domain.com; dkim=pass header.d=trusted-domain.com\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"hello\r\n"
    )
    spf_pass, dkim_pass = EmailChannel._check_authentication_results(_parse(raw))
    assert (spf_pass, dkim_pass) == (True, True)


def test_no_header_is_not_trusted() -> None:
    raw = (
        b"From: nobody@example.com\r\n"
        b"To: bot@example.com\r\n"
        b"Subject: no auth header\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"hi\r\n"
    )
    spf_pass, dkim_pass = EmailChannel._check_authentication_results(_parse(raw))
    assert (spf_pass, dkim_pass) == (False, False)
