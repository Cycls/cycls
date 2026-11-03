import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, cleanup, act, fireEvent, screen } from "@testing-library/react";
import { Canvas, type CanvasFile } from "../src/components/canvas";
import { readClipSteps, type VideoClipStep, type VideoEditorApi } from "../src/hooks/use-files";
import { ToastProvider } from "../src/lib/toast";

// A video's editor is a full-page overlay of its own. When another tab is shown while it is open
// (the agent opened the MP4 it rendered, stepped aside for Ask Cycls), its tab stays mounted, hidden,
// so the editor stays open; a video tab closed meanwhile saves what is unsaved, then goes.

const EDITOR = "https://editor.example";
const VIDEO: CanvasFile = { path: "videos/launch.video.html", name: "launch.video.html" };
const MP4: CanvasFile = { path: "videos/launch.mp4", name: "launch.mp4" };
const PLAYER = JSON.stringify({ html: "<html><head></head><body>P</body></html>", reason: null, version: "v1" });
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

function api(): VideoEditorApi & Record<string, ReturnType<typeof vi.fn>> {
  return {
    open: vi.fn(async () => ({ url: `${EDITOR}/s/abc/`, sid: "abc", versions: { [VIDEO.path]: "v1" } })),
    replace: vi.fn(async () => {}),
    close: vi.fn(async () => {}),
    render: vi.fn(async () => ({ state: "done" as const })),
    renderState: vi.fn(async () => ({ state: "done" as const })),
    readText: vi.fn(async () => ({ text: "<html>v1</html>", version: "v1" })),
  } as never;
}

function canvas(tabs: CanvasFile[], active: string, videoEditor: VideoEditorApi) {
  return (
    <ToastProvider>
      <Canvas tabs={tabs} active={active} docked hidden={false} expanded={false}
              onToggleExpand={() => {}} onSelectTab={() => {}} onCloseTab={() => {}} onHide={() => {}}
              readFile={async () => PLAYER} openFile={async () => "blob:mp4"} writeFile={async () => ({ version: "v2" })}
              videoEditor={videoEditor} />
    </ToastProvider>
  );
}

const editor = () => document.querySelector('[data-testid="video-editor"]') as HTMLElement | null;
const editorFrame = () => editor()?.querySelector("iframe") as HTMLIFrameElement | null;
const say = (frame: HTMLIFrameElement, type: string, extra: Record<string, unknown> = {}) => window.dispatchEvent(
  new MessageEvent("message", { origin: EDITOR, source: frame.contentWindow, data: { source: "cycls-video-editor", type, ...extra } }));

async function openAside(a: VideoEditorApi) {
  const view = render(canvas([VIDEO, MP4], VIDEO.path, a));
  fireEvent.click(await screen.findByTestId("video-edit"));
  await flush();
  await flush();
  const frame = editorFrame()!;
  const post = vi.spyOn(frame.contentWindow!, "postMessage");
  say(frame, "ready", { protocol: 1 });
  await flush();
  await flush();
  const load = post.mock.calls.map((c) => c[0] as Record<string, unknown>).find((m) => m.type === "load")!;
  say(frame, "loaded", { doc: load.doc });
  say(frame, "ask", { doc: load.doc, path: VIDEO.path, time: 2, nodes: [{ name: "#title", type: "text", text: "Hi" }] });
  await flush();
  expect(editor()!.className).toContain("opacity-0");                       // stepped aside for the chat
  return { ...view, frame, post };
}

const flushAsked = (post: ReturnType<typeof vi.spyOn>) =>
  post.mock.calls.map((c) => c[0] as Record<string, unknown>).find((m) => m.type === "flush");

describe("a video's editor in the canvas", () => {
  beforeEach(() => { URL.revokeObjectURL = vi.fn(); });
  afterEach(() => cleanup());

  it("stays open, aside, when the agent opens another tab; Back brings it back", async () => {
    const a = api();
    const { rerender, frame, post } = await openAside(a);
    rerender(canvas([VIDEO, MP4], MP4.path, a));                            // the agent opened the MP4 it rendered
    await flush();
    expect(editorFrame()).toBe(frame);                                       // the same editor, not reopened
    expect(a.close).not.toHaveBeenCalled();
    expect(flushAsked(post)).toBeUndefined();
    fireEvent.click(screen.getByTestId("video-editor-back"));
    await flush();
    expect(editor()!.className).not.toContain("opacity-0");
    expect(editorFrame()).toBe(frame);
  });

  it("Done, from another tab, closes it and lets its tab go", async () => {
    const a = api();
    const { rerender, container, frame, post } = await openAside(a);
    rerender(canvas([VIDEO, MP4], MP4.path, a));
    await flush();
    expect(container.querySelectorAll("[inert]").length).toBe(1);            // the video's tab, hidden
    fireEvent.click(screen.getByTestId("video-editor-back"));
    fireEvent.click(screen.getByTestId("video-editor-done"));
    await flush();
    say(frame, "flushed", { id: flushAsked(post)!.id });
    await flush();
    await flush();
    expect(editor()).toBeNull();
    expect(a.close).toHaveBeenCalledWith("abc");
    // The editor is gone; the video's tab stays mounted, hidden, as every open tab now does (main's
    // canvas: going back to a tab finds it as it was).
    expect(container.querySelectorAll("[inert]").length).toBe(1);
  });

  it("its tab closed meanwhile saves what is unsaved, then the editor goes", async () => {
    const a = api();
    const { rerender, frame, post } = await openAside(a);
    rerender(canvas([VIDEO, MP4], MP4.path, a));
    await flush();
    rerender(canvas([MP4], MP4.path, a));                                    // the video's tab closed
    await flush();
    const ask = flushAsked(post);
    expect(ask).toBeTruthy();
    expect(editorFrame()).toBe(frame);                                       // not before it has saved
    say(frame, "flushed", { id: ask!.id });
    await flush();
    await flush();
    expect(editor()).toBeNull();
    expect(a.close).toHaveBeenCalledWith("abc");
  });
});

// Edit on a video file the person sent: its own video made (POST /video/clip, counted through), then
// opened in its editor as the canvas shows it.
const CLIP: CanvasFile = { path: "attachments/1a2b3c4d-interview.mp4", name: "1a2b3c4d-interview.mp4" };
const MADE: CanvasFile = { path: "videos/interview.video.html", name: "interview.video.html" };

function clipCanvas(tabs: CanvasFile[], active: string, videoEditor: VideoEditorApi, onAddFile: (p: string) => void) {
  return (
    <ToastProvider>
      <Canvas tabs={tabs} active={active} docked hidden={false} expanded={false}
              onToggleExpand={() => {}} onSelectTab={() => {}} onCloseTab={() => {}} onHide={() => {}}
              readFile={async () => PLAYER} openFile={async () => "blob:mp4"} writeFile={async () => ({ version: "v2" })}
              videoEditor={videoEditor} onAddFile={onAddFile} />
    </ToastProvider>
  );
}

describe("Edit on a clip", () => {
  beforeEach(() => { URL.revokeObjectURL = vi.fn(); });
  afterEach(() => cleanup());

  it("counts through making its video, then opens that video in the editor", async () => {
    let go = () => {};
    const gate = new Promise<void>((r) => { go = r; });
    const a = Object.assign(api(), {
      clip: vi.fn(async () => ({ editor: true, video: null })),
      fromClip: vi.fn(async (_p: string, onStep: (s: VideoClipStep) => void) => {
        onStep({ state: "sending", sent: 40, size: 100 });
        await gate;
        onStep({ state: "reading" });
        return { state: "ready" as const, path: MADE.path, made: true };
      }),
    });
    const opened = vi.fn();
    const { rerender } = render(clipCanvas([CLIP], CLIP.path, a, opened));
    fireEvent.click(await screen.findByTestId("clip-edit"));
    await flush();
    expect(a.fromClip).toHaveBeenCalledWith(CLIP.path, expect.any(Function));
    expect(screen.getByTestId("clip-edit").textContent).toMatch(/40/);       // the upload, counted
    expect((screen.getByTestId("clip-edit") as HTMLButtonElement).disabled).toBe(true);
    go();
    await flush();
    expect(opened).toHaveBeenCalledWith(MADE.path);                           // its video opened beside it
    rerender(clipCanvas([CLIP, MADE], MADE.path, a, opened));
    await flush();
    await flush();
    expect(a.open).toHaveBeenCalledWith(MADE.path);                           // and its editor, with no second press
    expect(editor()).not.toBeNull();
  });

  it("is not offered where Video is not, and says why it could not be made", async () => {
    const off = Object.assign(api(), { clip: vi.fn(async () => ({ editor: false, video: null })), fromClip: vi.fn() });
    render(clipCanvas([CLIP], CLIP.path, off, vi.fn()));
    await flush();
    await flush();
    expect(off.clip).toHaveBeenCalledWith(CLIP.path);
    expect(screen.queryByTestId("clip-edit")).toBeNull();
    cleanup();
    const failing = Object.assign(api(), {
      clip: vi.fn(async () => ({ editor: true, video: null })),
      fromClip: vi.fn(async () => ({ state: "failed" as const, message: "The clip was not taken: That file is not a video." })),
    });
    const opened = vi.fn();
    render(clipCanvas([CLIP], CLIP.path, failing, opened));
    fireEvent.click(await screen.findByTestId("clip-edit"));
    await flush();
    expect(screen.getByTestId("clip-edit-failed").textContent).toContain("not a video");
    expect((screen.getByTestId("clip-edit") as HTMLButtonElement).disabled).toBe(false);   // Edit again goes on
    expect(opened).not.toHaveBeenCalled();
  });
});

describe("readClipSteps", () => {
  const stream = (chunks: string[], fail = false) => new ReadableStream<Uint8Array>({
    start(c) {
      for (const s of chunks) c.enqueue(new TextEncoder().encode(s));
      if (fail) c.error(new Error("reset")); else c.close();
    },
  });

  it("reads a step split across chunks, and the last line with no newline", async () => {
    const steps: VideoClipStep[] = [];
    const end = await readClipSteps(stream(['{"state":"send', 'ing","sent":1,"size":2}\n{"state":"reading"}\n',
                                            '{"state":"ready","path":"videos/a.video.html"}']), (s) => steps.push(s));
    expect(steps.map((s) => s.state)).toEqual(["sending", "reading", "ready"]);
    expect(end).toEqual({ state: "ready", path: "videos/a.video.html" });
  });

  it("a stream cut short is a failure Edit can go on from", async () => {
    const end = await readClipSteps(stream(['{"state":"sending","sent":1,"size":2}\n'], true), () => {});
    expect(end.state).toBe("failed");
    expect((end as { message: string }).message).toMatch(/Press Edit to go on/);
  });
});
