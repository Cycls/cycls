import { it, expect, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { MessageBubble } from "../src/components/message";
import { setLang } from "../src/lib/i18n";
import type { AgentState, Part } from "../src/hooks/use-chat";

// The agents a turn started read as one card: a row each, the working ones first; a row opens that agent's work.

afterEach(() => { cleanup(); setLang("en"); });

const agent = (id: string, a: Partial<AgentState>): Part => ({
  type: "step", id, tool_name: "Agent", step: a.label,
  agent: { label: "", brief: "", status: "working", started: "2026-11-08T10:00:00Z", steps: [], ...a },
});

it("shows one card, the working agents first, and opens one's brief, steps and report", () => {
  render(<MessageBubble message={{ role: "assistant", content: "", parts: [
    { type: "text", text: "I'll split this up." },
    agent("a1", { label: "Draft the sheet", status: "done", ended: "2026-11-08T10:03:00Z",
                  brief: "Create pricing.xlsx", report: "pricing.xlsx is ready." }),
    agent("a2", { label: "Research prices", steps: [{ id: "s1", tool_name: "Web Search", step: "Jahez fee" }] }),
  ] }} />);
  expect(screen.getByText("2 agents")).toBeTruthy();
  const labels = screen.getAllByText(/Draft the sheet|Research prices/).map((e) => e.textContent);
  expect(labels).toEqual(["Research prices", "Draft the sheet"]);
  expect(screen.getByText("Web Search · Jahez fee")).toBeTruthy();
  fireEvent.click(screen.getByText("Draft the sheet"));
  expect(screen.getByText("Create pricing.xlsx")).toBeTruthy();
  expect(screen.getByText("Report")).toBeTruthy();
  fireEvent.pointerDown(screen.getByText("I'll split this up."));
  expect(screen.queryByText("Create pricing.xlsx")).toBeNull();
});

it("counts its agents in Arabic's own forms", () => {
  setLang("ar");
  render(<MessageBubble message={{ role: "assistant", content: "", parts: [agent("a1", { label: "أ" }), agent("a2", { label: "ب" })] }} />);
  expect(screen.getByText("وكيلان")).toBeTruthy();
});
