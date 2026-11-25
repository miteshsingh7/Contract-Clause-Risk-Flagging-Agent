/**
 * TypeScript types mirroring the backend Pydantic schemas.
 */

export type RiskLevel = "Acceptable" | "Needs Negotiation" | "Unacceptable";

export type DecisionStatus = "approved" | "edited" | "rejected";

export type ReviewStatus = "processing" | "awaiting_review" | "finalized" | "failed";

export type DiffType = "equal" | "insert" | "delete";

export interface DiffSegment {
  type: DiffType;
  text: string;
}

export interface PlaybookRule {
  rule_id: string;
  clause_type: string;
  title: string;
  standard_position: string;
  acceptable_fallback: string;
  unacceptable_triggers: string[];
  preferred_language: string;
  rationale: string;
}

export interface ClauseAnalysis {
  clause_id: string;
  clause_type: string;
  risk_level: RiskLevel;
  cited_rule_ids: string[];
  explanation: string;
  suggested_redline?: string | null;
  confidence: number;
  needs_human_review: boolean;
  review_reason?: string | null;
}

export interface ReviewDecisionRecord {
  decision_id: number;
  review_id: string;
  clause_id: string;
  status: DecisionStatus;
  reviewer_name: string;
  reviewer_note?: string | null;
  final_text?: string | null;
  decided_at: string;
}

export interface ClauseWithDecision {
  clause_id: string;
  section_number?: string | null;
  title?: string | null;
  text: string;
  analysis: ClauseAnalysis;
  current_decision?: ReviewDecisionRecord | null;
}

export interface ReviewSummary {
  review_id: string;
  contract_name: string;
  status: ReviewStatus;
  created_at: string;
  finalized_at?: string | null;
  total_clauses: number;
  analyzed_clauses: number;
  acceptable_count: number;
  needs_negotiation_count: number;
  unacceptable_count: number;
  needs_human_review_count: number;
  pending_decisions: number;
  error_message?: string | null;
  disclaimer: string;
}

export interface ReviewDetailResponse {
  review_id: string;
  contract_name: string;
  status: ReviewStatus;
  created_at: string;
  finalized_at?: string | null;
  total_clauses: number;
  analyzed_clauses: number;
  progress: {
    analyzed: number;
    total: number;
  };
  acceptable_count: number;
  needs_negotiation_count: number;
  unacceptable_count: number;
  needs_human_review_count: number;
  pending_decisions: number;
  missing_clause_types: string[];
  clauses: ClauseWithDecision[];
  error_message?: string | null;
  disclaimer: string;
}

export interface ClauseDetailResponse {
  review_id: string;
  clause_id: string;
  section_number?: string | null;
  title?: string | null;
  text: string;
  analysis: ClauseAnalysis;
  suggested_redline?: string | null;
  redline_diff?: DiffSegment[] | null;
  decision_diff?: DiffSegment[] | null;
  cited_rules: PlaybookRule[];
  current_decision?: ReviewDecisionRecord | null;
  decision_history: ReviewDecisionRecord[];
  disclaimer: string;
}

export interface DecisionRequest {
  status: DecisionStatus;
  reviewer_name: string;
  reviewer_note?: string | null;
  final_text?: string | null;
}

export interface FinalizeResponse {
  review_id: string;
  status: ReviewStatus;
  finalized_at: string;
  message: string;
  disclaimer: string;
}

export interface UploadResponse {
  review_id: string;
  contract_name: string;
  status: ReviewStatus;
  disclaimer: string;
}

export interface ReviewStatusResponse {
  review_id: string;
  status: ReviewStatus;
  progress: {
    analyzed: number;
    total: number;
  };
  pending_decisions: number;
  error_message?: string | null;
  disclaimer: string;
}

export interface ApiErrorDetail {
  message?: string;
  pending_clause_ids?: string[];
  pending_count?: number;
}
