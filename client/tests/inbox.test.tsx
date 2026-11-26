import { renderHook, act, render, screen, cleanup, fireEvent } from "@testing-library/react";
import { test, expect, afterEach, vi } from "vitest";
import { InboxBell } from "../src/components/inbox";
import { useInbox, type InboxItem } from "../src/hooks/use-inbox";
import { chime } from "../src/lib/chime";

// The bell: what concerns you in every workspace, its count in the tab's title, an item opening its chat in its own
// workspace; something new sounds once, never on the first look nor for the chat in front of you.

vi.mock("../src/lib/chime", () => ({ chime: vi.fn(), soundsOn: () => true, setSoundsOn: vi.fn() }));
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.mocked(chime).mockClear(); document.title = "Super"; });

const OMAR: InboxItem = { id: "n1", kind: "mention", by: { id: "omar", name: "Omar" }, ws: "t-1", chat: "team-1",
                          title: "Budget", text: "@Mo can you check slide 4?", at: new Date().toISOString() };

test("the bell counts what is new, lists it when opened, and an item opens its chat where it lives", async () => {
  document.title = "Super";
  const open = vi.fn(async () => {}), onOpen = vi.fn();
  const { rerender } = render(<InboxBell inbox={{ items: [], unread: 2, open }} workspaces={[{ id: "t-1", name: "Research", icon: "🔬" }]}
                                         here="u-mo" onOpen={onOpen} />);
  expect(screen.getByText("2")).toBeTruthy();
  expect(document.title).toBe("(2) Super");
  fireEvent.click(screen.getByLabelText("Notifications"));
  expect(open).toHaveBeenCalled();
  rerender(<InboxBell inbox={{ items: [OMAR], unread: 0, open }} workspaces={[{ id: "t-1", name: "Research", icon: "🔬" }]}
                      here="u-mo" onOpen={onOpen} />);
  expect(document.title).toBe("Super");
  expect(screen.getByText("Omar")).toBeTruthy();
  expect(screen.getByText(/Budget · 🔬 Research/)).toBeTruthy();   // another workspace's, named
  fireEvent.click(screen.getByText("@Mo can you check slide 4?"));
  expect(onOpen).toHaveBeenCalledWith(OMAR);
});

test("a task that ended while you were away says how it ended, and opens its chat", () => {
  const onOpen = vi.fn();
  const away: InboxItem = { id: "a1", kind: "away", state: "approve", ws: "u-mo", chat: "c1", title: "Launch deck", at: new Date().toISOString() };
  render(<InboxBell inbox={{ items: [away], unread: 1, open: vi.fn(async () => {}) }} here="u-mo" onOpen={onOpen} />);
  fireEvent.click(screen.getByLabelText("Notifications"));
  expect(screen.getByText(/Launch deck/)).toBeTruthy();
  fireEvent.click(screen.getByText("Your task needs your OK"));
  expect(onOpen).toHaveBeenCalledWith(away);
});

test("a look every 15 seconds keeps the count, sounds for something new elsewhere, and reads what is about the chat in front", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: false });
  Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
  vi.spyOn(document, "hasFocus").mockReturnValue(true);
  const at = (m: number) => `2026-11-23T10:0${m}:00Z`;
  const answers = [{ items: [{ ...OMAR, at: at(0) }], unread: 1 },
                   { items: [{ ...OMAR, id: "n2", chat: "team-2", at: at(1) }], unread: 2 },
                   { items: [{ ...OMAR, id: "n3", chat: "team-1", at: at(2) }], unread: 3 }];
  const asked: string[] = [];
  const api = vi.fn(async (path: string) => {
    asked.push(path);
    const said = path === "/inbox/seen" ? { ok: true, unread: 2 } : answers.shift() ?? { items: [], unread: 2 };
    return new Response(JSON.stringify(said), { headers: { "Content-Type": "application/json" } });
  });
  const { result } = renderHook(() => useInbox(api, true, "team-1"));
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(result.current.unread).toBe(1);
  expect(chime).not.toHaveBeenCalled();   // what was there before the app opened
  await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
  expect(result.current.unread).toBe(2);
  expect(chime).toHaveBeenCalledTimes(1);   // new, in another chat
  await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
  expect(result.current.unread).toBe(2);   // new, but about the chat in front of you: read as it came
  expect(chime).toHaveBeenCalledTimes(1);
  expect(asked).toEqual(["/inbox?limit=1", "/inbox?limit=1", "/inbox?limit=1", "/inbox/seen"]);
});
