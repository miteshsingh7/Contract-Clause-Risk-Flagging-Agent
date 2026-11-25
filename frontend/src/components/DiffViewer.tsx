import React, { useState } from "react";
import { DiffSegment } from "../api/types";

interface DiffViewerProps {
  segments?: DiffSegment[] | null;
  cleanText?: string | null;
  label?: string;
  isAiSuggestion?: boolean;
}

export const DiffViewer: React.FC<DiffViewerProps> = ({
  segments,
  cleanText,
  label,
  isAiSuggestion = true,
}) => {
  const [viewMode, setViewMode] = useState<"diff" | "clean">("diff");

  if (!segments || segments.length === 0) {
    if (cleanText) {
      return (
        <div className="clause-serif text-[#22303C] whitespace-pre-wrap break-words">
          {cleanText}
        </div>
      );
    }
    return (
      <div className="text-[14px] italic text-[#6B7480] py-1">
        No redline suggested. Clause complies with company playbook standard position.
      </div>
    );
  }

  const headerText =
    label ||
    (isAiSuggestion ? "AI suggestion, not yet approved" : "Suggested redline");

  return (
    <div>
      <div className="flex items-center justify-between mb-2.5 gap-4">
        <div className="flex items-center gap-2 text-[#6B7480] text-[14px]">
          <span>{headerText}</span>
          {label && isAiSuggestion && (
            <span className="text-[13px] text-[#6B7480]">
              · AI suggestion, not yet approved
            </span>
          )}
        </div>

        <div className="flex items-center gap-3 text-[14px] shrink-0">
          <button
            type="button"
            aria-label="Diff View"
            onClick={() => setViewMode("diff")}
            className={
              viewMode === "diff"
                ? "text-[#22303C] font-medium"
                : "text-[#6B7480] hover:text-[#22303C] transition-colors"
            }
          >
            Diff
          </button>
          <span className="text-[#D9D5CC]" aria-hidden="true">
            /
          </span>
          <button
            type="button"
            aria-label="Clean Text"
            onClick={() => setViewMode("clean")}
            className={
              viewMode === "clean"
                ? "text-[#22303C] font-medium"
                : "text-[#6B7480] hover:text-[#22303C] transition-colors"
            }
          >
            Clean text
          </button>
        </div>
      </div>

      <div className="clause-serif text-[#22303C] whitespace-pre-wrap break-words">
        {viewMode === "diff" ? (
          <div>
            {segments.map((seg, idx) => {
              const nextSeg = segments[idx + 1];
              const needsGapBeforeInsert =
                seg.type === "delete" &&
                nextSeg?.type === "insert" &&
                !/\s$/.test(seg.text) &&
                !/^\s/.test(nextSeg.text);

              if (seg.type === "delete") {
                return (
                  <span
                    key={idx}
                    className={`text-[#A4493D] line-through${
                      needsGapBeforeInsert ? " mr-1.5" : ""
                    }`}
                  >
                    {seg.text}
                  </span>
                );
              }
              if (seg.type === "insert") {
                return (
                  <span
                    key={idx}
                    className="text-[#5E7A63] underline"
                  >
                    {seg.text}
                  </span>
                );
              }
              return <span key={idx}>{seg.text}</span>;
            })}
          </div>
        ) : (
          <div>
            {cleanText ||
              segments
                .filter((s) => s.type !== "delete")
                .map((s) => s.text)
                .join("")}
          </div>
        )}
      </div>
    </div>
  );
};
