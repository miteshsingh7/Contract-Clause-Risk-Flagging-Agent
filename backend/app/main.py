"""FastAPI application entry point.

Contract Clause Risk-Flagging and Redline-Suggestion Agent (Advisory Only).
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.playbook import router as playbook_router
from app.api.reviews import router as reviews_router
from app.core.config import settings
from app.services.db import init_db
from app.services.vector_store import init_vector_store


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context for startup and shutdown events."""
    # Startup: Initialize relational database tables
    init_db()
    # Initialize playbook vector store if enabled or empty
    await init_vector_store()
    yield
    # Shutdown logic (if any)


# Initialize FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "An advisory AI agent that compares contract clauses against a corporate "
        "negotiation playbook to flag risks and recommend redlines. "
        "NOTE: All outputs are advisory and must be reviewed by qualified legal counsel."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configure CORS restricted to frontend origins and local development hosts
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health_router)
app.include_router(playbook_router)
app.include_router(reviews_router)


@app.get("/", summary="Root Index", tags=["General"])
async def root_index() -> dict:
    """Root endpoint providing service information and API links."""
    return {
        "message": f"Welcome to {settings.APP_NAME}",
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/health",
        "playbook_rules": "/playbook/rules",
        "disclaimer": settings.LEGAL_DISCLAIMER,
    }
