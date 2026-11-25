import React, { useState, useEffect } from "react";
import { Link } from "react-router-dom";

interface HeaderProps {
  reviewerName: string;
  onReviewerNameChange: (name: string) => void;
}

export const Header: React.FC<HeaderProps> = ({ reviewerName, onReviewerNameChange }) => {
  const [localName, setLocalName] = useState(reviewerName);

  useEffect(() => {
    setLocalName(reviewerName);
  }, [reviewerName]);

  const handleBlur = () => {
    const trimmed = localName.trim();
    onReviewerNameChange(trimmed);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      handleBlur();
    }
  };

  return (
    <>
      <header className="h-[52px] bg-[#22303C] px-6 flex items-center justify-between sticky top-0 z-30">
        <Link
          to="/"
          className="text-white text-[16px] font-medium tracking-normal hover:opacity-90 transition-opacity"
        >
          Contract Review
        </Link>

        <div className="flex items-center gap-3">
          {!reviewerName && (
            <span className="hidden sm:inline text-[#D9D5CC] text-[12px]">
              Name required to decide
            </span>
          )}
          <input
            id="reviewer-name-input"
            aria-label="Reviewer Name"
            type="text"
            placeholder="Reviewer name..."
            value={localName}
            onChange={(e) => setLocalName(e.target.value)}
            onBlur={handleBlur}
            onKeyDown={handleKeyDown}
            className="bg-transparent text-white text-[14px] font-normal px-3 py-1.5 rounded-[6px] border border-[#3a4a59] placeholder-[#9CA3AF] focus:outline-none focus:border-[#6B7480] w-48"
          />
        </div>
      </header>

      {/* Advisory Notice */}
      <div className="px-6 py-4">
        <div className="max-w-[1392px] mx-auto text-[#6B7480] text-[13px]">
          Advisory only. Recommendations follow the company playbook and require approval by a qualified legal professional.
        </div>
      </div>
    </>
  );
};
