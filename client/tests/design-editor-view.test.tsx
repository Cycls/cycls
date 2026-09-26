import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, cleanup, act } from "@testing-library/react";
import { DesignEditorView } from "../src/components/design-editor-view";

// The editor iframe talks to its host over postMessage. An agent edit reaches the
// editor only AFTER the server applied and saved it, so when the live replay fails
// (`commandError`) the host must re-open the editor on the saved file — a stale
// document left in the editor would later auto-save over the agent's change.

const EDITOR = "https://ed.example";
const bytes = { "blob:orig": [1, 2, 3], "blob:fresh": [9, 9] } as Record<string, number[]>;
const b64 = (a: number[]) => btoa(String.fromCharCode(...a));

function fromEditor(type: string, extra: Record<string, unknown> = {}) {
  window.dispatchEvent(new MessageEvent("message", { origin: EDITOR, data: { source: "cycls-editor", type, ...extra } }));
}

const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

describe("DesignEditorView — a failed live replay", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async (u: string) => ({ arrayBuffer: async () => new Uint8Array(bytes[u]).buffer })));
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("re-opens the editor on the saved file, not the stale one", async () => {
    const reload = vi.fn(async () => "blob:fresh");
    const { container } = render(
      <DesignEditorView url="blob:orig" path="designs/launch.fig" name="launch.fig"
                        editorUrl={EDITOR} writeFile={async () => {}} reload={reload} />);
    const first = container.querySelector("iframe")!;
    const post1 = vi.spyOn(first.contentWindow!, "postMessage");
    fromEditor("ready");
    await flush();
    expect(post1).toHaveBeenCalledWith(expect.objectContaining({ type: "load", fig: b64(bytes["blob:orig"]) }), EDITOR);
    fromEditor("loaded");
    await flush();

    fromEditor("commandError", { message: "null is not an object" });
    await flush();
    expect(reload).toHaveBeenCalledOnce();
    const second = container.querySelector("iframe")!;
    expect(second).not.toBe(first);                              // remounted
    const post2 = vi.spyOn(second.contentWindow!, "postMessage");
    fromEditor("ready");
    await flush();
    expect(post2).toHaveBeenCalledWith(expect.objectContaining({ type: "load", fig: b64(bytes["blob:fresh"]) }), EDITOR);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:fresh");
  });

  it("a save error does not re-open anything", async () => {
    const reload = vi.fn(async () => "blob:fresh");
    const { container } = render(
      <DesignEditorView url="blob:orig" path="designs/launch.fig" name="launch.fig"
                        editorUrl={EDITOR} writeFile={async () => {}} reload={reload} />);
    const first = container.querySelector("iframe")!;
    fromEditor("ready");
    await flush();
    fromEditor("loaded");
    fromEditor("error", { message: "exportFigFile timeout (20s)" });
    await flush();
    expect(reload).not.toHaveBeenCalled();
    expect(container.querySelector("iframe")).toBe(first);
  });
});
