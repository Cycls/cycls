import { render, screen, act, cleanup, waitFor, fireEvent, within } from "@testing-library/react";
import { test, expect, afterEach, vi } from "vitest";
import { useChat, type ChatApi } from "../src/hooks/use-chat";
import { Chat } from "../src/components/chat";

// The chat view, rendered whole. A long chat opens on its newest page: it shows before its pictures arrive, and reaching
// the top reads the page before. A team workspace's people sit at the top of every chat, on a phone too, and who is
// typing shows as faces and dots.

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState({}, "", "/"); });
const browser = (desktop = false) => {
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: desktop && q.includes("min-width"), addEventListener() {}, removeEventListener() {} }));
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  URL.revokeObjectURL = () => {};
};

test("a chat opened again still reads its older messages at the top, and shows before its pictures", async () => {
  const watched: [Element, IntersectionObserverCallback][] = [];
  vi.stubGlobal("IntersectionObserver", class {
    constructor(private cb: IntersectionObserverCallback) {}
    observe(el: Element) { watched.push([el, this.cb]); }
    disconnect() {}
  });
  browser();
  const asked: string[] = [];
  const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
  global.fetch = vi.fn(async (url: string) => {
    asked.push(String(url));
    if (String(url).includes("/files/")) return new Promise<Response>(() => {});   // a picture still on its way
    if (String(url).includes("before=")) return json({ messages: [{ role: "user", content: "the first one" }], start: 0 });
    if (!String(url).includes("/chats/c1")) return json([]);
    return json({ title: "General", start: 40, next: 60, run: null, messages: [
      { role: "user", content: "the newest", attachments: [{ name: "a.png", type: "image/png", url: "", size: 1, path: "attachments/a.png" }] }] });
  }) as unknown as typeof fetch;
  let chat!: ChatApi;
  const Harness = () => { chat = useChat(""); return <Chat chat={chat} />; };
  render(<Harness />);

  act(() => { void chat.loadChat("c1"); });
  await screen.findByText("the newest");
  act(() => { void chat.loadChat("c1"); });
  await waitFor(() => expect(chat.chatLoading).toBe(false));
  const [top, seen] = watched.filter(([el]) => el.isConnected).at(-1)!;
  act(() => seen([{ isIntersecting: true, target: top } as IntersectionObserverEntry], {} as IntersectionObserver));
  await screen.findByText("the first one");
  expect(asked.some((u) => u.includes("before=40"))).toBe(true);
});

test.each([["computer", true], ["phone", false]])("on a %s a team workspace's people sit at the top of every chat, you first, and who is typing shows as faces and dots", async (_, desktop) => {
  browser(desktop);
  vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });
  global.fetch = vi.fn(async (url: string) => new Response(JSON.stringify(!String(url).includes("/chats/team-1") ? [] :
    { title: "Launch", next: 1, run: null, messages: [{ role: "user", content: "hi", id: "m00001", by: { id: "u_sara", name: "Sara" } }],
      live: { typing: [{ id: "u_sara", name: "Sara" }] } }), { headers: { "Content-Type": "application/json" } })) as unknown as typeof fetch;
  const general = { id: "t-shared", name: "General", type: "team" as const, role: "admin", builtin: "general" };
  const workspaces = { active: general, items: [general], canCreate: false, isOrgAdmin: true,
    orgMembers: [{ id: "u_me", name: "Mohammed" }, { id: "u_sara", name: "Sara" }], fetchMembers: async () => [] };
  let chat!: ChatApi;
  const Harness = () => { chat = useChat(""); return <Chat chat={chat} config={{ name: "super" } as never}
    account={{ user: { id: "u_me" }, workspaces } as never} />; };
  render(<Harness />);
  expect(await screen.findByRole("button", { name: "Members" })).toBeTruthy();   // a new chat, not a team chat: there too
  act(() => { void chat.loadChat("team-1"); });
  expect((await screen.findByRole("status")).getAttribute("title")).toBe("Sara is typing…");

  fireEvent.click(await screen.findByRole("button", { name: "Members" }));   // at the top on a phone as on a computer
  const list = within(screen.getByText("Manage people").parentElement!);   // the button is an admin's
  expect(list.getAllByText(/^(super|Mohammed|Sara)$/).map((e) => e.textContent)).toEqual(["Mohammed", "Sara"]);   // people only
  expect(list.getByText("Everyone in the organization")).toBeTruthy();
});
