import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, cleanup, act } from "@testing-library/react";
import { Canvas, type CanvasFile } from "../src/components/canvas";

// Two kinds of pane stay mounted behind the tab in front: an app once shown (a running
// program isn't restarted by a tab switch) and a design editor until it has saved. Both
// are iframes, and an iframe taken out of the page or moved in it reloads — so a tab
// switch may neither remount nor move one of them.

const EDITOR = "https://ed.example";
const APP = "apps/studio/index.html", FIG = "designs/a.fig", MD = "notes.md";
const TABS: CanvasFile[] = [{ path: APP, name: "Studio" }, { path: FIG, name: "a.fig" }, { path: MD, name: "notes.md" }];
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

// Stable across renders, as the chat's are: a new one would re-attach the app's bridge.
const readFile = async (p: string) => (p.startsWith(APP) ? "<!doctype html><html><body>app</body></html>" : "# notes");
const openFile = async () => "blob:fig";
const writeFile = async () => {};
const noop = () => {};

function canvas(active: string, working?: string[], tabs = TABS) {
  return (
    <Canvas tabs={tabs} active={active} docked hidden={false} expanded={false} working={working}
            onToggleExpand={noop} onSelectTab={noop} onCloseTab={noop} onHide={noop}
            readFile={readFile} openFile={openFile} writeFile={writeFile} designEditorUrl={EDITOR} />
  );
}

describe("the panes behind the tab in front", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ arrayBuffer: async () => new Uint8Array([1]).buffer })));
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  const appFrame = (c: HTMLElement) => c.querySelector<HTMLIFrameElement>("iframe[srcdoc]");
  const editorFrame = (c: HTMLElement) => c.querySelector<HTMLIFrameElement>(`iframe[src^="${EDITOR}"]`);
  // Every node taken out of the page from here on (a move is a removal, then an addition).
  const removals = (root: HTMLElement) => {
    const gone: Node[] = [];
    const seen = (records: MutationRecord[]) => records.forEach((r) => gone.push(...r.removedNodes));
    const watch = new MutationObserver(seen);
    watch.observe(root, { childList: true, subtree: true });
    return { took: (frame: Node) => { seen(watch.takeRecords()); return gone.some((n) => n.contains(frame)); } };
  };
  // The editor's side of its handshake, and of a save.
  const editor = (frame: HTMLIFrameElement) => {
    const post = vi.spyOn(frame.contentWindow!, "postMessage");
    const say = (type: string, extra: Record<string, unknown> = {}) => window.dispatchEvent(
      new MessageEvent("message", { origin: EDITOR, source: frame.contentWindow, data: { source: "cycls-editor", type, ...extra } }));
    const asked = () => post.mock.calls.map((c) => c[0] as Record<string, unknown>).find((m) => m.type === "flush");
    return { say, asked };
  };

  it("an app stays as it is, and an editor until it has saved, through every switch", async () => {
    const { container, rerender } = render(canvas(APP));
    await flush();
    const app = appFrame(container)!;
    expect(app).toBeTruthy();
    const out = removals(container);

    rerender(canvas(FIG));                                   // the design, in front of the app
    await flush();
    const fig = editorFrame(container)!;
    expect(fig).toBeTruthy();
    expect(fig.closest("[inert]")).toBeNull();
    expect(appFrame(container)).toBe(app);                   // the same frame…
    expect(app.closest("[inert]")).toBeTruthy();             // …hidden, out of reach
    const ed = editor(fig);
    ed.say("ready", { protocol: 2 });
    await flush();

    rerender(canvas(MD));                                    // a document: both wait behind it
    await flush();
    expect(appFrame(container)).toBe(app);
    expect(editorFrame(container)).toBe(fig);
    expect(fig.closest("[inert]")).toBeTruthy();
    expect(ed.asked()).toBeTruthy();                         // the editor was asked to save

    rerender(canvas(APP));                                   // back to the app, the editor still saving
    await flush();
    expect(appFrame(container)).toBe(app);
    expect(app.closest("[inert]")).toBeNull();
    expect(editorFrame(container)).toBe(fig);
    expect(out.took(app)).toBe(false);                       // neither was ever taken out or moved
    expect(out.took(fig)).toBe(false);

    ed.say("flushed", { id: ed.asked()!.id, ok: true });
    await flush();
    expect(editorFrame(container)).toBeNull();               // saved: gone
    expect(appFrame(container)).toBe(app);
    expect(out.took(app)).toBe(false);
  });

  it("a file being written shows its skeleton, but never in place of an editor that is saving", async () => {
    const { container, rerender } = render(canvas(APP));
    await flush();
    rerender(canvas(FIG));
    await flush();
    const fig = editorFrame(container)!;
    const ed = editor(fig);
    ed.say("ready", { protocol: 2 });
    await flush();
    rerender(canvas(MD));
    await flush();
    expect(appFrame(container)).toBeTruthy();

    rerender(canvas(MD, [APP, FIG]));                        // the agent starts on both
    await flush();
    expect(editorFrame(container)).toBe(fig);                // the editor is there to save: it stays
    expect(appFrame(container)).toBeNull();                  // the app comes back fresh when it's written
  });

  it("two editors saving at once: neither is moved", async () => {
    const FIG2 = "designs/b.fig";
    const tabs = [...TABS, { path: FIG2, name: "b.fig" }];
    const frameOf = (c: HTMLElement, title: string) => c.querySelector<HTMLIFrameElement>(`iframe[title="${title}"]`);
    const { container, rerender } = render(canvas(FIG, undefined, tabs));
    await flush();
    const a = frameOf(container, "a.fig")!;
    const edA = editor(a);
    edA.say("ready", { protocol: 2 });
    await flush();
    const out = removals(container);

    rerender(canvas(FIG2, undefined, tabs));                 // the second design: the first saves behind it
    await flush();
    const b = frameOf(container, "b.fig")!;
    const edB = editor(b);
    edB.say("ready", { protocol: 2 });
    await flush();

    rerender(canvas(MD, undefined, tabs));                   // and away from that one too, before the first is done
    await flush();
    expect(frameOf(container, "a.fig")).toBe(a);
    expect(frameOf(container, "b.fig")).toBe(b);
    expect(out.took(a)).toBe(false);
    expect(out.took(b)).toBe(false);                         // a moved frame reloads, and loses what it hadn't saved

    edA.say("flushed", { id: edA.asked()!.id, ok: true });
    edB.say("flushed", { id: edB.asked()!.id, ok: true });
    await flush();
    expect(container.querySelector("iframe")).toBeNull();
  });
});
