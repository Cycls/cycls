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

  it("Other opens a line to write in: for one choice, what is written is the answer", () => {
    const onSubmit = vi.fn();
    render(<AskCard questions={[questions[0]]} onSubmit={onSubmit} onDismiss={vi.fn()} />);
    fireEvent.click(screen.getByText("Other…"));
    expect(onSubmit).not.toHaveBeenCalled();
    const line = screen.getByPlaceholderText("Type your answer");
    fireEvent.change(line, { target: { value: "Sepia" } });
    fireEvent.keyDown(line, { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledWith(["Sepia"]);
  });

  it("an Other the model wrote is that line, in its words, never sent as an answer", () => {
    const onSubmit = vi.fn();
    const ask = [{ question: "أي نمط؟", options: [{ label: "داكن" }, { label: "أخرى (حدد)" }], multi: false }];
    render(<AskCard questions={ask} onSubmit={onSubmit} onDismiss={vi.fn()} />);
    expect(screen.getAllByRole("button").filter((b) => b.textContent === "أخرى (حدد)")).toHaveLength(1);
    fireEvent.click(screen.getByText("أخرى (حدد)"));
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.change(screen.getByPlaceholderText("اكتب إجابتك"), { target: { value: "بني" } });
    fireEvent.click(screen.getByText("إرسال"));
    expect(onSubmit).toHaveBeenCalledWith(["بني"]);
  });

  it("for several choices, what is written joins the picks", () => {
    const onSubmit = vi.fn();
    render(<AskCard questions={[questions[1]]} onSubmit={onSubmit} onDismiss={vi.fn()} />);
    fireEvent.click(screen.getByText("Pricing"));
    fireEvent.click(screen.getByText("Other…"));
    fireEvent.change(screen.getByPlaceholderText("Type your answer"), { target: { value: "FAQ" } });
    fireEvent.click(screen.getByText(/Submit/));
    expect(onSubmit).toHaveBeenCalledWith(["Pricing, FAQ"]);
  });
});
