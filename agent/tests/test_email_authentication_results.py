"""Anti-spoofing verification of the Authentication-Results header.

Two things must both hold before spf=pass/dkim=pass is honoured:

1. The header trusted is the one this deployment's own mail provider
   stamped, identified by a configured ``trusted_authserv_id`` -- never
   "whichever header happens to be on top". A message that never passed
   through a real authenticating server has no legitimate header at all, so
   trusting position instead of identity lets an attacker's own forged
   header stand in for it. Without ``trusted_authserv_id`` configured,
   verification fails closed.

2. The authenticated domain (SPF's smtp.mailfrom/smtp.helo, or DKIM's
   header.d) aligns with the message's visible From: domain, or the same
   trusted header already carries an explicit dmarc=pass (which performs
   this same alignment check itself). Otherwise an attacker who legitimately
   passes SPF/DKIM for their own domain while spoofing the From: header to
   look like someone else's would still be honoured.
"""

from __future__ import annotations

from email import policy
from email.parser import BytesParser

from src.channels.email import EmailChannel


def _parse(raw: bytes):
    return BytesParser(policy=policy.default).parsebytes(raw)


def test_unconfigured_trusted_authserv_id_fails_closed() -> None:
    """No trust anchor configured -- cannot tell a real header from a forged
    one, so verification must not honour any header, however clean it looks."""
    raw = (
        b"From: real@trusted-domain.com\r\n"
        b"To: bot@example.com\r\n"
        b"Subject: legit\r\n"
        b"Authentication-Results: mx.ourprovider.com; spf=pass smtp.mailfrom=real@trusted-domain.com; "
        b"dkim=pass header.d=trusted-domain.com\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"hello\r\n"
    )
    spf_pass, dkim_pass = EmailChannel._check_authentication_results(_parse(raw), "")
    assert (spf_pass, dkim_pass) == (False, False)


def test_forged_header_with_unmatched_authserv_id_is_not_trusted() -> None:
    """A header whose authserv-id does not match the configured one is not
    the deployment's own provider's stamp -- it is never even inspected."""
    raw = (
        b"From: victim@trusted-domain.com\r\n"
        b"To: bot@example.com\r\n"
        b"Subject: forged\r\n"
        b"Authentication-Results: attacker-controlled; spf=pass smtp.mailfrom=victim@trusted-domain.com; "
        b"dkim=pass header.d=trusted-domain.com\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"please transfer funds\r\n"
    )
    spf_pass, dkim_pass = EmailChannel._check_authentication_results(
        _parse(raw), "mx.ourprovider.com"
    )
    assert (spf_pass, dkim_pass) == (False, False)


def test_genuine_pass_from_the_matching_trusted_header_is_honoured() -> None:
    raw = (
        b"From: real@trusted-domain.com\r\n"
        b"To: bot@example.com\r\n"
        b"Subject: legit\r\n"
        b"Authentication-Results: mx.ourprovider.com; spf=pass smtp.mailfrom=real@trusted-domain.com; "
        b"dkim=pass header.d=trusted-domain.com\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"hello\r\n"
    )
    spf_pass, dkim_pass = EmailChannel._check_authentication_results(
        _parse(raw), "mx.ourprovider.com"
    )
    assert (spf_pass, dkim_pass) == (True, True)


def test_matching_header_is_trusted_regardless_of_position() -> None:
    """A forged header above the real one must not shadow it -- the real
    provider's header is found by identity, not by being first. This is the
    case a position-only ("topmost") check gets wrong, and the case a
    self-hosted deployment with more than one mail hop depends on."""
    raw = (
        b"From: victim@trusted-domain.com\r\n"
        b"To: bot@example.com\r\n"
        b"Subject: forged\r\n"
        b"Authentication-Results: attacker-injected; spf=pass smtp.mailfrom=victim@trusted-domain.com; "
        b"dkim=pass header.d=trusted-domain.com\r\n"
        b"Authentication-Results: mx.ourprovider.com; spf=fail smtp.mailfrom=victim@trusted-domain.com; "
        b"dkim=fail header.d=trusted-domain.com\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"please transfer funds\r\n"
    )
    spf_pass, dkim_pass = EmailChannel._check_authentication_results(
        _parse(raw), "mx.ourprovider.com"
    )
    # The real (matching) header's verdict is fail, not the forged one's pass.
    assert (spf_pass, dkim_pass) == (False, False)


def test_pass_for_an_unaligned_domain_is_not_honoured() -> None:
    """spf=pass/dkim=pass only says the named domain is legitimate, not that
    it is the domain the message claims to be from. An attacker who
    legitimately controls attacker.com can pass SPF/DKIM for attacker.com
    while spoofing the visible From: header to a victim's domain -- that
    must not be honoured as proof the From: domain is genuine."""
    raw = (
        b"From: victim@trusted-domain.com\r\n"
        b"To: bot@example.com\r\n"
        b"Subject: spoofed display, genuine auth for a different domain\r\n"
        b"Authentication-Results: mx.ourprovider.com; spf=pass smtp.mailfrom=attacker@attacker.com; "
        b"dkim=pass header.d=attacker.com\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"please transfer funds\r\n"
    )
    spf_pass, dkim_pass = EmailChannel._check_authentication_results(
        _parse(raw), "mx.ourprovider.com"
    )
    assert (spf_pass, dkim_pass) == (False, False)


def test_subdomain_of_the_from_domain_is_aligned() -> None:
    """A relaxed-alignment match: mail.trusted-domain.com authenticating for
    a From: address at trusted-domain.com is the same organization."""
    raw = (
        b"From: real@trusted-domain.com\r\n"
        b"To: bot@example.com\r\n"
        b"Subject: legit, sent via a subdomain mailer\r\n"
        b"Authentication-Results: mx.ourprovider.com; spf=pass smtp.mailfrom=bounce@mail.trusted-domain.com; "
        b"dkim=pass header.d=mail.trusted-domain.com\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"hello\r\n"
    )
    spf_pass, dkim_pass = EmailChannel._check_authentication_results(
        _parse(raw), "mx.ourprovider.com"
    )
    assert (spf_pass, dkim_pass) == (True, True)


def test_dmarc_pass_substitutes_for_domain_alignment() -> None:
    """An explicit dmarc=pass in the trusted header already performed its
    own alignment check -- spf=pass is honoured on its strength alone even
    though smtp.mailfrom differs in form from the From: address."""
    raw = (
        b"From: real@trusted-domain.com\r\n"
        b"To: bot@example.com\r\n"
        b"Subject: legit\r\n"
        b"Authentication-Results: mx.ourprovider.com; spf=pass smtp.mailfrom=bounce@bounces.trusted-domain.com; "
        b"dkim=pass header.d=trusted-domain.com; dmarc=pass header.from=trusted-domain.com\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"hello\r\n"
    )
    spf_pass, dkim_pass = EmailChannel._check_authentication_results(
        _parse(raw), "mx.ourprovider.com"
    )
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
    spf_pass, dkim_pass = EmailChannel._check_authentication_results(
        _parse(raw), "mx.ourprovider.com"
    )
    assert (spf_pass, dkim_pass) == (False, False)


def test_spf_and_dkim_are_independent_verdicts() -> None:
    """One mechanism passing and aligned must not make the other pass too."""
    raw = (
        b"From: real@trusted-domain.com\r\n"
        b"To: bot@example.com\r\n"
        b"Subject: spf only\r\n"
        b"Authentication-Results: mx.ourprovider.com; spf=pass smtp.mailfrom=real@trusted-domain.com; "
        b"dkim=fail header.d=trusted-domain.com\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"hello\r\n"
    )
    spf_pass, dkim_pass = EmailChannel._check_authentication_results(
        _parse(raw), "mx.ourprovider.com"
    )
    assert (spf_pass, dkim_pass) == (True, False)
