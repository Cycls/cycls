import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";
import { MessageBubble } from "../src/components/message";
import { setLang } from "../src/lib/i18n";
import type { Message, Part } from "../src/hooks/use-chat";

// A long turn reads as one line of work: think, call, think, call folds into a single "N steps" summary, and a
// tool that says what it does in plain words (`.on(title=…)`) shows a sentence in the UI's language, not name(input).

afterEach(() => { cleanup(); setLang("en"); });

const said = (parts: Part[]): Message => ({ role: "assistant", content: "", parts });
const think = (s: string): Part => ({ type: "thinking", thinking: s });
const sql = (id: string, step: string, ar: string): Part => ({
  type: "step", id, tool_name: "checked market data", step, plain: true, ok: true,
  i18n: { ar: { tool_name: "راجعت بيانات السوق", step: ar } },
});

describe("a stretch of work", () => {
  it("folds thinking and steps into one summary line, counting only the steps", () => {
    render(<MessageBubble message={said([
      think("first I need the results"), sql("t1", "Checking quarterly results for 4030", "أراجع النتائج الربعية لـ 4030"),
      think("now prices"), sql("t2", "Checking prices for 4030", "أراجع الأسعار لـ 4030"),
      think("enough to answer"), { type: "text", text: "Bahri's profit rose." },
    ])} />);
    expect(screen.getByText("2 steps")).toBeTruthy();
    expect(screen.getByText(/checked market data/)).toBeTruthy();
    expect(screen.queryByText("Thinking")).toBeNull();                       // folded away, not a ladder of them
    expect(screen.queryByText("Checking prices for 4030")).toBeNull();
    expect(screen.getByText("Bahri's profit rose.")).toBeTruthy();

    fireEvent.click(screen.getByText("2 steps"));
    expect(screen.getByText("Checking prices for 4030")).toBeTruthy();       // a sentence, not checked market data(…)
    expect(screen.getAllByText("Thinking")).toHaveLength(3);
  });

  it("one step with its thinking still folds, and says step, not steps", () => {
    render(<MessageBubble message={said([think("look it up"), sql("t1", "Checking prices for 2222", "أراجع الأسعار لـ 2222")])} />);
    expect(screen.getByText("1 step")).toBeTruthy();
  });

  it("thinking alone, before the answer, stays as it was", () => {
    render(<MessageBubble message={said([think("easy one"), { type: "text", text: "Yes." }])} />);
    expect(screen.getByText("Thinking")).toBeTruthy();
  });

  it("speaks the UI's language when the tool gave its words in it", () => {
    setLang("ar");
    render(<MessageBubble message={said([think("x"), sql("t1", "Checking prices for 2222", "أراجع الأسعار لـ 2222"),
                                         sql("t2", "Checking prices for 1120", "أراجع الأسعار لـ 1120")])} />);
    expect(screen.getByText(/راجعت بيانات السوق/)).toBeTruthy();
    fireEvent.click(screen.getByText(/2 خطوات/));
    expect(screen.getByText("أراجع الأسعار لـ 1120")).toBeTruthy();
  });

  it("stays one line while it streams: a tool's raw result and a blank line between calls split nothing", () => {
    const raw = { columns: ["close"], rows: [[27.1]] } as unknown as Part;   // a custom tool's result, no `type`
    render(<MessageBubble isStreaming message={said([
      think("a"), sql("t1", "Checking prices for 2222", "…"), raw, { type: "text", text: "\n\n" },
      think("b"), sql("t2", "Checking dividends for 2222", "…"), raw,
      think("c"), sql("t3", "Checking company profiles for 2222", "…"),
    ])} />);
    expect(screen.getByText("3 steps")).toBeTruthy();
    expect(screen.getAllByText(/steps?$/)).toHaveLength(1);
  });

  it("keeps the live step in view under the summary while the turn runs", () => {
    render(<MessageBubble isStreaming message={said([
      sql("t1", "Checking prices for 2222", "أراجع الأسعار لـ 2222"), think("hmm"),
      sql("t2", "Checking dividends for 2222", "أراجع التوزيعات لـ 2222"),
    ])} />);
    expect(screen.getByText("Checking dividends for 2222")).toBeTruthy();
    expect(screen.queryByText("Checking prices for 2222")).toBeNull();
  });

  it("says how long the stretch took, from its first part to what came after it", () => {
    const t = 1_800_000_000_000;
    render(<MessageBubble message={said([
      { ...think("a"), at: t }, { ...sql("t1", "Checking prices for 2222", "…"), at: t + 4_000 },
      { ...think("b"), at: t + 9_000 }, { ...sql("t2", "Checking dividends for 2222", "…"), at: t + 20_000 },
      { type: "text", text: "Done.", at: t + 72_000 },
    ])} />);
    expect(screen.getByTestId("steps-span").textContent).toContain("1m 12s");
  });

  it("counts up while it runs, and the live step under it shows no second clock", () => {
    vi.useFakeTimers();
    const t = Date.now();
    render(<MessageBubble isStreaming message={said([
      { ...think("a"), at: t - 40_000 }, { ...sql("t1", "Checking prices for 2222", "…"), at: t - 30_000 },
      { ...sql("t2", "Checking dividends for 2222", "…"), at: t - 20_000 },
    ])} />);
    expect(screen.getByTestId("steps-span").textContent).toContain("40s");
    expect(screen.queryByTestId("step-elapsed")).toBeNull();
    act(() => { vi.advanceTimersByTime(3_000); });
    expect(screen.getByTestId("steps-span").textContent).toContain("43s");
    vi.useRealTimers();
  });

  it("thinking wears the same star as a step, in the group and alone", () => {
    const star = (el: Element | null) => el?.querySelector('svg[viewBox="0 0 161 161"] path')?.getAttribute("d");
    render(<MessageBubble message={said([think("a"), sql("t1", "Checking prices for 2222", "…"),
                                         think("b"), sql("t2", "Checking dividends for 2222", "…")])} />);
    fireEvent.click(screen.getByText("2 steps"));
    const thought = screen.getAllByTestId("thinking-row")[0];
    const step = screen.getByText("Checking prices for 2222").parentElement;
    expect(star(thought)).toBeTruthy();
    expect(star(thought)).toBe(star(step));
    cleanup();
    render(<MessageBubble message={said([think("easy one"), { type: "text", text: "Yes." }])} />);
    expect(star(screen.getByTestId("thinking-row"))).toBeTruthy();
  });
});
