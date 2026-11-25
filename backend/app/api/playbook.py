"""FastAPI router for company playbook management and semantic rule search."""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import settings
from app.models.schemas import (
    PlaybookReindexRequest,
    PlaybookReindexResponse,
    PlaybookRule,
    PlaybookSearchRequest,
    PlaybookSearchResponse,
    RuleSearchResult,
)
from app.services.db import has_active_processing_reviews
from app.services.playbook import get_rule, list_rules
from app.services.vector_store import ingest_playbook, retrieve_rules

router = APIRouter(prefix="/playbook", tags=["Playbook"])


@router.get(
    "/rules",
    response_model=List[PlaybookRule],
    summary="List Playbook Rules",
)
def get_rules_endpoint(
    clause_type: Optional[str] = Query(
        default=None,
        description="Filter rules by normalized clause type (e.g., 'limitation_of_liability')",
    ),
) -> List[PlaybookRule]:
    """Retrieve all playbook rules, optionally filtered by clause type."""
    return list_rules(clause_type=clause_type)


@router.get(
    "/rules/{rule_id}",
    response_model=PlaybookRule,
    summary="Get Rule by ID",
)
def get_rule_by_id_endpoint(
    rule_id: str,
) -> PlaybookRule:
    """Retrieve a single playbook rule by its unique rule_id (e.g., 'LOL-01')."""
    rule = get_rule(rule_id)
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Playbook rule with ID '{rule_id}' not found in the negotiation playbook.",
        )
    return rule


@router.post(
    "/search",
    response_model=PlaybookSearchResponse,
    summary="Semantic Playbook Rule Search",
)
async def search_playbook_endpoint(
    payload: PlaybookSearchRequest,
) -> PlaybookSearchResponse:
    """Perform semantic vector search against the playbook vector store.

    Accepts contract clause text, an optional clause type filter, and optional top_k.
    Returns matching playbook rules ranked by semantic similarity score.
    """
    raw_results = await retrieve_rules(
        clause_text=payload.clause_text,
        clause_type=payload.clause_type,
        top_k=payload.top_k,
    )

    items = [
        RuleSearchResult(rule=rule, similarity_score=score)
        for rule, score in raw_results
    ]

    return PlaybookSearchResponse(
        query=payload.clause_text,
        clause_type=payload.clause_type,
        total_results=len(items),
        results=items,
    )


@router.post(
    "/reindex",
    response_model=PlaybookReindexResponse,
    summary="Reindex Playbook Vector Store",
)
async def reindex_playbook_endpoint(
    payload: Optional[PlaybookReindexRequest] = None,
) -> PlaybookReindexResponse:
    """Rebuild or re-ingest all playbook rules into ChromaDB."""
    rebuild = payload.rebuild if payload is not None else True

    if rebuild and has_active_processing_reviews():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Cannot rebuild playbook vector store while contract reviews are "
                "actively processing. Please wait for processing to complete or "
                "reindex with rebuild=false."
            ),
        )

    try:
        count = await ingest_playbook(rebuild=rebuild)
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reindex playbook vector store: {val_err}",
        ) from val_err
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reindexing failed: {exc}",
        ) from exc

    return PlaybookReindexResponse(
        status="ok",
        indexed_count=count,
        collection_name=settings.PLAYBOOK_COLLECTION_NAME,
    )
