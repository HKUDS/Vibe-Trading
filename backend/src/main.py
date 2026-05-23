"""FastAPI application entry point."""

from __future__ import annotations

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from interface.api.router import api_router

logger = structlog.get_logger()

app = FastAPI(
    title="Vibe-Trading Copy API",
    description="Quantitative strategy marketplace with copy trading",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — tighten in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5899", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "service": "vibe-trading-copy"}


@app.on_event("startup")
async def startup() -> None:
    """Initialize on startup."""
    logger.info("api_startup", service="vibe-trading-copy")


@app.on_event("shutdown")
async def shutdown() -> None:
    """Cleanup on shutdown."""
    logger.info("api_shutdown", service="vibe-trading-copy")
