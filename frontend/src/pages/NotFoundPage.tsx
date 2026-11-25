import React from "react";
import { Link } from "react-router-dom";
import { FileQuestion, ArrowLeft } from "lucide-react";

export const NotFoundPage: React.FC = () => {
  return (
    <div className="min-h-[60vh] flex items-center justify-center px-6">
      <div className="max-w-md w-full text-center bg-[#F7F5F1] border border-[#D9D5CC] rounded-[6px] p-8">
        <div className="w-12 h-12 bg-[#EFECE6] border border-[#D9D5CC] text-[#22303C] rounded-full flex items-center justify-center mx-auto mb-4">
          <FileQuestion className="w-6 h-6" />
        </div>
        <h1 className="text-[20px] font-medium text-[#22303C] mb-2">Page Not Found</h1>
        <p className="text-[14px] text-[#6B7480] mb-6">
          The requested page or contract review does not exist.
        </p>
        <Link
          to="/"
          className="inline-flex items-center gap-2 px-[18px] py-2 bg-[#22303C] text-white rounded-[6px] text-[14px] font-medium hover:opacity-90 transition-opacity"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Contracts
        </Link>
      </div>
    </div>
  );
};

export default NotFoundPage;
