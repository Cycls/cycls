import { render, screen, act, cleanup, waitFor, fireEvent, within } from "@testing-library/react";
import { test, expect, afterEach, vi } from "vitest";
import { useChat, type ChatApi } from "../src/hooks/use-chat";
import { Chat } from "../src/components/chat";

// The chat view, rendered whole. A long chat opens on its newest page: it shows before its pictures arrive, and reaching
// the top reads the page before. A team workspace's people sit at the top of every chat on a computer, and who is
// typing shows as faces and dots. Search reaches every workspace, and a workspace switch shows what was there at once.

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState({}, "", "/"); sessionStorage.clear(); });
const browser = (desktop = false) => {
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: desktop && q.includes("min-width"), addEventListener() {}, removeEventListener() {} }));
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  URL.revokeObjectURL = () => {};
  Element.prototype.scrollIntoView = () => {};
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

test("a team workspace's people sit at the top of every chat, you first, and who is typing shows as faces and dots", async () => {
  browser(true);
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

  fireEvent.click(await screen.findByRole("button", { name: "Members" }));
  const list = within(screen.getByText("Manage people").parentElement!);   // the button is an admin's
  expect(list.getAllByText(/^(super|Mohammed|Sara)$/).map((e) => e.textContent)).toEqual(["Mohammed", "Sara"]);   // people only
  expect(list.getByText("Everyone in the organization")).toBeTruthy();
});

const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });

test("search reaches every workspace you're in: a hit from another says where it lives, and opens there as it loads", async () => {
  browser(true);
  vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });
  global.fetch = vi.fn(async () => json([])) as unknown as typeof fetch;
  const research = { id: "t-research", name: "Research", icon: "🔬", type: "team" as const, role: "editor" };
  const found = { workspaces: [{ id: "u-u_me", name: "Personal" }, research], chats: [], apps: [],
    files: [{ name: "plan.md", path: "docs/plan.md", ws: "t-research" }] };
  const switched: (string | null)[] = [];
  const files = { entries: [], path: "", onNavigate() {}, readFile: async () => "# Plan", onOpenFile: async () => "", searchFiles: async () => [] };
  const Harness = ({ at }: { at: typeof research | null }) => <Chat key={at?.id} view={`search:${at?.id}`} chat={useChat("")} files={files as never}
    account={{ user: { id: "u_me" }, workspaces: { active: at, items: [research], canCreate: false, isOrgAdmin: false, orgMembers: [],
      fetchMembers: async () => [], onSwitch: (id: string | null) => switched.push(id), search: async () => found } } as never} />;
  const { rerender } = render(<Harness at={null} />);
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
  fireEvent.change(screen.getByPlaceholderText("Search chats, files and apps…"), { target: { value: "plan" } });
  fireEvent.click(await screen.findByText("🔬 Research"));
  expect(switched).toEqual(["t-research"]);
  expect(window.location.search).toBe("?file=docs%2Fplan.md");
  rerender(<Harness at={research} />);   // App remounts Chat on the workspace switched to
  expect((await screen.findAllByText("plan.md")).length).toBeGreaterThan(0);   // its canvas tab
  expect(window.location.search).toBe("");
});

test("back in a workspace, its chats show at once while the fresh list loads, the panel still open", async () => {
  browser(true);
  vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });
  sessionStorage.setItem("cycls_panel", "1");
  sessionStorage.setItem("cycls_panel_tab", "chats");
  let listed: Promise<Response> = Promise.resolve(json([{ id: "c1", title: "Launch plan", updatedAt: "2026-11-20T10:00:00Z" }]));
  global.fetch = vi.fn(async (url: string) => (String(url).includes("/chats") ? (await listed).clone() : json([]))) as unknown as typeof fetch;
  const Harness = ({ view }: { view: string }) => <Chat key={view} view={view} chat={useChat("")} account={{ user: { id: "u_me" } } as never} />;
  const { rerender } = render(<Harness view="back:a" />);
  await screen.findByText("Launch plan");
  listed = Promise.resolve(json([{ id: "c2", title: "Hiring", updatedAt: "2026-11-21T10:00:00Z" }]));
  rerender(<Harness view="back:b" />);
  await screen.findByText("Hiring");
  listed = new Promise(() => {});   // the fresh list never comes
  rerender(<Harness view="back:a" />);
  expect(screen.getByText("Launch plan")).toBeTruthy();
  expect(screen.queryByText("Hiring")).toBeNull();
});
