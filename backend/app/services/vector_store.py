"""Vector store and semantic retrieval service for company negotiation playbook rules.

Uses ChromaDB persistent storage at CHROMA_PATH with embeddings generated via
the application's provider-agnostic LLM/embedding wrapper (Gemini default).
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection

from app.core.config import settings
from app.models.schemas import PlaybookRule
from app.services.llm import generate_embedding
from app.services.playbook import list_rules, load_playbook

logger = logging.getLogger(__name__)

# Cached ChromaDB client instance and its target path
_CHROMA_CLIENT: Optional[ClientAPI] = None
_CURRENT_CHROMA_PATH: Optional[str] = None


def get_chroma_client(chroma_path: Optional[Union[str, Path]] = None) -> ClientAPI:
    """Initialize or return persistent ChromaDB client."""
    global _CHROMA_CLIENT, _CURRENT_CHROMA_PATH
    target_path = str(chroma_path or settings.CHROMA_PATH)

    # Ensure storage directory exists
    Path(target_path).mkdir(parents=True, exist_ok=True)

    if _CHROMA_CLIENT is None or _CURRENT_CHROMA_PATH != target_path:
        _CHROMA_CLIENT = chromadb.PersistentClient(path=target_path)
        _CURRENT_CHROMA_PATH = target_path

    return _CHROMA_CLIENT


def get_playbook_collection(
    client: Optional[ClientAPI] = None,
    collection_name: Optional[str] = None,
    chroma_path: Optional[Union[str, Path]] = None,
) -> Collection:
    """Retrieve or create the ChromaDB collection configured for playbook rules.

    Configured with cosine distance for normalized [0, 1] similarity scoring.
    """
    chroma_client = client or get_chroma_client(chroma_path)
    col_name = collection_name or settings.PLAYBOOK_COLLECTION_NAME

    return chroma_client.get_or_create_collection(
        name=col_name,
        metadata={"hnsw:space": "cosine"},
    )


def format_rule_document(rule: PlaybookRule) -> str:
    """Format a PlaybookRule into a semantic text representation for vector embedding.

    Includes clause type, title, standard position, fallback, and unacceptable triggers.
    """
    triggers_str = (
        ", ".join(rule.unacceptable_triggers)
        if rule.unacceptable_triggers
        else "None specified"
    )
    return (
        f"Clause Type: {rule.clause_type}\n"
        f"Title: {rule.title}\n"
        f"Standard Position: {rule.standard_position}\n"
        f"Acceptable Fallback: {rule.acceptable_fallback}\n"
        f"Unacceptable Triggers: {triggers_str}"
    )


async def ingest_playbook(
    rules: Optional[List[PlaybookRule]] = None,
    rebuild: bool = False,
    chroma_path: Optional[Union[str, Path]] = None,
    collection_name: Optional[str] = None,
) -> int:
    """Ingest playbook rules into the ChromaDB vector store.

    Idempotent by default (upserts by rule_id). If rebuild is True, wipes existing
    collection before indexing.

    Args:
        rules: Optional list of rules to ingest. Defaults to all rules from playbook.json.
        rebuild: If True, clears existing collection and re-indexes from scratch.
        chroma_path: Optional path override for ChromaDB storage.
        collection_name: Optional collection name override.

    Returns:
        Total number of rules indexed in the collection.
    """
    client = get_chroma_client(chroma_path)
    col_name = collection_name or settings.PLAYBOOK_COLLECTION_NAME

    if rebuild:
        try:
            client.delete_collection(name=col_name)
            logger.info("Deleted existing collection '%s' for complete rebuild.", col_name)
        except Exception:
            # Collection may not exist yet
            pass

    collection = get_playbook_collection(
        client=client,
        collection_name=col_name,
        chroma_path=chroma_path,
    )

    rule_list = rules if rules is not None else load_playbook()
    if not rule_list:
        logger.warning("No playbook rules found to ingest.")
        return 0

    ids: List[str] = []
    documents: List[str] = []
    metadatas: List[Dict[str, Any]] = []

    for rule in rule_list:
        ids.append(rule.rule_id)
        doc_text = format_rule_document(rule)
        documents.append(doc_text)
        metadatas.append(
            {
                "rule_id": rule.rule_id,
                "clause_type": rule.clause_type.strip().lower(),
                "title": rule.title,
                "rule_json": rule.model_dump_json(),
            }
        )

    # Generate embeddings using our configured LLM/embedding wrapper
    logger.info("Generating embeddings for %d playbook rules...", len(documents))
    embeddings = await generate_embedding(documents)

    # Ingestion via upsert guarantees idempotence (no duplicate records)
    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas,
    )

    total_indexed = collection.count()
    logger.info(
        "Playbook ingestion complete. Collection '%s' now contains %d rules.",
        col_name,
        total_indexed,
    )
    return total_indexed


async def retrieve_rules(
    clause_text: str,
    clause_type: Optional[str] = None,
    top_k: Optional[int] = None,
    chroma_path: Optional[Union[str, Path]] = None,
    collection_name: Optional[str] = None,
) -> List[Tuple[PlaybookRule, float]]:
    """Retrieve playbook rules relevant to a given clause text.

    Args:
        clause_text: Text of the contract clause to search for.
        clause_type: Optional clause type filter (e.g. 'limitation_of_liability').
        top_k: Maximum number of rules to return. Defaults to settings.DEFAULT_TOP_K.
        chroma_path: Optional storage path override.
        collection_name: Optional collection name override.

    Returns:
        List of (PlaybookRule, similarity_score) tuples ordered by relevance.
        Returns an empty list on no matches; never raises an exception.
    """
    stripped_text = clause_text.strip() if clause_text else ""
    if not stripped_text:
        return []

    try:
        collection = get_playbook_collection(
            collection_name=collection_name,
            chroma_path=chroma_path,
        )
        total_items = collection.count()
        if total_items == 0:
            logger.debug("Playbook vector collection is empty. Returning empty results.")
            return []

        # Determine number of results to request
        target_k = top_k if (top_k is not None and top_k > 0) else settings.DEFAULT_TOP_K
        query_k = min(target_k, total_items)
        if query_k <= 0:
            return []

        # Generate query vector embedding
        query_embedding = await generate_embedding(stripped_text)
        # Ensure single embedding is passed as a list of floats
        if isinstance(query_embedding, list) and query_embedding and isinstance(query_embedding[0], list):
            query_vector = query_embedding[0]
        else:
            query_vector = query_embedding

        # Build optional metadata filter
        where_filter: Optional[Dict[str, Any]] = None
        if clause_type:
            normalized_type = clause_type.strip().lower()
            where_filter = {"clause_type": normalized_type}

        # Query ChromaDB collection
        query_results = collection.query(
            query_embeddings=[query_vector],
            n_results=query_k,
            where=where_filter,
            include=["metadatas", "distances"],
        )

        matched_metadatas = query_results.get("metadatas", [[]])[0]
        matched_distances = query_results.get("distances", [[]])[0]

        results: List[Tuple[PlaybookRule, float]] = []

        for meta, dist in zip(matched_metadatas, matched_distances):
            if not meta or "rule_json" not in meta:
                continue

            try:
                rule_obj = PlaybookRule.model_validate_json(meta["rule_json"])
            except Exception as deser_err:
                logger.warning("Failed to deserialize rule JSON from metadata: %s", deser_err)
                continue

            # Convert cosine distance (0 to 2) to normalized similarity score (0.0 to 1.0)
            # Distance 0.0 -> Similarity 1.0; Distance >= 1.0 -> Similarity approaches 0.0
            similarity = max(0.0, min(1.0, 1.0 - float(dist)))
            results.append((rule_obj, round(similarity, 4)))

        return results

    except Exception as exc:
        logger.warning("Error during playbook rule retrieval: %s. Returning empty results.", exc)
        return []


async def init_vector_store(chroma_path: Optional[Union[str, Path]] = None) -> None:
    """Initialize vector store on application startup.

    Automatically ingests playbook rules if collection is empty or if
    ENABLE_PLAYBOOK_AUTO_INGEST is True. Handles missing API keys gracefully.
    """
    try:
        collection = get_playbook_collection(chroma_path=chroma_path)
        count = collection.count()

        if count == 0 or settings.ENABLE_PLAYBOOK_AUTO_INGEST:
            logger.info("Initializing playbook vector store (count=%d, auto_ingest=%s)...", count, settings.ENABLE_PLAYBOOK_AUTO_INGEST)
            await ingest_playbook(rebuild=settings.ENABLE_PLAYBOOK_AUTO_INGEST, chroma_path=chroma_path)
        else:
            logger.info("Playbook vector store already populated (%d rules). Skipping auto-ingest.", count)

    except ValueError as val_err:
        # LLM_API_KEY may not be configured in local/offline test mode
        logger.warning(
            "Playbook auto-ingestion skipped on startup: %s. "
            "Configure LLM_API_KEY and run /playbook/reindex when ready.",
            val_err,
        )
    except Exception as exc:
        logger.warning("Playbook auto-ingestion encountered an issue on startup: %s", exc)
