"""Optional OpenBB Workspace AI-service endpoints.

These endpoints are not required for a custom agent to function, but OpenBB
Workspace will use them when available to improve UX:

* ``POST /v1/generate/chat/title``      -- summarise a chat into a short title.
* ``POST /v1/generate/dashboard/title`` -- name a dashboard from its contents.
* ``POST /v1/enhance_prompt``           -- rewrite / enrich a user prompt.

Each endpoint performs a single lightweight, non-streaming LLM call using
Vibe-Trading's :class:`ChatLLM`. They are intentionally tolerant of request
shape differences across Workspace versions.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("openbb_bridge")

ai_service_router = APIRouter(tags=["openbb-workspace-ai"])

_TITLE_MAX_WORDS = 8


def _run_llm(system: str, user: str) -> str:
    """Run a single synchronous ChatLLM call and return trimmed text."""
    from src.providers.chat import ChatLLM

    llm = ChatLLM()
    response = llm.chat(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        timeout=30,
    )
    return (response.content or "").strip()


def _extract_messages_text(payload: Dict[str, Any]) -> str:
    """Flatten whatever conversation representation Workspace sent to text."""
    messages: List[Any] = payload.get("messages") or []
    lines: List[str] = []
    for message in messages:
        if isinstance(message, dict):
            role = message.get("role", "user")
            content = message.get("content", "")
            if not isinstance(content, str):
                content = str(content)
            lines.append(f"{role}: {content}")
    if not lines:
        # Fall back to any obvious free-text field.
        for key in ("content", "text", "prompt", "query"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                lines.append(value)
                break
    return "\n".join(lines)[:4000]


async def _safe_json(request: Request) -> Dict[str, Any]:
    try:
        payload = await request.json()
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


@ai_service_router.post("/v1/generate/chat/title")
async def generate_chat_title(request: Request) -> JSONResponse:
    """Generate a concise title for a chat conversation."""
    payload = await _safe_json(request)
    conversation = _extract_messages_text(payload)
    if not conversation:
        return JSONResponse(content={"title": "New chat"})
    try:
        title = await asyncio.to_thread(
            _run_llm,
            (
                "You generate short, descriptive chat titles. Respond with a "
                f"title of at most {_TITLE_MAX_WORDS} words, no quotes, no "
                "trailing punctuation."
            ),
            f"Conversation:\n{conversation}\n\nTitle:",
        )
    except Exception as exc:
        logger.warning("chat title generation failed: %s", exc)
        return JSONResponse(content={"title": "New chat"})
    return JSONResponse(content={"title": title[:80] or "New chat"})


@ai_service_router.post("/v1/generate/dashboard/title")
async def generate_dashboard_title(request: Request) -> JSONResponse:
    """Generate a concise title for a dashboard."""
    payload = await _safe_json(request)
    context = _extract_messages_text(payload) or str(payload)[:2000]
    if not context.strip():
        return JSONResponse(content={"title": "New dashboard"})
    try:
        title = await asyncio.to_thread(
            _run_llm,
            (
                "You generate short, descriptive dashboard titles. Respond with "
                f"a title of at most {_TITLE_MAX_WORDS} words, no quotes."
            ),
            f"Dashboard contents:\n{context}\n\nTitle:",
        )
    except Exception as exc:
        logger.warning("dashboard title generation failed: %s", exc)
        return JSONResponse(content={"title": "New dashboard"})
    return JSONResponse(content={"title": title[:80] or "New dashboard"})


@ai_service_router.post("/v1/enhance_prompt")
async def enhance_prompt(request: Request) -> JSONResponse:
    """Rewrite a user prompt into a clearer, richer version."""
    payload = await _safe_json(request)
    prompt = payload.get("prompt") or payload.get("query") or payload.get("text") or ""
    if not isinstance(prompt, str) or not prompt.strip():
        return JSONResponse(content={"prompt": prompt or ""})
    try:
        enhanced = await asyncio.to_thread(
            _run_llm,
            (
                "You are a prompt engineer for a finance research agent. Rewrite "
                "the user's prompt to be clearer and more specific while "
                "preserving intent. Respond with only the rewritten prompt."
            ),
            prompt,
        )
    except Exception as exc:
        logger.warning("prompt enhancement failed: %s", exc)
        return JSONResponse(content={"prompt": prompt})
    return JSONResponse(content={"prompt": enhanced or prompt})


def register_ai_service_routes(app: FastAPI) -> None:
    """Register the optional AI-service endpoints onto ``app``."""
    app.include_router(ai_service_router)
