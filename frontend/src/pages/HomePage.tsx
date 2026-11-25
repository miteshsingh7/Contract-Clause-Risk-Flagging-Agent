import React, { useState, useEffect, useRef } from "react";
import { useNavigate, Link } from "react-router-dom";
import {
  Upload,
  FileText,
  AlertCircle,
  Clock,
  ArrowRight,
  RefreshCw,
  CheckCircle2,
  X,
  ShieldCheck,
  FileDiff,
  Lock,
} from "lucide-react";
import { uploadContract, listReviews, ApiError } from "../api/client";
import { ReviewSummary } from "../api/types";

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB
const ALLOWED_EXTENSIONS = [".docx", ".pdf"];

export const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Upload state
  const [dragActive, setDragActive] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);

  // Reviews table state
  const [reviews, setReviews] = useState<ReviewSummary[]>([]);
  const [isLoadingReviews, setIsLoadingReviews] = useState(true);
  const [reviewsError, setReviewsError] = useState<string | null>(null);

  const fetchReviewsList = async () => {
    setIsLoadingReviews(true);
    setReviewsError(null);
    try {
      const data = await listReviews();
      setReviews(data);
    } catch (err: any) {
      setReviewsError(err?.message || "Failed to load contract reviews.");
    } finally {
      setIsLoadingReviews(false);
    }
  };

  useEffect(() => {
    fetchReviewsList();
  }, []);

  const validateFile = (file: File): string | null => {
    const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      return "Unsupported file format. Only .docx and .pdf files are accepted.";
    }
    if (file.size === 0) {
      return "Uploaded file is empty.";
    }
    if (file.size > MAX_FILE_SIZE) {
      return "File size exceeds maximum allowed limit of 10 MB.";
    }
    return null;
  };

  const handleFileSelection = (file: File | undefined) => {
    if (!file) return;
    setUploadError(null);
    const errorMsg = validateFile(file);
    if (errorMsg) {
      setUploadError(errorMsg);
      setSelectedFile(null);
      return;
    }
    setSelectedFile(file);
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileSelection(e.dataTransfer.files[0]);
    }
  };

  const handleUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile) return;

    const errorMsg = validateFile(selectedFile);
    if (errorMsg) {
      setUploadError(errorMsg);
      return;
    }

    setIsUploading(true);
    setUploadError(null);

    try {
      const response = await uploadContract(selectedFile);
      navigate(`/reviews/${encodeURIComponent(response.review_id)}`);
    } catch (err: any) {
      if (err instanceof ApiError) {
        setUploadError(err.message);
      } else {
        setUploadError(err?.message || "Failed to upload contract.");
      }
      setIsUploading(false);
    }
  };

  const renderStatusText = (status: string) => {
    switch (status) {
      case "processing":
        return (
          <span className="inline-flex items-center gap-1.5 text-[13px] text-[#22303C]">
            <RefreshCw className="w-3.5 h-3.5 animate-spin text-[#6B7480]" />
            Processing
          </span>
        );
      case "awaiting_review":
        return (
          <span className="inline-flex items-center gap-1.5 text-[13px] text-[#9A7B2F]">
            <Clock className="w-3.5 h-3.5" />
            Awaiting review
          </span>
        );
      case "finalized":
        return (
          <span className="inline-flex items-center gap-1.5 text-[13px] text-[#5E7A63]">
            <CheckCircle2 className="w-3.5 h-3.5" />
            Finalized
          </span>
        );
      case "failed":
        return (
          <span className="inline-flex items-center gap-1.5 text-[13px] text-[#A4493D]">
            <AlertCircle className="w-3.5 h-3.5" />
            Failed
          </span>
        );
      default:
        return <span className="text-[13px] text-[#6B7480]">{status}</span>;
    }
  };

  return (
    <div className="max-w-[1392px] mx-auto px-6 pb-16 space-y-12">
      {/* Centered Editorial Upload Workspace */}
      <section className="pt-4 pb-2 max-w-3xl mx-auto">
        <div className="text-center mb-8">
          <h1 className="text-[28px] font-medium tracking-tight text-[#22303C] mb-2">
            Contract Risk Assessment &amp; Redlining
          </h1>
          <p className="text-[14px] text-[#6B7480] max-w-xl mx-auto leading-relaxed">
            Upload an agreement (.docx or .pdf, up to 10 MB) to segment clauses, compare against the corporate negotiation playbook, and generate advisory redlines.
          </p>
        </div>

        <form onSubmit={handleUploadSubmit} className="space-y-6">
          <div
            onDragEnter={handleDrag}
            onDragLeave={handleDrag}
            onDragOver={handleDrag}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`bg-[#F7F5F1] rounded-[6px] border-2 border-dashed p-10 text-center cursor-pointer transition-colors ${
              dragActive
                ? "border-[#22303C] bg-[#EFECE6]"
                : selectedFile
                ? "border-[#5E7A63]"
                : "border-[#D9D5CC] hover:border-[#22303C]"
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".docx,.pdf"
              className="hidden"
              onChange={(e) => handleFileSelection(e.target.files?.[0])}
            />

            <div className="flex flex-col items-center justify-center">
              <div className="w-12 h-12 rounded-full bg-[#EFECE6] border border-[#D9D5CC] text-[#22303C] flex items-center justify-center mb-4">
                {selectedFile ? (
                  <FileText className="w-5 h-5 text-[#5E7A63]" />
                ) : (
                  <Upload className="w-5 h-5 text-[#22303C]" />
                )}
              </div>

              <p className="text-[15px] font-medium text-[#22303C] mb-1">
                Drag and drop your contract here, or{" "}
                <span className="underline underline-offset-4">browse</span>
              </p>
              <p className="text-[13px] text-[#6B7480]">
                Supports .docx or .pdf up to 10 MB
              </p>

              {selectedFile && (
                <div
                  className="mt-5 inline-flex items-center gap-2.5 px-4 py-1.5 rounded-full border border-[#D9D5CC] bg-[#EFECE6] text-[13px] text-[#22303C]"
                  onClick={(e) => e.stopPropagation()}
                >
                  <FileText className="w-4 h-4 text-[#5E7A63] shrink-0" />
                  <span className="font-medium truncate max-w-[260px]">
                    {selectedFile.name}
                  </span>
                  <span className="text-[#6B7480]">
                    ({(selectedFile.size / 1024).toFixed(1)} KB)
                  </span>
                  <button
                    type="button"
                    aria-label="Remove selected file"
                    onClick={() => {
                      setSelectedFile(null);
                      setUploadError(null);
                      if (fileInputRef.current) fileInputRef.current.value = "";
                    }}
                    className="ml-1 text-[#6B7480] hover:text-[#22303C] transition-colors"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}
            </div>
          </div>

          {uploadError && (
            <div
              className="p-3 rounded-[6px] border border-[#A4493D] bg-[#F7F5F1] text-[13px] text-[#A4493D] flex items-center gap-2"
              role="alert"
            >
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{uploadError}</span>
            </div>
          )}

          <div className="flex justify-center">
            <button
              type="submit"
              disabled={!selectedFile || isUploading}
              className="inline-flex items-center justify-center gap-2 min-w-[240px] px-6 py-2.5 rounded-[6px] text-[14px] font-medium text-white bg-[#22303C] hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition-opacity"
            >
              {isUploading ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>Uploading &amp; analyzing...</span>
                </>
              ) : (
                <>
                  <Upload className="w-4 h-4" />
                  <span>Start contract review</span>
                </>
              )}
            </button>
          </div>
        </form>

        {/* Subtle 3-Column Capability Strip */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-8 pt-4 border-t border-[#D9D5CC] text-[13px] text-[#6B7480]">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-[#22303C] shrink-0" />
            <span>Playbook-grounded risk analysis</span>
          </div>
          <div className="flex items-center gap-2 md:justify-center">
            <FileDiff className="w-4 h-4 text-[#22303C] shrink-0" />
            <span>Word-level redline diffs</span>
          </div>
          <div className="flex items-center gap-2 md:justify-end">
            <Lock className="w-4 h-4 text-[#22303C] shrink-0" />
            <span>Mandatory counsel signoff</span>
          </div>
        </div>
      </section>

      {/* Contract Reviews Archive Table */}
      <section className="bg-[#F7F5F1] rounded-[6px] border border-[#D9D5CC] overflow-hidden">
        <div className="px-6 py-4 border-b border-[#D9D5CC] flex items-center justify-between">
          <h2 className="text-[16px] font-medium text-[#22303C]">
            Contract Reviews
          </h2>
          <button
            type="button"
            onClick={fetchReviewsList}
            disabled={isLoadingReviews}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-[6px] text-[13px] text-[#22303C] bg-transparent hover:bg-[#EFECE6] border border-[#D9D5CC] transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoadingReviews ? "animate-spin" : ""}`} />
            <span>Refresh</span>
          </button>
        </div>

        {reviewsError && (
          <div className="p-4 border-b border-[#D9D5CC] text-[13px] text-[#A4493D] flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{reviewsError}</span>
          </div>
        )}

        {isLoadingReviews ? (
          <div className="p-12 text-center text-[#6B7480] text-[14px]">
            <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2 text-[#6B7480]" />
            Loading contract reviews...
          </div>
        ) : reviews.length === 0 ? (
          <div className="p-12 text-center text-[#6B7480] text-[14px]">
            No contract reviews yet. Upload a contract above to begin.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead className="border-b border-[#D9D5CC] text-[#6B7480] font-normal">
                <tr>
                  <th className="py-3 px-6 font-medium">Contract</th>
                  <th className="py-3 px-4 font-medium">Status</th>
                  <th className="py-3 px-4 font-medium">Created</th>
                  <th className="py-3 px-4 font-medium">Risk summary</th>
                  <th className="py-3 px-4 font-medium">Pending</th>
                  <th className="py-3 px-6 text-right font-medium">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#D9D5CC] text-[#22303C]">
                {reviews.map((r) => (
                  <tr key={r.review_id} className="hover:bg-[#EFECE6]/60 transition-colors">
                    <td className="py-3.5 px-6 font-medium">
                      <div className="flex items-center gap-2">
                        <FileText className="w-4 h-4 text-[#6B7480] shrink-0" />
                        <span className="truncate max-w-xs">{r.contract_name}</span>
                      </div>
                    </td>
                    <td className="py-3.5 px-4">{renderStatusText(r.status)}</td>
                    <td className="py-3.5 px-4 text-[#6B7480]">
                      {new Date(r.created_at).toLocaleDateString(undefined, {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </td>
                    <td className="py-3.5 px-4">
                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]">
                        <span>
                          <span className="text-[#5E7A63]">Acceptable</span>{" "}
                          <span className="font-medium ml-0.5">{r.acceptable_count}</span>
                        </span>
                        <span>
                          <span className="text-[#9A7B2F]">Needs negotiation</span>{" "}
                          <span className="font-medium ml-0.5">{r.needs_negotiation_count}</span>
                        </span>
                        <span>
                          <span className="text-[#A4493D]">Unacceptable</span>{" "}
                          <span className="font-medium ml-0.5">{r.unacceptable_count}</span>
                        </span>
                      </div>
                    </td>
                    <td className="py-3.5 px-4">
                      {r.pending_decisions > 0 ? (
                        <span className="text-[#9A7B2F] font-medium">
                          {r.pending_decisions} pending
                        </span>
                      ) : (
                        <span className="text-[#6B7480]">All decided</span>
                      )}
                    </td>
                    <td className="py-3.5 px-6 text-right">
                      <Link
                        to={`/reviews/${encodeURIComponent(r.review_id)}`}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[13px] font-medium rounded-[6px] border border-[#22303C] text-[#22303C] hover:bg-[#22303C] hover:text-white transition-colors"
                      >
                        <span>Open</span>
                        <ArrowRight className="w-3.5 h-3.5" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
};
