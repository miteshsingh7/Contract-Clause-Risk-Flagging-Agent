import React from "react";
import { DecisionStatus } from "../api/types";

interface DecisionBadgeProps {
  status?: DecisionStatus | "pending" | string | null;
  size?: "sm" | "md";
}

export const DecisionBadge: React.FC<DecisionBadgeProps> = ({ status, size = "md" }) => {
  const isSm = size === "sm";
  const baseClasses = isSm
    ? "inline-flex items-center text-[13px] font-normal"
    : "inline-flex items-center text-[14px] font-normal";

  switch (status) {
    case "approved":
      return (
        <span
          className={`${baseClasses} text-[#5E7A63]`}
          aria-label="Decision: Approved"
        >
          Approved
        </span>
      );

    case "edited":
      return (
        <span
          className={`${baseClasses} text-[#22303C]`}
          aria-label="Decision: Edited"
        >
          Edited
        </span>
      );

    case "rejected":
      return (
        <span
          className={`${baseClasses} text-[#A4493D]`}
          aria-label="Decision: Rejected"
        >
          Rejected
        </span>
      );

    default:
      return (
        <span
          className={`${baseClasses} text-[#6B7480]`}
          aria-label="Decision: Pending"
        >
          Pending
        </span>
      );
  }
};
