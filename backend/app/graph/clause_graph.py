"""Per-clause analysis graph built with LangGraph.

Nodes:
1. classify: Assigns the clause a playbook category (or 'other') + confidence.
2. retrieve: Fetches relevant playbook rules (filtered or global fallback).
3. analyze: Evaluates risk level strictly against retrieved rules (Acceptable / Needs Negotiation / Unacceptable).
4. redline: Generates minimal compliant redline (conditional, skipped for Acceptable).
5. ground: Non-LLM verification node checking citation existence, grounding, confidence, and human review flags.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple, TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.graph.prompts import (
    ANALYZE_SYSTEM_PROMPT,
    CLASSIFY_SYSTEM_PROMPT,
    COMBINED_ANALYZE_SYSTEM_PROMPT,
    REDLINE_SYSTEM_PROMPT,
    build_analyze_prompt,
    build_classify_prompt,
    build_combined_analyze_prompt,
    build_redline_prompt,
)
from app.models.schemas import (
    AnalysisOutput,
    ClassificationOutput,
    Clause,
    ClauseAnalysis,
    ClauseTypeEnum,
    CombinedAnalysisOutput,
    PlaybookRule,
    RedlineOutput,
    RiskLevel,
)
from app.services.llm import DailyQuotaExceededError, generate_structured_json
from app.services.playbook import get_rule
from app.services.vector_store import retrieve_rules

logger = logging.getLogger(__name__)


class ClauseState(TypedDict, total=False):
    """Shared state for the per-clause LangGraph workflow."""

    clause: Clause
    clause_type: str
    classification_confidence: float
    classification_reasoning: Optional[str]
    retrieved_rules: List[Tuple[PlaybookRule, float]]
    risk_level: Optional[RiskLevel]
    cited_rule_ids: List[str]
    explanation: Optional[str]
    analysis_confidence: float
    suggested_redline: Optional[str]
    skip_redline: bool
    needs_human_review: bool
    review_reason: Optional[str]
    final_analysis: Optional[ClauseAnalysis]
    error: Optional[str]


# ------------------------------------------------------------------------------
# Node 1: Retrieve (Candidate Rules)
# ------------------------------------------------------------------------------


async def retrieve_node(state: ClauseState) -> Dict[str, Any]:
    """Retrieve relevant candidate playbook rules using semantic search across all rules."""
    # Keep pre-populated rules if provided (e.g. test fixtures)
    if state.get("retrieved_rules") is not None:
        return {"retrieved_rules": state["retrieved_rules"]}

    clause = state["clause"]
    retrieved = await retrieve_rules(
        clause_text=clause.text,
        clause_type=None,
        top_k=settings.DEFAULT_TOP_K,
    )
    return {"retrieved_rules": retrieved}


# Legacy / standalone classify node retained for compatibility if called directly
async def classify_node(state: ClauseState) -> Dict[str, Any]:
    """Classify the clause into one of the 10 playbook clause types or 'other'."""
    clause = state["clause"]
    prompt = build_classify_prompt(
        clause_text=clause.text,
        section_title=clause.title,
    )

    try:
        raw_output = await generate_structured_json(
            prompt=prompt,
            system_instruction=CLASSIFY_SYSTEM_PROMPT,
            response_schema=ClassificationOutput,
        )
        parsed = ClassificationOutput.model_validate(raw_output)
        return {
            "clause_type": parsed.clause_type.value,
            "classification_confidence": parsed.confidence,
            "classification_reasoning": parsed.reasoning,
        }
    except DailyQuotaExceededError:
        raise
    except Exception as exc:
        logger.warning("Classification failed for clause %s: %s", clause.id, exc)
        return {
            "clause_type": "other",
            "classification_confidence": 0.0,
            "classification_reasoning": f"Classification error: {exc}",
            "review_reason": f"Classification error: {exc}",
            "error": str(exc),
        }


# ------------------------------------------------------------------------------
# Node 2: Combined Analyze (Classify + Risk Analysis)
# ------------------------------------------------------------------------------


async def analyze_node(state: ClauseState) -> Dict[str, Any]:
    """Analyze clause: classify category and evaluate risk in a single structured LLM call."""
    clause = state["clause"]
    retrieved_rules = state.get("retrieved_rules", [])

    # If no playbook rules matched, flag for human review
    if not retrieved_rules:
        logger.info("No playbook rules matched for clause %s", clause.id)
        return {
            "clause_type": "other",
            "risk_level": RiskLevel.NEEDS_NEGOTIATION,
            "cited_rule_ids": [],
            "explanation": "No applicable playbook rule found for this clause category.",
            "analysis_confidence": 0.0,
            "needs_human_review": True,
            "review_reason": "No applicable playbook rule",
        }

    prompt = build_combined_analyze_prompt(
        clause_text=clause.text,
        retrieved_rules=retrieved_rules,
        section_number=clause.section_number,
        section_title=clause.title,
    )

    try:
        raw_output = await generate_structured_json(
            prompt=prompt,
            system_instruction=COMBINED_ANALYZE_SYSTEM_PROMPT,
            response_schema=CombinedAnalysisOutput,
        )

        # Support CombinedAnalysisOutput, AnalysisOutput (mock compatibility), and raw dicts
        if isinstance(raw_output, dict) and "clause_type" in raw_output:
            parsed = CombinedAnalysisOutput.model_validate(raw_output)
            c_type = parsed.clause_type.value if hasattr(parsed.clause_type, "value") else str(parsed.clause_type)
            risk = parsed.risk_level
            c_ids = parsed.cited_rule_ids
            expl = parsed.explanation
            conf = parsed.confidence
        elif isinstance(raw_output, dict) and "risk_level" in raw_output:
            parsed_analysis = AnalysisOutput.model_validate(raw_output)
            c_type = state.get("clause_type", "other")
            risk = parsed_analysis.risk_level
            c_ids = parsed_analysis.cited_rule_ids
            expl = parsed_analysis.explanation
            conf = parsed_analysis.confidence
        else:
            parsed = CombinedAnalysisOutput.model_validate(raw_output)
            c_type = parsed.clause_type.value if hasattr(parsed.clause_type, "value") else str(parsed.clause_type)
            risk = parsed.risk_level
            c_ids = parsed.cited_rule_ids
            expl = parsed.explanation
            conf = parsed.confidence

        return {
            "clause_type": c_type,
            "risk_level": risk,
            "cited_rule_ids": c_ids,
            "explanation": expl,
            "analysis_confidence": conf,
        }
    except DailyQuotaExceededError:
        raise
    except Exception as exc:
        logger.warning("Analysis failed for clause %s: %s", clause.id, exc)
        return {
            "clause_type": state.get("clause_type", "other"),
            "risk_level": RiskLevel.NEEDS_NEGOTIATION,
            "cited_rule_ids": [],
            "explanation": f"Analysis execution failure: {exc}",
            "analysis_confidence": 0.0,
            "needs_human_review": True,
            "review_reason": f"Analysis error: {exc}",
            "error": str(exc),
        }


# ------------------------------------------------------------------------------
# Conditional Edge Router
# ------------------------------------------------------------------------------


def should_redline(state: ClauseState) -> str:
    """Route to redline node only if risk level is Needs Negotiation or Unacceptable and redlines are not skipped."""
    if state.get("skip_redline"):
        return "ground"
    risk = state.get("risk_level")
    if risk in (RiskLevel.NEEDS_NEGOTIATION, RiskLevel.UNACCEPTABLE):
        return "redline"
    return "ground"


# ------------------------------------------------------------------------------
# Node 4: Redline
# ------------------------------------------------------------------------------


async def redline_node(state: ClauseState) -> Dict[str, Any]:
    """Generate suggested replacement language adapted to contract terms."""
    clause = state["clause"]
    risk_level = state.get("risk_level", RiskLevel.NEEDS_NEGOTIATION)
    explanation = state.get("explanation", "")
    cited_ids = state.get("cited_rule_ids", [])

    # Gather matching PlaybookRule instances for the cited IDs
    relevant_rules: List[PlaybookRule] = []
    for rid in cited_ids:
        r = get_rule(rid)
        if r and r not in relevant_rules:
            relevant_rules.append(r)

    # Fallback to top retrieved rule if no valid cited rule
    if not relevant_rules and state.get("retrieved_rules"):
        relevant_rules = [state["retrieved_rules"][0][0]]

    prompt = build_redline_prompt(
        clause_text=clause.text,
        risk_level=str(risk_level.value if hasattr(risk_level, "value") else risk_level),
        explanation=explanation,
        cited_rules=relevant_rules,
    )

    try:
        raw_output = await generate_structured_json(
            prompt=prompt,
            system_instruction=REDLINE_SYSTEM_PROMPT,
            response_schema=RedlineOutput,
        )
        parsed = RedlineOutput.model_validate(raw_output)
        return {"suggested_redline": parsed.suggested_redline}
    except DailyQuotaExceededError:
        if state.get("raise_quota_error"):
            raise
        logger.warning("Redline generation skipped due to daily quota limit for clause %s", clause.id)
        return {
            "suggested_redline": None,
            "error": "Daily API quota reached during redline generation",
        }
    except Exception as exc:
        logger.warning("Redline generation failed for clause %s: %s", clause.id, exc)
        return {
            "suggested_redline": None,
            "error": str(exc),
        }


# ------------------------------------------------------------------------------
# Node 5: Ground (Non-LLM Verification)
# ------------------------------------------------------------------------------


def ground_node(state: ClauseState) -> Dict[str, Any]:
    """Non-LLM grounding check validating citations and human review requirements."""
    clause = state["clause"]
    clause_type = state.get("clause_type", "other")
    risk_level = state.get("risk_level", RiskLevel.NEEDS_NEGOTIATION)
    raw_cited_ids = state.get("cited_rule_ids", [])
    explanation = state.get("explanation", "")
    confidence = float(state.get("analysis_confidence", 0.0))
    suggested_redline = state.get("suggested_redline")
    if state.get("skip_redline") and risk_level != RiskLevel.ACCEPTABLE and suggested_redline is None:
        suggested_redline = "pending"
    needs_review = bool(state.get("needs_human_review", False))
    review_reasons: List[str] = []

    if state.get("review_reason"):
        review_reasons.append(state["review_reason"])
    if state.get("error") and not any(str(state["error"]) in r for r in review_reasons):
        review_reasons.append(f"Error: {state['error']}")

    # 1. Grounding verification: Cited rule IDs must exist and be in retrieved rules
    retrieved_rule_ids = {r.rule_id for r, _ in state.get("retrieved_rules", [])}
    valid_cited_ids: List[str] = []

    for rid in raw_cited_ids:
        clean_id = rid.strip()
        rule_in_playbook = get_rule(clean_id) is not None
        rule_in_retrieved = clean_id in retrieved_rule_ids

        if rule_in_playbook and rule_in_retrieved:
            if clean_id not in valid_cited_ids:
                valid_cited_ids.append(clean_id)
        else:
            logger.info(
                "Grounding check removed invalid citation '%s' for clause %s (in_playbook=%s, in_retrieved=%s)",
                clean_id,
                clause.id,
                rule_in_playbook,
                rule_in_retrieved,
            )

    # 2. If non-Acceptable clause has no valid citations after removal
    if risk_level != RiskLevel.ACCEPTABLE and not valid_cited_ids:
        needs_review = True
        review_reasons.append("Non-Acceptable clause lacks grounded playbook citation")
        confidence = min(confidence, 0.4)

    # 3. Low confidence check
    if confidence < settings.CONFIDENCE_THRESHOLD:
        needs_review = True
        review_reasons.append(
            f"Confidence score {confidence:.2f} is below threshold ({settings.CONFIDENCE_THRESHOLD:.2f})"
        )

    # 4. 'other' clause type check
    if clause_type == "other":
        needs_review = True
        review_reasons.append("Clause type was categorized as 'other'")

    # Assemble final ClauseAnalysis object
    final_analysis = ClauseAnalysis(
        clause_id=clause.id,
        clause_type=clause_type,
        risk_level=risk_level,
        cited_rule_ids=valid_cited_ids,
        explanation=explanation,
        suggested_redline=suggested_redline,
        confidence=round(confidence, 2),
        needs_human_review=needs_review,
        review_reason="; ".join(review_reasons) if review_reasons else None,
    )

    return {
        "cited_rule_ids": valid_cited_ids,
        "analysis_confidence": confidence,
        "needs_human_review": needs_review,
        "review_reason": final_analysis.review_reason,
        "final_analysis": final_analysis,
    }


# ------------------------------------------------------------------------------
# Build and Compile Per-Clause Graph
# ------------------------------------------------------------------------------


def create_clause_analysis_graph() -> StateGraph:
    """Build the per-clause LangGraph StateGraph.

    Merged workflow:
    START -> retrieve -> analyze -> should_redline -> (redline -> ground) / ground -> END
    """
    builder = StateGraph(ClauseState)

    builder.add_node("retrieve", retrieve_node)
    builder.add_node("analyze", analyze_node)
    builder.add_node("redline", redline_node)
    builder.add_node("ground", ground_node)

    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "analyze")
    builder.add_conditional_edges(
        "analyze",
        should_redline,
        {
            "redline": "redline",
            "ground": "ground",
        },
    )
    builder.add_edge("redline", "ground")
    builder.add_edge("ground", END)

    return builder.compile()


# Global compiled per-clause graph instance
clause_analysis_graph = create_clause_analysis_graph()
