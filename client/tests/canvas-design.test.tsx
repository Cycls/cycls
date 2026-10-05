import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, cleanup, act, fireEvent, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { Canvas, addMenuLeft, type CanvasFile } from "../src/components/canvas";
import { DESIGN_PRESETS } from "../src/components/canvas-utils";
import { encPath } from "../src/hooks/use-files";

// Designs in the canvas: a design editor whose tab is switched away from stays
// mounted, hidden, until it has saved what's unsaved; "New design" is in the +
// menu, with the server's sizes.

const EDITOR = "https://ed.example";
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const TABS: CanvasFile[] = [{ path: "designs/a.fig", name: "a.fig" }, { path: "notes.md", name: "notes.md" }];

function canvas(active: string, extra: Record<string, unknown> = {}) {
  return (
    <Canvas tabs={TABS} active={active} docked hidden={false} expanded={false}
            onToggleExpand={() => {}} onSelectTab={() => {}} onCloseTab={() => {}} onHide={() => {}}
            readFile={async () => "# notes"} openFile={async () => "blob:fig"} writeFile={async () => {}}
            designEditorUrl={EDITOR} {...extra} />
  );
}

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
    expect(openFile).toHaveBeenCalledWith("designs/a.fig?as=pdf");
  });

  it("another file keeps its one Download", async () => {
    render(canvas("notes.md"));
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    expect(screen.getByText("Download")).toBeTruthy();
    expect(screen.queryByText("Download PDF")).toBeNull();
  });
});

describe("a design's Edit | Preview switch", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ arrayBuffer: async () => new Uint8Array([1]).buffer })));
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  const slides = (n: number) => JSON.stringify({ count: n, slides: Array.from({ length: n }, (_, i) => `data:image/jpeg;base64,S${i + 1}`), fig: "designs/a.fig" });
  const reader = (n: number) => vi.fn(async (p: string) => (p.includes("?as=slides") ? slides(n) : "# notes"));
  const pressed = (name: string) => screen.getByRole("button", { name }).getAttribute("aria-pressed");

  it("shows the design without the editor around it, and comes back to the same editor", async () => {
    const readFile = reader(1);
    const { container } = render(canvas("designs/a.fig", { readFile }));
    await flush();
    const frame = container.querySelector("iframe")!;
    expect(pressed("Edit")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await flush();
    expect(readFile).toHaveBeenCalledWith("designs/a.fig?as=slides", true);
    expect((screen.getByTestId("design-picture") as HTMLImageElement).src).toBe("data:image/jpeg;base64,S1");
    expect(pressed("Preview")).toBe("true");
    expect(container.querySelector("iframe")).toBe(frame);                  // the editor is still there…
    expect(frame.closest("[inert]")).toBeTruthy();                           // …under the preview, out of reach
    expect(screen.queryByRole("button", { name: "Full screen" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    await flush();
    expect(screen.queryByTestId("design-preview")).toBeNull();
    expect(container.querySelector("iframe")).toBe(frame);                  // the same one: nothing reloaded
    expect(frame.closest("[inert]")).toBeNull();
  });

  it("a design of several frames previews as its slides", async () => {
    render(canvas("designs/a.fig", { readFile: reader(3) }));
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await flush();
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
    render(canvas("designs/a.fig", { readFile }));
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await flush();
    expect(screen.getByText(/Preview isn't available/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
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
    expect(openFile).toHaveBeenCalledWith("designs/a.fig?as=png&page=Story");
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await flush();
    await flush();
    fireEvent.click(tab("Post"));
    await flush();
    await download("Download PDF");
    expect(openFile).toHaveBeenLastCalledWith("designs/a.fig?as=pdf&page=Post");
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
    render(canvas("designs/a.fig", { readFile }));
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await flush();
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

  it("keeps a switched-away editor until it has saved", async () => {
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
      fireEvent.click(screen.getByLabelText("Full screen"));
      expect(asked).toEqual([container.querySelector("iframe")!.parentElement]);
    } finally {
      delete (document as unknown as Record<string, unknown>).fullscreenEnabled;
      delete (Element.prototype as unknown as Record<string, unknown>).requestFullscreen;
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
    const py = readFileSync(join(__dirname, "../../cycls/_agent/tools/__init__.py"), "utf8");
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
