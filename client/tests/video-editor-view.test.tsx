import { describe, it, expect, vi, afterEach } from "vitest";
import { useState } from "react";
import { render, cleanup, act, fireEvent, screen } from "@testing-library/react";
import { VideoEditorView, detachVideoEditorsUnder, flushVideoEditor, refreshVideoEditors, reloadVideoEditors } from "../src/components/video-editor-view";
import { designSelection } from "../src/components/design-editor-view";
import { selectionLabel } from "../src/components/selection-chip";
import type { VideoEditorApi } from "../src/hooks/use-files";
import { ToastProvider } from "../src/lib/toast";

// The video editor is an iframe on the video service's origin, editing ONE composition through a
// session the SDK opened (POST /video/editor). Its saves come back as clean source and are written
// here only to that composition and to the words files the session was given, against their
// versions; an agent edit reaches it as a load of the new file, after what is unsaved went out.

const EDITOR = "https://editor.example";
const PATH = "videos/launch.video.html";
const WORDS = "videos/voice/intro.words.json";
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

function api(over: Partial<VideoEditorApi> = {}): VideoEditorApi & Record<string, ReturnType<typeof vi.fn>> {
  return {
    open: vi.fn(async () => ({ url: `${EDITOR}/s/abc/`, sid: "abc", versions: { [PATH]: "v1", [WORDS]: "w1" } })),
    replace: vi.fn(async () => {}),
    close: vi.fn(async () => {}),
    render: vi.fn(async () => ({ state: "rendering" as const, progress: 0 })),
    renderState: vi.fn(async () => ({ state: "done" as const, path: "videos/launch.mp4" })),
    readText: vi.fn(async () => ({ text: "<html>v1</html>", version: "v1" })),
    ...over,
  } as never;
}

async function mount(opts: { api?: VideoEditorApi; writeFile?: (p: string, d: BlobPart, o?: unknown) => Promise<unknown> } = {}) {
  const a = opts.api ?? api();
  const writeFile = vi.fn(opts.writeFile ?? (async (p: string) => ({ version: p === PATH ? "v2" : "w2" })));
  const onClose = vi.fn();
  render(<ToastProvider><VideoEditorView path={PATH} name="launch.video.html" api={a} writeFile={writeFile as never} onClose={onClose} /></ToastProvider>);
  await flush();
  await flush();
  const frame = document.querySelector("iframe") as HTMLIFrameElement;
  const post = frame ? vi.spyOn(frame.contentWindow!, "postMessage") : null;
  return { a, writeFile, onClose, frame, post };
}

function fromEditor(frame: HTMLIFrameElement, type: string, extra: Record<string, unknown> = {}, origin = EDITOR, source: Window | null = frame.contentWindow) {
  window.dispatchEvent(new MessageEvent("message", { origin, source, data: { source: "cycls-video-editor", type, ...extra } }));
}

const sent = (post: ReturnType<typeof vi.spyOn> | null, type?: string) =>
  (post?.mock.calls ?? []).map((c) => c[0] as Record<string, unknown>).filter((m) => !type || m.type === type);

async function ready(frame: HTMLIFrameElement, post: ReturnType<typeof vi.spyOn> | null) {
  fromEditor(frame, "ready", { protocol: 1 });
  await flush();
  await flush();
  const load = sent(post, "load").at(-1)!;
  fromEditor(frame, "loaded", { doc: load.doc });
  await flush();
  return load;
}

afterEach(() => cleanup());

describe("VideoEditorView", () => {
  it("opens a session and loads the workspace's file into it, from the editor's origin only", async () => {
    const { a, frame, post } = await mount();
    expect(a.open).toHaveBeenCalledWith(PATH);
    expect(frame.src).toBe(`${EDITOR}/s/abc/?theme=light`);
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts allow-same-origin allow-forms allow-downloads");
    fromEditor(frame, "ready", { protocol: 1 }, "https://evil.example");     // another origin: ignored
    await flush();
    expect(sent(post, "load")).toEqual([]);
    const load = await ready(frame, post);
    expect(load).toMatchObject({ target: "cycls-video-editor", html: "<html>v1</html>" });
    expect(post!.mock.calls.at(-1)![1]).toBe(EDITOR);
  });

  it("writes a save only to the composition and the words it was given, against their versions", async () => {
    const { frame, post, writeFile } = await mount();
    const load = await ready(frame, post);
    fromEditor(frame, "saved", { doc: load.doc, id: 1, composition: "<html>v2</html>", words: [
      { path: WORDS, text: JSON.stringify({ words: [{ text: "Hi" }] }) },
      { path: "videos/other.words.json", text: JSON.stringify({ words: [] }) },     // not given: not written
      { path: "apps/x/index.html", text: "<script>bad</script>" },                   // never
      { path: WORDS.replace("intro", "intro"), text: "not json" },                    // not words: skipped
    ] });
    await flush();
    await flush();
    expect(writeFile.mock.calls.map((c) => [c[0], (c[2] as { base?: string }).base])).toEqual([[PATH, "v1"], [WORDS, "w1"]]);
    expect(sent(post, "written").at(-1)).toMatchObject({ doc: load.doc, id: 1, ok: true });
    fromEditor(frame, "saved", { doc: load.doc, id: 2, composition: "<html>v3</html>" });
    await flush();
    await flush();
    expect((writeFile.mock.calls.at(-1)![2] as { base?: string }).base).toBe("v2");      // the next save stands on the last
    fromEditor(frame, "saved", { doc: "old-doc", id: 3, composition: "<html>stale</html>" });
    await flush();
    expect(sent(post, "written").at(-1)).toMatchObject({ id: 3, ok: false });
    expect(writeFile).toHaveBeenCalledTimes(3);
  });

  it("a stale save opens the conflict dialog, and keep mine writes over the newer file", async () => {
    let first = true;
    const { frame, post, writeFile } = await mount({ writeFile: async () => {
      if (first) { first = false; throw Object.assign(new Error("HTTP 412"), { status: 412 }); }
      return { version: "v9" };
    } });
    const load = await ready(frame, post);
    fromEditor(frame, "saved", { doc: load.doc, id: 1, composition: "<html>mine</html>" });
    await flush();
    await flush();
    expect(screen.getByTestId("video-conflict")).toBeTruthy();
    expect(screen.queryByText("Saving…")).toBeNull();                       // seen behind the dialog in the two-editors walk
    expect(sent(post, "written").at(-1)).toMatchObject({ ok: false });
    fireEvent.click(screen.getByText("Keep mine"));
    await flush();
    await flush();
    expect(writeFile.mock.calls.at(-1)![2]).toMatchObject({ force: true });
    expect(screen.queryByTestId("video-conflict")).toBeNull();
  });

  it("a save refused for access says so, not try again (taken off the team while editing)", async () => {
    const { frame, post } = await mount({ writeFile: async () => {
      throw Object.assign(new Error("HTTP 404"), { status: 404 });
    } });
    const load = await ready(frame, post);
    fromEditor(frame, "saved", { doc: load.doc, id: 1, composition: "<html>mine</html>" });
    await flush();
    await flush();
    expect(screen.getByText("Not saved — you no longer have access to this file")).toBeTruthy();
    expect(screen.queryByTestId("video-conflict")).toBeNull();
    expect(sent(post, "written").at(-1)).toMatchObject({ ok: false });
  });

  it("an agent edit flushes what is unsaved, then loads the new file", async () => {
    const a = api();
    const { frame, post } = await mount({ api: a });
    await ready(frame, post);
    a.readText.mockResolvedValueOnce({ text: "<html>agent</html>", version: "v5" });
    act(() => reloadVideoEditors(PATH, "v5"));
    await flush();
    const f = sent(post, "flush").at(-1)!;
    fromEditor(frame, "flushed", { id: f.id });
    await flush();
    await flush();
    expect(sent(post, "load").at(-1)).toMatchObject({ html: "<html>agent</html>" });
  });

  it("at a turn's end an open editor takes its file in again only if a file tool changed it", async () => {
    const a = api();
    const { frame, post } = await mount({ api: a });
    await ready(frame, post);
    const loads = sent(post, "load").length;
    await act(() => refreshVideoEditors());                              // unchanged: left alone
    await flush();
    expect(sent(post, "flush")).toEqual([]);
    expect(sent(post, "load")).toHaveLength(loads);
    a.readText.mockResolvedValue({ text: "<html>by edit</html>", version: "v7" });
    await act(() => refreshVideoEditors());                              // changed: flush, then load
    await flush();
    const f = sent(post, "flush").at(-1)!;
    fromEditor(frame, "flushed", { id: f.id });
    await flush();
    await flush();
    expect(sent(post, "load").at(-1)).toMatchObject({ html: "<html>by edit</html>" });
  });

  it("selection and ask go to the composer, with the time", async () => {
    const asked: unknown[] = [];
    const onAsk = (e: Event) => asked.push((e as CustomEvent).detail);
    window.addEventListener("cycls:ask-selection", onAsk);
    const { frame, post } = await mount();
    const load = await ready(frame, post);
    fromEditor(frame, "selection", { doc: load.doc, path: PATH, time: 4.2, nodes: [{ name: "t2", type: "h1", text: "Hello" }] });
    await flush();
    const sel = designSelection(PATH)!;
    expect(sel).toMatchObject({ path: PATH, frame: null, time: 4.2, nodes: [{ name: "t2", type: "h1", text: "Hello" }] });
    expect(selectionLabel(sel)).toBe("launch.video.html · 4.2 s: t2");
    fromEditor(frame, "ask", { doc: load.doc, path: PATH, time: 1, nodes: [{ name: "mus", type: "audio" }] });
    await flush();
    expect(asked).toHaveLength(1);
    window.removeEventListener("cycls:ask-selection", onAsk);
  });

  it("ask steps the editor aside, still open, so the composer under it can be typed into; Back returns", async () => {
    const onClose = vi.fn();
    function Host() {
      const [aside, setAside] = useState(false);
      return <VideoEditorView path={PATH} name="launch.video.html" api={api()} writeFile={vi.fn() as never} onClose={onClose}
                              aside={aside} onAside={() => setAside(true)} onBack={() => setAside(false)} />;
    }
    render(<ToastProvider><Host /></ToastProvider>);
    await flush();
    await flush();
    const frame = document.querySelector("iframe") as HTMLIFrameElement;
    const post = vi.spyOn(frame.contentWindow!, "postMessage");
    const load = await ready(frame, post);
    const overlay = screen.getByTestId("video-editor");
    const aside = () => overlay.className.includes("opacity-0") && overlay.hasAttribute("inert");
    expect(aside()).toBe(false);
    fromEditor(frame, "selection", { doc: load.doc, path: PATH, time: 2, nodes: [{ name: "t1", type: "h1" }] });
    await flush();
    expect(aside()).toBe(false);                                        // a plain selection keeps it in view
    fromEditor(frame, "ask", { doc: load.doc, path: PATH, time: 2, nodes: [{ name: "t1", type: "h1" }] });
    await flush();
    expect(aside()).toBe(true);
    // never `visibility: hidden`: Chrome stops drawing the cross-origin editor, and an agent's change
    // loaded meanwhile never got its preview (production, 2026-10-18)
    expect(overlay.className).not.toContain("invisible");
    expect(document.querySelector("iframe")).toBe(frame);              // the same session, not reopened
    fireEvent.keyDown(window, { key: "Escape" });                       // Escape in the composer: not Done
    await flush();
    expect(sent(post, "flush")).toEqual([]);                            // Done would flush first
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("video-editor-back"));
    await flush();
    expect(aside()).toBe(false);
    expect(screen.queryByTestId("video-editor-back")).toBeNull();
  });

  it("a render waits for the saves before it, and reports its progress to the editor", async () => {
    const { a, frame, post } = await mount();
    const load = await ready(frame, post);
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fromEditor(frame, "render", { doc: load.doc, quality: "standard" });
    await flush();
    await act(async () => { await vi.advanceTimersByTimeAsync(2100); });
    vi.useRealTimers();
    expect(a.render).toHaveBeenCalledWith(PATH, "standard");
    expect(sent(post, "render-state").map((m) => m.state)).toEqual(["rendering", "done"]);
  });

  it("a lost session opens another; flush and delete reach an open editor", async () => {
    const a = api();
    const { frame, post } = await mount({ api: a });
    const load = await ready(frame, post);
    const flushed = flushVideoEditor(PATH, 1000);
    await flush();
    fromEditor(frame, "flushed", { id: sent(post, "flush").at(-1)!.id });
    expect(await flushed).toBe(true);
    const reattach = detachVideoEditorsUnder("videos");
    fromEditor(frame, "saved", { doc: load.doc, id: 9, composition: "<html>x</html>" });
    await flush();
    expect(sent(post, "written").at(-1)).toMatchObject({ id: 9, ok: false });       // being deleted: not written
    reattach();
    fromEditor(frame, "error", { doc: load.doc, lost: true });
    await flush();
    await flush();
    expect(a.open).toHaveBeenCalledTimes(2);
  });

  it("an editor that is not offered says why", async () => {
    const a = api({ open: vi.fn(async () => { throw Object.assign(new Error("HTTP 503"), { status: 503, response: new Response(JSON.stringify({ detail: "The video editor is not available here." })) }); }) });
    await mount({ api: a });
    expect(screen.getByText("The video editor is not available here.")).toBeTruthy();
  });

  it("tells the editor it does media and requests; lists, adds and saves dropped files through the SDK", async () => {
    const a = api({
      media: vi.fn(async () => [{ path: "uploads/p.jpg", kind: "picture", size: 10 }]),
      addMedia: vi.fn(async () => ({ id: "picture" })),
      saveDropped: vi.fn(async (f: File) => `uploads/${f.name}`),
    } as never);
    const { frame, post } = await mount({ api: a });
    const load = await ready(frame, post);
    expect(sent(post, "host").at(-1)).toMatchObject({ features: ["media", "request"] });
    fromEditor(frame, "media-list", { doc: load.doc, id: "q1" });
    await flush();
    expect(sent(post, "media-list").at(-1)).toMatchObject({ id: "q1", files: [{ path: "uploads/p.jpg", kind: "picture" }] });
    fromEditor(frame, "media-add", { doc: load.doc, id: "q2", file: "uploads/p.jpg", kind: "picture", at: 2.5 });
    await flush();
    expect(a.addMedia).toHaveBeenLastCalledWith(PATH, "abc", "uploads/p.jpg", "picture", 2.5);
    expect(sent(post, "media-added").at(-1)).toMatchObject({ id: "q2", ok: true, added: 1 });
    fromEditor(frame, "media-add", { doc: "old", id: "q3", file: "uploads/p.jpg", kind: "picture", at: 0 });
    await flush();
    expect(a.addMedia).toHaveBeenCalledTimes(1);                          // not for a copy no longer loaded
    const clip = new File(["x"], "b roll.mp4", { type: "video/mp4" });
    const pic = new File(["y"], "logo.png", { type: "image/png" });
    fromEditor(frame, "media-drop", { doc: load.doc, id: "q4", files: [clip, pic, "not a file"], at: 1 });
    await flush();
    await flush();
    await flush();
    expect((a.saveDropped as ReturnType<typeof vi.fn>).mock.calls.map((c) => (c[0] as File).name)).toEqual(["b roll.mp4", "logo.png"]);
    expect((a.addMedia as ReturnType<typeof vi.fn>).mock.calls.slice(1).map((c) => [c[2], c[3], c[4]]))
      .toEqual([["uploads/b roll.mp4", "video", 1], ["uploads/logo.png", "picture", 6]]);    // one after the other
    expect(sent(post, "media-added").at(-1)).toMatchObject({ id: "q4", ok: true, added: 2 });
    (a.addMedia as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("A picture in a video is at most 2 MB."));
    fromEditor(frame, "media-add", { doc: load.doc, id: "q5", file: "uploads/big.png", kind: "picture", at: 0 });
    await flush();
    expect(sent(post, "media-added").at(-1)).toMatchObject({ id: "q5", ok: false, error: "A picture in a video is at most 2 MB." });
  });

  it("Translate asks the agent in the chat, naming the video, and steps the editor aside", async () => {
    const asked: unknown[] = [];
    const onSend = (e: Event) => asked.push((e as CustomEvent).detail);
    window.addEventListener("cycls:send", onSend);
    const onAside = vi.fn();
    render(<ToastProvider><VideoEditorView path={PATH} name="launch.video.html" api={api()} writeFile={vi.fn() as never}
                                           onClose={vi.fn()} onAside={onAside} /></ToastProvider>);
    await flush();
    await flush();
    const frame = document.querySelector("iframe") as HTMLIFrameElement;
    const post = vi.spyOn(frame.contentWindow!, "postMessage");
    const load = await ready(frame, post);
    fromEditor(frame, "request", { doc: load.doc, kind: "captions", to: "ar" });
    fromEditor(frame, "request", { doc: load.doc, kind: "dub", to: "ar-SA" });
    fromEditor(frame, "request", { doc: load.doc, kind: "dub", to: "ar" });
    fromEditor(frame, "request", { doc: load.doc, kind: "delete everything", to: "en" });   // not a request it makes
    await flush();
    expect(asked).toEqual([
      { text: `Translate the captions of ${PATH} into Arabic.`, origin: "video_editor" },
      { text: `Dub ${PATH} into Saudi Arabic.`, origin: "video_editor" },
      { text: `Dub ${PATH} into Standard Arabic.`, origin: "video_editor" },
    ]);
    expect(onAside).toHaveBeenCalled();
    window.removeEventListener("cycls:send", onSend);
  });
});
