import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DiffViewer } from "../components/DiffViewer";
import { DiffSegment } from "../api/types";

describe("DiffViewer Component", () => {
  const sampleDiff: DiffSegment[] = [
    { type: "equal", text: "Party A shall indemnify " },
    { type: "delete", text: "all damages " },
    { type: "insert", text: "direct damages only " },
    { type: "equal", text: "up to fees paid." },
  ];

  it("renders diff view with insertions underlined and deletions struck through", () => {
    render(
      <DiffViewer
        segments={sampleDiff}
        label="Suggested Redline Diff"
        isAiSuggestion={true}
      />
    );

    expect(screen.getByText("Suggested Redline Diff")).toBeInTheDocument();

    const insertedText = screen.getByText("direct damages only");
    expect(insertedText).toHaveClass("underline");

    const deletedText = screen.getByText("all damages");
    expect(deletedText).toHaveClass("line-through");

    // Check advisory disclaimer notice
    expect(screen.getByText(/AI suggestion, not yet approved/i)).toBeInTheDocument();
  });

  it("toggles between diff view and clean text view", () => {
    render(
      <DiffViewer
        segments={[
          { type: "delete", text: "Original" },
          { type: "insert", text: "Clean revised" },
          { type: "equal", text: " wording." },
        ]}
        cleanText="Clean revised wording."
      />
    );

    // Initial diff mode shows underline on insert
    expect(screen.getByText("Clean revised")).toHaveClass("underline");

    // Click Clean Text toggle
    const cleanButton = screen.getByRole("button", { name: /clean text/i });
    fireEvent.click(cleanButton);

    // Now clean revised text is rendered in clean view
    expect(screen.getByText("Clean revised wording.")).toBeInTheDocument();

    // Toggle back to Diff View
    const diffButton = screen.getByRole("button", { name: /diff view/i });
    fireEvent.click(diffButton);
    expect(screen.getByText("Clean revised")).toHaveClass("underline");
  });

  it("handles empty segments gracefully", () => {
    render(<DiffViewer segments={[]} />);
    expect(screen.getByText(/No redline suggested/i)).toBeInTheDocument();
  });
});
