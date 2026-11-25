import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RiskBadge } from "../components/RiskBadge";

describe("RiskBadge Component", () => {
  it("renders Acceptable risk badge with accessible text and styling", () => {
    render(<RiskBadge level="Acceptable" />);
    const badge = screen.getByLabelText("Risk level: Acceptable");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass("text-[#5E7A63]");
    expect(screen.getByText("Acceptable")).toBeInTheDocument();
  });

  it("renders Needs Negotiation risk badge", () => {
    render(<RiskBadge level="Needs Negotiation" />);
    const badge = screen.getByLabelText("Risk level: Needs Negotiation");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass("text-[#9A7B2F]");
    expect(screen.getByText("Needs negotiation")).toBeInTheDocument();
  });

  it("renders Unacceptable risk badge", () => {
    render(<RiskBadge level="Unacceptable" />);
    const badge = screen.getByLabelText("Risk level: Unacceptable");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass("text-[#A4493D]");
    expect(screen.getByText("Unacceptable")).toBeInTheDocument();
  });

  it("renders small size when specified", () => {
    render(<RiskBadge level="Acceptable" size="sm" />);
    const badge = screen.getByLabelText("Risk level: Acceptable");
    expect(badge).toHaveClass("text-[13px]");
  });
});
