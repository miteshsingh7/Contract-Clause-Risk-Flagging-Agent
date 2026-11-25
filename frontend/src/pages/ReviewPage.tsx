import React, { useState, useEffect, useRef, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import {
  AlertTriangle,
  AlertCircle,
  Download,
  Lock,
  RefreshCw,
  Search,
  ChevronDown,
  ChevronUp,
  ArrowLeft,
  XCircle,
} from "lucide-react";
import {
  getReview,
  getReviewStatus,
  getClauseDetail,
  submitDecision,
  finalizeReview,
  downloadReport,
  ApiError,
} from "../api/client";
import {
  ClauseDetailResponse,
  DecisionStatus,
  ReviewDetailResponse,
} from "../api/types";
import { RiskBadge } from "../components/RiskBadge";
import { DecisionBadge } from "../components/DecisionBadge";
import { DiffViewer } from "../components/DiffViewer";
import { PlaybookRuleCard } from "../components/PlaybookRuleCard";
import { FinalizeModal } from "../components/FinalizeModal";

interface ReviewPageProps {
  reviewerName: string;
}

export const ReviewPage: React.FC<ReviewPageProps> = ({ reviewerName }) => {
  const { reviewId } = useParams<{ reviewId: string }>();

  // Review & Polling State
  const [review, setReview] = useState<ReviewDetailResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [pendingErrorClauses, setPendingErrorClauses] = useState<string[]>([]);

  // Selected Clause State
  const [selectedClauseId, setSelectedClauseId] = useState<string | null>(null);
  const [clauseDetail, setClauseDetail] = useState<ClauseDetailResponse | null>(null);
  const [isLoadingClause, setIsLoadingClause] = useState(false);

  // Filters State
  const [filterRisk, setFilterRisk] = useState<string>("ALL");
  const [filterDecision, setFilterDecision] = useState<string>("ALL");
  const [filterOnlyNeedsAttention, setFilterOnlyNeedsAttention] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [showExtraFilters, setShowExtraFilters] = useState(false);

  // Missing clauses & Resulting text accordions
  const [isMissingClausesOpen, setIsMissingClausesOpen] = useState(false);
  const [isResultingOpen, setIsResultingOpen] = useState(false);

  // Decision Form State
  const [decisionAction, setDecisionAction] = useState<DecisionStatus>("approved");
  const [decisionNote, setDecisionNote] = useState("");
  const [decisionFinalText, setDecisionFinalText] = useState("");
  const [formValidationError, setFormValidationError] = useState<string | null>(null);
  const [isSubmittingDecision, setIsSubmittingDecision] = useState(false);

  // Finalize Modal State
  const [isFinalizeModalOpen, setIsFinalizeModalOpen] = useState(false);
  const [isFinalizing, setIsFinalizing] = useState(false);

  // Report Download State
  const [isDownloadingReport, setIsDownloadingReport] = useState<string | null>(null);

  // List Ref for Keyboard Navigation
  const clauseListRef = useRef<HTMLElement>(null);

  // Fetch Review Data
  const loadReviewData = useCallback(async () => {
    if (!reviewId) return;
    try {
      const data = await getReview(reviewId);
      setReview(data);

      // Auto-select first clause if none selected
      if (!selectedClauseId && data.clauses.length > 0) {
        setSelectedClauseId(data.clauses[0].clause_id);
      }
    } catch (err: any) {
      setErrorMessage(err?.message || "Failed to load contract review.");
    } finally {
      setIsLoading(false);
    }
  }, [reviewId, selectedClauseId]);

  // Initial Load
  useEffect(() => {
    loadReviewData();
  }, [loadReviewData]);

  // Polling for Processing State
  useEffect(() => {
    if (!reviewId || !review || review.status !== "processing") return;

    const intervalId = setInterval(async () => {
      try {
        const statusData = await getReviewStatus(reviewId);
        if (statusData.status !== "processing") {
          clearInterval(intervalId);
          loadReviewData();
        } else {
          setReview((prev) =>
            prev
              ? {
                  ...prev,
                  progress: statusData.progress,
                  status: statusData.status,
                }
              : null
          );
        }
      } catch {
        clearInterval(intervalId);
      }
    }, 2500);

    return () => clearInterval(intervalId);
  }, [reviewId, review?.status, loadReviewData]);

  // Fetch Clause Detail when selected clause changes
  useEffect(() => {
    if (!reviewId || !selectedClauseId) return;

    let isMounted = true;
    setIsLoadingClause(true);
    setFormValidationError(null);

    getClauseDetail(reviewId, selectedClauseId)
      .then((data) => {
        if (!isMounted) return;
        setClauseDetail(data);

        // Pre-fill decision form values
        if (data.current_decision) {
          setDecisionAction(data.current_decision.status);
          setDecisionNote(data.current_decision.reviewer_note || "");
          setDecisionFinalText(
            data.current_decision.final_text ||
              data.suggested_redline ||
              data.text
          );
        } else {
          if (data.analysis.risk_level === "Acceptable") {
            setDecisionAction("approved");
          } else {
            setDecisionAction(data.suggested_redline ? "approved" : "edited");
          }
          setDecisionNote("");
          setDecisionFinalText(data.suggested_redline || data.text);
        }
      })
      .catch((err) => {
        if (!isMounted) return;
        setErrorMessage(err?.message || "Failed to load clause detail.");
      })
      .finally(() => {
        if (isMounted) setIsLoadingClause(false);
      });

    return () => {
      isMounted = false;
    };
  }, [reviewId, selectedClauseId]);

  // Filter clauses
  const filteredClauses = (review?.clauses || []).filter((item) => {
    if (filterRisk !== "ALL" && item.analysis.risk_level !== filterRisk) {
      return false;
    }
    if (filterDecision !== "ALL") {
      const decStatus = item.current_decision?.status || "pending";
      if (decStatus !== filterDecision) return false;
    }
    if (filterOnlyNeedsAttention) {
      const isCompliant =
        item.analysis.risk_level === "Acceptable" && !item.analysis.needs_human_review;
      const isAlreadyDecided = !!item.current_decision;
      if (isCompliant || isAlreadyDecided) return false;
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchTitle = (item.title || "").toLowerCase().includes(q);
      const matchSec = (item.section_number || "").toLowerCase().includes(q);
      const matchText = item.text.toLowerCase().includes(q);
      const matchType = item.analysis.clause_type.toLowerCase().includes(q);
      if (!matchTitle && !matchSec && !matchText && !matchType) return false;
    }
    return true;
  });

  // Keyboard navigation between clauses (Up / Down arrows)
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return;
      }
      if (filteredClauses.length === 0) return;

      const currentIndex = filteredClauses.findIndex(
        (c) => c.clause_id === selectedClauseId
      );

      if (e.key === "ArrowDown") {
        e.preventDefault();
        const nextIndex = Math.min(currentIndex + 1, filteredClauses.length - 1);
        setSelectedClauseId(filteredClauses[nextIndex].clause_id);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        const prevIndex = Math.max(currentIndex - 1, 0);
        setSelectedClauseId(filteredClauses[prevIndex].clause_id);
      }
    },
    [filteredClauses, selectedClauseId]
  );

  // Submit Decision
  const handleDecisionSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!reviewId || !selectedClauseId || !review || isSubmittingDecision) return;

    if (!reviewerName.trim()) {
      setFormValidationError(
        "Reviewer Name is required. Please set your name in the top navigation bar."
      );
      return;
    }

    if (decisionAction === "edited" && !decisionFinalText.trim()) {
      setFormValidationError("Final clause text is required when decision status is 'Edited'.");
      return;
    }

    if (decisionAction === "rejected" && !decisionNote.trim()) {
      setFormValidationError("Reviewer note is required when decision status is 'Rejected'.");
      return;
    }

    setFormValidationError(null);
    setIsSubmittingDecision(true);

    try {
      await submitDecision(reviewId, selectedClauseId, {
        status: decisionAction,
        reviewer_name: reviewerName.trim(),
        reviewer_note: decisionNote.trim() || null,
        final_text: decisionAction === "edited" ? decisionFinalText.trim() : null,
      });

      await Promise.all([
        loadReviewData(),
        getClauseDetail(reviewId, selectedClauseId).then(setClauseDetail),
      ]);
    } catch (err: any) {
      setFormValidationError(err?.message || "Failed to submit decision.");
    } finally {
      setIsSubmittingDecision(false);
    }
  };

  // Finalize Review
  const handleFinalizeConfirm = async () => {
    if (!reviewId || isFinalizing) return;
    setIsFinalizing(true);
    setPendingErrorClauses([]);
    setErrorMessage(null);

    try {
      await finalizeReview(reviewId);
      setIsFinalizeModalOpen(false);
      await loadReviewData();
    } catch (err: any) {
      setIsFinalizeModalOpen(false);
      if (err instanceof ApiError && err.status === 409) {
        setErrorMessage(err.message);
        if (err.pendingClauseIds) {
          setPendingErrorClauses(err.pendingClauseIds);
        }
      } else {
        setErrorMessage(err?.message || "Failed to finalize review.");
      }
    } finally {
      setIsFinalizing(false);
    }
  };

  // Handle Report Downloads
  const handleDownload = async (format: "json" | "md" | "docx") => {
    if (!reviewId || !review) return;
    setIsDownloadingReport(format);
    try {
      await downloadReport(reviewId, format, review.contract_name);
    } catch (err: any) {
      alert(`Download error: ${err?.message || "Failed to download report."}`);
    } finally {
      setIsDownloadingReport(null);
    }
  };

  // Resulting clause text computation helper
  const getResultingTextInfo = () => {
    if (!clauseDetail) return null;
    const dec = clauseDetail.current_decision;

    if (dec && dec.status === "edited") {
      return {
        text: dec.final_text || clauseDetail.text,
        source: "edited by legal reviewer",
      };
    }
    if (dec && dec.status === "approved") {
      return {
        text: clauseDetail.suggested_redline || clauseDetail.text,
        source: clauseDetail.suggested_redline
          ? "suggested redline approved"
          : "original text approved without changes",
      };
    }
    if (dec && dec.status === "rejected") {
      return {
        text: clauseDetail.text,
        source: "original text (suggested redline rejected)",
      };
    }
    return {
      text: clauseDetail.text,
      source: "original text (pending / no changes)",
    };
  };

  // Loading state
  if (isLoading) {
    return (
      <div className="max-w-[1392px] mx-auto px-6 py-20 text-center text-[#6B7480]">
        <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-3" />
        <p className="text-[14px]">Loading review session...</p>
      </div>
    );
  }

  // Missing/Error state
  if (!review) {
    return (
      <div className="max-w-xl mx-auto px-6 py-20 text-center">
        <div className="bg-[#F7F5F1] border border-[#D9D5CC] rounded-[6px] p-8">
          <AlertCircle className="w-10 h-10 text-[#A4493D] mx-auto mb-3" />
          <h2 className="text-[18px] font-medium text-[#22303C] mb-1">
            Contract Review Not Found
          </h2>
          <p className="text-[14px] text-[#6B7480] mb-6">
            {errorMessage || "Invalid review ID."}
          </p>
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 px-[18px] py-2 rounded-[6px] bg-[#22303C] text-white text-[14px] font-medium"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Contracts
          </Link>
        </div>
      </div>
    );
  }

  // Processing View
  if (review.status === "processing") {
    const analyzed = review.progress.analyzed || 0;
    const total = review.progress.total || 10;
    const percent = Math.min(Math.round((analyzed / Math.max(total, 1)) * 100), 99);

    return (
      <div className="max-w-xl mx-auto px-6 py-20 text-center">
        <div className="bg-[#F7F5F1] border border-[#D9D5CC] rounded-[6px] p-8">
          <div className="w-12 h-12 rounded-full border border-[#D9D5CC] bg-[#EFECE6] text-[#22303C] flex items-center justify-center mx-auto mb-5">
            <RefreshCw className="w-5 h-5 animate-spin" />
          </div>
          <h2 className="text-[18px] font-medium text-[#22303C] mb-2">
            Analyzing Contract Clauses...
          </h2>
          <p className="text-[14px] text-[#6B7480] mb-6">
            Segmenting <strong className="text-[#22303C] font-medium">{review.contract_name}</strong> and evaluating substantive clauses against the negotiation playbook.
          </p>

          <div className="w-full bg-[#EFECE6] rounded-full h-2.5 mb-3 overflow-hidden border border-[#D9D5CC]">
            <div
              className="bg-[#22303C] h-2.5 rounded-full transition-all duration-500 ease-out"
              style={{ width: `${percent}%` }}
            />
          </div>
          <div className="flex justify-between text-[13px] text-[#6B7480]">
            <span>
              {analyzed} of {total} clauses evaluated
            </span>
            <span>{percent}%</span>
          </div>
        </div>
      </div>
    );
  }

  // Failed View
  if (review.status === "failed") {
    return (
      <div className="max-w-2xl mx-auto px-6 py-20 text-center">
        <div className="bg-[#F7F5F1] border border-[#D9D5CC] rounded-[6px] p-8">
          <XCircle className="w-10 h-10 text-[#A4493D] mx-auto mb-3" />
          <h2 className="text-[18px] font-medium text-[#22303C] mb-2">
            Analysis Execution Failed
          </h2>
          <p className="text-[14px] text-[#6B7480] mb-4 leading-relaxed">
            The automated analysis pipeline encountered an error processing{" "}
            <strong className="text-[#22303C] font-medium">{review.contract_name}</strong>.
          </p>
          {review.error_message && (
            <div className="p-3 bg-[#EFECE6] border border-[#A4493D] rounded-[6px] text-[13px] font-mono text-[#A4493D] text-left mb-6 max-h-40 overflow-y-auto">
              {review.error_message}
            </div>
          )}
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 px-[18px] py-2 rounded-[6px] bg-[#22303C] text-white text-[14px] font-medium"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Contracts
          </Link>
        </div>
      </div>
    );
  }

  const isFinalized = review.status === "finalized";
  const resultingInfo = getResultingTextInfo();

  return (
    <div className="outline-none" onKeyDown={handleKeyDown} tabIndex={0}>
      {/* Summary Row & Contract Context */}
      <div className="px-6 pb-6">
        <div className="max-w-[1392px] mx-auto space-y-3">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <Link
                to="/"
                className="text-[#6B7480] hover:text-[#22303C] transition-colors inline-flex items-center gap-1 text-[13px]"
                title="Back to contracts"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                <span>Contracts</span>
              </Link>
              <span className="text-[#D9D5CC]">/</span>
              <span className="text-[15px] font-medium text-[#22303C] truncate max-w-md">
                {review.contract_name}
              </span>
              <span className="text-[#6B7480]">·</span>
              {isFinalized ? (
                <span className="inline-flex items-center gap-1 text-[13px] text-[#5E7A63] font-medium">
                  <Lock className="w-3.5 h-3.5" />
                  Finalized
                </span>
              ) : (
                <span className="text-[13px] text-[#9A7B2F]">Awaiting review</span>
              )}
            </div>

            {isFinalized && (
              <div className="flex flex-wrap items-center gap-2 text-[13px]">
                <span className="text-[#6B7480] inline-flex items-center gap-1.5 mr-1">
                  <Download className="w-3.5 h-3.5" />
                  Export:
                </span>
                <button
                  type="button"
                  onClick={() => handleDownload("md")}
                  disabled={isDownloadingReport !== null}
                  className="px-3 py-1 rounded-[6px] border border-[#D9D5CC] bg-[#F7F5F1] text-[#22303C] hover:border-[#22303C] transition-colors"
                >
                  {isDownloadingReport === "md" ? "..." : "Markdown"}
                </button>
                <button
                  type="button"
                  onClick={() => handleDownload("docx")}
                  disabled={isDownloadingReport !== null}
                  className="px-3 py-1 rounded-[6px] border border-[#D9D5CC] bg-[#F7F5F1] text-[#22303C] hover:border-[#22303C] transition-colors"
                >
                  {isDownloadingReport === "docx" ? "..." : "Word (.docx)"}
                </button>
                <button
                  type="button"
                  onClick={() => handleDownload("json")}
                  disabled={isDownloadingReport !== null}
                  className="px-3 py-1 rounded-[6px] border border-[#D9D5CC] bg-[#F7F5F1] text-[#22303C] hover:border-[#22303C] transition-colors"
                >
                  {isDownloadingReport === "json" ? "..." : "JSON"}
                </button>
              </div>
            )}
          </div>

          {/* Inline Metrics Strip */}
          <div className="flex flex-wrap items-center gap-x-8 gap-y-2 text-[14px]">
            <div>
              <span className="text-[#6B7480]">Acceptable</span>
              <span className="text-[#22303C] font-medium ml-1.5">
                {review.acceptable_count}
              </span>
            </div>
            <div>
              <span className="text-[#6B7480]">Needs negotiation</span>
              <span className="text-[#22303C] font-medium ml-1.5">
                {review.needs_negotiation_count}
              </span>
            </div>
            <div>
              <span className="text-[#6B7480]">Unacceptable</span>
              <span className="text-[#22303C] font-medium ml-1.5">
                {review.unacceptable_count}
              </span>
            </div>
            <div>
              <span className="text-[#6B7480]">Pending decisions</span>
              <span className="text-[#22303C] font-medium ml-1.5">
                {review.pending_decisions}
              </span>
            </div>
            {review.needs_human_review_count > 0 && (
              <div>
                <span className="text-[#6B7480]">Flagged for review</span>
                <span className="text-[#22303C] font-medium ml-1.5">
                  {review.needs_human_review_count}
                </span>
              </div>
            )}
          </div>

          {/* 409 Pending Clauses Error Banner */}
          {errorMessage && (
            <div className="p-3.5 bg-[#F7F5F1] border border-[#A4493D] rounded-[6px] text-[13px] text-[#A4493D] space-y-1.5">
              <div className="flex items-center gap-2 font-medium">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>{errorMessage}</span>
              </div>
              {pendingErrorClauses.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5 pt-1">
                  <span className="text-[#22303C]">Jump to pending clause:</span>
                  {pendingErrorClauses.map((cid) => (
                    <button
                      key={cid}
                      type="button"
                      onClick={() => setSelectedClauseId(cid)}
                      className="px-2 py-0.5 rounded-[6px] border border-[#A4493D] text-[#A4493D] hover:bg-[#A4493D] hover:text-white transition-colors font-medium"
                    >
                      {cid}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Missing Clause Findings (Informational Accordion) */}
          {review.missing_clause_types && review.missing_clause_types.length > 0 && (
            <div className="border-t border-b border-[#D9D5CC] text-[13px]">
              <button
                type="button"
                onClick={() => setIsMissingClausesOpen(!isMissingClausesOpen)}
                className="w-full py-2.5 flex items-center justify-between text-left text-[#6B7480] hover:text-[#22303C] transition-colors"
              >
                <span>
                  Informational: {review.missing_clause_types.length} standard playbook clause type(s) not found in this contract
                </span>
                {isMissingClausesOpen ? (
                  <ChevronUp className="w-4 h-4 shrink-0" />
                ) : (
                  <ChevronDown className="w-4 h-4 shrink-0" />
                )}
              </button>

              {isMissingClausesOpen && (
                <div className="pb-3 space-y-2 text-[#6B7480]">
                  <p>
                    The following clause types were omitted from this agreement. Counsel should evaluate if any are required:
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {review.missing_clause_types.map((m) => (
                      <span
                        key={m}
                        className="px-2.5 py-0.5 rounded-[6px] bg-[#F7F5F1] text-[#22303C] border border-[#D9D5CC]"
                      >
                        {m.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Main Content Two-Column Workspace */}
      <div className="max-w-[1392px] mx-auto px-6 pb-12">
        <div className="flex flex-col lg:flex-row gap-6 items-start">
          {/* Left Column: Clause List */}
          <aside
            ref={clauseListRef}
            className="w-full lg:w-[340px] flex-shrink-0 bg-[#F7F5F1] border border-[#D9D5CC] rounded-[6px] p-5"
          >
            {/* Primary Tabs: All / Needs attention */}
            <div className="flex items-center justify-between pb-4 border-b border-[#D9D5CC]">
              <div className="flex items-center gap-6">
                <button
                  type="button"
                  onClick={() => setFilterOnlyNeedsAttention(false)}
                  className={
                    !filterOnlyNeedsAttention
                      ? "text-[14px] text-[#22303C] font-medium pb-0.5 border-b-2 border-[#22303C]"
                      : "text-[14px] text-[#6B7480] hover:text-[#22303C] transition-colors"
                  }
                >
                  All
                </button>
                <button
                  type="button"
                  onClick={() => setFilterOnlyNeedsAttention(true)}
                  className={
                    filterOnlyNeedsAttention
                      ? "text-[14px] text-[#22303C] font-medium pb-0.5 border-b-2 border-[#22303C]"
                      : "text-[14px] text-[#6B7480] hover:text-[#22303C] transition-colors"
                  }
                >
                  Needs attention
                </button>
              </div>

              <button
                type="button"
                onClick={() => setShowExtraFilters(!showExtraFilters)}
                aria-label="Toggle search and filters"
                className="text-[12px] text-[#6B7480] hover:text-[#22303C] inline-flex items-center gap-1"
              >
                <Search className="w-3.5 h-3.5" />
                <span>Filter</span>
              </button>
            </div>

            {/* Expandable Search & Dropdown Filters */}
            {showExtraFilters && (
              <div className="py-3 border-b border-[#D9D5CC] space-y-2 text-[13px]">
                <input
                  type="text"
                  placeholder="Search clauses or text..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full px-3 py-1.5 rounded-[6px] border border-[#D9D5CC] bg-transparent text-[#22303C] placeholder-[#6B7480] focus:outline-none focus:border-[#22303C]"
                />
                <div className="grid grid-cols-2 gap-2">
                  <select
                    aria-label="Filter by risk level"
                    value={filterRisk}
                    onChange={(e) => setFilterRisk(e.target.value)}
                    className="w-full px-2 py-1 rounded-[6px] border border-[#D9D5CC] bg-[#F7F5F1] text-[#22303C] focus:outline-none focus:border-[#22303C]"
                  >
                    <option value="ALL">All risks</option>
                    <option value="Acceptable">Acceptable</option>
                    <option value="Needs Negotiation">Needs negotiation</option>
                    <option value="Unacceptable">Unacceptable</option>
                  </select>
                  <select
                    aria-label="Filter by decision"
                    value={filterDecision}
                    onChange={(e) => setFilterDecision(e.target.value)}
                    className="w-full px-2 py-1 rounded-[6px] border border-[#D9D5CC] bg-[#F7F5F1] text-[#22303C] focus:outline-none focus:border-[#22303C]"
                  >
                    <option value="ALL">All decisions</option>
                    <option value="pending">Pending</option>
                    <option value="approved">Approved</option>
                    <option value="edited">Edited</option>
                    <option value="rejected">Rejected</option>
                  </select>
                </div>
              </div>
            )}

            {/* Clause Items */}
            <div className="flex flex-col divide-y divide-[#D9D5CC] pt-1 max-h-[680px] overflow-y-auto">
              {filteredClauses.length === 0 ? (
                <div className="py-8 text-center text-[#6B7480] text-[13px]">
                  No clauses match the active filters.
                </div>
              ) : (
                filteredClauses.map((c) => {
                  const isSelected = c.clause_id === selectedClauseId;
                  const prefix = c.section_number ? c.section_number : c.clause_id;

                  return (
                    <button
                      key={c.clause_id}
                      type="button"
                      onClick={() => setSelectedClauseId(c.clause_id)}
                      className={`w-full text-left py-3.5 pl-3 pr-2 -ml-2 transition-opacity ${
                        isSelected
                          ? "border-l-2 border-[#22303C]"
                          : "hover:opacity-80"
                      }`}
                    >
                      <div className="text-[#22303C] font-medium text-[14px] mb-1">
                        {prefix} {c.title || "Untitled"}
                      </div>
                      <div className="text-[13px] flex flex-wrap items-center gap-3">
                        <RiskBadge level={c.analysis.risk_level} size="sm" />
                        <DecisionBadge
                          status={c.current_decision?.status || "pending"}
                          size="sm"
                        />
                        {c.analysis.needs_human_review && (
                          <span className="text-[#9A7B2F] text-[12px]">Review</span>
                        )}
                      </div>
                    </button>
                  );
                })
              )}
            </div>

            <div className="pt-3 mt-1 border-t border-[#D9D5CC] text-[12px] text-[#6B7480] text-center">
              Use ↑ / ↓ arrow keys to navigate
            </div>
          </aside>

          {/* Right Column: Detail & Redline */}
          <section className="flex-1 w-full bg-[#F7F5F1] border border-[#D9D5CC] rounded-[6px] p-8">
            {isLoadingClause ? (
              <div className="py-24 text-center text-[#6B7480] text-[14px]">
                <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2" />
                Loading clause details...
              </div>
            ) : !clauseDetail ? (
              <div className="py-24 text-center text-[#6B7480] text-[14px]">
                Select a clause from the left to view policy analysis and record a decision.
              </div>
            ) : (
              <>
                {/* Title & Metadata */}
                <div>
                  <h1 className="text-[20px] font-medium text-[#22303C] mb-1.5">
                    {clauseDetail.section_number
                      ? `Section ${clauseDetail.section_number}, `
                      : `${clauseDetail.clause_id}, `}
                    {clauseDetail.title || "Untitled Clause"}
                  </h1>
                  <div className="text-[14px] flex flex-wrap items-center gap-3">
                    <RiskBadge level={clauseDetail.analysis.risk_level} />
                    <span className="text-[#6B7480]">·</span>
                    <span className="text-[#6B7480]">
                      Confidence {clauseDetail.analysis.confidence.toFixed(2)}
                    </span>
                    <span className="text-[#6B7480]">·</span>
                    <span className="text-[#6B7480]">
                      {clauseDetail.analysis.clause_type}
                    </span>
                    <span className="text-[#6B7480]">·</span>
                    <DecisionBadge
                      status={clauseDetail.current_decision?.status || "pending"}
                    />
                    {clauseDetail.analysis.needs_human_review && (
                      <>
                        <span className="text-[#6B7480]">·</span>
                        <span className="text-[#9A7B2F] text-[13px]">
                          Flagged: {clauseDetail.analysis.review_reason || "Policy review"}
                        </span>
                      </>
                    )}
                  </div>
                </div>

                <div className="mt-8 flex flex-col gap-8">
                  {/* Block 1: Original clause */}
                  <div>
                    <div className="text-[#6B7480] text-[14px] mb-2.5">
                      Original clause
                    </div>
                    <p className="clause-serif text-[#22303C] whitespace-pre-wrap">
                      “{clauseDetail.text}”
                    </p>
                  </div>

                  {/* Block 2: AI suggestion & Diff */}
                  <DiffViewer
                    segments={clauseDetail.redline_diff}
                    cleanText={clauseDetail.suggested_redline}
                    isAiSuggestion={true}
                  />

                  {/* Block 3: Why this was flagged */}
                  <div>
                    <div className="text-[#22303C] font-medium text-[14px] mb-2">
                      Why this was flagged
                    </div>
                    <p className="text-[#22303C] text-[14px] leading-relaxed">
                      {clauseDetail.analysis.explanation}
                    </p>
                  </div>

                  {/* Block 4: Expandable rules */}
                  {clauseDetail.cited_rules && clauseDetail.cited_rules.length > 0 && (
                    <div className="border-t border-[#D9D5CC]">
                      {clauseDetail.cited_rules.map((rule) => (
                        <PlaybookRuleCard key={rule.rule_id} rule={rule} />
                      ))}
                    </div>
                  )}

                  {/* Resulting Clause Text (Collapsible) */}
                  {resultingInfo && (
                    <div className="border-t border-b border-[#D9D5CC]">
                      <button
                        type="button"
                        onClick={() => setIsResultingOpen(!isResultingOpen)}
                        className="w-full py-3 flex items-center justify-between text-left text-[14px] text-[#6B7480] hover:text-[#22303C] transition-colors"
                      >
                        <span>
                          Resulting clause text ({resultingInfo.source})
                        </span>
                        <span className="text-[#22303C] text-[16px] leading-none ml-2">
                          {isResultingOpen ? "–" : "+"}
                        </span>
                      </button>
                      {isResultingOpen && (
                        <div className="pb-4 clause-serif text-[#22303C] whitespace-pre-wrap">
                          {resultingInfo.text}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Block 5: Decision Area */}
                  {!isFinalized ? (
                    <form onSubmit={handleDecisionSubmit} className="flex flex-col gap-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <h3 className="text-[14px] font-medium text-[#22303C]">
                          Record Reviewer Decision
                        </h3>
                        <span className="text-[13px] text-[#6B7480]">
                          Logged as:{" "}
                          <strong className="text-[#22303C] font-medium">
                            {reviewerName || "Unspecified"}
                          </strong>
                        </span>
                      </div>

                      <div className="flex items-center gap-3">
                        <button
                          type="button"
                          onClick={() => setDecisionAction("approved")}
                          className={
                            decisionAction === "approved"
                              ? "bg-[#22303C] text-white px-[18px] py-2 rounded-[6px] text-[14px] font-medium hover:opacity-90 transition-opacity"
                              : "bg-transparent border border-[#22303C] text-[#22303C] px-[18px] py-2 rounded-[6px] text-[14px] font-normal hover:bg-[#22303C]/5 transition-colors"
                          }
                        >
                          Approve
                        </button>
                        <button
                          type="button"
                          onClick={() => setDecisionAction("edited")}
                          className={
                            decisionAction === "edited"
                              ? "bg-[#22303C] text-white px-[18px] py-2 rounded-[6px] text-[14px] font-medium hover:opacity-90 transition-opacity"
                              : "bg-transparent border border-[#22303C] text-[#22303C] px-[18px] py-2 rounded-[6px] text-[14px] font-normal hover:bg-[#22303C]/5 transition-colors"
                          }
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          onClick={() => setDecisionAction("rejected")}
                          className={
                            decisionAction === "rejected"
                              ? "bg-[#22303C] text-white px-[18px] py-2 rounded-[6px] text-[14px] font-medium hover:opacity-90 transition-opacity"
                              : "bg-transparent border border-[#22303C] text-[#22303C] px-[18px] py-2 rounded-[6px] text-[14px] font-normal hover:bg-[#22303C]/5 transition-colors"
                          }
                        >
                          Reject
                        </button>
                      </div>

                      {decisionAction === "edited" && (
                        <div>
                          <label className="block text-[13px] font-medium text-[#22303C] mb-1.5">
                            Final Modified Clause Text{" "}
                            <span className="text-[#A4493D]">*</span>
                          </label>
                          <textarea
                            rows={4}
                            value={decisionFinalText}
                            onChange={(e) => setDecisionFinalText(e.target.value)}
                            placeholder="Enter finalized clause text..."
                            className="w-full bg-transparent border border-[#D9D5CC] rounded-[6px] p-3 clause-serif text-[#22303C] placeholder-[#6B7480] focus:outline-none focus:border-[#22303C]"
                          />
                        </div>
                      )}

                      <div>
                        <textarea
                          rows={2}
                          value={decisionNote}
                          onChange={(e) => setDecisionNote(e.target.value)}
                          placeholder={
                            decisionAction === "rejected"
                              ? "Explain why the redline was rejected or business risk accepted..."
                              : "Add internal note or negotiation guidance..."
                          }
                          className="w-full bg-transparent border border-[#D9D5CC] rounded-[6px] p-3 text-[14px] text-[#22303C] placeholder-[#6B7480] focus:outline-none focus:border-[#22303C] resize-none"
                        />
                      </div>

                      {formValidationError && (
                        <div className="p-2.5 rounded-[6px] border border-[#A4493D] text-[13px] text-[#A4493D] flex items-center gap-2">
                          <AlertTriangle className="w-4 h-4 shrink-0" />
                          <span>{formValidationError}</span>
                        </div>
                      )}

                      <div className="flex justify-end">
                        <button
                          type="submit"
                          disabled={isSubmittingDecision}
                          className="px-[18px] py-2 rounded-[6px] text-[14px] font-medium text-white bg-[#22303C] hover:opacity-90 disabled:opacity-50 transition-opacity"
                        >
                          {isSubmittingDecision ? "Saving decision..." : "Save decision"}
                        </button>
                      </div>
                    </form>
                  ) : (
                    <div className="p-4 border border-[#D9D5CC] rounded-[6px] text-[14px] text-[#6B7480] flex items-center gap-2">
                      <Lock className="w-4 h-4 text-[#5E7A63] shrink-0" />
                      <span>
                        This contract review has been <strong className="text-[#22303C] font-medium">finalized</strong>. All clause decisions are permanently locked into the audit trail.
                      </span>
                    </div>
                  )}

                  {/* Decision History Audit Trail */}
                  {clauseDetail.decision_history &&
                    clauseDetail.decision_history.length > 0 && (
                      <div className="pt-4 border-t border-[#D9D5CC] space-y-2.5">
                        <div className="text-[14px] font-medium text-[#22303C]">
                          Decision Audit Trail ({clauseDetail.decision_history.length})
                        </div>
                        <div className="divide-y divide-[#D9D5CC] border-t border-[#D9D5CC]">
                          {clauseDetail.decision_history.map((record) => (
                            <div key={record.decision_id} className="py-3 space-y-1">
                              <div className="flex items-center justify-between text-[13px]">
                                <div className="flex items-center gap-3">
                                  <DecisionBadge status={record.status} size="sm" />
                                  <span className="font-medium text-[#22303C]">
                                    {record.reviewer_name}
                                  </span>
                                </div>
                                <span className="text-[#6B7480]">
                                  {new Date(record.decided_at).toLocaleString()}
                                </span>
                              </div>
                              {record.reviewer_note && (
                                <p className="text-[#6B7480] text-[13px]">
                                  Note: {record.reviewer_note}
                                </p>
                              )}
                              {record.final_text && (
                                <div className="mt-1 clause-serif text-[#22303C] text-[15px]">
                                  {record.final_text}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                </div>
              </>
            )}

            {/* Block 6: Finalize Action Row */}
            {!isFinalized && (
              <div className="mt-8 pt-4 border-t border-[#D9D5CC] flex items-center justify-end gap-5">
                <span className="text-[#6B7480] text-[14px]">
                  {review.pending_decisions}{" "}
                  {review.pending_decisions === 1 ? "decision" : "decisions"} pending
                </span>
                <button
                  type="button"
                  onClick={() => setIsFinalizeModalOpen(true)}
                  disabled={review.pending_decisions > 0}
                  className={
                    review.pending_decisions > 0
                      ? "px-[18px] py-2 rounded-[6px] border border-[#D9D5CC] text-[#6B7480] text-[14px] cursor-not-allowed bg-transparent"
                      : "px-[18px] py-2 rounded-[6px] bg-[#22303C] text-white text-[14px] font-medium hover:opacity-90 transition-opacity"
                  }
                >
                  Finalize review
                </button>
              </div>
            )}
          </section>
        </div>
      </div>

      {/* Finalize Confirmation Modal */}
      <FinalizeModal
        isOpen={isFinalizeModalOpen}
        onClose={() => setIsFinalizeModalOpen(false)}
        onConfirm={handleFinalizeConfirm}
        isSubmitting={isFinalizing}
        contractName={review.contract_name}
      />
    </div>
  );
};
