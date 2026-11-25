"""Health check endpoint router."""

from fastapi import APIRouter
from app.core.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Application Health Check")
async def health_check() -> dict:
    """Return application operational status, configured provider, and legal advisory disclaimer."""
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "llm_provider": settings.LLM_PROVIDER,
        "disclaimer": settings.LEGAL_DISCLAIMER,
    }
