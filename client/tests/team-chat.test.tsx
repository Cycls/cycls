import { renderHook, act, render, screen, cleanup, fireEvent } from "@testing-library/react";
import { test, expect, afterEach, vi } from "vitest";
import { useChat } from "../src/hooks/use-chat";
import { MessageBubble } from "../src/components/message";

// A team chat: a message to the team alone runs nothing, and a teammate's message stands beside their face.

vi.mock("../src/lib/analytics", () => ({ track: vi.fn() }));
const TEAM = { agent: "Super", names: ["Super", "all", "Noura Saad"], people: { u_noura: "Noura Saad" }, me: "u_me" };
afterEach(() => { cleanup(); window.history.replaceState({}, "", "/"); });

test("a message to the team is kept with no run, and a new chat takes the id it was given", async () => {
  const bodies: Record<string, unknown>[] = [];
  global.fetch = vi.fn(async (_url: string, init?: RequestInit) => {
    bodies.push(JSON.parse(String(init?.body)));
    return new Response(JSON.stringify({ chat_id: "team-1", posted: true }), { headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
  const { result } = renderHook(() => useChat(""));
  await act(() => result.current.send("Nice, I'll check slide 4", undefined, "keyboard", { team: true, post: true }));
  expect(bodies).toEqual([{ messages: [{ role: "user", content: "Nice, I'll check slide 4", id: expect.any(String) }], post: true, team: true }]);
  expect(result.current.chatId).toBe("team-1");
  expect(result.current.messages.map((m) => m.role)).toEqual(["user"]);   // no reply waits under it
  expect(result.current.isStreaming).toBe(false);
});

test("a teammate's message shows who wrote it; yours stays as it is", () => {
  render(<>
    <MessageBubble message={{ role: "user", content: "تمام، أراجع الأرقام", by: { id: "u_noura", name: "Noura" } }} team={TEAM} />
    <MessageBubble message={{ role: "user", content: "Mine", by: { id: "u_me", name: "Mohammed", you: true } }} team={TEAM} />
  </>);
  expect(screen.getByText("Noura")).toBeTruthy();
  expect(screen.queryByText("Mohammed")).toBeNull();
});

test("in a team chat a name said is painted, and the agent's reply says it is the agent's", () => {
  const team = TEAM;
  render(<>
    <MessageBubble message={{ role: "user", content: "@super and @Noura Saad, look. @all too", by: { id: "u_me", you: true } }} team={team} />
    <MessageBubble message={{ role: "assistant", content: "", parts: [{ type: "text", text: "On it" }] }} team={team} />
  </>);
  expect(screen.getByText("@super").className).toContain("font-medium");
  expect(screen.getByText("@Noura Saad").className).toContain("font-medium");
  expect(screen.getByText("@all").className).toContain("font-medium");
  expect(screen.getByText("Super")).toBeTruthy();
});

test("an attached file opens in the canvas, not in a new page", () => {
  const open = vi.fn();
  render(<MessageBubble message={{ role: "user", content: "see", attachments: [{ name: "a.png", type: "image/png", url: "blob:a", size: 10, path: "uploads/a.png" }] }}
                        onOpenFile={open} />);
  expect(screen.queryByRole("link")).toBeNull();
  fireEvent.click(screen.getByAltText("a.png"));
  expect(open).toHaveBeenCalledWith("uploads/a.png");
});

test("a message sent here and read back by the team chat's next look, before its send returned, shows once", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: false });
  let sent = "";
  global.fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (/\/chat(\?|$)/.test(String(url))) {   // the send is slow: the look every 3s comes back first
      sent = JSON.parse(String(init?.body)).messages[0].id;
      await new Promise((r) => setTimeout(r, 4000));
      return new Response(JSON.stringify({ chat_id: "team-1", posted: true }), { headers: { "Content-Type": "application/json" } });
    }
    const messages = sent ? [{ role: "user", content: "On it", id: sent, by: { id: "u_me", you: true } }] : [];
    return new Response(JSON.stringify({ title: "t", messages, next: messages.length, run: null }), { headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
  const { result } = renderHook(() => useChat(""));
  await act(() => result.current.loadChat("team-1"));
  act(() => { void result.current.send("On it", undefined, "keyboard", { team: true, post: true }); });
  await act(async () => { await vi.advanceTimersByTimeAsync(3500); });
  expect(result.current.messages.map((m) => m.content)).toEqual(["On it"]);
  await act(async () => { await vi.advanceTimersByTimeAsync(7000); });
  expect(result.current.messages.map((m) => m.content)).toEqual(["On it"]);
  vi.useRealTimers();
});

test("during someone else's run a message to the team goes at once, and what is held shows to all", async () => {
  const posts: unknown[] = [];
  global.fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (/\/chat(\?|$)/.test(String(url))) {
      posts.push(JSON.parse(String(init?.body)));
      return new Response(JSON.stringify({ chat_id: "team-1", posted: true }), { headers: { "Content-Type": "application/json" } });
    }
    return new Response(JSON.stringify({ title: "t", messages: [], next: 0, run: "running",
      live: { held: [{ role: "user", content: "Before you", id: "held-01", by: { id: "u_omar", name: "Omar" } }], asker: { id: "u_eli", name: "Eli" } } }),
      { headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
  const { result } = renderHook(() => useChat(""));
  await act(() => result.current.loadChat("team-1"));
  expect(result.current.live.asker?.name).toBe("Eli");
  expect(result.current.live.held.map((m) => m.id)).toEqual(["held-01"]);
  await act(() => result.current.send("While Super works", undefined, "keyboard", { team: true, post: true }));
  expect(posts).toHaveLength(1);
});

test("a message's tools react in one click, and its delete asks once more", () => {
  const react = vi.fn(), rewrite = vi.fn(async () => {});
  render(<MessageBubble message={{ role: "user", content: "Mine", id: "msg-0001", by: { id: "u_me", you: true } }} team={TEAM} onReact={react} onRewrite={rewrite} />);
  fireEvent.click(screen.getByText("👍"));
  expect(react).toHaveBeenCalledWith("👍");
  fireEvent.click(screen.getByLabelText("Delete"));
  expect(rewrite).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Delete"));
  expect(rewrite).toHaveBeenCalledWith();
});

test("a video sent in the chat plays there when pressed, fetched only then", async () => {
  const resolve = vi.fn(async () => "blob:clip");
  const { container } = render(<MessageBubble message={{ role: "user", content: "", attachments: [{ name: "clip.mp4", type: "video/mp4", url: "", size: 10, path: "attachments/clip.mp4" }] }}
                                              resolveMedia={resolve} />);
  expect(resolve).not.toHaveBeenCalled();
  await act(async () => { fireEvent.click(screen.getByLabelText("clip.mp4")); });
  expect(resolve).toHaveBeenCalledWith("attachments/clip.mp4");
  expect(container.querySelector("video")?.getAttribute("src")).toBe("blob:clip");
});
