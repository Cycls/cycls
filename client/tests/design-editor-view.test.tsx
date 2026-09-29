import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, cleanup, act, fireEvent, screen } from "@testing-library/react";
import {
  DesignEditorView, detachDesignEditorsUnder, flushDesignEditor, fullscreenDesignEditor, type DesignHost,
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

function mount(opts: { writeFile?: (p: string, d: BlobPart) => Promise<void>; reload?: () => Promise<string>; host?: DesignHost } = {}) {
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
    expect(writeFile).toHaveBeenCalledWith("designs/launch.fig", expect.anything());
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

  it("goes full screen in its own box, keeps Esc, and leaves first for what opens elsewhere", async () => {
    const fs = fakeFullscreen();
    try {
      const h = host();
      const { frame } = mount({ host: h });
      const first = frame();
      await ready(first, 2);
      await act(async () => { fullscreenDesignEditor("designs/launch.fig"); await new Promise((r) => setTimeout(r, 0)); });
      expect(document.fullscreenElement).toBe(first.parentElement);        // the editor's box, not the page
      expect(frame()).toBe(first);                                          // nothing reloads
      expect(fs.keyboard.lock).toHaveBeenCalledWith(["Escape"]);
      expect(screen.getByText("Exit full screen")).toBeTruthy();

      fromEditor(first, "newDesign", { size: [1080, 1080] });              // opens in another canvas tab
      await flush();
      expect(fs.exit).toHaveBeenCalledOnce();
      expect(fs.exit.mock.invocationCallOrder[0]).toBeLessThan(h.newDesign.mock.invocationCallOrder[0]);
      expect(fs.keyboard.unlock).toHaveBeenCalled();
      expect(screen.queryByText("Exit full screen")).toBeNull();
    } finally {
      fs.restore();
    }
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
