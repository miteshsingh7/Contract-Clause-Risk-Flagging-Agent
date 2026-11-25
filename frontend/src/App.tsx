import React, { useState, useEffect } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Header } from "./components/Header";
import { HomePage } from "./pages/HomePage";
import { ReviewPage } from "./pages/ReviewPage";
import { NotFoundPage } from "./pages/NotFoundPage";

const STORAGE_KEY = "contract_reviewer_name";

export const App: React.FC = () => {
  const [reviewerName, setReviewerName] = useState<string>(() => {
    return localStorage.getItem(STORAGE_KEY) || "";
  });

  const handleReviewerNameChange = (name: string) => {
    setReviewerName(name);
    localStorage.setItem(STORAGE_KEY, name);
  };

  useEffect(() => {
    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY && e.newValue !== null) {
        setReviewerName(e.newValue);
      }
    };
    window.addEventListener("storage", handleStorageChange);
    return () => window.removeEventListener("storage", handleStorageChange);
  }, []);

  return (
    <BrowserRouter>
      <div className="min-h-screen flex flex-col bg-[#EFECE6] text-[#22303C] font-sans">
        <Header
          reviewerName={reviewerName}
          onReviewerNameChange={handleReviewerNameChange}
        />

        <main className="flex-1">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route
              path="/reviews/:reviewId"
              element={<ReviewPage reviewerName={reviewerName} />}
            />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </main>

        <footer className="border-t border-[#D9D5CC] bg-[#EFECE6] py-4 px-6 text-[13px] text-[#6B7480]">
          <div className="max-w-[1392px] mx-auto flex flex-col sm:flex-row items-center justify-between gap-2">
            <div>Contract Review — Advisory Only</div>
            <div>Not legal advice · Qualified legal counsel approval required</div>
          </div>
        </footer>
      </div>
    </BrowserRouter>
  );
};

export default App;
