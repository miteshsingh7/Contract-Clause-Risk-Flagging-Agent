import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { ReviewPage } from "../pages/ReviewPage";
import * as apiClient from "../api/client";
import { ReviewDetailResponse, ClauseDetailResponse, ReviewStatusResponse } from "../api/types";

const sampleAwaitingReview: ReviewDetailResponse = {
  review_id: "rev-123",
  contract_name: "Master Services Agreement.docx",
  status: "awaiting_review",
  created_at: "2026-11-18T10:00:00Z",
  finalized_at: null,
  total_clauses: 2,
  analyzed_clauses: 2,
  progress: { analyzed: 2, total: 2 },
  acceptable_count: 1,
  needs_negotiation_count: 1,
  unacceptable_count: 0,
  needs_human_review_count: 1,
  pending_decisions: 1,
  missing_clause_types: ["data_protection"],
  clauses: [
    {
      clause_id: "C-001",
      section_number: "1.0",
      title: "Confidentiality",
      text: "Each party shall keep confidential information secret.",
      analysis: {
        clause_id: "C-001",
        clause_type: "confidentiality",
        risk_level: "Acceptable",
        cited_rule_ids: ["CONF-01"],
        explanation: "Standard mutual confidentiality obligation.",
        suggested_redline: null,
        confidence: 0.95,
        needs_human_review: false,
        review_reason: null,
      },
      current_decision: {
        decision_id: 1,
        review_id: "rev-123",
        clause_id: "C-001",
        status: "approved",
        reviewer_name: "Attorney Alice",
        reviewer_note: "Standard clause looks good.",
        final_text: "Each party shall keep confidential information secret.",
        decided_at: "2026-11-18T10:05:00Z",
      },
    },
    {
      clause_id: "C-002",
      section_number: "2.0",
      title: "Limitation of Liability",
      text: "Neither party shall be liable for indirect damages, but Supplier liability is capped at $10,000.",
      analysis: {
        clause_id: "C-002",
        clause_type: "limitation_of_liability",
        risk_level: "Needs Negotiation",
        cited_rule_ids: ["LOL-01"],
        explanation: "Liability cap is fixed at $10k rather than 12 months fees.",
        suggested_redline: "Liability shall be capped at total fees paid in previous 12 months.",
        confidence: 0.88,
        needs_human_review: true,
        review_reason: "Cap deviates from standard 12 months fees.",
      },
      current_decision: null,
    },
  ],
  error_message: null,
  disclaimer: "Advisory only.",
};

const sampleClause002Detail: ClauseDetailResponse = {
  review_id: "rev-123",
  clause_id: "C-002",
  section_number: "2.0",
  title: "Limitation of Liability",
  text: "Neither party shall be liable for indirect damages, but Supplier liability is capped at $10,000.",
  analysis: {
    clause_id: "C-002",
    clause_type: "limitation_of_liability",
    risk_level: "Needs Negotiation",
    cited_rule_ids: ["LOL-01"],
    explanation: "Liability cap is fixed at $10k rather than 12 months fees.",
    suggested_redline: "Liability shall be capped at total fees paid in previous 12 months.",
    confidence: 0.88,
    needs_human_review: true,
    review_reason: "Cap deviates from standard 12 months fees.",
  },
  suggested_redline: "Liability shall be capped at total fees paid in previous 12 months.",
  redline_diff: [
    { type: "equal", text: "Neither party shall be liable for indirect damages, but " },
    { type: "delete", text: "Supplier liability is capped at $10,000." },
    { type: "insert", text: "Liability shall be capped at total fees paid in previous 12 months." },
  ],
  decision_diff: null,
  cited_rules: [
    {
      rule_id: "LOL-01",
      clause_type: "limitation_of_liability",
      title: "Mutual 12-Month Fee Cap",
      standard_position: "12 months fees paid",
      acceptable_fallback: "6 months fees paid",
      unacceptable_triggers: ["Unlimited liability", "Uncapped indirect damages"],
      preferred_language: "Neither party shall exceed 12 months fees.",
      rationale: "Aligns risk with contract value.",
    },
  ],
  current_decision: null,
  decision_history: [],
  disclaimer: "Advisory only.",
};

vi.mock("../api/client", () => {
  return {
    getReview: vi.fn(),
    getReviewStatus: vi.fn(),
    getClauseDetail: vi.fn().mockImplementation(() => Promise.resolve(sampleClause002Detail)),
    submitDecision: vi.fn().mockImplementation(() => Promise.resolve({ success: true })),
    finalizeReview: vi.fn().mockImplementation(() => Promise.resolve({ success: true })),
    downloadReport: vi.fn().mockImplementation(() => Promise.resolve()),
    ApiError: class ApiError extends Error {
      status: number;
      detail: any;
      constructor(message: string, status: number = 400, detail?: any) {
        super(message);
        this.status = status;
        this.detail = detail;
      }
    },
  };
});

describe("ReviewPage Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.getClauseDetail).mockResolvedValue(sampleClause002Detail);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders pending count and disables finalize button when pending_decisions > 0", async () => {
    vi.mocked(apiClient.getReview).mockResolvedValue(sampleAwaitingReview);

    render(
      <MemoryRouter initialEntries={["/reviews/rev-123"]}>
        <Routes>
          <Route path="/reviews/:reviewId" element={<ReviewPage reviewerName="Counsel Jane" />} />
        </Routes>
      </MemoryRouter>
    );

    // Wait for review details to load
    await waitFor(() => {
      expect(screen.getByText("Master Services Agreement.docx")).toBeInTheDocument();
    });

    // Check finalize button is disabled with pending count
    const finalizeBtn = screen.getByRole("button", { name: /finalize review/i });
    expect(finalizeBtn).toBeDisabled();
    expect(screen.getByText(/1 decision pending/i)).toBeInTheDocument();

    // Report buttons should NOT be visible when status is awaiting_review
    expect(screen.queryByRole("button", { name: /export markdown/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /export word/i })).not.toBeInTheDocument();
  });

  it("enables finalize button and enables report downloads when review is finalized", async () => {
    const finalizedReview: ReviewDetailResponse = {
      ...sampleAwaitingReview,
      status: "finalized",
      pending_decisions: 0,
      finalized_at: "2026-11-18T10:30:00Z",
    };
    vi.mocked(apiClient.getReview).mockResolvedValue(finalizedReview);

    render(
      <MemoryRouter initialEntries={["/reviews/rev-123"]}>
        <Routes>
          <Route path="/reviews/:reviewId" element={<ReviewPage reviewerName="Counsel Jane" />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Master Services Agreement.docx")).toBeInTheDocument();
    });

    // Finalized badge must be displayed
    expect(screen.getByText("Finalized")).toBeInTheDocument();

    // Report buttons MUST be visible
    expect(screen.getByRole("button", { name: /markdown/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /word \(\.docx\)/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /json/i })).toBeInTheDocument();
  });

  it("validates decision form inputs before submitting", async () => {
    vi.mocked(apiClient.getReview).mockResolvedValue(sampleAwaitingReview);

    // 1. Render without a reviewer name
    const { rerender } = render(
      <MemoryRouter initialEntries={["/reviews/rev-123"]}>
        <Routes>
          <Route path="/reviews/:reviewId" element={<ReviewPage reviewerName="" />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Master Services Agreement.docx")).toBeInTheDocument();
    });

    // Selecting C-002
    const clauseItem = screen.getByRole("button", { name: /Limitation of Liability/i });
    fireEvent.click(clauseItem);

    await waitFor(() => {
      expect(screen.getByText("Record Reviewer Decision")).toBeInTheDocument();
    });

    // When reviewerName is empty, clicking submit shows the validation error
    const submitBtn = screen.getByRole("button", { name: /save decision/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(
        screen.getByText(/Reviewer Name is required. Please set your name in the top navigation bar./i)
      ).toBeInTheDocument();
    });
    expect(apiClient.submitDecision).not.toHaveBeenCalled();

    // 2. Rerender with valid reviewer name
    rerender(
      <MemoryRouter initialEntries={["/reviews/rev-123"]}>
        <Routes>
          <Route path="/reviews/:reviewId" element={<ReviewPage reviewerName="Counsel Jane" />} />
        </Routes>
      </MemoryRouter>
    );

    // Choose 'Edit' decision
    const editBtn = screen.getByRole("button", { name: /^edit$/i });
    fireEvent.click(editBtn);

    // Empty the final text textarea
    const finalTextarea = screen.getByPlaceholderText(/enter finalized clause text.../i);
    fireEvent.change(finalTextarea, { target: { value: "   " } });

    // Click submit
    fireEvent.click(submitBtn);

    // Error for empty final text must be displayed
    await waitFor(() => {
      expect(
        screen.getByText(/Final clause text is required when decision status is 'Edited'./i)
      ).toBeInTheDocument();
    });
    expect(apiClient.submitDecision).not.toHaveBeenCalled();

    // Choose 'Reject' decision
    const rejectBtn = screen.getByRole("button", { name: /^reject$/i });
    fireEvent.click(rejectBtn);

    // Ensure reviewer note is empty
    const notesInput = screen.getByPlaceholderText(/explain why the redline was rejected/i);
    fireEvent.change(notesInput, { target: { value: "" } });

    fireEvent.click(submitBtn);
    await waitFor(() => {
      expect(
        screen.getByText(/Reviewer note is required when decision status is 'Rejected'./i)
      ).toBeInTheDocument();
    });
    expect(apiClient.submitDecision).not.toHaveBeenCalled();

    // Now fill valid rejection note
    fireEvent.change(notesInput, { target: { value: "Supplier cap rejected completely." } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(apiClient.submitDecision).toHaveBeenCalledWith("rev-123", "C-002", {
        status: "rejected",
        reviewer_name: "Counsel Jane",
        reviewer_note: "Supplier cap rejected completely.",
        final_text: null,
      });
    });
  });

  it("handles polling during 'processing' and stops on 'awaiting_review'", async () => {
    const processingReview: ReviewDetailResponse = {
      ...sampleAwaitingReview,
      status: "processing",
      clauses: [],
    };

    const processingStatus: ReviewStatusResponse = {
      review_id: "rev-123",
      status: "processing",
      progress: { analyzed: 1, total: 2 },
      pending_decisions: 1,
      error_message: null,
      disclaimer: "Advisory only.",
    };

    const readyStatus: ReviewStatusResponse = {
      review_id: "rev-123",
      status: "awaiting_review",
      progress: { analyzed: 2, total: 2 },
      pending_decisions: 1,
      error_message: null,
      disclaimer: "Advisory only.",
    };

    vi.mocked(apiClient.getReview)
      .mockResolvedValueOnce(processingReview)
      .mockResolvedValueOnce(sampleAwaitingReview);

    vi.mocked(apiClient.getReviewStatus)
      .mockResolvedValueOnce(processingStatus)
      .mockResolvedValueOnce(readyStatus);

    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });

    render(
      <MemoryRouter initialEntries={["/reviews/rev-123"]}>
        <Routes>
          <Route path="/reviews/:reviewId" element={<ReviewPage reviewerName="Counsel Jane" />} />
        </Routes>
      </MemoryRouter>
    );

    // Wait for initial getReview to complete and processing view to show
    await waitFor(() => {
      expect(screen.getByText(/Analyzing Contract Clauses.../i)).toBeInTheDocument();
    });

    // Advance timer by 2600ms
    await vi.advanceTimersByTimeAsync(2600);
    expect(apiClient.getReviewStatus).toHaveBeenCalledTimes(1);

    // Advance timer another 2600ms
    await vi.advanceTimersByTimeAsync(2600);
    expect(apiClient.getReviewStatus).toHaveBeenCalledTimes(2);

    // After transitioning to 'awaiting_review', further timer intervals must not call getReviewStatus
    await vi.advanceTimersByTimeAsync(5000);
    expect(apiClient.getReviewStatus).toHaveBeenCalledTimes(2);
  });
});
