"""Mount authenticated session route families and compact input validation errors."""

from __future__ import annotations

import re
import sys

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.api.goal_routes import register_goal_routes
from src.api.session_actions import register_session_actions, register_session_submissions
from src.api.session_reads import register_session_reads
from src.session.input_rules import MAX_MESSAGE_CHARS


def register_sessions_routes(app: FastAPI) -> None:
    """Mount session and goal routes using the host api_server dependencies."""
    @app.exception_handler(RequestValidationError)
    async def compact_message_validation(request: Request, exc: RequestValidationError):
        """Report oversized chat input without echoing the rejected prompt."""
        if re.fullmatch(r"/sessions/[^/]+/messages", request.url.path) and any(
            error.get("type") == "string_too_long" and error.get("loc") == ("body", "content")
            for error in exc.errors()
        ):
            return JSONResponse(
                status_code=422,
                content={"detail": {
                    "code": "message_too_long",
                    "max_length": MAX_MESSAGE_CHARS,
                    "message": f"Message must contain at most {MAX_MESSAGE_CHARS} characters. Shorten it before sending.",
                }},
            )
        return await request_validation_exception_handler(request, exc)

    host = sys.modules.get("api_server") or sys.modules.get("agent.api_server")
    if host is None:
        raise RuntimeError(
            "register_sessions_routes: api_server module not in sys.modules; "
            "ensure api_server is imported before calling this function"
        )

    register_session_submissions(app, host)
    register_session_reads(app, host)
    register_session_actions(app, host)
    register_goal_routes(app, host)
