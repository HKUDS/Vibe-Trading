"""Tests for the HMAC-authenticated universe-panel pickle cache (VT-010).

The sidecar next to each ``<name>.pkl`` is a *keyed* HMAC-SHA256 tag, not a bare
digest. These tests pin the security property that matters: a local attacker who
can rewrite the pickle but does not hold the secret cannot forge a matching
sidecar, so the tampered blob is rejected before ``pickle.loads``.
"""

from __future__ import annotations

import hashlib
import pickle
import stat

import pandas as pd
import pytest

from src.tools import alpha_bench_tool as abt


def _panel() -> dict[str, pd.DataFrame]:
    close = pd.DataFrame(
        {"AAA": [10.0, 11.0, 12.0], "BBB": [20.0, 19.0, 21.0]},
        index=pd.date_range("2020-01-01", periods=3, freq="B"),
    )
    return {"close": close, "open": close, "volume": close}


class _FakeCfg:
    def __init__(self, api_auth_key: str) -> None:
        self.api = type("_Api", (), {"api_auth_key": api_auth_key})()


@pytest.fixture
def no_api_key(monkeypatch):
    """Force the key-file fallback path (no API_AUTH_KEY configured)."""
    monkeypatch.setattr(abt, "get_env_config", lambda: _FakeCfg(""))


def test_cache_roundtrips_when_untampered(tmp_path, no_api_key):
    cache_path = tmp_path / "csi300_2020-01-01_2020-12-31.pkl"
    panel = _panel()

    abt._write_pickle_cache(tmp_path, cache_path, panel)
    loaded = abt._read_pickle_cache(cache_path)

    assert loaded is not None
    pd.testing.assert_frame_equal(loaded["close"], panel["close"])


def test_tampered_pickle_with_unkeyed_sha256_is_rejected(tmp_path, no_api_key):
    cache_path = tmp_path / "sp500_2020-01-01_2020-12-31.pkl"
    abt._write_pickle_cache(tmp_path, cache_path, _panel())

    # Attacker who lacks the HMAC secret: rewrites the pickle with a malicious
    # payload and recomputes only a *bare* sha256 sidecar (the pre-VT-010 tag).
    evil = pickle.dumps({"close": pd.DataFrame({"X": [9.0]}), "pwned": True})
    cache_path.write_bytes(evil)
    abt._sha256_path(cache_path).write_text(
        hashlib.sha256(evil).hexdigest(), encoding="utf-8"
    )

    assert abt._read_pickle_cache(cache_path) is None


def test_fallback_key_is_stable_and_0600(tmp_path, no_api_key):
    key1 = abt._cache_hmac_key(tmp_path)
    key2 = abt._cache_hmac_key(tmp_path)

    assert key1 == key2  # reused, not freshly random per call
    assert len(key1) == 32

    key_file = tmp_path / ".hmac_key"
    assert key_file.is_file()
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600


def test_configured_api_key_takes_priority(tmp_path, monkeypatch):
    monkeypatch.setattr(abt, "get_env_config", lambda: _FakeCfg("super-secret-key"))

    key = abt._cache_hmac_key(tmp_path)

    assert key == b"super-secret-key"
    # No key file is written when an explicit secret is configured.
    assert not (tmp_path / ".hmac_key").exists()
