/**
 * Typed API client using native fetch.
 */

import {
  ClauseDetailResponse,
  DecisionRequest,
  FinalizeResponse,
  ReviewDecisionRecord,
  ReviewDetailResponse,
  ReviewStatusResponse,
  ReviewSummary,
  UploadResponse,
} from "./types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

export class ApiError extends Error {
  status: number;
  data: any;
  pendingClauseIds?: string[];

  constructor(message: string, status: number, data?: any) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;

    // Check if error detail contains pending clause IDs (from 409 finalize conflicts)
    if (data?.detail && typeof data.detail === "object") {
      this.pendingClauseIds = data.detail.pending_clause_ids;
    }
  }
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  const response = await fetch(url, options);

  if (!response.ok) {
    let errorData: any = null;
    let errorMessage = `HTTP ${response.status} ${response.statusText}`;

    try {
      errorData = await response.json();
      if (typeof errorData?.detail === "string") {
        errorMessage = errorData.detail;
      } else if (typeof errorData?.detail === "object" && errorData.detail?.message) {
        errorMessage = errorData.detail.message;
      } else if (errorData?.message) {
        errorMessage = errorData.message;
      }
    } catch {
      // Fallback to text or statusText if response is not JSON
    }

    throw new ApiError(errorMessage, response.status, errorData);
  }

  return response.json() as Promise<T>;
}

export async function uploadContract(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  return request<UploadResponse>("/contracts/upload", {
    method: "POST",
    body: formData,
  });
}

export async function listReviews(): Promise<ReviewSummary[]> {
  return request<ReviewSummary[]>("/reviews");
}

export async function getReview(reviewId: string): Promise<ReviewDetailResponse> {
  return request<ReviewDetailResponse>(`/reviews/${encodeURIComponent(reviewId)}`);
}

export async function getReviewStatus(reviewId: string): Promise<ReviewStatusResponse> {
  return request<ReviewStatusResponse>(`/reviews/${encodeURIComponent(reviewId)}/status`);
}

export async function getClauseDetail(
  reviewId: string,
  clauseId: string
): Promise<ClauseDetailResponse> {
  return request<ClauseDetailResponse>(
    `/reviews/${encodeURIComponent(reviewId)}/clauses/${encodeURIComponent(clauseId)}`
  );
}

export async function submitDecision(
  reviewId: string,
  clauseId: string,
  payload: DecisionRequest
): Promise<ReviewDecisionRecord> {
  return request<ReviewDecisionRecord>(
    `/reviews/${encodeURIComponent(reviewId)}/clauses/${encodeURIComponent(clauseId)}/decision`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    }
  );
}

export async function finalizeReview(reviewId: string): Promise<FinalizeResponse> {
  return request<FinalizeResponse>(`/reviews/${encodeURIComponent(reviewId)}/finalize`, {
    method: "POST",
  });
}

export function getReportDownloadUrl(
  reviewId: string,
  format: "json" | "md" | "docx"
): string {
  return `${API_BASE_URL}/reviews/${encodeURIComponent(reviewId)}/report?format=${format}`;
}

export async function downloadReport(
  reviewId: string,
  format: "json" | "md" | "docx",
  contractName: string
): Promise<void> {
  const url = getReportDownloadUrl(reviewId, format);
  const response = await fetch(url);

  if (!response.ok) {
    let errorDetail = `Failed to download report (HTTP ${response.status})`;
    try {
      const err = await response.json();
      if (err.detail) errorDetail = typeof err.detail === "string" ? err.detail : err.detail.message;
    } catch {}
    throw new ApiError(errorDetail, response.status);
  }

  const blob = await response.blob();
  const cleanName = contractName.replace(/\.[^/.]+$/, "").replace(/[^a-zA-Z0-9_-]/g, "_");
  const ext = format === "docx" ? "docx" : format === "md" ? "md" : "json";
  const filename = `${cleanName}_Review_Report.${ext}`;

  const downloadUrl = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = downloadUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.URL.revokeObjectURL(downloadUrl);
}
