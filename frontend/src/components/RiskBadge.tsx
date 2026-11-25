import React from "react";
import { RiskLevel } from "../api/types";

interface RiskBadgeProps {
  level: RiskLevel | string;
  size?: "sm" | "md";
}

export const RiskBadge: React.FC<RiskBadgeProps> = ({ level, size = "md" }) => {
  const isSm = size === "sm";
  const baseClasses = isSm
    ? "inline-flex items-center text-[13px] font-normal"
    : "inline-flex items-center text-[14px] font-normal";

  switch (level) {
    case "Acceptable":
      return (
        <span
          className={`${baseClasses} text-[#5E7A63]`}
          aria-label="Risk level: Acceptable"
        >
          Acceptable
        </span>
      );

    case "Needs Negotiation":
      return (
        <span
          className={`${baseClasses} text-[#9A7B2F]`}
          aria-label="Risk level: Needs Negotiation"
        >
          Needs negotiation
        </span>
      );

    case "Unacceptable":
      return (
        <span
          className={`${baseClasses} text-[#A4493D]`}
          aria-label="Risk level: Unacceptable"
        >
          Unacceptable
        </span>
      );

    default:
      return (
        <span
          className={`${baseClasses} text-[#6B7480]`}
          aria-label={`Risk level: ${level}`}
        >
          {level || "Unrated"}
        </span>
      );
  }
};
