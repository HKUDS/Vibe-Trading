from __future__ import annotations

from fastapi import FastAPI

from src.api.alpha_genesis_routes import register_alpha_genesis_routes


async def _noop_auth() -> None:
    return None


def test_hidden_alpha_genesis_surfaces_are_read_only_and_not_job_triggers() -> None:
    app = FastAPI()
    register_alpha_genesis_routes(app, require_auth=_noop_auth)
    openapi = app.openapi()

    for path, methods in openapi["paths"].items():
        if "alpha-genesis" not in path:
            continue
        assert set(methods) == {"get"}
        assert "mine" not in path
        assert "run" not in path
        assert "job" not in path
        assert "order" not in path
        assert "broker" not in path


def test_alpha_genesis_router_source_has_no_write_method_decorators() -> None:
    source = __import__("src.api.alpha_genesis_routes", fromlist=[""]).__loader__.get_source(  # type: ignore[union-attr]
        "src.api.alpha_genesis_routes"
    )

    assert source is not None
    for token in (".post(", ".put(", ".patch(", ".delete("):
        assert token not in source
