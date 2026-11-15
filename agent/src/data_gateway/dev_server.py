"""Isolated loopback gateway while the main checkout has unresolved merges.

Run: PYTHONPATH=agent python -m src.data_gateway.dev_server
Production mounts register_gateway_routes with the existing require_auth hook.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from src.config.accessor import get_env_value

from . import get_gateway
from .api import register_gateway_routes


@asynccontextmanager
async def lifespan(app):
    yield
    get_gateway().close()


app = FastAPI(lifespan=lifespan)


def loopback_only(request: Request):
    """Limit this development entry to local clients and local Host headers."""
    if not request.client or request.client.host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(403, "Local preview only")
    if request.url.hostname not in {"127.0.0.1", "localhost", "::1", "testserver"}:
        raise HTTPException(403, "Local preview only")


register_gateway_routes(app, loopback_only)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(get_env_value("VIBE_GATEWAY_PORT", "8910")))
