import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, cleanup, act, fireEvent, screen } from "@testing-library/react";
import { Canvas, type CanvasFile } from "../src/components/canvas";
import type { VideoEditorApi } from "../src/hooks/use-files";
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
  expect(editor()!.className).toContain("invisible");                       // stepped aside for the chat
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
    expect(editor()!.className).not.toContain("invisible");
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
    expect(container.querySelectorAll("[inert]").length).toBe(0);            // nothing left mounted behind
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
