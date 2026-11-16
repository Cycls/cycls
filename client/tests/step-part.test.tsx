import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup, screen, act } from "@testing-library/react";
import { StepPart, writingNow } from "../src/components/parts/step-part";
import { setLang } from "../src/lib/i18n";

// A deck's tool input streams for minutes. The row showed only the tool's name and a
// pulse — which read as stuck, and got Stop pressed. It now says what is being written
// and for how long.

afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("writingNow — the value a tool call's input is on", () => {
  const open = '{"action":"render","spec":{"frames":[{"layout":"cover","title": "Brewly — Q3 rev';

  it("is the text streamed so far", () => {
    expect(writingNow(open)).toBe("Brewly — Q3 rev");
    expect(writingNow(open + 'iew","subtitle": "')).toBe("");                 // the next value hasn't started
    expect(writingNow(open + 'iew"')).toBe("Brewly — Q3 review");             // a value that has closed
  });

  it("reads escapes, even one the stream cut in half", () => {
    expect(writingNow('{"text": "say \\"hi\\"\\nnow')).toBe('say "hi" now');
    expect(writingNow('{"text": "\\u0645\\u0631\\u062d\\u0628')).toBe("مرحب");
    expect(writingNow('{"text": "\\u0645\\u0631\\u062d\\u06')).toBe("مرح");    // the fourth letter is half-sent
    expect(writingNow('{"text": "line one\\')).toBe("line one");
  });

  it("keeps the latest of a long value, and nothing when there is no text", () => {
    const long = writingNow(`{"content": "${"word ".repeat(60)}the end`);
    expect(long.length).toBeLessThanOrEqual(80);
    expect(long.endsWith("the end")).toBe(true);
    expect(writingNow('{"number": 42, "list": [1, 2')).toBe("");
    expect(writingNow(undefined)).toBe("");
  });
});

describe("a live tool row", () => {
  it("says what is being written until its label arrives", () => {
    const { rerender } = render(<StepPart step="" toolName="Design" isStreaming args={'{"spec":{"title": "Market size'} />);
    expect(screen.getByTestId("step-writing").textContent).toBe(" · writing… “Market size”");
    rerender(<StepPart step="pitch" toolName="Design" isStreaming args={'{"spec":{"title": "Market size"}}'} />);
    expect(screen.queryByTestId("step-writing")).toBeNull();                   // the call is running: its own label
    rerender(<StepPart step="" toolName="Design" args={'{"spec":{"title": "Market size'} />);
    expect(screen.queryByTestId("step-writing")).toBeNull();                   // not live: history
  });

  it("shows how long it has been going, once that is worth knowing", () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000);
    render(<StepPart step="" toolName="Design" isStreaming args="{" at={1_000_000} />);
    expect(screen.queryByTestId("step-elapsed")).toBeNull();
    act(() => { vi.advanceTimersByTime(42_000); });
    expect(screen.getByTestId("step-elapsed").textContent).toBe("42s");
    act(() => { vi.advanceTimersByTime(30_000); });
    expect(screen.getByTestId("step-elapsed").textContent).toBe("1m 12s");
  });

  it("a finished row has no timer", () => {
    render(<StepPart step="pitch" toolName="Design" at={Date.now() - 60_000} />);
    expect(screen.queryByTestId("step-elapsed")).toBeNull();
  });
});

describe("a built-in tool's row says what it does in plain words, in the person's language", () => {
  afterEach(() => setLang("en"));

  it("names the tool plainly, never its code name", () => {
    render(<StepPart toolName="Bash" step="Convert the report to PDF" />);
    expect(screen.getByText("Task")).toBeTruthy();
    expect(screen.queryByText(/Bash/)).toBeNull();
    cleanup();
    render(<StepPart toolName="Database" step="apps/expense-tracker/orders" />);   // an app's data, not memory
    expect(screen.getByText("App data")).toBeTruthy();
    expect(screen.getByText("expense-tracker: orders")).toBeTruthy();
  });

  it("in Arabic too, Design included, with its document's tile", () => {
    setLang("ar");
    const { container } = render(<StepPart toolName="Design" step="launch-poster" />);
    expect(screen.getByText("تصميم")).toBeTruthy();
    expect(container.textContent).toContain("design");   // the design's own tile
  });
});
