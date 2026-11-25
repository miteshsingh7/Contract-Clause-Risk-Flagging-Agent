"""Pydantic schemas and domain models for contract clause analysis and review.

All models adhere to Pydantic v2 conventions and support advisory legal workflows.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class RiskLevel(str, Enum):
    """Categorical risk classification for a contract clause."""

    ACCEPTABLE = "Acceptable"
    NEEDS_NEGOTIATION = "Needs Negotiation"
    UNACCEPTABLE = "Unacceptable"


class DecisionStatus(str, Enum):
    """Human-in-the-loop legal reviewer decision status."""

    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"


class DiffType(str, Enum):
    """Word-level diff operation category."""

    EQUAL = "equal"
    INSERT = "insert"
    DELETE = "delete"


class DiffSegment(BaseModel):
    """Word-level diff segment with operation type and literal text."""

    type: DiffType = Field(
        ...,
        description="Diff operation: 'equal' (unchanged), 'insert' (added), or 'delete' (removed)",
    )
    text: str = Field(
        ...,
        description="Verbatim segment text including whitespace and punctuation",
    )


class ReviewStatus(str, Enum):
    """Lifecycle status of a contract review."""

    PROCESSING = "processing"
    AWAITING_REVIEW = "awaiting_review"
    FINALIZED = "finalized"
    FAILED = "failed"


class ClauseTypeEnum(str, Enum):
    """Standardized clause categories from the playbook plus 'other'."""

    LIMITATION_OF_LIABILITY = "limitation_of_liability"
    INDEMNIFICATION = "indemnification"
    TERMINATION = "termination"
    CONFIDENTIALITY = "confidentiality"
    GOVERNING_LAW = "governing_law"
    IP_OWNERSHIP = "ip_ownership"
    PAYMENT_TERMS = "payment_terms"
    AUTO_RENEWAL = "auto_renewal"
    DATA_PROTECTION = "data_protection"
    ASSIGNMENT = "assignment"
    OTHER = "other"


class PlaybookRule(BaseModel):
    """Defines a negotiation rule for a specific clause type in the corporate playbook."""

    rule_id: str = Field(
        ...,
        description="Unique identifier for the playbook rule (e.g., 'LOL-01')",
        examples=["LOL-01"],
    )
    clause_type: str = Field(
        ...,
        description="Normalized category of the clause (e.g., 'limitation_of_liability')",
        examples=["limitation_of_liability"],
    )
    title: str = Field(
        ...,
        description="Descriptive title of the rule",
        examples=["Aggregate Liability Cap"],
    )
    standard_position: str = Field(
        ...,
        description="Company's primary preferred contractual stance",
    )
    acceptable_fallback: str = Field(
        ...,
        description="Compromise position acceptable during negotiation without escalation",
    )
    unacceptable_triggers: List[str] = Field(
        default_factory=list,
        description="Conditions, terms, or phrases that trigger an 'Unacceptable' risk rating",
    )
    preferred_language: str = Field(
        ...,
        description="Model clause language representing the company standard",
    )
    rationale: str = Field(
        ...,
        description="Business or legal reasoning supporting this rule",
    )


class Clause(BaseModel):
    """Extracted clause from a contract document."""

    id: str = Field(
        ...,
        description="Unique clause identifier within the document (e.g., 'clause-1')",
    )
    section_number: Optional[str] = Field(
        default=None,
        description="Document section number (e.g., 'Section 4.1')",
    )
    title: Optional[str] = Field(
        default=None,
        description="Clause or section heading title",
    )
    text: str = Field(
        ...,
        description="Full verbatim text of the contract clause",
    )
    clause_type: Optional[str] = Field(
        default=None,
        description="Categorized clause type if identified during classification",
    )


class ClauseAnalysis(BaseModel):
    """Advisory analysis result for an individual contract clause."""

    clause_id: str = Field(
        ...,
        description="Reference to the analyzed Clause id",
    )
    clause_type: str = Field(
        ...,
        description="Identified clause category evaluated against the playbook",
    )
    risk_level: RiskLevel = Field(
        ...,
        description="Evaluated risk level: 'Acceptable', 'Needs Negotiation', or 'Unacceptable'",
    )
    cited_rule_ids: List[str] = Field(
        default_factory=list,
        description="List of playbook rule IDs that informed this analysis",
    )
    explanation: str = Field(
        ...,
        description="Clear legal/business rationale explaining why this risk level was assigned",
    )
    suggested_redline: Optional[str] = Field(
        default=None,
        description="Proposed redline or replacement language when negotiation is required",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Model confidence score between 0.0 and 1.0",
    )
    needs_human_review: bool = Field(
        default=False,
        description="Flag indicating this clause requires human legal review",
    )
    review_reason: Optional[str] = Field(
        default=None,
        description="Reason human review was requested (e.g. low confidence, ungrounded citation, unclassified clause)",
    )


class ReviewDecision(BaseModel):
    """Human legal reviewer's feedback and decision on an analyzed clause."""

    clause_id: str = Field(
        ...,
        description="ID of the clause being reviewed",
    )
    status: DecisionStatus = Field(
        ...,
        description="Reviewer decision: 'approved', 'edited', or 'rejected'",
    )
    reviewer_note: Optional[str] = Field(
        default=None,
        description="Optional commentary or feedback provided by the reviewer",
    )
    final_text: Optional[str] = Field(
        default=None,
        description="Approved final clause text (incorporating any reviewer edits)",
    )
    reviewed_by: Optional[str] = Field(
        default=None,
        description="Identifier or name of the qualified legal reviewer",
    )
    reviewed_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when the decision was recorded",
    )


class ParsedParagraph(BaseModel):
    """An individual paragraph extracted by the document parser preserving structural metadata."""

    text: str = Field(
        ...,
        description="Verbatim paragraph text",
    )
    style_name: Optional[str] = Field(
        default="Normal",
        description="Original heading or paragraph style name (e.g. 'Heading 1', 'Normal')",
    )
    is_heading: bool = Field(
        default=False,
        description="True if paragraph represents a heading or section title",
    )
    heading_level: Optional[int] = Field(
        default=None,
        description="Heading level (1 for top-level, 2 for sub-headings) if applicable",
    )
    order_index: int = Field(
        default=0,
        description="Sequential index of the paragraph in the original document",
    )


class ParsedDocument(BaseModel):
    """Document representation produced by the parsing layer preserving paragraph order."""

    contract_name: str = Field(
        ...,
        description="Filename or identifier of the parsed contract",
    )
    file_type: str = Field(
        ...,
        description="Source document format (e.g., 'docx', 'pdf')",
    )
    file_path: Optional[str] = Field(
        default=None,
        description="Absolute or relative file path on disk",
    )
    paragraphs: List[ParsedParagraph] = Field(
        default_factory=list,
        description="Ordered list of extracted paragraphs",
    )

    @property
    def total_paragraphs(self) -> int:
        """Return total number of extracted paragraphs."""
        return len(self.paragraphs)


class SegmentationResult(BaseModel):
    """Structured result of segmenting a parsed contract into clauses and non-substantive elements."""

    contract_name: str = Field(
        ...,
        description="Name of the processed contract",
    )
    clauses: List[Clause] = Field(
        default_factory=list,
        description="List of substantive business clauses extracted from the document",
    )
    preamble: Optional[str] = Field(
        default=None,
        description="Preamble, introductory recital, or parties block marked as non-substantive",
    )
    definitions: Optional[Clause] = Field(
        default=None,
        description="Extracted definitions section (if present), kept separate from substantive clauses",
    )
    signature_block: Optional[str] = Field(
        default=None,
        description="Signature block at the end of the document marked as non-substantive",
    )
    total_substantive_clauses: int = Field(
        default=0,
        description="Total count of substantive clauses",
    )


class MergeCorrection(BaseModel):
    """Instruction for LLM refinement to merge mistakenly split clauses."""

    clause_ids: List[str] = Field(
        ...,
        description="Consecutive clause IDs that belong to the same top-level clause and should be merged",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Rationale explaining why these clauses should be merged",
    )


class SplitCorrection(BaseModel):
    """Instruction for LLM refinement to split mistakenly merged clauses."""

    clause_id: str = Field(
        ...,
        description="ID of the clause that should be split",
    )
    split_after_text: str = Field(
        ...,
        description="Exact substring in the clause text after which the split should occur",
    )
    new_clause_title: Optional[str] = Field(
        default=None,
        description="Proposed title for the newly created second clause",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Rationale explaining why this clause should be split",
    )


class RefinementPlan(BaseModel):
    """Structured correction plan proposed by the LLM refinement pass."""

    has_corrections: bool = Field(
        default=False,
        description="True if boundary corrections (merges or splits) are required",
    )
    merges: List[MergeCorrection] = Field(
        default_factory=list,
        description="List of merge instructions",
    )
    splits: List[SplitCorrection] = Field(
        default_factory=list,
        description="List of split instructions",
    )
    explanation: Optional[str] = Field(
        default=None,
        description="Summary explanation of the boundary assessment",
    )


class RuleSearchResult(BaseModel):
    """Playbook rule matched from semantic vector search along with its similarity score."""

    rule: PlaybookRule = Field(
        ...,
        description="Matched playbook rule object",
    )
    similarity_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Normalized semantic similarity score between 0.0 and 1.0",
    )


class PlaybookSearchRequest(BaseModel):
    """Request payload for semantic playbook rule search."""

    clause_text: str = Field(
        ...,
        description="Contract clause text to match against the playbook",
        min_length=1,
    )
    clause_type: Optional[str] = Field(
        default=None,
        description="Optional clause type to filter search (e.g. 'limitation_of_liability')",
    )
    top_k: Optional[int] = Field(
        default=None,
        ge=1,
        le=20,
        description="Number of top matching rules to return (defaults to system setting)",
    )


class PlaybookSearchResponse(BaseModel):
    """Response payload for semantic playbook rule search."""

    query: str = Field(
        ...,
        description="Original query clause text",
    )
    clause_type: Optional[str] = Field(
        default=None,
        description="Clause type filter applied (if any)",
    )
    total_results: int = Field(
        ...,
        description="Number of matching rules returned",
    )
    results: List[RuleSearchResult] = Field(
        default_factory=list,
        description="Ranked list of matching playbook rules with similarity scores",
    )


class PlaybookReindexRequest(BaseModel):
    """Request payload for rebuilding or re-ingesting the playbook vector store."""

    rebuild: bool = Field(
        default=True,
        description="If True, clears existing vector collection before re-ingesting",
    )


class PlaybookReindexResponse(BaseModel):
    """Response payload for playbook reindexing."""

    status: str = Field(
        default="ok",
        description="Operation status",
    )
    indexed_count: int = Field(
        ...,
        description="Total number of rules indexed into ChromaDB",
    )
    collection_name: str = Field(
        ...,
        description="Name of the ChromaDB collection",
    )


class ClassificationOutput(BaseModel):
    """Structured output from LLM clause classification node."""

    clause_type: ClauseTypeEnum = Field(
        ...,
        description="Classified category from the 10 playbook clause types, or 'other'",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Classification confidence score between 0.0 and 1.0",
    )
    reasoning: Optional[str] = Field(
        default=None,
        description="Brief justification for why this category was selected",
    )


class AnalysisOutput(BaseModel):
    """Structured output from LLM clause risk analysis node."""

    risk_level: RiskLevel = Field(
        ...,
        description="Evaluated risk: 'Acceptable', 'Needs Negotiation', or 'Unacceptable'",
    )
    cited_rule_ids: List[str] = Field(
        default_factory=list,
        description="List of exact playbook rule IDs that justify this rating (e.g. ['LOL-01'])",
    )
    explanation: str = Field(
        ...,
        description="Plain-language explanation identifying the specific standard position, fallback, or trigger",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Analysis confidence score between 0.0 and 1.0",
    )


class CombinedAnalysisOutput(BaseModel):
    """Structured output from merged classify & analyze node."""

    clause_type: ClauseTypeEnum = Field(
        ...,
        description="Classified category from the 10 playbook clause types, or 'other'",
    )
    risk_level: RiskLevel = Field(
        ...,
        description="Evaluated risk: 'Acceptable', 'Needs Negotiation', or 'Unacceptable'",
    )
    cited_rule_ids: List[str] = Field(
        default_factory=list,
        description="List of exact playbook rule IDs that justify this rating (e.g. ['LOL-01'])",
    )
    explanation: str = Field(
        ...,
        description="Plain-language explanation identifying the specific standard position, fallback, or trigger",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Overall evaluation confidence score between 0.0 and 1.0",
    )


class RedlineOutput(BaseModel):
    """Structured output from LLM redline generation node."""

    suggested_redline: str = Field(
        ...,
        description="Proposed replacement clause text incorporating playbook position and contract party names",
    )
    summary_of_changes: Optional[str] = Field(
        default=None,
        description="Brief summary of specific modifications introduced in the redline",
    )


class ContractAnalysisResult(BaseModel):
    """Aggregated contract analysis result produced by the contract-level pipeline."""

    contract_name: str = Field(
        ...,
        description="Filename or name of the analyzed contract",
    )
    analyses: List[ClauseAnalysis] = Field(
        default_factory=list,
        description="Per-clause risk analyses in document order",
    )
    missing_clause_types: List[str] = Field(
        default_factory=list,
        description="Playbook clause types not identified in any substantive clause",
    )
    total_clauses: int = Field(
        default=0,
        description="Total number of evaluated substantive clauses",
    )
    acceptable_count: int = Field(
        default=0,
        description="Total clauses rated Acceptable",
    )
    needs_negotiation_count: int = Field(
        default=0,
        description="Total clauses rated Needs Negotiation",
    )
    unacceptable_count: int = Field(
        default=0,
        description="Total clauses rated Unacceptable",
    )
    needs_human_review_count: int = Field(
        default=0,
        description="Total clauses flagged for manual human legal review",
    )
    disclaimer: str = Field(
        default=(
            "ADVISORY ONLY: Recommendations are based on the company negotiation playbook. "
            "Qualified legal professionals must review and approve all clauses and redlines."
        ),
        description="Mandatory advisory notice",
    )


# ------------------------------------------------------------------------------
# Review & Human Decision API Models
# ------------------------------------------------------------------------------


class DecisionRequest(BaseModel):
    """Payload for submitting or updating a human reviewer decision on a clause."""

    status: DecisionStatus = Field(
        ...,
        description="Reviewer decision: 'approved', 'edited', or 'rejected'",
    )
    reviewer_name: str = Field(
        ...,
        min_length=1,
        description="Name or identifier of the qualified legal reviewer",
    )
    reviewer_note: Optional[str] = Field(
        default=None,
        description="Commentary explaining the decision (mandatory for 'rejected')",
    )
    final_text: Optional[str] = Field(
        default=None,
        description="Final modified clause text (mandatory for 'edited')",
    )

    @model_validator(mode="after")
    def validate_decision_rules(self) -> "DecisionRequest":
        clean_name = self.reviewer_name.strip()
        if not clean_name:
            raise ValueError("reviewer_name must not be empty or whitespace")
        self.reviewer_name = clean_name

        if self.status == DecisionStatus.EDITED:
            if not self.final_text or not self.final_text.strip():
                raise ValueError("final_text is required when decision status is 'edited'")
        elif self.status == DecisionStatus.REJECTED:
            if not self.reviewer_note or not self.reviewer_note.strip():
                raise ValueError("reviewer_note is required when decision status is 'rejected'")
        return self


class ReviewDecisionRecord(BaseModel):
    """Immutable audit trail record for a single reviewer decision event."""

    decision_id: int
    review_id: str
    clause_id: str
    status: DecisionStatus
    reviewer_name: str
    reviewer_note: Optional[str] = None
    final_text: Optional[str] = None
    decided_at: str


class ReportClauseItem(BaseModel):
    """Structured clause item compiled for deterministic report generation."""

    clause_id: str
    section_number: Optional[str] = None
    title: Optional[str] = None
    clause_type: str
    risk_level: RiskLevel
    confidence: float
    needs_human_review: bool = False
    review_reason: Optional[str] = None
    original_text: str
    suggested_redline: Optional[str] = None
    redline_diff: List[DiffSegment] = Field(default_factory=list)
    cited_rules: List[PlaybookRule] = Field(default_factory=list)
    explanation: str
    decision: Optional[ReviewDecisionRecord] = None
    decision_diff: Optional[List[DiffSegment]] = None
    resulting_text: str
    resulting_text_source: str


class ReviewReport(BaseModel):
    """Comprehensive contract review report compiling all clause analyses and reviewer decisions."""

    report_id: str = Field(
        ...,
        description="Unique identifier for this review report",
    )
    contract_name: str = Field(
        ...,
        description="Name or filename of the evaluated contract",
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when the report was generated",
    )
    total_clauses: int = Field(
        ...,
        description="Total number of evaluated clauses",
    )
    acceptable_count: int = Field(
        ...,
        description="Number of clauses rated 'Acceptable'",
    )
    needs_negotiation_count: int = Field(
        ...,
        description="Number of clauses rated 'Needs Negotiation'",
    )
    unacceptable_count: int = Field(
        ...,
        description="Number of clauses rated 'Unacceptable'",
    )
    analyses: List[ClauseAnalysis] = Field(
        default_factory=list,
        description="Detailed clause analysis records",
    )
    decisions: Optional[List[ReviewDecision]] = Field(
        default=None,
        description="Human reviewer decisions corresponding to the analyses",
    )
    summary: Optional[str] = Field(
        default=None,
        description="Executive summary of key findings and negotiation posture",
    )
    disclaimer: str = Field(
        default=(
            "ADVISORY ONLY: This report is generated by an automated assistant and "
            "does not constitute formal legal advice. Qualified legal counsel must "
            "review and approve all clauses and redlines."
        ),
        description="Mandatory legal disclaimer",
    )

    # Extended Report Builder Fields (Step 6)
    review_id: Optional[str] = Field(
        default=None,
        description="Associated review identifier",
    )
    uploaded_at: Optional[str] = Field(
        default=None,
        description="Timestamp when contract was uploaded",
    )
    finalized_at: Optional[str] = Field(
        default=None,
        description="Timestamp when review was finalized",
    )
    reviewers: List[str] = Field(
        default_factory=list,
        description="List of distinct legal reviewer names involved",
    )
    needs_human_review_count: int = Field(
        default=0,
        description="Total clauses flagged for manual human review",
    )
    approved_count: int = Field(
        default=0,
        description="Total clauses with approved decisions",
    )
    edited_count: int = Field(
        default=0,
        description="Total clauses with edited decisions",
    )
    rejected_count: int = Field(
        default=0,
        description="Total clauses with rejected decisions",
    )
    highest_risk_clauses: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of highest-risk clauses (Unacceptable first) with section numbers",
    )
    missing_clause_types: List[str] = Field(
        default_factory=list,
        description="Playbook clause types missing from the contract (informational)",
    )
    clauses: List[ReportClauseItem] = Field(
        default_factory=list,
        description="Detailed per-clause report items in section order",
    )
    appendix_decision_history: Dict[str, List[ReviewDecisionRecord]] = Field(
        default_factory=dict,
        description="Full append-only audit trail per clause",
    )
    resulting_text_rule_note: str = Field(
        default=(
            "RESULTING CLAUSE TEXT RULE: The resulting text per clause represents: "
            "(1) the reviewer final_text if edited, "
            "(2) the AI-suggested redline if approved, or "
            "(3) the original contract text if rejected or if compliant without changes."
        ),
        description="Explicit rule defining resulting clause text computation",
    )


class ClauseWithDecision(BaseModel):
    """Clause text and analysis combined with current human review decision."""

    clause_id: str
    section_number: Optional[str] = None
    title: Optional[str] = None
    text: str
    analysis: ClauseAnalysis
    current_decision: Optional[ReviewDecisionRecord] = None


class ReviewSummary(BaseModel):
    """High-level summary of a contract review for listing endpoints."""

    review_id: str
    contract_name: str
    status: ReviewStatus
    created_at: str
    finalized_at: Optional[str] = None
    total_clauses: int = 0
    analyzed_clauses: int = 0
    acceptable_count: int = 0
    needs_negotiation_count: int = 0
    unacceptable_count: int = 0
    needs_human_review_count: int = 0
    pending_decisions: int = 0
    error_message: Optional[str] = None
    disclaimer: str = Field(
        default=(
            "ADVISORY ONLY: Recommendations are based on the company negotiation playbook. "
            "Qualified legal professionals must review and approve all clauses and redlines."
        )
    )


class ReviewDetailResponse(BaseModel):
    """Comprehensive contract review details with all clauses and decisions."""

    review_id: str
    contract_name: str
    status: ReviewStatus
    created_at: str
    finalized_at: Optional[str] = None
    total_clauses: int = 0
    analyzed_clauses: int = 0
    progress: Dict[str, int]
    acceptable_count: int = 0
    needs_negotiation_count: int = 0
    unacceptable_count: int = 0
    needs_human_review_count: int = 0
    pending_decisions: int = 0
    missing_clause_types: List[str] = Field(default_factory=list)
    clauses: List[ClauseWithDecision] = Field(default_factory=list)
    error_message: Optional[str] = None
    disclaimer: str = Field(
        default=(
            "ADVISORY ONLY: Recommendations are based on the company negotiation playbook. "
            "Qualified legal professionals must review and approve all clauses and redlines."
        )
    )


class ClauseDetailResponse(BaseModel):
    """Detailed view of an individual clause with full playbook rules and history."""

    review_id: str
    clause_id: str
    section_number: Optional[str] = None
    title: Optional[str] = None
    text: str
    analysis: ClauseAnalysis
    suggested_redline: Optional[str] = None
    redline_diff: Optional[List[DiffSegment]] = None
    decision_diff: Optional[List[DiffSegment]] = None
    cited_rules: List[PlaybookRule] = Field(default_factory=list)
    current_decision: Optional[ReviewDecisionRecord] = None
    decision_history: List[ReviewDecisionRecord] = Field(default_factory=list)
    disclaimer: str = Field(
        default=(
            "ADVISORY ONLY: Recommendations are based on the company negotiation playbook. "
            "Qualified legal professionals must review and approve all clauses and redlines."
        )
    )


class FinalizeResponse(BaseModel):
    """Response returned upon successful review finalization."""

    review_id: str
    status: ReviewStatus
    finalized_at: str
    message: str = "Review finalized successfully."
    disclaimer: str = Field(
        default=(
            "ADVISORY ONLY: Recommendations are based on the company negotiation playbook. "
            "Qualified legal professionals must review and approve all clauses and redlines."
        )
    )


class UploadResponse(BaseModel):
    """Response returned upon contract upload."""

    review_id: str
    contract_name: str
    status: ReviewStatus
    disclaimer: str = Field(
        default=(
            "ADVISORY ONLY: Recommendations are based on the company negotiation playbook. "
            "Qualified legal professionals must review and approve all clauses and redlines."
        )
    )


class ReviewStatusResponse(BaseModel):
    """Lightweight response for status polling."""

    review_id: str
    status: ReviewStatus
    progress: Dict[str, int]
    pending_decisions: int = 0
    error_message: Optional[str] = None
    disclaimer: str = Field(
        default=(
            "ADVISORY ONLY: Recommendations are based on the company negotiation playbook. "
            "Qualified legal professionals must review and approve all clauses and redlines."
        )
    )
