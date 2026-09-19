import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { ToastProvider } from "../src/lib/toast";
import { SurveyStrip, toQuestions, sentProps, type Survey } from "../src/components/survey-strip";

const capture = vi.fn();
vi.mock("../src/lib/analytics", () => ({ surveysProvider: () => ({ on: vi.fn(), event: (...a: unknown[]) => capture(...a) }), track: vi.fn() }));

const survey: Survey = {
  id: "s1", name: "How was that?", type: "api",
  questions: [
    { id: "q1", type: "rating", question: "Useful?", display: "number", scale: 5, lowerBoundLabel: "No", upperBoundLabel: "Very" },
    { id: "q2", type: "single_choice", question: "For?", choices: ["Work", "Study"] },
    { id: "q3", type: "multiple_choice", question: "Which?", choices: ["A", "B"] },
    { id: "q4", type: "link", question: "Docs" },
    { id: "q5", type: "open", question: "More?" },
  ],
};

describe("survey questions", () => {
  it("maps types, skipping links", () => {
    const qs = toQuestions(survey);
    expect(qs.map((q) => q.options.length)).toEqual([5, 2, 2, 0]);
    expect(qs[0].options[0].hint).toBe("No");
    expect(qs[2].multi).toBe(true);
    expect(qs[3].open).toBe(true);
  });

  it("sends the answers the way PostHog's widget does", () => {
    const p = sentProps(survey, [["4"], ["Work"], ["A", "B"], "faster"]) as Record<string, unknown>;
    expect(p.$survey_response_q1).toBe(4);
    expect(p.$survey_response_q2).toBe("Work");
    expect(p.$survey_response_q3).toEqual(["A", "B"]);
    expect(p.$survey_response_q5).toBe("faster");
    expect(p).not.toHaveProperty("$survey_response_q4");
    expect(p.$survey_completed).toBe(true);
    expect((p.$set as Record<string, boolean>)["$survey_responded/s1"]).toBe(true);
    expect((p.$survey_questions as { response: unknown }[])[3].response).toBeNull();
  });
});

describe("the strip", () => {
  beforeEach(() => { capture.mockClear(); localStorage.clear(); });
  afterEach(cleanup);

  it("steps through every question and sends once at the end", () => {
    const onDone = vi.fn();
    render(<ToastProvider><SurveyStrip survey={survey} onDone={onDone} /></ToastProvider>);
    expect(capture).toHaveBeenCalledWith("survey shown", expect.objectContaining({ $survey_id: "s1" }));
    fireEvent.click(screen.getByText("4"));
    expect(screen.getByText("For?")).toBeTruthy();       // advanced, nothing sent
    expect(onDone).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Work"));
    fireEvent.click(screen.getByText("A"));
    fireEvent.click(screen.getByText("Send"));
    const input = screen.getByRole("textbox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "faster" } });
    fireEvent.keyDown(input, { key: "Enter" });
    const sent = capture.mock.calls.find((c) => c[0] === "survey sent")?.[1] as Record<string, unknown>;
    expect(sent.$survey_response_q1).toBe(4);
    expect(sent.$survey_response_q3).toEqual(["A"]);
    expect(sent.$survey_response_q5).toBe("faster");
    expect(localStorage.getItem("seenSurvey_s1")).toBe("true");
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("dismisses with PostHog's event and marks it seen", () => {
    const onDone = vi.fn();
    render(<ToastProvider><SurveyStrip survey={survey} onDone={onDone} /></ToastProvider>);
    fireEvent.click(screen.getByLabelText("Dismiss"));
    expect(capture).toHaveBeenCalledWith("survey dismissed", expect.objectContaining({ $survey_id: "s1", $survey_partially_completed: false }));
    expect(localStorage.getItem("seenSurvey_s1")).toBe("true");
    expect(onDone).toHaveBeenCalledTimes(1);
  });
});
