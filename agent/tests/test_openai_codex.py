"""Tests for the OpenAI Codex OAuth provider adapter."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.providers import llm as llm_mod
from src.providers.chat import ProviderStreamError
from src.providers.openai_codex import (
    DEFAULT_CODEX_URL,
    CodexAuthenticationError,
    CodexStreamError,
    OpenAICodexLLM,
    _CodexRefreshError,
    _build_codex_token_storage,
    _codex_refresh_lock,
    _events_from_lines,
    _get_codex_token,
    _message_chunks_from_events,
    _strip_model_prefix,
    _token_expiry_ms,
    login_openai_codex,
    validate_codex_base_url,
)


DEFAULT_CODEX_MODEL = "openai-codex/gpt-5.4"


def _jwt(payload: dict[str, object]) -> str:
    """Build an unsigned JWT-shaped value for claim parsing tests."""
    import base64

    def _part(value: dict[str, object]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{_part({'alg': 'none'})}.{_part(payload)}.signature"


def test_provider_default_model_matches_live_codex_account_path() -> None:
    providers_path = Path(__file__).resolve().parents[1] / "src" / "providers" / "llm_providers.json"
    providers = json.loads(providers_path.read_text(encoding="utf-8"))
    codex_provider = next(item for item in providers if item["name"] == "openai-codex")

    assert codex_provider["default_model"] == DEFAULT_CODEX_MODEL


def test_codex_base_url_is_restricted_to_chatgpt_endpoint() -> None:
    assert validate_codex_base_url(DEFAULT_CODEX_URL + "/") == DEFAULT_CODEX_URL

    with pytest.raises(ValueError):
        validate_codex_base_url("https://api.openai.com/v1")


def test_build_llm_returns_codex_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_mod, "_dotenv_loaded", True)
    monkeypatch.setenv("LANGCHAIN_PROVIDER", "openai-codex")
    monkeypatch.setenv("LANGCHAIN_MODEL_NAME", DEFAULT_CODEX_MODEL)
    monkeypatch.setenv("OPENAI_CODEX_BASE_URL", DEFAULT_CODEX_URL)

    adapter = llm_mod.build_llm()

    assert isinstance(adapter, OpenAICodexLLM)
    assert adapter.model == DEFAULT_CODEX_MODEL


def test_codex_body_strips_provider_prefix_and_converts_tools() -> None:
    adapter = OpenAICodexLLM(model=DEFAULT_CODEX_MODEL)

    body = adapter.bind_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "Run a shell command",
                    "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
                },
            }
        ]
    )._body(
        [
            {"role": "system", "content": "You are careful."},
            {"role": "user", "content": "Say hi."},
        ],
        stream=True,
    )

    assert _strip_model_prefix(DEFAULT_CODEX_MODEL) == "gpt-5.4"
    assert body["model"] == "gpt-5.4"
    assert body["instructions"] == "You are careful."
    assert body["tools"][0]["name"] == "bash"
    assert body["input"][0]["content"][0]["text"] == "Say hi."


def test_codex_storage_is_vibe_owned_and_never_imports_codex_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "vibe-home"
    user_home = tmp_path / "user-home"
    official_store = user_home / ".codex" / "auth.json"
    official_store.parent.mkdir(parents=True)
    official_store.write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": "official-access-must-not-be-imported",
                    "refresh_token": "official-refresh-must-not-be-imported",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VIBE_TRADING_HOME", str(runtime_root))
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("USERPROFILE", str(user_home))
    monkeypatch.setenv("OAUTH_CLI_KIT_TOKEN_PATH", str(official_store))

    storage = _build_codex_token_storage()

    assert storage.get_token_path() == runtime_root / "auth" / "openai-codex.json"
    assert storage.load() is None


def test_explicit_login_always_runs_interactive_with_vibe_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    oauth_cli_kit = pytest.importorskip("oauth_cli_kit")
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    calls: list[dict[str, object]] = []
    interactive_token = SimpleNamespace(
        access="new-access",
        refresh="new-refresh",
        expires=int(time.time() * 1000) + 3_600_000,
        account_id="account-1",
    )

    def _interactive(**kwargs: object) -> object:
        calls.append(kwargs)
        return interactive_token

    def _unexpected_cache_probe(*args: object, **kwargs: object) -> object:
        raise AssertionError("explicit login must not accept a cached token")

    monkeypatch.setattr(oauth_cli_kit, "login_oauth_interactive", _interactive)
    monkeypatch.setattr(oauth_cli_kit, "get_token", _unexpected_cache_probe)

    result = login_openai_codex(print_fn=lambda _: None, prompt_fn=lambda _: "code")

    assert result is interactive_token
    assert len(calls) == 1
    storage = calls[0]["storage"]
    assert storage.get_token_path() == tmp_path / "auth" / "openai-codex.json"


def test_missing_codex_token_raises_login_hint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    adapter = OpenAICodexLLM(model=DEFAULT_CODEX_MODEL)

    with pytest.raises(CodexAuthenticationError, match="vibe-trading provider login openai-codex"):
        adapter._headers()


def test_real_jwt_expiry_overrides_stale_stored_expiry() -> None:
    jwt_expiry_seconds = int(time.time()) + 90
    token = SimpleNamespace(
        access=_jwt({"exp": jwt_expiry_seconds}),
        expires=int(time.time() * 1000) + 86_400_000,
    )

    assert _token_expiry_ms(token) == jwt_expiry_seconds * 1000


def test_stale_refresh_fallback_invalidates_only_vibe_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import src.providers.openai_codex as codex_mod
    import oauth_cli_kit

    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    storage = _build_codex_token_storage()
    storage.save(
        SimpleNamespace(
            access="server-invalid-access",
            refresh="server-invalid-refresh",
            expires=int(time.time() * 1000) + 3_600_000,
            account_id="account-1",
        )
    )

    refresh_calls: list[dict[str, object]] = []

    def _stale_fallback(**kwargs: object) -> object:
        refresh_calls.append(kwargs)
        return storage.load()

    monkeypatch.setattr(codex_mod, "_build_codex_token_storage", lambda: storage)
    monkeypatch.setattr(oauth_cli_kit, "get_token", _stale_fallback)

    with pytest.raises(CodexAuthenticationError, match="provider login openai-codex"):
        _get_codex_token(force_refresh=True, rejected_access="server-invalid-access")

    assert storage.load() is None
    assert refresh_calls[0]["storage"] is storage
    assert refresh_calls[0]["min_ttl_seconds"] > 1_000_000_000


def test_force_refresh_ignores_clock_fresh_expiry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import src.providers.openai_codex as codex_mod

    storage = _build_codex_token_storage(tmp_path / "openai-codex.json")
    storage.save(
        SimpleNamespace(
            access="server-invalid-access",
            refresh="old-refresh",
            expires=int(time.time() * 1000) + 3_600_000,
            account_id="account-1",
        )
    )
    refreshed = SimpleNamespace(
        access="recovered-access",
        refresh="rotated-refresh",
        expires=int(time.time() * 1000) + 3_600_000,
        account_id="account-1",
    )
    refresh_calls: list[str] = []

    def _refresh(token: object, destination: object) -> object:
        refresh_calls.append(token.access)
        destination.save(refreshed)
        return refreshed

    monkeypatch.setattr(codex_mod, "_build_codex_token_storage", lambda: storage)
    monkeypatch.setattr(codex_mod, "_refresh_codex_token", _refresh)

    result = _get_codex_token(
        force_refresh=True,
        rejected_access="server-invalid-access",
    )

    assert result is refreshed
    assert refresh_calls == ["server-invalid-access"]
    assert storage.load().access == "recovered-access"


def test_force_refresh_reuses_token_rotated_by_another_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import src.providers.openai_codex as codex_mod

    storage = _build_codex_token_storage(tmp_path / "openai-codex.json")
    storage.save(
        SimpleNamespace(
            access="already-rotated-access",
            refresh="already-rotated-refresh",
            expires=int(time.time() * 1000) + 3_600_000,
            account_id="account-1",
        )
    )
    monkeypatch.setattr(codex_mod, "_build_codex_token_storage", lambda: storage)
    monkeypatch.setattr(
        codex_mod,
        "_refresh_codex_token",
        lambda *args, **kwargs: pytest.fail("must not rotate a second time"),
    )

    result = _get_codex_token(
        force_refresh=True,
        rejected_access="older-rejected-access",
    )

    assert result.access == "already-rotated-access"


def test_transient_forced_refresh_failure_preserves_cache_and_is_retryable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import src.providers.openai_codex as codex_mod

    storage = _build_codex_token_storage(tmp_path / "openai-codex.json")
    storage.save(
        SimpleNamespace(
            access="server-invalid-access",
            refresh="recoverable-refresh",
            expires=int(time.time() * 1000) + 3_600_000,
            account_id="account-1",
        )
    )

    def _unavailable(*args: object, **kwargs: object) -> object:
        raise _CodexRefreshError(
            "temporarily unavailable",
            status_code=503,
            permanent=False,
        )

    monkeypatch.setattr(codex_mod, "_build_codex_token_storage", lambda: storage)
    monkeypatch.setattr(codex_mod, "_refresh_codex_token", _unavailable)

    with pytest.raises(CodexStreamError) as excinfo:
        _get_codex_token(
            force_refresh=True,
            rejected_access="server-invalid-access",
        )

    assert excinfo.value.status_code == 503
    assert storage.load().refresh == "recoverable-refresh"


def test_sse_events_parse_text_and_function_calls() -> None:
    events = list(
        _events_from_lines(
            [
                'data: {"type":"response.output_text.delta","delta":"Hi"}',
                "",
                'data: {"type":"response.output_item.added","item":{"type":"function_call","call_id":"call_1","id":"fc_1","name":"bash","arguments":""}}',
                "",
                'data: {"type":"response.function_call_arguments.delta","call_id":"call_1","delta":"{\\"command\\":\\"pw"}',
                "",
                'data: {"type":"response.function_call_arguments.delta","call_id":"call_1","delta":"d\\"}"}',
                "",
                'data: {"type":"response.output_item.done","item":{"type":"function_call","call_id":"call_1"}}',
                "",
                "data: [DONE]",
                "",
            ]
        )
    )

    chunks = list(_message_chunks_from_events(events))

    assert chunks[0].content == "Hi"
    assert chunks[1].tool_calls == [{"id": "call_1|fc_1", "name": "bash", "args": {"command": "pwd"}}]


def test_stream_non_401_response_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeResponse:
        status_code = 403

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"forbidden"

    class _FakeClient:
        def __init__(self, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def stream(self, *args: object, **kwargs: object) -> _FakeResponse:
            return _FakeResponse()

    import src.providers.openai_codex as codex_mod

    monkeypatch.setattr(codex_mod.httpx, "Client", _FakeClient)
    adapter = OpenAICodexLLM(model=DEFAULT_CODEX_MODEL)
    adapter._headers = lambda **kwargs: {}

    with pytest.raises(RuntimeError, match="OpenAI Codex HTTP 403"):
        list(adapter.stream([{"role": "user", "content": "hello"}]))


def test_stream_non_200_response_raises_typed_codex_stream_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #7: a Codex 4xx raises ``CodexStreamError`` with ``status_code`` set.

    Regression: a plain ``RuntimeError`` carried no ``status_code`` attribute,
    so ``ProviderStreamError.status_code`` was ``None`` (retryable=True) for
    every codex error — including deterministic 400/401/403. The fix is a
    ``CodexStreamError(RuntimeError)`` subclass that exposes the upstream
    status so retry classification works correctly.
    """
    request_count = 0

    class _FakeResponse:
        status_code = 401

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"unauthorized"

    class _FakeClient:
        def __init__(self, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def stream(self, *args: object, **kwargs: object) -> _FakeResponse:
            nonlocal request_count
            request_count += 1
            return _FakeResponse()

    import src.providers.openai_codex as codex_mod

    monkeypatch.setattr(codex_mod.httpx, "Client", _FakeClient)
    adapter = OpenAICodexLLM(model=DEFAULT_CODEX_MODEL)
    adapter._headers = lambda **kwargs: {"Authorization": "Bearer still-invalid"}

    with pytest.raises(CodexStreamError) as excinfo:
        list(adapter.stream([{"role": "user", "content": "hello"}]))

    # CodexStreamError carries the status_code so ProviderStreamError
    # classifies 401 as non-retryable downstream.
    assert excinfo.value.status_code == 401
    assert request_count == 2

    err = ProviderStreamError(
        provider="openai-codex",
        model=DEFAULT_CODEX_MODEL,
        original=excinfo.value,
    )
    assert err.status_code == 401
    assert err.retryable is False


def test_stream_refreshes_once_after_clock_fresh_token_gets_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.providers.openai_codex as codex_mod

    responses = [401, 200]
    sent_authorizations: list[str] = []
    header_calls: list[tuple[bool, str | None]] = []

    class _FakeResponse:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"error":{"code":"token_invalidated"}}'

        def iter_lines(self) -> list[str]:
            return [
                'data: {"type":"response.output_text.delta","delta":"recovered"}',
                "",
                "data: [DONE]",
                "",
            ]

    class _FakeClient:
        def __init__(self, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def stream(self, *args: object, **kwargs: object) -> _FakeResponse:
            sent_authorizations.append(kwargs["headers"]["Authorization"])
            return _FakeResponse(responses.pop(0))

    def _headers(*, force_refresh: bool = False, rejected_access: str | None = None) -> dict[str, str]:
        header_calls.append((force_refresh, rejected_access))
        access = "fresh-access" if force_refresh else "server-invalid-access"
        return {"Authorization": f"Bearer {access}"}

    monkeypatch.setattr(codex_mod.httpx, "Client", _FakeClient)
    adapter = OpenAICodexLLM(model=DEFAULT_CODEX_MODEL)
    adapter._headers = _headers

    chunks = list(adapter.stream([{"role": "user", "content": "hello"}]))

    assert [chunk.content for chunk in chunks] == ["recovered"]
    assert sent_authorizations == ["Bearer server-invalid-access", "Bearer fresh-access"]
    assert header_calls == [
        (False, None),
        (True, "server-invalid-access"),
    ]


def test_refresh_lock_uses_windows_byte_range_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import src.providers.openai_codex as codex_mod

    calls: list[tuple[int, int]] = []

    class _FakeMsvcrt:
        LK_LOCK = 1
        LK_UNLCK = 2

        @staticmethod
        def locking(fd: int, mode: int, count: int) -> None:
            assert count == 1
            calls.append((mode, count))

    storage = _build_codex_token_storage(tmp_path / "openai-codex.json")
    monkeypatch.setattr(codex_mod, "fcntl", None)
    monkeypatch.setattr(codex_mod, "msvcrt", _FakeMsvcrt)

    with _codex_refresh_lock(storage):
        assert calls == [(_FakeMsvcrt.LK_LOCK, 1)]

    assert calls == [
        (_FakeMsvcrt.LK_LOCK, 1),
        (_FakeMsvcrt.LK_UNLCK, 1),
    ]


def test_codex_400_is_non_retryable_via_codex_stream_error() -> None:
    """Deterministic codex 400 is non-retryable through CodexStreamError."""
    err = ProviderStreamError(
        provider="openai-codex",
        model=DEFAULT_CODEX_MODEL,
        original=CodexStreamError(400, "bad request body"),
    )
    assert err.status_code == 400
    assert err.retryable is False


def test_codex_500_is_retryable_via_codex_stream_error() -> None:
    """Transient codex 500 stays retryable."""
    err = ProviderStreamError(
        provider="openai-codex",
        model=DEFAULT_CODEX_MODEL,
        original=CodexStreamError(500, "boom"),
    )
    assert err.status_code == 500
    assert err.retryable is True
