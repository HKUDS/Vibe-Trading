from __future__ import annotations

from fastapi import FastAPI

from src.api.alpha_genesis_routes import register_alpha_genesis_routes


async def _noop_auth() -> None:
    return None


def test_alpha_genesis_api_is_get_only() -> None:
    app = FastAPI()
    register_alpha_genesis_routes(app, require_auth=_noop_auth)

    paths = app.openapi()["paths"]
    alpha_genesis_paths = {
        path: methods
        for path, methods in paths.items()
        if "alpha-genesis" in path
    }

    assert alpha_genesis_paths
    for methods in alpha_genesis_paths.values():
        assert set(methods).issubset({"get"})
