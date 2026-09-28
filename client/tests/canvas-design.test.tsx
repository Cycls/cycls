import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, cleanup, act, fireEvent, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { Canvas, type CanvasFile } from "../src/components/canvas";
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
