import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { AskCard } from "../src/components/ask-card";

vi.mock("../src/lib/analytics", () => ({ track: vi.fn() }));

const questions = [
  { question: "Which style?", options: [{ label: "Dark" }, { label: "Light" }], multi: false },
  { question: "Which sections?", options: [{ label: "Pricing" }, { label: "Team" }], multi: true },
  { question: "Anything else?", options: [], multi: false },
];

describe("AskCard", () => {
  afterEach(cleanup);
  it("a single-select tap advances; only the last step submits", () => {
    const onSubmit = vi.fn(), onDismiss = vi.fn();
    render(<AskCard questions={questions} onSubmit={onSubmit} onDismiss={onDismiss} />);
    fireEvent.click(screen.getByText("Dark"));
    expect(screen.getByText("Which sections?")).toBeTruthy();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(onDismiss).not.toHaveBeenCalled();
  });
});
