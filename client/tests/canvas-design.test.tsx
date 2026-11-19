import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, cleanup, act, fireEvent, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { Canvas, addMenuLeft, type CanvasFile } from "../src/components/canvas";
import { DESIGN_PRESETS } from "../src/components/canvas-utils";
import { encPath } from "../src/hooks/use-files";

// Designs in the canvas: a design opens in its editor — ▶ Present, the slide tools and the notes are in the
// editor, which asks the canvas to present and to add a slide; an older editor (no "present" in its `ready`)
// keeps the Edit | Preview switch. Every open tab stays mounted, hidden, and a design editor whose tab is
// closed stays until it has saved what's unsaved; "New design" is in the + menu, with the server's sizes.

const EDITOR = "https://ed.example";
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const TABS: CanvasFile[] = [{ path: "designs/a.fig", name: "a.fig" }, { path: "notes.md", name: "notes.md" }];
const ONE = JSON.stringify({ count: 1, slides: ["data:image/jpeg;base64,S1"], fig: "designs/a.fig" });

function canvas(active: string, extra: Record<string, unknown> = {}) {
  return (
    <Canvas tabs={TABS} active={active} docked hidden={false} expanded={false}
            onToggleExpand={() => {}} onSelectTab={() => {}} onCloseTab={() => {}} onHide={() => {}}
            readFile={async (p: string) => (p.includes("?as=slides") ? ONE : "# notes")} openFile={async () => "blob:fig"} writeFile={async () => {}}
            designEditorUrl={EDITOR} {...extra} />
  );
}
// The design's editor, and what it says to this window; `talk` also answers its flushes (nothing unsaved).
function editorOf(container: HTMLElement) {
  const frame = container.querySelector("iframe")!;
  const say = (type: string, extra: Record<string, unknown> = {}) => window.dispatchEvent(
    new MessageEvent("message", { origin: EDITOR, source: frame.contentWindow, data: { source: "cycls-editor", type, ...extra } }));
  return { frame, say };
}
function talk(container: HTMLElement) {
  const { frame, say } = editorOf(container);
  const post = vi.spyOn(frame.contentWindow!, "postMessage");
  post.mockImplementation(((m: Record<string, unknown>) => { if (m.type === "flush") say("flushed", { id: m.id, ok: true }); }) as never);
  const sent = (type: string) => post.mock.calls.map((c) => c[0] as Record<string, unknown>).filter((m) => m.type === type);
  return { frame, say, post, sent };
}
// An older editor — no "present" in its `ready` (today's production one): it keeps the Edit | Preview switch.
async function older(container: HTMLElement, features: string[] = []) {
  const t = talk(container);
  t.say("ready", { protocol: 2, features });
  await flush();
  await flush();
  return t;
}
const toEdit = async () => { fireEvent.click(screen.getByRole("button", { name: "Edit" })); await flush(); };
const toPreview = async () => { fireEvent.click(screen.getByRole("button", { name: "Preview" })); await flush(); await flush(); };

describe("the + menu", () => {
  it("stays inside the window", () => {
    expect(addMenuLeft(400, 1536)).toBe(400);            // room to spare: under the button
    expect(addMenuLeft(1289, 1536)).toBe(1240);          // QA: its right edge was at 1577 in a 1536 window
    expect(addMenuLeft(20, 300)).toBe(8);                // a window narrower than the menu: from the left
  });
});

describe("a design's Download", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ arrayBuffer: async () => new Uint8Array([1]).buffer })));
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("offers the picture and a PDF, not only the .fig", async () => {
    // ⋮ › Download gave the .fig alone: nothing a person can post or send.
    const openFile = vi.fn(async () => "blob:x");
    render(canvas("designs/a.fig", { openFile }));
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    for (const label of ["Download PNG", "Download PDF", "Download design (.fig)"]) expect(screen.getByText(label)).toBeTruthy();
    expect(screen.queryByText("Download")).toBeNull();
    openFile.mockClear();
    await act(async () => { fireEvent.click(screen.getByText("Download PDF")); await new Promise((r) => setTimeout(r, 0)); });
    expect(openFile).toHaveBeenCalledWith("designs/a.fig?as=pdf&download=1");
  });

  it("another file keeps its one Download", async () => {
    render(canvas("notes.md"));
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    expect(screen.getByText("Download")).toBeTruthy();
    expect(screen.queryByText("Download PDF")).toBeNull();
  });
});

describe("a design opens in its editor", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ arrayBuffer: async () => new Uint8Array([1]).buffer })));
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  const slides = (n: number) => JSON.stringify({ count: n, slides: Array.from({ length: n }, (_, i) => `data:image/jpeg;base64,S${i + 1}`),
                                                 names: Array.from({ length: n }, (_, i) => `slide-${i + 1}`), fig: "designs/a.fig" });
  const reader = (n: number) => vi.fn(async (p: string) => (p.includes("?as=slides") ? slides(n) : "# notes"));
  // The editor up and loaded, saying it presents.
  async function opened(container: HTMLElement) {
    const t = talk(container);
    t.say("ready", { protocol: 2, features: ["present"] });
    await flush();
    await flush();
    t.say("loaded", { doc: t.sent("load")[0]?.doc });
    await flush();
    return t;
  }

  it("at once, with a picture of its first slide until the editor has it — and no Edit | Preview", async () => {
    const readFile = reader(1);
    const { container } = render(canvas("designs/a.fig", { readFile }));
    await flush();
    const frame = container.querySelector("iframe")!;
    expect(frame).toBeTruthy();                                              // the editor, not a preview first
    expect(frame.closest("[inert]")).toBeNull();
    expect(readFile).toHaveBeenCalledWith("designs/a.fig?as=slides", true); // its slides as pictures, once
    expect((screen.getByTestId("design-opening").querySelector("img") as HTMLImageElement).src).toBe("data:image/jpeg;base64,S1");
    const t = talk(container);
    t.say("ready", { protocol: 2, features: ["present"] });
    await flush();
    await flush();
    expect(screen.queryByRole("button", { name: "Preview" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(t.sent("host")).toEqual([{ target: "cycls-editor", type: "host", features: ["present", "slides"] }]);
    expect(screen.getByTestId("design-opening")).toBeTruthy();               // until the editor has the design
    t.say("loaded", { doc: t.sent("load")[0]?.doc });
    await flush();
    expect(screen.queryByTestId("design-opening")).toBeNull();
    expect(screen.queryByTestId("design-preview")).toBeNull();
  });

  it("on a narrow screen too (a phone had only the preview)", async () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} }));
    const { container } = render(canvas("designs/a.fig", { readFile: reader(1) }));
    await flush();
    expect(container.querySelector("iframe")).toBeTruthy();
  });

  it("one the agent is making shows no picture, and stays in the editor when its turn ends", async () => {
    const live = (on: boolean) => canvas("designs/a.fig", { readFile: reader(1), tabs: [{ path: "designs/a.fig", name: "a", live: on }, TABS[1]] });
    const { container, rerender } = render(live(true));
    await flush();
    const frame = container.querySelector("iframe")!;
    expect(screen.queryByTestId("design-opening")).toBeNull();               // it is drawn in the editor as it is made
    talk(container).say("ready", { protocol: 2, features: ["present"] });
    await flush();
    rerender(live(false));                                                    // the turn is over
    await flush();
    await flush();
    expect(container.querySelector("iframe")).toBe(frame);
    expect(frame.closest("[inert]")).toBeNull();
    expect(screen.queryByTestId("design-preview")).toBeNull();
  });

  it("says what it is beside its name", async () => {
    const deck = JSON.stringify({ count: 8, slides: Array(8).fill("data:image/jpeg;base64,S"), fig: "designs/a.fig", kind: "deck" });
    render(canvas("designs/a.fig", { readFile: async (p: string) => (p.includes("?as=slides") ? deck : "") }));
    await flush();
    expect(screen.getByTestId("design-kind").textContent).toBe("· Deck · 8 slides");
    expect(screen.getAllByText("a").length).toBeGreaterThan(0);               // its name, without ".fig"
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    for (const label of ["Download PDF", "Download PowerPoint", "Download images (.zip)", "Download design (.fig)"]) expect(screen.getByText(label)).toBeTruthy();
  });

  it("▶ Present in the editor: the deck as saved, full screen, from that slide", async () => {
    const readFile = reader(3);
    const { container } = render(canvas("designs/a.fig", { readFile }));
    await flush();
    const t = await opened(container);
    let answer = true;
    t.post.mockImplementation(((m: Record<string, unknown>) => { if (m.type === "flush" && answer) t.say("flushed", { id: m.id, ok: true }); }) as never);
    answer = false;                                                           // the save, held: nothing is read before it
    readFile.mockClear();
    t.say("present", { doc: t.sent("load")[0]?.doc, slide: "slide-2", index: 0 });   // by name, not its place
    await flush();
    expect(screen.getByTestId("present-getting").textContent).toBe("Getting the slides ready…");   // at once
    const ask = t.sent("flush").at(-1);
    expect(ask).toBeTruthy();
    expect(readFile).not.toHaveBeenCalled();
    t.say("flushed", { id: ask!.id, ok: true });
    await flush();
    await flush();
    expect(readFile).toHaveBeenCalledWith("designs/a.fig?as=slides", true);
    expect(screen.getByTestId("present-mode")).toBeTruthy();
    expect(screen.getByTestId("present-counter").textContent).toBe("2 / 3");
    expect(screen.queryByTestId("present-getting")).toBeNull();
  });

  it("+ Add slide in the editor: the service makes it, and the editor makes it too, as an agent's edit", async () => {
    const deckOp = vi.fn(async () => ({ ok: true, slides: 4, added: 3, script: "/* the new slide */", version: "v9" }));
    const { container } = render(canvas("designs/a.fig", { readFile: reader(3), deckOp }));
    await flush();
    const t = await opened(container);
    const frame = t.frame;
    t.say("slideOp", { doc: t.sent("load")[0]?.doc, op: "add", number: 2 });
    await flush();
    await flush();
    expect(deckOp).toHaveBeenCalledWith("designs/a.fig", { op: "add", number: 2 });   // after slide 2
    expect(t.sent("command").map((m) => m.script)).toEqual(["/* the new slide */"]);   // made in place…
    expect(container.querySelector("iframe")).toBe(frame);                             // …not reopened
  });

  it("+ Add slide with nothing to make in place: the editor opens the deck again, on the new slide", async () => {
    const deckOp = vi.fn(async () => ({ ok: true, slides: 4, added: 3 }));
    const { container } = render(canvas("designs/a.fig", { readFile: reader(3), deckOp }));
    await flush();
    const t = await opened(container);
    t.say("slideOp", { doc: t.sent("load")[0]?.doc, op: "add" });
    await flush();
    await flush();
    expect(deckOp).toHaveBeenCalledWith("designs/a.fig", { op: "add" });              // at the end
    const again = await opened(container);                                           // the editor, opened anew
    expect(again.frame).not.toBe(t.frame);
    expect(again.sent("slide")).toEqual([{ target: "cycls-editor", type: "slide", index: 2 }]);
  });
});

describe("an older editor keeps its Edit | Preview switch", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ arrayBuffer: async () => new Uint8Array([1]).buffer })));
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  const slides = (n: number) => JSON.stringify({ count: n, slides: Array.from({ length: n }, (_, i) => `data:image/jpeg;base64,S${i + 1}`), fig: "designs/a.fig" });
  const reader = (n: number) => vi.fn(async (p: string) => (p.includes("?as=slides") ? slides(n) : "# notes"));
  const pressed = (name: string) => screen.getByRole("button", { name }).getAttribute("aria-pressed");

  it("opens in the editor; Preview and Edit go back and forth to the same one", async () => {
    const { container } = render(canvas("designs/a.fig", { readFile: reader(1) }));
    await flush();
    const frame = container.querySelector("iframe")!;
    expect(screen.queryByRole("button", { name: "Preview" })).toBeNull();    // not until the editor says what it is
    await older(container);
    expect(pressed("Edit")).toBe("true");
    await toPreview();
    expect(pressed("Preview")).toBe("true");
    expect((screen.getByTestId("design-picture") as HTMLImageElement).src).toBe("data:image/jpeg;base64,S1");
    expect(container.querySelector("iframe")).toBe(frame);                  // the editor is still there…
    expect(frame.closest("[inert]")).toBeTruthy();                           // …under the preview, out of reach
    expect(screen.queryByRole("button", { name: "Full screen" })).toBeNull();
    await toEdit();
    expect(screen.queryByTestId("design-preview")).toBeNull();
    expect(container.querySelector("iframe")).toBe(frame);                  // the same one: nothing reloaded
    expect(frame.closest("[inert]")).toBeNull();
  });

  it("while the agent works on it, it stays where the person is; when its turn ends, the preview — unless the person took to the editor", async () => {
    const live = (on: boolean) => canvas("designs/a.fig", { readFile: reader(1), tabs: [{ path: "designs/a.fig", name: "a", live: on }, TABS[1]] });
    const { container, rerender } = render(live(true));                     // one the agent is making opens in the editor
    await flush();
    await older(container);
    expect(pressed("Edit")).toBe("true");
    rerender(live(false));                                                    // the turn is over
    await flush();
    await flush();
    expect(pressed("Preview")).toBe("true");
    expect(screen.getByTestId("design-picture")).toBeTruthy();

    // Its next turn, the person on the preview: it stays the preview, which shows each change as it is saved.
    rerender(live(true));
    await flush();
    expect(pressed("Preview")).toBe("true");
    rerender(live(false));
    await flush();
    expect(pressed("Preview")).toBe("true");

    await toEdit();                                                           // the person went to the editor themselves:
    rerender(live(true));
    await flush();
    expect(pressed("Edit")).toBe("true");                                     // a turn keeps them there…
    rerender(live(false));
    await flush();
    expect(pressed("Edit")).toBe("true");                                     // …and so does its end
    cleanup();

    // One the agent is making opens in the editor: a person who clicks into it keeps it when the turn ends.
    const again = render(live(true));
    await flush();
    await older(again.container);
    const frame = again.container.querySelector("iframe")!;
    frame.focus();
    window.dispatchEvent(new Event("blur"));
    await flush();
    again.rerender(live(false));
    await flush();
    expect(pressed("Edit")).toBe("true");
  });

  it("a design of several frames previews as its slides", async () => {
    const { container } = render(canvas("designs/a.fig", { readFile: reader(3) }));
    await flush();
    await older(container);
    await toPreview();
    expect(screen.getByTestId("deck-counter").textContent).toBe("1 / 3");
    expect(screen.getByRole("button", { name: /Present/ })).toBeTruthy();
  });

  it("saves what's unsaved before it shows the preview", async () => {
    const readFile = reader(1);
    const { container } = render(canvas("designs/a.fig", { readFile }));
    await flush();
    const frame = container.querySelector("iframe")!;
    const post = vi.spyOn(frame.contentWindow!, "postMessage");
    const say = (type: string, extra: Record<string, unknown> = {}) => window.dispatchEvent(
      new MessageEvent("message", { origin: EDITOR, source: frame.contentWindow, data: { source: "cycls-editor", type, ...extra } }));
    say("ready", { protocol: 2 });
    await flush();
    await flush();
    readFile.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await flush();
    const ask = post.mock.calls.map((c) => c[0] as Record<string, unknown>).find((m) => m.type === "flush");
    expect(ask).toBeTruthy();
    expect(readFile).not.toHaveBeenCalled();                                // not before the save
    say("flushed", { id: ask!.id, ok: true });
    await flush();
    expect(readFile).toHaveBeenCalledWith("designs/a.fig?as=slides", true);
  });

  it("when there's nothing to show it says so, and Edit still works", async () => {
    const readFile = vi.fn(async (p: string) => { if (p.includes("?as=slides")) throw new Error("415"); return "x"; });
    const { container } = render(canvas("designs/a.fig", { readFile }));
    await flush();
    await older(container);
    await toPreview();
    expect(screen.getByText(/Preview isn't available/)).toBeTruthy();
    await toEdit();
    expect(screen.queryByTestId("design-preview")).toBeNull();
  });
});

// A design's pages are its variants — a post, a story, a banner of one piece of work.
// A preview shows one page at a time, and a download is of the page in view.
describe("a design of several pages", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ arrayBuffer: async () => new Uint8Array([1]).buffer })));
    URL.revokeObjectURL = vi.fn();
    localStorage.clear();
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  const PAGES = [{ name: "Post", frames: 1 }, { name: "Story", frames: 1 }, { name: "Carousel", frames: 2 }, { name: "Blank", frames: 0 }];
  const manifest = (page: string) => {
    const n = PAGES.find((p) => p.name === page)!.frames;
    return JSON.stringify({ count: n, slides: Array.from({ length: n }, (_, i) => `data:image/jpeg;base64,${page}${i + 1}`),
                            fig: "designs/a.fig", pages: PAGES, page });
  };
  const reader = () => vi.fn(async (p: string) => {
    if (!p.includes("?as=slides")) return "# notes";
    return manifest(decodeURIComponent(/[?&]page=([^&]+)/.exec(p)?.[1] ?? "Post"));
  });
  // The canvas with its editor loaded, on `page`.
  async function open(readFile: ReturnType<typeof reader>, page: string, extra: Record<string, unknown> = {}) {
    const utils = render(canvas("designs/a.fig", { readFile, ...extra }));
    await flush();
    const frame = utils.container.querySelector("iframe")!;
    const post = vi.spyOn(frame.contentWindow!, "postMessage");
    const say = (type: string, more: Record<string, unknown> = {}) => window.dispatchEvent(
      new MessageEvent("message", { origin: EDITOR, source: frame.contentWindow, data: { source: "cycls-editor", type, ...more } }));
    say("ready", { protocol: 2, features: ["pages"] });
    await flush();
    await flush();
    const load = post.mock.calls.map((c) => c[0] as Record<string, unknown>).find((m) => m.type === "load")!;
    say("loaded", { doc: load.doc });
    say("pages", { doc: load.doc, page, pages: PAGES.map((p) => p.name) });
    await flush();
    // The editor answers a flush at once (nothing unsaved).
    post.mockImplementation(((m: Record<string, unknown>) => { if (m.type === "flush") say("flushed", { id: m.id, ok: true }); }) as never);
    readFile.mockClear();                                                     // what it opened on is not what's tested
    return { ...utils, post, say };
  }
  const sent = (post: { mock: { calls: unknown[][] } }, type: string) =>
    post.mock.calls.map((c) => c[0] as Record<string, unknown>).filter((m) => m.type === type);
  const tab = (name: string) => screen.getByRole("tab", { name });

  it("its pages are tabs above the editor: one click goes to that page", async () => {
    // The docked editor is too narrow for its own Pages panel: Cycls has the tabs.
    const readFile = reader();
    const { post, say } = await open(readFile, "Story");
    expect(screen.getAllByRole("tab").map((el) => el.textContent)).toEqual(["Post", "Story", "Carousel", "Blank"]);
    expect(tab("Story").getAttribute("aria-selected")).toBe("true");
    readFile.mockClear();
    fireEvent.click(tab("Post"));
    expect(sent(post, "page")).toEqual([{ target: "cycls-editor", type: "page", name: "Post" }]);
    expect(readFile).not.toHaveBeenCalled();                                // nothing is rendered for it: the editor shows it
    say("pages", { doc: sent(post, "load")[0]?.doc, page: "Post", pages: ["Post", "Story"] });   // the editor says so; a page went
    await flush();
    expect(tab("Post").getAttribute("aria-selected")).toBe("true");
    expect(screen.getAllByRole("tab")).toHaveLength(2);
    expect(screen.getAllByRole("tablist")).toHaveLength(1);
  });

  it("previews the page in view, and its tabs go to the others — in the editor too", async () => {
    const readFile = reader();
    const { post } = await open(readFile, "Story");
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await flush();
    await flush();
    expect(readFile).toHaveBeenCalledWith("designs/a.fig?as=slides&page=Story", true);   // not the first page's
    expect((screen.getByTestId("design-picture") as HTMLImageElement).src).toBe("data:image/jpeg;base64,Story1");
    expect(screen.getAllByRole("tab").map((el) => el.textContent)).toEqual(["Post", "Story", "Carousel", "Blank"]);
    expect(tab("Story").getAttribute("aria-selected")).toBe("true");
    expect(screen.getAllByRole("tablist")).toHaveLength(1);                 // one row of tabs, not the preview's own too

    fireEvent.click(tab("Carousel"));                                       // a page of several frames: its slides
    await flush();
    expect(readFile).toHaveBeenCalledWith("designs/a.fig?as=slides&page=Carousel", true);
    expect(screen.getByTestId("deck-counter").textContent).toBe("1 / 2");
    expect(tab("Carousel").getAttribute("aria-selected")).toBe("true");
    expect(sent(post, "page")).toEqual([{ target: "cycls-editor", type: "page", name: "Carousel" }]);   // Edit comes back on it

    fireEvent.click(tab("Blank"));                                          // an empty page says so, and can be left
    await flush();
    expect(screen.getByTestId("page-empty").textContent).toBe("This page is empty.");
    fireEvent.click(tab("Post"));
    await flush();
    expect((screen.getByTestId("design-picture") as HTMLImageElement).src).toBe("data:image/jpeg;base64,Post1");
  });

  it("downloads the page in view — the editor's, or the preview's", async () => {
    const openFile = vi.fn(async () => "blob:x");
    await open(reader(), "Story", { openFile });
    const download = async (label: string) => {
      fireEvent.click(screen.getByRole("button", { name: "More" }));
      await act(async () => { fireEvent.click(screen.getByText(label)); await new Promise((r) => setTimeout(r, 0)); });
    };
    openFile.mockClear();
    await download("Download PNG");
    expect(openFile).toHaveBeenCalledWith("designs/a.fig?as=png&page=Story&download=1");
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await flush();
    await flush();
    fireEvent.click(tab("Post"));
    await flush();
    await download("Download PDF");
    expect(openFile).toHaveBeenLastCalledWith("designs/a.fig?as=pdf&page=Post&download=1");
  });

  it("a page renamed since falls back to the first one", async () => {
    const readFile = vi.fn(async (p: string) => {
      if (p.includes("page=Story")) throw new Error("404");
      return p.includes("?as=slides") ? manifest("Post") : "# notes";
    });
    await open(readFile as never, "Story");
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await flush();
    await flush();
    expect(readFile).toHaveBeenLastCalledWith("designs/a.fig?as=slides", true);
    expect((screen.getByTestId("design-picture") as HTMLImageElement).src).toBe("data:image/jpeg;base64,Post1");
    // Asked once for the page, once for the first one — not again and again.
    expect(readFile.mock.calls.filter((c) => String(c[0]).includes("?as=slides"))).toHaveLength(2);
  });

  it("when even the first page can't be shown it says so, once", async () => {
    const readFile = vi.fn(async (p: string) => { if (p.includes("?as=slides")) throw new Error("502"); return "# notes"; });
    await open(readFile as never, "Story");
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await flush();
    await flush();
    expect(screen.getByText(/Preview isn't available/)).toBeTruthy();
    expect(readFile.mock.calls.filter((c) => String(c[0]).includes("?as=slides"))).toHaveLength(2);
  });

  it("a design of one page has no tabs and names no page", async () => {
    const one = JSON.stringify({ count: 1, slides: ["data:image/jpeg;base64,S1"], fig: "designs/a.fig", pages: [{ name: "design", frames: 1 }], page: "design" });
    const readFile = vi.fn(async (p: string) => (p.includes("?as=slides") ? one : "# notes"));
    const { container } = render(canvas("designs/a.fig", { readFile }));
    await flush();
    await older(container);
    await toPreview();
    expect(readFile).toHaveBeenCalledWith("designs/a.fig?as=slides", true);
    expect(screen.queryByRole("tablist")).toBeNull();
  });
});

describe("designs in the canvas", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ arrayBuffer: async () => new Uint8Array([1]).buffer })));
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("keeps a switched-away editor while its tab is open, and a closed one until it has saved", async () => {
    const { container, rerender } = render(canvas("designs/a.fig"));
    await flush();
    const frame = container.querySelector("iframe")!;
    expect(frame).toBeTruthy();
    const post = vi.spyOn(frame.contentWindow!, "postMessage");
    const say = (type: string, extra: Record<string, unknown> = {}) => window.dispatchEvent(
      new MessageEvent("message", { origin: EDITOR, source: frame.contentWindow, data: { source: "cycls-editor", type, ...extra } }));
    say("ready", { protocol: 2 });
    await flush();

    rerender(canvas("notes.md"));
    await flush();
    expect(container.querySelector("iframe")).toBe(frame);                 // still mounted…
    expect(frame.closest("[inert]")).toBeTruthy();                          // …hidden, out of reach
    rerender(canvas("designs/a.fig"));
    await flush();
    expect(container.querySelector("iframe")).toBe(frame);                 // back to it: the same editor, not reloaded
    expect(frame.closest("[inert]")).toBeNull();

    rerender(canvas("notes.md", { tabs: [TABS[1]] }));                     // its tab closed
    await flush();
    expect(container.querySelector("iframe")).toBe(frame);                 // kept until it has saved
    const ask = post.mock.calls.map((c) => c[0] as Record<string, unknown>).find((m) => m.type === "flush");
    expect(ask).toBeTruthy();
    say("flushed", { id: ask!.id, ok: true });
    await flush();
    expect(container.querySelector("iframe")).toBeNull();                   // saved: gone
  });

  it("closing the last tab saves its editor before the canvas goes", async () => {
    const onCloseTab = vi.fn();
    const { container } = render(canvas("designs/a.fig", { tabs: [TABS[0]], onCloseTab }));
    await flush();
    const frame = container.querySelector("iframe")!;
    const post = vi.spyOn(frame.contentWindow!, "postMessage");
    const say = (type: string, extra: Record<string, unknown> = {}) => window.dispatchEvent(
      new MessageEvent("message", { origin: EDITOR, source: frame.contentWindow, data: { source: "cycls-editor", type, ...extra } }));
    say("ready", { protocol: 2 });
    await flush();

    fireEvent.click(screen.getByLabelText("Close a.fig"));
    await flush();
    const ask = post.mock.calls.map((c) => c[0] as Record<string, unknown>).find((m) => m.type === "flush");
    expect(ask).toBeTruthy();
    expect(onCloseTab).not.toHaveBeenCalled();                              // not before it has saved
    say("flushed", { id: ask!.id, ok: true });
    await flush();
    expect(onCloseTab).toHaveBeenCalledWith("designs/a.fig");
  });

  it("a design's header opens its editor full screen", async () => {
    const asked: Element[] = [];
    Object.defineProperty(document, "fullscreenEnabled", { configurable: true, value: true });
    Object.defineProperty(Element.prototype, "requestFullscreen", {
      configurable: true, value: async function (this: Element) { asked.push(this); },
    });
    try {
      const { container } = render(canvas("designs/a.fig"));
      await flush();
      await toEdit();
      fireEvent.click(screen.getByLabelText("Full screen"));
      expect(asked).toEqual([container.querySelector("iframe")!.parentElement]);
    } finally {
      delete (document as unknown as Record<string, unknown>).fullscreenEnabled;
      delete (Element.prototype as unknown as Record<string, unknown>).requestFullscreen;
    }
  });

  it("an editor full screen leaves it when another tab is shown, rather than a blank screen", async () => {
    // The agent opens a file while the person works full screen: the editor's tab goes invisible under it.
    let full: Element | null = null;
    const exit = vi.fn(async () => { full = null; });
    Object.defineProperty(document, "fullscreenElement", { configurable: true, get: () => full });
    Object.defineProperty(document, "exitFullscreen", { configurable: true, value: exit });
    try {
      const { container, rerender } = render(canvas("designs/a.fig"));
      await flush();
      await toEdit();
      full = container.querySelector("iframe")!.parentElement;
      rerender(canvas("designs/a.fig"));                                    // the same tab: stays
      expect(exit).not.toHaveBeenCalled();
      rerender(canvas("notes.md"));
      await flush();
      expect(exit).toHaveBeenCalledOnce();
    } finally {
      delete (document as unknown as Record<string, unknown>).fullscreenElement;
      delete (document as unknown as Record<string, unknown>).exitFullscreen;
    }
  });

  it("offers New design in the + menu, with the server's sizes", async () => {
    const onNewDesign = vi.fn();
    render(canvas("notes.md", { onAddFile: () => {}, searchFiles: async () => [], onNewDesign }));
    fireEvent.click(screen.getByLabelText("Open a file"));
    await flush();
    fireEvent.click(screen.getByTestId("new-design-story"));
    expect(onNewDesign).toHaveBeenCalledWith("story");
  });

  it("the sizes are the server's presets", () => {
    const py = readFileSync(join(__dirname, "../../cycls/_agent/design/prepare.py"), "utf8");
    const block = py.slice(py.indexOf("_DESIGN_SIZES = {"), py.indexOf("}", py.indexOf("_DESIGN_SIZES = {")));
    const server = Object.fromEntries([...block.matchAll(/"([a-z0-9-]+)": \[(\d+), (\d+)\]/g)].map((m) => [m[1], [+m[2], +m[3]]]));
    for (const p of DESIGN_PRESETS) expect(server[p.key], p.key).toEqual([...p.size]);
  });
});

describe("paths in URLs", () => {
  it("encodes each segment and keeps the caller's query", () => {
    expect(encPath("my docs/a#b?.txt")).toBe("my%20docs/a%23b%3F.txt");
    expect(encPath("designs/pitch.deck.json?as=slides")).toBe("designs/pitch.deck.json?as=slides");
    expect(encPath("حملة/صورة.png")).toBe(`${encodeURIComponent("حملة")}/${encodeURIComponent("صورة.png")}`);
    expect(encPath("a/b.pdf?download")).toBe("a/b.pdf?download");
  });
});

describe("tabs in the canvas", () => {
  it("going back to a tab finds it as it was; a hidden one catches up when it is shown", async () => {
    const readFile = vi.fn(async (p: string) => `# ${p}`);
    const openFile = async () => "blob:x";   // stable, as the app's are
    const tabs = [{ path: "a.md", name: "a.md" }, { path: "b.md", name: "b.md" }];
    const view = (active: string, reloadKey = 0) => canvas(active, { tabs, readFile, openFile, reloadKey });
    const reads = () => readFile.mock.calls.map((c) => c[0]);
    const { rerender } = render(view("a.md"));
    await flush();
    rerender(view("b.md"));
    await flush();
    rerender(view("a.md"));
    await flush();
    expect(reads()).toEqual(["a.md", "b.md"]);                    // each fetched once
    rerender(view("a.md", 1));                                     // a turn ended
    await flush();
    expect(reads()).toEqual(["a.md", "b.md", "a.md"]);             // only the one in view refetches
    rerender(view("b.md", 1));
    await flush();
    expect(reads()).toEqual(["a.md", "b.md", "a.md", "b.md"]);     // the other, once shown
  });
});
