import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, cleanup, act, fireEvent, screen } from "@testing-library/react";
import {
  DesignEditorView, designSelection, detachDesignEditorsUnder, flushDesignEditor, fullscreenDesignEditor, type DesignHost,
} from "../src/components/design-editor-view";
import { ToastProvider } from "../src/lib/toast";

// The editor iframe talks to its host over postMessage (protocol 2). It edits ONE
// workspace file: every save goes to that file, confirmed with `written`; a save
// from a replaced document is refused; new designs, copies and exports come to the
// host, which writes them into the workspace. An agent edit reaches the editor only
// AFTER the server applied and saved it, so when the live replay fails
// (`commandError`) the host re-opens the editor on the saved file.

const EDITOR = "https://ed.example";
const bytes = { "blob:orig": [1, 2, 3], "blob:fresh": [9, 9] } as Record<string, number[]>;
const b64 = (a: number[]) => btoa(String.fromCharCode(...a));
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

function fromEditor(frame: HTMLIFrameElement, type: string, extra: Record<string, unknown> = {}, source: Window | null = frame.contentWindow) {
  window.dispatchEvent(new MessageEvent("message", { origin: EDITOR, source, data: { source: "cycls-editor", type, ...extra } }));
}

function host(): DesignHost & { [k: string]: ReturnType<typeof vi.fn> } {
  return {
    newDesign: vi.fn(async () => {}),
    writeNew: vi.fn(async (p: string) => p.replace(/(\.\w+)$/, "-2$1")),
    brand: vi.fn(async () => ({ colors: { primary: "#b45309" } })),
    openInCanvas: vi.fn(),
    refreshFiles: vi.fn(),
  } as never;
}

// A host whose server serves designs with their version (X-Version).
function versioned(version: () => string) {
  const h = host();
  h.fetchVersioned = vi.fn(async () => ({ url: "blob:orig", version: version() }));
  return h;
}

// A save the server refused: the file is at `version` now.
const stale412 = (version: string) =>
  Object.assign(new Error("HTTP 412"), { status: 412, response: new Response(JSON.stringify({ detail: "changed", version })) });

const command = (detail: Record<string, unknown>) =>
  act(async () => { window.dispatchEvent(new CustomEvent("cycls:design-command", { detail: { path: "designs/launch.fig", ...detail } })); });

function mount(opts: { writeFile?: (p: string, d: BlobPart, o?: unknown) => Promise<unknown>; reload?: () => Promise<string>; host?: DesignHost } = {}) {
  const writeFile = vi.fn(opts.writeFile ?? (async () => {}));
  const utils = render(
    <DesignEditorView url="blob:orig" path="designs/launch.fig" name="launch.fig" editorUrl={EDITOR}
                      writeFile={writeFile} reload={opts.reload} host={opts.host} />);
  const frame = () => utils.container.querySelector("iframe")!;
  return { ...utils, frame, writeFile };
}

// The browser's full screen (jsdom has none): one element at a time, with its
// change event, and the keyboard lock Chrome and Edge have.
function fakeFullscreen() {
  let el: Element | null = null;
  const change = () => document.dispatchEvent(new Event("fullscreenchange"));
  const exit = vi.fn(async () => { el = null; change(); });
  const keyboard = { lock: vi.fn(async () => {}), unlock: vi.fn() };
  Object.defineProperty(document, "fullscreenElement", { configurable: true, get: () => el });
  Object.defineProperty(document, "fullscreenEnabled", { configurable: true, value: true });
  Object.defineProperty(document, "exitFullscreen", { configurable: true, value: exit });
  Object.defineProperty(Element.prototype, "requestFullscreen", {
    configurable: true, value: async function (this: Element) { el = this; change(); },
  });
  Object.defineProperty(navigator, "keyboard", { configurable: true, value: keyboard });
  const restore = () => {
    for (const k of ["fullscreenElement", "fullscreenEnabled", "exitFullscreen"]) delete (document as unknown as Record<string, unknown>)[k];
    delete (Element.prototype as unknown as Record<string, unknown>).requestFullscreen;
    delete (navigator as unknown as Record<string, unknown>).keyboard;
  };
  return { exit, keyboard, restore };
}

// The editor side of a load: `ready` → the host's `load` (returned).
async function ready(frame: HTMLIFrameElement, protocol?: number) {
  const post = vi.spyOn(frame.contentWindow!, "postMessage");
  fromEditor(frame, "ready", protocol ? { protocol } : {});
  await flush();
  await flush();
  const load = post.mock.calls.map((c) => c[0] as Record<string, unknown>).find((m) => m.type === "load")!;
  fromEditor(frame, "loaded", { doc: load?.doc });
  await flush();
  return { post, load };
}

describe("DesignEditorView", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async (u: string) => ({ arrayBuffer: async () => new Uint8Array(bytes[u]).buffer })));
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); document.body.classList.remove("dark"); });

  it("a failed live replay re-opens the editor on the saved file, not the stale one", async () => {
    const reload = vi.fn(async () => "blob:fresh");
    const { frame } = mount({ reload });
    const first = frame();
    const { post } = await ready(first);
    expect(post).toHaveBeenCalledWith(expect.objectContaining({ type: "load", fig: b64(bytes["blob:orig"]) }), EDITOR);

    fromEditor(first, "commandError", { message: "null is not an object" });
    await flush();
    expect(reload).toHaveBeenCalledOnce();
    const second = frame();
    expect(second).not.toBe(first);                              // remounted
    const { post: post2 } = await ready(second);
    expect(post2).toHaveBeenCalledWith(expect.objectContaining({ type: "load", fig: b64(bytes["blob:fresh"]) }), EDITOR);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:fresh");
  });

  it("a save error does not re-open anything", async () => {
    const reload = vi.fn(async () => "blob:fresh");
    const { frame } = mount({ reload });
    const first = frame();
    await ready(first);
    fromEditor(first, "error", { message: "exportFigFile timeout (20s)" });
    await flush();
    expect(reload).not.toHaveBeenCalled();
    expect(frame()).toBe(first);
  });

  it("takes messages from its own editor only", async () => {
    const { frame, writeFile } = mount();
    await ready(frame());
    fromEditor(frame(), "saved", { fig: b64([7]) }, window);     // another window
    await flush();
    expect(writeFile).not.toHaveBeenCalled();
  });

  it("protocol 2: tags each load, writes its saves to the file, and confirms them", async () => {
    const h = host();
    const { frame, writeFile } = mount({ host: h });
    const { post, load } = await ready(frame(), 2);
    expect(load).toMatchObject({ protocol: 2, name: "launch.fig", brand: { colors: { primary: "#b45309" } } });
    expect(typeof load.doc).toBe("string");

    fromEditor(frame(), "saved", { doc: load.doc, id: "s1", fig: b64([5, 6]) });
    await flush();
    expect(writeFile).toHaveBeenCalledWith("designs/launch.fig", expect.anything(), expect.objectContaining({ silent: true }));
    expect(post).toHaveBeenCalledWith({ target: "cycls-editor", type: "written", doc: load.doc, id: "s1", ok: true }, EDITOR);

    // A save from a document since replaced isn't written over the file.
    writeFile.mockClear();
    fromEditor(frame(), "saved", { doc: "an-older-load", id: "s2", fig: b64([1]) });
    await flush();
    expect(writeFile).not.toHaveBeenCalled();
    expect(post).toHaveBeenCalledWith(expect.objectContaining({ type: "written", id: "s2", ok: false }), EDITOR);

    // A write that fails says so.
    writeFile.mockImplementationOnce(async () => { throw new Error("503"); });
    fromEditor(frame(), "saved", { doc: load.doc, id: "s3", fig: b64([1]) });
    await flush();
    expect(post).toHaveBeenCalledWith(expect.objectContaining({ type: "written", id: "s3", ok: false }), EDITOR);
  });

  it("new designs, exports and copies go to Cycls", async () => {
    const h = host();
    const { frame } = mount({ host: h });
    const { load } = await ready(frame(), 2);

    fromEditor(frame(), "newDesign", { size: [1080, 640] });
    await flush();
    expect(h.newDesign).toHaveBeenCalledWith([1080, 640]);

    fromEditor(frame(), "export", { doc: load.doc, files: [
      { name: "slide-1@2x.png", mime: "image/png", data: b64([137, 80]) },
      { name: "evil.html", mime: "text/html", data: b64([60]) },             // not a type an export writes
    ] });
    await flush();
    expect(h.writeNew).toHaveBeenCalledTimes(1);
    expect(h.writeNew).toHaveBeenCalledWith("designs/launch-slide-1@2x.png", expect.anything());
    expect(h.refreshFiles).toHaveBeenCalled();

    fromEditor(frame(), "saveCopy", { doc: load.doc, name: "launch.fig", fig: b64([4]) });
    await flush();
    const input = screen.getByLabelText("Name of the copy") as HTMLInputElement;
    expect(input.value).toBe("launch copy");
    fireEvent.change(input, { target: { value: "launch v2" } });
    fireEvent.submit(input.closest("form")!);
    await flush();
    expect(h.writeNew).toHaveBeenLastCalledWith("designs/launch v2.fig", expect.anything());
    expect(h.openInCanvas).toHaveBeenCalledWith("designs/launch v2-2.fig");
  });

  it("follows Cycls's light/dark live, without reloading the editor", async () => {
    const { frame } = mount({ host: host() });
    const first = frame();
    const src = first.getAttribute("src");
    const { post } = await ready(first, 2);
    await act(async () => { document.body.classList.add("dark"); await new Promise((r) => setTimeout(r, 0)); });
    expect(post).toHaveBeenCalledWith({ target: "cycls-editor", type: "theme", theme: "dark" }, EDITOR);
    expect(frame()).toBe(first);
    expect(frame().getAttribute("src")).toBe(src);
  });

  it("saves name the version they started from; a change made elsewhere asks, and Keep mine writes over it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const writeFile = vi.fn()
        .mockRejectedValueOnce(stale412("v9"))
        .mockResolvedValue({ version: "v10" });
      const { frame } = mount({ host: versioned(() => "v1"), writeFile });
      const { post, load } = await ready(frame(), 2);
      fromEditor(frame(), "saved", { doc: load.doc, id: "s1", name: "launch.fig", fig: b64([7]) });
      await flush();
      expect(writeFile).toHaveBeenLastCalledWith("designs/launch.fig", expect.anything(), { silent: true, base: "v1" });
      expect(post).toHaveBeenCalledWith(expect.objectContaining({ type: "written", id: "s1", ok: false }), EDITOR);
      expect(screen.queryByText("This design changed elsewhere")).toBeNull();   // an agent edit may yet explain it
      await act(async () => { vi.advanceTimersByTime(3100); });
      expect(screen.getByText("This design changed elsewhere")).toBeTruthy();

      fromEditor(frame(), "saved", { doc: load.doc, id: "s2", name: "launch.fig", fig: b64([8]) });   // held while deciding
      await flush();
      expect(writeFile).toHaveBeenCalledTimes(1);
      fireEvent.click(screen.getByText("Keep mine"));
      await flush();
      expect(post).toHaveBeenCalledWith({ target: "cycls-editor", type: "save" }, EDITOR);
      fromEditor(frame(), "saved", { doc: load.doc, id: "s3", name: "launch.fig", fig: b64([8]) });
      await flush();
      expect(writeFile).toHaveBeenLastCalledWith("designs/launch.fig", expect.anything(), { silent: true, base: "v9", force: true });
      expect(screen.queryByText("This design changed elsewhere")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("an agent edit landing makes a stale save expected: quiet, and saved again on the edit's version", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const writeFile = vi.fn()
        .mockRejectedValueOnce(stale412("v2"))
        .mockResolvedValue({ version: "v3" });
      const { frame } = mount({ host: versioned(() => "v1"), writeFile });
      const { post, load } = await ready(frame(), 2);
      await command({ script: "S", intent: "tidy", version: "v2" });
      expect(post).toHaveBeenCalledWith({ target: "cycls-editor", type: "command", script: "S", intent: "tidy" }, EDITOR);
      fromEditor(frame(), "saved", { doc: load.doc, id: "s1", name: "launch.fig", fig: b64([7]) });   // made before the edit
      await flush();
      await act(async () => { vi.advanceTimersByTime(3500); });
      expect(screen.queryByText("This design changed elsewhere")).toBeNull();
      fromEditor(frame(), "applied", { doc: load.doc });
      await flush();
      expect(post).toHaveBeenCalledWith(expect.objectContaining({ type: "flush" }), EDITOR);   // what was refused goes now
      fromEditor(frame(), "saved", { doc: load.doc, id: "s2", name: "launch.fig", fig: b64([9]) });
      await flush();
      expect(writeFile).toHaveBeenLastCalledWith("designs/launch.fig", expect.anything(), { silent: true, base: "v2" });
    } finally {
      vi.useRealTimers();
    }
  });

  it("agent edits replay one at a time, and one the editor loaded already is skipped", async () => {
    const { frame } = mount({ host: versioned(() => "v5") });
    const { post, load } = await ready(frame(), 2);
    const commands = () => post.mock.calls.map((c) => c[0] as Record<string, unknown>).filter((m) => m.type === "command").map((m) => m.script);
    await command({ script: "A", version: "v5" });   // saved before this load read the file: it's in already
    await command({ script: "B", version: "v6" });
    await command({ script: "C", version: "v7" });
    expect(commands()).toEqual(["B"]);
    fromEditor(frame(), "applied", { doc: load.doc });
    await flush();
    expect(commands()).toEqual(["B", "C"]);
  });

  it("an agent edit that arrives while the editor is still loading waits for it", async () => {
    // It used to go at once, the editor answered `commandError: no document is open`,
    // and the host threw the load away for a second one.
    const { frame } = mount({ host: versioned(() => "v5") });
    const post = vi.spyOn(frame().contentWindow!, "postMessage");
    const sent = (type: string) => post.mock.calls.map((c) => c[0] as Record<string, unknown>).filter((m) => m.type === type);
    fromEditor(frame(), "ready", { protocol: 2 });
    await flush();
    await flush();
    expect(sent("load").length).toBe(1);
    await command({ script: "A", version: "v5" });   // in the file this load read (its version)
    await command({ script: "B", version: "v6" });   // saved after it
    expect(sent("command")).toEqual([]);              // the document isn't open yet
    fromEditor(frame(), "loaded", { doc: sent("load")[0].doc });
    await flush();
    expect(sent("command").map((m) => m.script)).toEqual(["B"]);
    expect(frame().contentWindow).toBe(post.mock.instances[0]);   // the same editor: no reload
  });

  it("edits the loaded file already holds are not replayed, however many", async () => {
    const { frame } = mount({ host: versioned(() => "v7") });
    const post = vi.spyOn(frame().contentWindow!, "postMessage");
    const scripts = () => post.mock.calls.map((c) => c[0] as Record<string, unknown>).filter((m) => m.type === "command").map((m) => m.script);
    await command({ script: "A", version: "v6" });   // both saved before the editor asked for the file
    await command({ script: "B", version: "v7" });
    fromEditor(frame(), "ready", { protocol: 2 });
    await flush();
    await flush();
    const load = post.mock.calls.map((c) => c[0] as Record<string, unknown>).find((m) => m.type === "load")!;
    fromEditor(frame(), "loaded", { doc: load.doc });
    await flush();
    expect(scripts()).toEqual([]);                    // v7 holds A and B
    await command({ script: "C", version: "v8" });
    expect(scripts()).toEqual(["C"]);
  });

  it("reports what's selected, by name, for Add selection", async () => {
    const { frame } = mount({ host: versioned(() => "v1") });
    const { load } = await ready(frame(), 2);
    const heard: unknown[] = [];
    const listen = (e: Event) => heard.push((e as CustomEvent).detail);
    window.addEventListener("cycls:design-selection", listen);
    fromEditor(frame(), "selection", { doc: load.doc, frame: "slide-1", nodes: [{ name: "headline", type: "TEXT", text: "Night Roast" }] });
    await flush();
    const sel = { path: "designs/launch.fig", frame: "slide-1", nodes: [{ name: "headline", type: "TEXT", text: "Night Roast" }] };
    expect(designSelection("designs/launch.fig")).toEqual(sel);
    expect(heard).toEqual([sel]);
    fromEditor(frame(), "selection", { doc: load.doc, frame: null, nodes: [] });
    await flush();
    expect(designSelection("designs/launch.fig")).toBeNull();
    window.removeEventListener("cycls:design-selection", listen);
  });

  it("the editor gets Cycls's language: in its URL, and on every load", async () => {
    const { frame } = mount({ host: versioned(() => "v1") });
    expect(frame().getAttribute("src")).toContain("&lang=en");
    const { post } = await ready(frame(), 2);
    expect(post).toHaveBeenCalledWith({ target: "cycls-editor", type: "locale", lang: "en" }, EDITOR);
  });

  it("goes full screen in its own box, and leaves first for what opens elsewhere", async () => {
    const fs = fakeFullscreen();
    try {
      const h = host();
      const { frame } = mount({ host: h });
      const first = frame();
      await ready(first, 2);
      await act(async () => { fullscreenDesignEditor("designs/launch.fig"); await new Promise((r) => setTimeout(r, 0)); });
      expect(document.fullscreenElement).toBe(first.parentElement);        // the editor's box, not the page
      expect(frame()).toBe(first);                                          // nothing reloads
      expect(screen.getByText("Exit full screen")).toBeTruthy();

      fromEditor(first, "newDesign", { size: [1080, 1080] });              // opens in another canvas tab
      await flush();
      expect(fs.exit).toHaveBeenCalledOnce();
      expect(fs.exit.mock.invocationCallOrder[0]).toBeLessThan(h.newDesign.mock.invocationCallOrder[0]);
      expect(screen.queryByTestId("exit-fullscreen")).toBeNull();
    } finally {
      fs.restore();
    }
  });

  it("full screen can be left: Esc stays the browser's, and the Exit button never goes away", async () => {
    // Esc was locked to the editor (hold it to leave) and the button hid after 2.5 s,
    // reachable only from a thin strip at the top: no visible way out.
    const fs = fakeFullscreen();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { frame } = mount({ host: host() });
      await ready(frame(), 2);
      await act(async () => { fullscreenDesignEditor("designs/launch.fig"); await new Promise((r) => setTimeout(r, 0)); });
      expect(fs.keyboard.lock).not.toHaveBeenCalled();                      // one press of Esc leaves, as on any page
      await act(async () => { vi.advanceTimersByTime(4000); });             // long after the first hint
      const exit = screen.getByRole("button", { name: "Exit full screen" });
      expect(exit.className).not.toContain("pointer-events-none");
      expect(exit.className).not.toContain("opacity-0");
      await act(async () => { fireEvent.click(exit); });
      expect(fs.exit).toHaveBeenCalledOnce();
      expect(document.fullscreenElement).toBeNull();
    } finally {
      vi.useRealTimers();
      fs.restore();
    }
  });

  it("Export › PDF in the editor is rendered by Cycls and lands beside the design", async () => {
    // The editor's own PDF embeds no fonts (Arabic and web fonts come out wrong), so
    // the editor asks (`exportAs`) and Cycls exports the saved file through the service.
    const h = host();
    h.exportDesign = vi.fn(async () => "designs/launch.pdf");
    const { container } = render(
      <ToastProvider>
        <DesignEditorView url="blob:orig" path="designs/launch.fig" name="launch.fig" editorUrl={EDITOR}
                          writeFile={async () => {}} host={h} />
      </ToastProvider>);
    const frame = container.querySelector("iframe")!;
    const { post, load } = await ready(frame, 2);
    fromEditor(frame, "exportAs", { doc: load.doc, format: "pdf" });
    await flush();
    const asked = post.mock.calls.map((c) => c[0] as Record<string, unknown>).find((m) => m.type === "flush")!;
    expect(asked).toBeTruthy();                                              // what's unsaved goes first
    expect(h.exportDesign).not.toHaveBeenCalled();
    fromEditor(frame, "flushed", { id: asked.id, ok: true });
    await flush();
    expect(h.exportDesign).toHaveBeenCalledWith("designs/launch.fig", "pdf");
    expect(screen.getByText("Exported to launch.pdf")).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByText("Open")); });
    expect(h.openInCanvas).toHaveBeenCalledWith("designs/launch.pdf");
    fromEditor(frame, "exportAs", { doc: load.doc, format: "exe" });         // only what Cycls exports
    await flush();
    expect(h.exportDesign).toHaveBeenCalledOnce();
  });

  it("full screen shows Cycls's toasts inside it", async () => {
    const fs = fakeFullscreen();
    try {
      const h = host();
      const { container } = render(
        <ToastProvider>
          <DesignEditorView url="blob:orig" path="designs/launch.fig" name="launch.fig" editorUrl={EDITOR}
                            writeFile={async () => {}} host={h} />
        </ToastProvider>);
      const frame = container.querySelector("iframe")!;
      const { load } = await ready(frame, 2);
      await act(async () => { fullscreenDesignEditor("designs/launch.fig"); await new Promise((r) => setTimeout(r, 0)); });
      fromEditor(frame, "export", { doc: load.doc, files: [{ name: "hero.png", mime: "image/png", data: b64([137, 80]) }] });
      await flush();
      expect(frame.parentElement!.contains(screen.getByText("Exported to launch-hero-2.png"))).toBe(true);
    } finally {
      fs.restore();
    }
  });

  it("flushes on request, and a file being deleted gets no more writes", async () => {
    const { frame, writeFile } = mount({ host: host() });
    const { post, load } = await ready(frame(), 2);

    const done = flushDesignEditor("designs/launch.fig", 2000);
    await flush();
    const ask = post.mock.calls.map((c) => c[0] as Record<string, unknown>).find((m) => m.type === "flush")!;
    fromEditor(frame(), "flushed", { id: ask.id, ok: true });
    expect(await done).toBe(true);
    expect(await flushDesignEditor("designs/other.fig")).toBe(true);    // nothing open there

    const reattach = detachDesignEditorsUnder("designs");
    fromEditor(frame(), "saved", { doc: load.doc, id: "s9", fig: b64([1]) });
    await flush();
    expect(writeFile).not.toHaveBeenCalled();
    expect(post).toHaveBeenCalledWith(expect.objectContaining({ type: "written", id: "s9", ok: false }), EDITOR);
    reattach();
    fromEditor(frame(), "saved", { doc: load.doc, id: "s10", fig: b64([1]) });
    await flush();
    expect(writeFile).toHaveBeenCalledOnce();
  });

  it("an editor from before protocol 2 is never waited on", async () => {
    const { frame } = mount({ host: host() });
    await ready(frame());
    expect(await flushDesignEditor("designs/launch.fig", 50)).toBe(true);
  });
});
