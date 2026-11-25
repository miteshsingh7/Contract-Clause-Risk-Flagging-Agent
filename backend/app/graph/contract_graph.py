"""Contract-level LangGraph analysis pipeline.

Orchestrates:
1. parse: Ingests .docx or .pdf into ParsedDocument.
2. segment: Partitions paragraphs into complete substantive Clause units.
3. analyze_clauses: Concurrently runs per-clause graph with retries and fault tolerance.
4. summarize: Compiles contract-level metrics and identifies missing playbook clauses.

State is strictly serializable (dicts/lists/primitives) for future checkpointer attachment.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict, Union

from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import var_child_runnable_config
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.core.config import settings
from app.graph.clause_graph import clause_analysis_graph
from app.models.schemas import (
    Clause,
    ClauseAnalysis,
    ContractAnalysisResult,
    ParsedDocument,
    RiskLevel,
    SegmentationResult,
)
from app.services.db import (
    save_clause_analyses,
    update_review_status,
)
from app.services.llm import DailyQuotaExceededError
from app.services.parser import parse_document
from app.services.segmenter import segment_document

logger = logging.getLogger(__name__)

# Complete set of standard clause types defined in the corporate playbook
PLAYBOOK_CLAUSE_TYPES: List[str] = [
    "limitation_of_liability",
    "indemnification",
    "termination",
    "confidentiality",
    "governing_law",
    "ip_ownership",
    "payment_terms",
    "auto_renewal",
    "data_protection",
    "assignment",
]


class ContractState(TypedDict, total=False):
    """Serializable shared state for the contract-level workflow."""

    file_path: str
    contract_name: str
    parsed_doc: Optional[Dict[str, Any]]
    clauses: List[Dict[str, Any]]
    analyses: List[Dict[str, Any]]
    missing_clause_types: List[str]
    total_clauses: int
    acceptable_count: int
    needs_negotiation_count: int
    unacceptable_count: int
    needs_human_review_count: int
    result: Optional[Dict[str, Any]]
    error: Optional[str]
    review_status: Optional[str]
    interrupt_resume: Optional[Any]


# ------------------------------------------------------------------------------
# Node 1: Parse
# ------------------------------------------------------------------------------


def parse_node(state: ContractState) -> Dict[str, Any]:
    """Parse input contract file into ParsedDocument."""
    file_path = state["file_path"]
    try:
        parsed = parse_document(file_path)
        return {
            "contract_name": parsed.contract_name,
            "parsed_doc": parsed.model_dump(),
        }
    except Exception as exc:
        logger.error("Document parsing failed for '%s': %s", file_path, exc)
        return {
            "contract_name": Path(file_path).name,
            "parsed_doc": None,
            "error": f"Parsing failed: {exc}",
        }


# ------------------------------------------------------------------------------
# Node 2: Segment
# ------------------------------------------------------------------------------


async def segment_node(state: ContractState) -> Dict[str, Any]:
    """Segment parsed document into substantive clauses."""
    if state.get("error") or not state.get("parsed_doc"):
        return {"clauses": []}

    parsed_doc_data = state["parsed_doc"]
    parsed_doc = ParsedDocument.model_validate(parsed_doc_data)

    try:
        segmentation = await segment_document(
            parsed_document=parsed_doc,
            enable_llm_refinement=settings.ENABLE_LLM_SEGMENT_REFINEMENT,
        )
        clause_dicts = [c.model_dump() for c in segmentation.clauses]
        return {
            "clauses": clause_dicts,
            "total_clauses": len(clause_dicts),
        }
    except Exception as exc:
        logger.error("Document segmentation failed: %s", exc)
        return {
            "clauses": [],
            "total_clauses": 0,
            "error": f"Segmentation failed: {exc}",
        }


# ------------------------------------------------------------------------------
# Node 3: Analyze Clauses (with Concurrency & Retries)
# ------------------------------------------------------------------------------


async def _analyze_single_clause_with_retries(
    clause: Clause,
    semaphore: asyncio.Semaphore,
) -> ClauseAnalysis:
    """Execute per-clause analysis graph with concurrency control and retries."""
    async with semaphore:
        retries = settings.MAX_LLM_RETRIES
        delay = 1.0

        for attempt in range(retries + 1):
            try:
                state_input = {"clause": clause}
                output_state = await clause_analysis_graph.ainvoke(state_input)

                final_analysis = output_state.get("final_analysis")
                if final_analysis is not None:
                    return final_analysis

                # If no final_analysis object was returned directly
                return ClauseAnalysis(
                    clause_id=clause.id,
                    clause_type=output_state.get("clause_type", "other"),
                    risk_level=output_state.get("risk_level", RiskLevel.NEEDS_NEGOTIATION),
                    cited_rule_ids=output_state.get("cited_rule_ids", []),
                    explanation=output_state.get("explanation", "Analysis completed."),
                    suggested_redline=output_state.get("suggested_redline"),
                    confidence=output_state.get("analysis_confidence", 0.5),
                    needs_human_review=output_state.get("needs_human_review", False),
                    review_reason=output_state.get("review_reason"),
                )

            except DailyQuotaExceededError:
                logger.error("Daily API quota exceeded during clause %s analysis. Halting.", clause.id)
                raise
            except Exception as exc:
                if attempt < retries:
                    logger.warning(
                        "Retry %d/%d for clause %s after error: %s",
                        attempt + 1,
                        retries,
                        clause.id,
                        exc,
                    )
                    await asyncio.sleep(delay)
                    delay *= 2.0
                else:
                    logger.error("Clause %s failed after %d retries: %s", clause.id, retries, exc)
                    # A failure on one clause must not crash the entire run
                    return ClauseAnalysis(
                        clause_id=clause.id,
                        clause_type="other",
                        risk_level=RiskLevel.NEEDS_NEGOTIATION,
                        cited_rule_ids=[],
                        explanation=f"Automated analysis failed due to system error: {exc}",
                        confidence=0.0,
                        needs_human_review=True,
                        review_reason=f"Pipeline error: {exc}",
                    )


async def analyze_clauses_node(state: ContractState) -> Dict[str, Any]:
    """Analyze all substantive clauses using the per-clause analysis graph."""
    clause_dicts = state.get("clauses", [])
    if not clause_dicts:
        return {"analyses": []}

    clauses = [Clause.model_validate(c) for c in clause_dicts]
    semaphore = asyncio.Semaphore(settings.CONCURRENCY_LIMIT)

    # Launch clause analyses concurrently bounded by the semaphore
    tasks = [_analyze_single_clause_with_retries(clause, semaphore) for clause in clauses]
    results: List[ClauseAnalysis] = await asyncio.gather(*tasks)

    analyses_dicts = [a.model_dump() for a in results]
    return {"analyses": analyses_dicts}


# ------------------------------------------------------------------------------
# Node 4: Summarize & Missing Clause Check
# ------------------------------------------------------------------------------


def summarize_node(state: ContractState) -> Dict[str, Any]:
    """Perform missing clause check and compute contract-level aggregate summary."""
    analyses_data = state.get("analyses", [])
    contract_name = state.get("contract_name", "Unknown Contract")

    analyses: List[ClauseAnalysis] = [
        ClauseAnalysis.model_validate(a) for a in analyses_data
    ]

    # Non-LLM missing clause check: list playbook types not matched by any clause
    identified_types = {a.clause_type.strip().lower() for a in analyses}
    missing_types = [
        ctype for ctype in PLAYBOOK_CLAUSE_TYPES
        if ctype not in identified_types
    ]

    # Aggregate risk counts
    acceptable = sum(1 for a in analyses if a.risk_level == RiskLevel.ACCEPTABLE)
    needs_neg = sum(1 for a in analyses if a.risk_level == RiskLevel.NEEDS_NEGOTIATION)
    unacceptable = sum(1 for a in analyses if a.risk_level == RiskLevel.UNACCEPTABLE)
    human_review = sum(1 for a in analyses if a.needs_human_review)

    contract_result = ContractAnalysisResult(
        contract_name=contract_name,
        analyses=analyses,
        missing_clause_types=missing_types,
        total_clauses=len(analyses),
        acceptable_count=acceptable,
        needs_negotiation_count=needs_neg,
        unacceptable_count=unacceptable,
        needs_human_review_count=human_review,
        disclaimer=settings.LEGAL_DISCLAIMER,
    )

    return {
        "missing_clause_types": missing_types,
        "acceptable_count": acceptable,
        "needs_negotiation_count": needs_neg,
        "unacceptable_count": unacceptable,
        "needs_human_review_count": human_review,
        "result": contract_result.model_dump(),
    }


# ------------------------------------------------------------------------------
# Node 5: Await Review (Human-in-the-Loop Interrupt)
# ------------------------------------------------------------------------------


async def await_review_node(state: ContractState, config: RunnableConfig) -> Dict[str, Any]:
    """Pause execution for human legal review via LangGraph interrupt."""
    is_checkpointed = config.get("configurable", {}).get("thread_id") is not None
    if not is_checkpointed or not settings.ENABLE_CHECKPOINTER:
        logger.debug("Checkpointer bypassed; skipping interrupt in await_review")
        return {"review_status": "awaiting_review"}

    token = var_child_runnable_config.set(config)
    try:
        interrupt_val = interrupt({
            "review_id": config.get("configurable", {}).get("thread_id"),
            "message": "Contract analysis completed. Awaiting human legal review and decisions.",
        })
        return {
            "review_status": "review_completed",
            "interrupt_resume": interrupt_val,
        }
    finally:
        var_child_runnable_config.reset(token)


# ------------------------------------------------------------------------------
# Node 6: Finalize
# ------------------------------------------------------------------------------


def finalize_node(state: ContractState) -> Dict[str, Any]:
    """Mark the contract review workflow finalized."""
    return {"review_status": "finalized"}


# ------------------------------------------------------------------------------
# Build and Compile Contract-Level Graph
# ------------------------------------------------------------------------------


def create_contract_analysis_graph(checkpointer: Optional[Any] = None) -> StateGraph:
    """Build and compile the contract-level LangGraph workflow."""
    builder = StateGraph(ContractState)

    builder.add_node("parse", parse_node)
    builder.add_node("segment", segment_node)
    builder.add_node("analyze_clauses", analyze_clauses_node)
    builder.add_node("summarize", summarize_node)
    builder.add_node("await_review", await_review_node)
    builder.add_node("finalize", finalize_node)

    builder.add_edge(START, "parse")
    builder.add_edge("parse", "segment")
    builder.add_edge("segment", "analyze_clauses")
    builder.add_edge("analyze_clauses", "summarize")
    builder.add_edge("summarize", "await_review")
    builder.add_edge("await_review", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile(checkpointer=checkpointer)


contract_analysis_graph = create_contract_analysis_graph()


# ------------------------------------------------------------------------------
# Execution & Human-in-the-Loop Resumption Helpers
# ------------------------------------------------------------------------------


async def process_contract_review_pipeline(
    review_id: str,
    file_path: str,
    checkpoint_path: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    """Execute the contract review pipeline and update database state."""
    logger.info("Starting processing for review %s (file: %s)", review_id, Path(file_path).name)
    try:
        chk_path = checkpoint_path or settings.CHECKPOINT_DB_PATH
        config = {"configurable": {"thread_id": review_id}}
        initial_state: ContractState = {"file_path": str(Path(file_path).resolve())}

        if settings.ENABLE_CHECKPOINTER:
            Path(chk_path).parent.mkdir(parents=True, exist_ok=True)
            async with AsyncSqliteSaver.from_conn_string(chk_path) as checkpointer:
                graph = create_contract_analysis_graph(checkpointer=checkpointer)
                final_state = await graph.ainvoke(initial_state, config=config)
        else:
            graph = create_contract_analysis_graph(checkpointer=None)
            final_state = await graph.ainvoke(initial_state, config=config)

        if final_state.get("error"):
            logger.error("Review %s pipeline reported error: %s", review_id, final_state["error"])
            update_review_status(
                review_id=review_id,
                status="failed",
                error_message=final_state["error"],
                db_path=db_path,
            )
            return

        clauses_data = final_state.get("clauses", [])
        analyses_data = final_state.get("analyses", [])
        missing_clauses = final_state.get("missing_clause_types", [])

        clauses = [Clause.model_validate(c) for c in clauses_data]
        analyses = [ClauseAnalysis.model_validate(a) for a in analyses_data]

        save_clause_analyses(
            review_id=review_id,
            clauses=clauses,
            analyses=analyses,
            missing_clauses=missing_clauses,
            db_path=db_path,
        )

        update_review_status(
            review_id=review_id,
            status="awaiting_review",
            missing_clauses=missing_clauses,
            total_clauses=len(clauses),
            analyzed_clauses=len(analyses),
            db_path=db_path,
        )
        logger.info(
            "Review %s successfully transitioned to awaiting_review (%d clauses)",
            review_id,
            len(clauses),
        )

    except Exception as exc:
        logger.exception("Unexpected failure processing review %s: %s", review_id, exc)
        update_review_status(
            review_id=review_id,
            status="failed",
            error_message=str(exc),
            db_path=db_path,
        )


async def resume_contract_review_graph(
    review_id: str,
    reviewer_name: str = "Counsel",
    checkpoint_path: Optional[str] = None,
) -> None:
    """Resume the LangGraph workflow paused at await_review to execute finalize."""
    if not settings.ENABLE_CHECKPOINTER:
        logger.debug("Checkpointer disabled; resume is a no-op")
        return

    chk_path = checkpoint_path or settings.CHECKPOINT_DB_PATH
    config = {"configurable": {"thread_id": review_id}}
    async with AsyncSqliteSaver.from_conn_string(chk_path) as checkpointer:
        graph = create_contract_analysis_graph(checkpointer=checkpointer)
        await graph.ainvoke(Command(resume={"finalized_by": reviewer_name}), config=config)
    logger.info("Resumed and finalized graph workflow for review %s", review_id)


# ------------------------------------------------------------------------------
# High-Level Execution Entry Point (Direct / Script / Benchmark)
# ------------------------------------------------------------------------------


async def analyze_contract(file_path: Union[str, Path]) -> ContractAnalysisResult:
    """Analyze an entire contract document end-to-end.

    Args:
        file_path: Path to the target contract document (.docx or .pdf).

    Returns:
        ContractAnalysisResult containing all per-clause findings and summary.
    """
    path_str = str(Path(file_path).resolve())
    initial_state: ContractState = {"file_path": path_str}

    final_state = await contract_analysis_graph.ainvoke(initial_state)

    if final_state.get("result"):
        return ContractAnalysisResult.model_validate(final_state["result"])

    error_msg = final_state.get("error", "Unknown error during contract processing.")
    raise RuntimeError(f"Contract analysis failed: {error_msg}")
