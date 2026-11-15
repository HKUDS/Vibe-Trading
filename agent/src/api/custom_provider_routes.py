"""Web API for test-first custom OpenAI-compatible provider profiles."""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any, Awaitable, Callable

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.api.settings_routes import _settings_store
from src.providers.custom_profiles import _perform_completion_test, _validate_custom_base_url, activate_custom_provider
from src.providers.custom_profiles import CustomProviderStore, STORE_LOCK

AuthDep = Callable[..., Awaitable[Any] | Any]
_TEST_TTL_S = 300.0
_TESTS: dict[str, tuple[float, str]] = {}


class CustomProviderTestRequest(BaseModel):
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    api_key: str = Field(min_length=1, max_length=500)


class CustomProviderSaveRequest(CustomProviderTestRequest):
    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=100)
    test_id: str = Field(min_length=1, max_length=80)


class CustomProviderActivateRequest(BaseModel):
    confirm: bool = False


def _fingerprint(payload: CustomProviderTestRequest) -> str:
    raw = "\x00".join((payload.base_url.strip(), payload.model.strip(), payload.api_key.strip()))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _prune_tests() -> None:
    now = time.monotonic()
    for test_id, (expires, _) in list(_TESTS.items()):
        if expires <= now:
            _TESTS.pop(test_id, None)


def register_custom_provider_routes(
    app: FastAPI,
    require_local_or_auth: AuthDep,
    require_settings_write_auth: AuthDep,
) -> None:
    @app.get("/settings/custom-providers", dependencies=[Depends(require_local_or_auth)])
    def list_custom_providers() -> dict[str, Any]:
        return {"status": "ok", "providers": CustomProviderStore().list_public()}

    @app.post("/settings/custom-providers/test", dependencies=[Depends(require_settings_write_auth)])
    async def test_custom_provider(payload: CustomProviderTestRequest) -> dict[str, Any]:
        try:
            payload.base_url = _validate_custom_base_url(payload.base_url)
            if not payload.model.strip() or not payload.api_key.strip():
                raise ValueError("Model and API key must not be blank")
            result = await _perform_completion_test(
                base_url=payload.base_url, model=payload.model, api_key=payload.api_key
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _prune_tests()
        test_id = uuid.uuid4().hex
        _TESTS[test_id] = (time.monotonic() + _TEST_TTL_S, _fingerprint(payload))
        return {"status": "ok", "test_id": test_id, **result}

    @app.post("/settings/custom-providers", dependencies=[Depends(require_settings_write_auth)])
    def save_custom_provider(payload: CustomProviderSaveRequest) -> dict[str, Any]:
        with STORE_LOCK:
            _prune_tests()
            try:
                payload.base_url = _validate_custom_base_url(payload.base_url)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            expected = _TESTS.get(payload.test_id)
            if expected is None or expected[0] <= time.monotonic() or expected[1] != _fingerprint(payload):
                raise HTTPException(status_code=409, detail="A successful provider test is required before saving")
            try:
                base_url = _validate_custom_base_url(payload.base_url)
                profile = CustomProviderStore().save(
                    profile_id=payload.id,
                    label=payload.label,
                    base_url=base_url,
                    model=payload.model,
                    api_key=payload.api_key,
                )
            except (RuntimeError, ValueError, OSError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            _TESTS.pop(payload.test_id, None)
            return {"status": "ok", "provider": profile}

    @app.post("/settings/custom-providers/{profile_id}/activate", dependencies=[Depends(require_settings_write_auth)])
    def activate_profile(profile_id: str, payload: CustomProviderActivateRequest) -> dict[str, Any]:
        if not payload.confirm:
            raise HTTPException(status_code=400, detail="Explicit confirmation is required to activate a provider")
        try:
            return activate_custom_provider(profile_id, store=CustomProviderStore(), settings=_settings_store())
        except OSError as exc:
            raise HTTPException(status_code=503, detail="Unable to save settings; check ownership and permissions for ~/.vibe-trading/.env") from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
