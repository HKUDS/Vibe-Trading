from __future__ import annotations

import sys
from pathlib import Path

from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "agent"

if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from api_server import app as _app  # noqa: E402


class SPAStaticFiles(StaticFiles):
    """Serve index.html for client-side routes in the built frontend."""

    async def get_response(self, path: str, scope: Scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


frontend_dist = ROOT / "frontend" / "dist"
if frontend_dist.exists() and not any(route.path == "/" for route in _app.routes):
    _app.mount("/", SPAStaticFiles(directory=str(frontend_dist), html=True), name="frontend")

app = _app
