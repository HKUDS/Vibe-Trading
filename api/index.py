from __future__ import annotations

from urllib.parse import parse_qs

from deployment.app import app as _app


class PathRewriteMiddleware:
    """Restore the original request path after Vercel rewrites it."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            query = parse_qs(scope.get("query_string", b"").decode())
            path = query.get("path", [None])[0]
            if path is not None:
                scope = dict(scope)
                scope["path"] = path or "/"
        await self.app(scope, receive, send)


app = PathRewriteMiddleware(_app)
