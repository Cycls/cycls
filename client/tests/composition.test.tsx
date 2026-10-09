import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor, renderHook, act } from "@testing-library/react";
import CompositionView, { COMPOSITION_CSP, parseManifest, withCsp } from "../src/components/composition-view";
import { isComposition, isHtml, isRenderable, tileExt, editWorkingPath } from "../src/components/canvas-utils";
import { useFileContent } from "../src/components/canvas";
import { useChat } from "../src/hooks/use-chat";

// A Video composition is its own kind: it plays from the page the video service builds of it,
// sandboxed, and never runs as a page on the app's origin.

describe("the composition kind", () => {
  it("is told apart from a page by its suffix", () => {
    expect(isComposition("videos/launch.video.html")).toBe(true);
    expect(isComposition("videos/LAUNCH.VIDEO.HTML")).toBe(true);
    expect(isComposition("site/index.html")).toBe(false);
    expect(isHtml("videos/launch.video.html")).toBe(true);   // why CanvasDoc checks it first
    expect(tileExt("videos/launch.video.html")).toBe("video");
    expect(isRenderable("videos/launch.video.html")).toBe(true);
  });

  it("is never opened half-written as a working page", () => {
    expect(editWorkingPath("videos/launch.video.html")).toBeNull();
    expect(editWorkingPath("site/index.html")).toBe("site/index.html");
  });

  it("fetches the player page, not its source", async () => {
    const readFile = vi.fn(async () => "{\"html\":null,\"reason\":\"x\"}");
    const openFile = vi.fn(async () => "blob:x");
    const file = { path: "videos/launch.video.html", name: "launch.video.html" };
    const { result } = renderHook(() => useFileContent(file, readFile, openFile));
    await waitFor(() => expect(result.current.content).toBe("{\"html\":null,\"reason\":\"x\"}"));
    expect(readFile).toHaveBeenCalledWith("videos/launch.video.html?as=player", true);
    expect(openFile).not.toHaveBeenCalled();
  });
});

const PAGE = "<!doctype html><html><head><meta charset=\"utf-8\"></head><body><hyperframes-player></hyperframes-player></body></html>";

describe("CompositionView", () => {
  it("plays the page in an iframe allowed scripts and nothing else, under our CSP", () => {
    const data = JSON.stringify({ html: PAGE, reason: null, render: { path: "videos/a.mp4", exists: false } });
    const { container } = render(<CompositionView data={data} name="a.video.html" />);
    const frame = container.querySelector("iframe")!;
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    const doc = frame.getAttribute("srcdoc")!;
    expect(doc.indexOf(COMPOSITION_CSP)).toBeGreaterThan(-1);
    expect(doc.indexOf("Content-Security-Policy")).toBeLessThan(doc.indexOf("charset"));   // first in <head>
    expect(screen.queryByRole("tablist")).toBeNull();   // no render yet: no switch
  });

  it("switches between the preview and the rendered MP4", async () => {
    const data = JSON.stringify({ html: PAGE, reason: null, version: "v1", render: { path: "videos/a.mp4", exists: true } });
    const openFile = vi.fn(async () => "blob:mp4");
    const { container } = render(<CompositionView data={data} name="a.video.html" openFile={openFile} />);
    expect(container.querySelector("iframe")).not.toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Video" }));
    await waitFor(() => expect(container.querySelector("video")?.getAttribute("src")).toBe("blob:mp4"));
    expect(openFile).toHaveBeenCalledWith("videos/a.mp4", true);
    expect(container.querySelector("iframe")).toBeNull();
  });

  it("with no preview shows the MP4 when there is one", async () => {
    const data = JSON.stringify({ html: null, reason: "service away", render: { path: "videos/a.mp4", exists: true } });
    const openFile = vi.fn(async () => "blob:mp4");
    const { container } = render(<CompositionView data={data} name="a.video.html" openFile={openFile} />);
    await waitFor(() => expect(container.querySelector("video")).not.toBeNull());
    expect(container.querySelector("iframe")).toBeNull();
  });

  it("with neither says why and offers the download", () => {
    const onDownload = vi.fn();
    const data = JSON.stringify({ html: null, reason: "The composition has 2 errors to fix first.", render: { path: "videos/a.mp4", exists: false } });
    render(<CompositionView data={data} name="a.video.html" onDownload={onDownload} />);
    expect(screen.getByText("The composition has 2 errors to fix first.")).toBeTruthy();
    fireEvent.click(screen.getByText("Download"));
    expect(onDownload).toHaveBeenCalled();
  });

  it("reads only a manifest", () => {
    expect(parseManifest("<html></html>")).toBeNull();
    expect(parseManifest("{\"other\":1}")).toBeNull();
    expect(parseManifest(null)).toBeNull();
    expect(withCsp("no head")).toContain("Content-Security-Policy");
  });
});

describe("a long tool call stays live", () => {
  function sseLines(lines: string[]): any {
    const body = lines.map((l) => `data: ${l}\n\n`).join("");
    let sent = false;
    return {
      ok: true,
      body: {
        getReader: () => ({
          read: async () => {
            if (sent) return { done: true, value: undefined };
            sent = true;
            return { done: false, value: new TextEncoder().encode(body) };
          },
        }),
      },
    };
  }

  it("keep-alive pings are not parts", async () => {
    global.fetch = vi.fn(async () =>
      sseLines([
        JSON.stringify({ type: "step", id: "V1", tool_name: "Video", step: "render reel" }),
        JSON.stringify({ type: "ping" }),
        JSON.stringify({ type: "ping" }),
        JSON.stringify({ type: "step", id: "V1", tool_name: "Video", step: "render reel" }),
        JSON.stringify({ type: "text", text: "Rendered." }),
      ]),
    ) as any;
    const { result } = renderHook(() => useChat("http://api.test"));
    await act(async () => { await result.current.send("make it"); });
    expect(result.current.messages[1].parts!.map((p: any) => p.type)).toEqual(["step", "text"]);
  });
});
