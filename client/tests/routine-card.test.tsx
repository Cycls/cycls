import { render, screen, cleanup, fireEvent, act } from "@testing-library/react";
import { test, expect, afterEach, vi } from "vitest";
import { MessageBubble } from "../src/components/message";
import { RoutinesContext, whenText, type Routine } from "../src/components/routine-card";
import { RoutinesPanel } from "../src/components/routines-panel";
import type { Connector } from "../src/components/connectors-dialog";

// A routine the agent proposes stands in its message: nothing is made before Set up, then it is the routine's card
// with Run now. A run's chat opens with a small line, not the instruction.

vi.mock("../src/lib/analytics", () => ({ track: vi.fn() }));
afterEach(cleanup);

const TENDERS: Routine = { id: "p1", name: "New construction tenders", prompt: "Look up construction tenders in Riyadh",
                           when: { every: "days", days: ["sun", "mon", "tue", "wed", "thu"], time: "08:00", tz: "Asia/Riyadh" },
                           fresh: true, connectors: [], files: ["apps/tenders"] };
const card = (extra = {}) => ({ role: "assistant" as const, content: "", parts: [{ type: "card", card: { action: "routine", routine: TENDERS, ...extra }, state: "waiting" }] });

test("its days and time, as the person's language says them", () => {
  expect(whenText(TENDERS.when)).toBe("Sun, Mon, Tue, Wed, Thu · 8:00 AM");
  expect(whenText({ every: "day", time: "21:30", tz: "UTC" })).toBe("Every day · 9:30 PM");
});

test("nothing is made before Set up, and then the card is the routine's, with Run now", async () => {
  const make = vi.fn(async () => {}), now = vi.fn(async () => {});
  const ctx = { routines: [] as Routine[], make, save: vi.fn(), remove: vi.fn(), now };
  const { rerender } = render(<RoutinesContext.Provider value={ctx}><MessageBubble message={card()} /></RoutinesContext.Provider>);
  expect(screen.getByText("A new chat for each run")).toBeTruthy();
  expect(screen.getByText("tenders")).toBeTruthy();
  expect(screen.queryByText("Run now")).toBeNull();
  await act(async () => { fireEvent.click(screen.getByText("Set up")); });
  expect(make).toHaveBeenCalledWith(TENDERS);
  rerender(<RoutinesContext.Provider value={{ ...ctx, routines: [TENDERS] }}><MessageBubble message={card()} /></RoutinesContext.Provider>);
  expect(screen.getByText("New construction tenders is set up")).toBeTruthy();
  await act(async () => { fireEvent.click(screen.getByText("Run now")); });
  expect(now).toHaveBeenCalledWith("p1");
});

test("Cancel makes nothing, and a run's chat opens with its line", () => {
  render(<RoutinesContext.Provider value={{ routines: [], make: vi.fn(), save: vi.fn(), remove: vi.fn(), now: vi.fn() }}>
    <MessageBubble message={card()} />
    <MessageBubble message={{ role: "user", content: "Look up construction tenders", routine: { id: "p1", name: "Tenders", at: "2026-11-23T05:00:00Z" } }} />
  </RoutinesContext.Provider>);
  fireEvent.click(screen.getByText("Cancel"));
  expect(screen.getByText("Not set up")).toBeTruthy();
  expect(screen.getByText(/^Routine · Tenders · /)).toBeTruthy();
  expect(screen.queryByText("Look up construction tenders")).toBeNull();
});

test("the tab shows the agent's ideas until the first routine; an idea puts its words in the box", () => {
  const onUse = vi.fn();
  const ideas = [{ name: "News on a topic", prompt: "Every morning at 8, send me what is new about [topic].", icon: "globe" }];
  const { rerender } = render(<RoutinesPanel routines={[]} examples={ideas} onNew={vi.fn()} onOpenChat={vi.fn()} onUse={onUse} />);
  fireEvent.click(screen.getByText("News on a topic"));
  expect(onUse).toHaveBeenCalledWith("Every morning at 8, send me what is new about [topic].");
  rerender(<RoutinesPanel routines={[{ ...TENDERS, on: true }]} examples={ideas} onNew={vi.fn()} onOpenChat={vi.fn()} onUse={onUse} />);
  expect(screen.getByText("New construction tenders")).toBeTruthy();
  expect(screen.queryByText("Ideas to start from")).toBeNull();
  expect(screen.queryByText("News on a topic")).toBeNull();
});

test("a file it works with opens in the canvas", () => {
  const open = vi.fn();
  render(<RoutinesContext.Provider value={{ routines: [], make: vi.fn(), save: vi.fn(), remove: vi.fn(), now: vi.fn(), edit: vi.fn(), open }}>
    <MessageBubble message={card()} />
  </RoutinesContext.Provider>);
  fireEvent.click(screen.getByText("tenders"));
  expect(open).toHaveBeenCalledWith("apps/tenders");
});

test("a connector the routine needs shows its state, Connect is on the card, and Set up waits for it", () => {
  const connect = vi.fn();
  const mail: Routine = { ...TENDERS, id: "p2", connectors: ["outlook"], files: [] };
  const msg = { role: "assistant" as const, content: "", parts: [{ type: "card", card: { action: "routine", routine: mail }, state: "waiting" }] };
  const ctx = (connected: boolean) => ({ routines: [], make: vi.fn(), save: vi.fn(), remove: vi.fn(), now: vi.fn(), edit: vi.fn(), connect,
    connectors: [{ name: "outlook", connected, title: { en: "Outlook", ar: "Outlook" } } as unknown as Connector] });
  const { rerender } = render(<RoutinesContext.Provider value={ctx(false)}><MessageBubble message={msg} /></RoutinesContext.Provider>);
  expect(screen.getByText("Connect Outlook to set it up")).toBeTruthy();
  expect((screen.getByText("Set up") as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByText("Connect"));
  expect(connect).toHaveBeenCalledWith("outlook");
  rerender(<RoutinesContext.Provider value={ctx(true)}><MessageBubble message={msg} /></RoutinesContext.Provider>);
  expect((screen.getByText("Set up") as HTMLButtonElement).disabled).toBe(false);
  expect(screen.getByText("A new chat for each run")).toBeTruthy();
});
