import React from "react";
import { Lock, AlertTriangle } from "lucide-react";

interface FinalizeModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  isSubmitting?: boolean;
  contractName: string;
}

export const FinalizeModal: React.FC<FinalizeModalProps> = ({
  isOpen,
  onClose,
  onConfirm,
  isSubmitting = false,
  contractName,
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-[#22303C]/40 flex items-center justify-center p-4">
      <div
        className="bg-[#F7F5F1] rounded-[6px] max-w-md w-full border border-[#D9D5CC] overflow-hidden"
        role="dialog"
        aria-modal="true"
        aria-labelledby="finalize-modal-title"
      >
        <div className="p-6">
          <div className="w-10 h-10 rounded-full border border-[#D9D5CC] bg-[#EFECE6] text-[#22303C] flex items-center justify-center mx-auto mb-4">
            <Lock className="w-4 h-4" />
          </div>

          <h3
            id="finalize-modal-title"
            className="text-[18px] font-medium text-[#22303C] text-center mb-2"
          >
            Finalize Contract Review?
          </h3>

          <p className="text-[14px] text-[#6B7480] text-center leading-relaxed mb-4">
            You are about to finalize the review for{" "}
            <strong className="text-[#22303C] font-medium">{contractName}</strong>.
          </p>

          <div className="border border-[#D9D5CC] bg-[#EFECE6] rounded-[6px] p-3.5 mb-6 text-[13px] text-[#22303C] flex items-start gap-2.5">
            <AlertTriangle className="w-4 h-4 text-[#9A7B2F] shrink-0 mt-0.5" />
            <div className="leading-relaxed">
              <strong className="font-medium">Locking action:</strong> Finalizing locks all clause decisions and concludes the review. Once locked, you can export official Markdown, Word (.docx), and JSON reports.
            </div>
          </div>

          <div className="flex items-center justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="px-[18px] py-2 text-[14px] text-[#22303C] bg-transparent border border-[#D9D5CC] hover:border-[#22303C] rounded-[6px] transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={onConfirm}
              disabled={isSubmitting}
              className="inline-flex items-center gap-1.5 px-[18px] py-2 text-[14px] font-medium text-white bg-[#22303C] hover:opacity-90 rounded-[6px] transition-opacity disabled:opacity-50"
            >
              {isSubmitting ? (
                <>
                  <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  <span>Finalizing...</span>
                </>
              ) : (
                <>
                  <Lock className="w-3.5 h-3.5" />
                  <span>Finalize &amp; Lock</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
