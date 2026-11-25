import React, { useState } from "react";
import { PlaybookRule } from "../api/types";

interface PlaybookRuleCardProps {
  rule: PlaybookRule;
}

export const PlaybookRuleCard: React.FC<PlaybookRuleCardProps> = ({ rule }) => {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="border-b border-[#D9D5CC]">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        className="w-full py-3.5 flex items-center justify-between text-left text-[14px] text-[#22303C] hover:opacity-80 transition-opacity"
      >
        <span>
          {rule.rule_id} {rule.title}
        </span>
        <span className="text-[#22303C] text-[16px] leading-none ml-2 shrink-0">
          {isOpen ? "–" : "+"}
        </span>
      </button>

      {isOpen && (
        <div className="pb-4 text-[14px] text-[#6B7480] space-y-2.5 leading-relaxed">
          <div>
            <span className="text-[#22303C] font-medium">Standard position: </span>
            <span>{rule.standard_position}</span>
          </div>

          <div>
            <span className="text-[#22303C] font-medium">Acceptable fallback: </span>
            <span>{rule.acceptable_fallback}</span>
          </div>

          {rule.unacceptable_triggers && rule.unacceptable_triggers.length > 0 && (
            <div>
              <div className="text-[#A4493D] font-medium mb-1">
                Unacceptable triggers:
              </div>
              <ul className="list-disc list-inside space-y-0.5 text-[#A4493D]">
                {rule.unacceptable_triggers.map((trigger, idx) => (
                  <li key={idx}>{trigger}</li>
                ))}
              </ul>
            </div>
          )}

          {rule.rationale && (
            <div>
              <span className="text-[#22303C] font-medium">Rationale: </span>
              <span>{rule.rationale}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
