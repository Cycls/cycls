// Cycls Sheets in the canvas: a file opens in the editor only when the workspace has it; the editor is
// framed with the theme and language, gets the workbook once it says it is ready, and only its own
// origin and frame are heard.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { OfficeEditorApi, SheetsOpened } from "../src/hooks/use-files";
import { CanvasHeaderSlot } from "../src/components/canvas-header-slot";
import { flushAllSheetsEditors, SheetsEditorView, SheetsOrPreview } from "../src/components/sheets-editor-view";
import { designSelection } from "../src/components/design-editor-view";

afterEach(cleanup);

const OPENED: SheetsOpened = {
  version: "abc123",
  modified: new Date().toISOString(),
  snapshot: { id: "book", sheetOrder: ["s1"] },
  notices: [{ kind: "chart", message: "1 chart on \"Sales\" stays in the file" }],
  activeSheet: "s1",
};

const api = (answer: Awaited<ReturnType<OfficeEditorApi["sheets"]>> | Error): OfficeEditorApi => ({
  sheets: vi.fn(async () => {
    if (answer instanceof Error) throw answer;
    return answer;
  }),
  sheetsOpen: vi.fn(async () => OPENED),
  pdf: vi.fn(async () => "blob:pdf"),
  sheetsSave: vi.fn(async () => ({ version: "v2", unchanged: false })),
});

function frameWith(posted: Array<[unknown, string]>) {
  const frame = document.querySelector("iframe")!;
  Object.defineProperty(frame, "contentWindow", {
    value: { postMessage: (m: unknown, o: string) => posted.push([m, o]) },
    configurable: true,
  });
  return frame;
}

const say = (origin: string, source: unknown, data: Record<string, unknown>) => act(() => {
  window.dispatchEvent(new MessageEvent("message", { origin, source: source as Window, data: { source: "cycls-sheets", ...data } }));
});

describe("Cycls Sheets in the canvas", () => {
  test("a workspace without Sheets keeps the preview", async () => {
    render(<SheetsOrPreview path="a/b.xlsx" name="b.xlsx" api={api({ editor: false, reason: "off" })} preview={<p>preview</p>} />);
    expect(await screen.findByText("preview")).toBeTruthy();
    expect(document.querySelector("iframe")).toBeNull();
  });

  test("a failed answer keeps the preview too", async () => {
    render(<SheetsOrPreview path="b.xlsx" name="b.xlsx" api={api(new Error("down"))} preview={<p>preview</p>} />);
    expect(await screen.findByText("preview")).toBeTruthy();
  });

  test("a workspace with Sheets frames the editor with the theme and language, under the file's header", async () => {
    const a = api({ editor: true, url: "https://office.test/sheets/", name: "b.xlsx" });
    render(<SheetsOrPreview path="reports/b.xlsx" name="b.xlsx" api={a} preview={<p>preview</p>} />);
    await waitFor(() => expect(document.querySelector("iframe")).not.toBeNull());
    const src = new URL(document.querySelector("iframe")!.getAttribute("src")!);
    expect(src.origin + src.pathname).toBe("https://office.test/sheets/");
    expect(src.searchParams.get("embed")).toBe("cycls");
    expect(["light", "dark"]).toContain(src.searchParams.get("theme"));
    expect(a.sheets).toHaveBeenCalledWith("reports/b.xlsx");
    expect(screen.queryByText("preview")).toBeNull();
    expect(screen.getByText("b.xlsx")).toBeTruthy();
    expect(screen.getByText("/ reports")).toBeTruthy();
  });

  test("only the editor's own origin and frame are heard; the workbook goes to that origin once it is ready", async () => {
    const a = api({ editor: true, url: "https://office.test/sheets/", name: "b.xlsx" });
    render(<SheetsEditorView url="https://office.test/sheets/" path="b.xlsx" name="b.xlsx" api={a} />);
    const posted: Array<[unknown, string]> = [];
    const frame = frameWith(posted);
    await waitFor(() => expect(a.sheetsOpen).toHaveBeenCalledWith("b.xlsx"));
    say("https://evil.test", frame.contentWindow, { type: "ready" });
    say("https://office.test", window, { type: "ready" });
    expect(posted).toHaveLength(0);

    say("https://office.test", frame.contentWindow, { type: "ready", protocol: 1 });
    await waitFor(() => expect(posted.map(([m]) => (m as { type: string }).type)).toContain("load"));
    expect(posted.every(([, origin]) => origin === "https://office.test")).toBe(true);
    const load = posted.find(([m]) => (m as { type: string }).type === "load")![0] as Record<string, unknown>;
    expect(load).toMatchObject({ target: "cycls-sheets", name: "b.xlsx", snapshot: OPENED.snapshot, activeSheet: "s1", readonly: false });
    expect(load.doc).toBe("b.xlsx@abc123");
    expect(posted.map(([m]) => (m as { type: string }).type)).toEqual(expect.arrayContaining(["theme", "locale"]));
  });

  test("the header lists what is kept but not shown, and Open offers Excel and PDF", async () => {
    const download = vi.fn();
    const a = api({ editor: true, url: "https://office.test/sheets/", name: "b.xlsx" });
    render(<SheetsEditorView url="https://office.test/sheets/" path="b.xlsx" name="b.xlsx" api={a} onDownload={download} />);
    fireEvent.click(await screen.findByText("ⓘ 1"));
    expect(screen.getByText(OPENED.notices[0].message)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Open/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Excel/ }));
    expect(download).toHaveBeenCalled();
  });

  test("full screen, from the canvas header, is the editor's box: nothing reloads, and Saved, Open and the way out come along", async () => {
    // The browser's full screen (jsdom has none): one element at a time, with its change event.
    let el: Element | null = null;
    const change = () => document.dispatchEvent(new Event("fullscreenchange"));
    const exit = vi.fn(async () => { el = null; change(); });
    Object.defineProperty(document, "fullscreenElement", { configurable: true, get: () => el });
    Object.defineProperty(document, "fullscreenEnabled", { configurable: true, value: true });
    Object.defineProperty(document, "exitFullscreen", { configurable: true, value: exit });
    Object.defineProperty(Element.prototype, "requestFullscreen", {
      configurable: true, value: async function (this: Element) { el = this; change(); },
    });
    const end = document.body.appendChild(document.createElement("div"));
    try {
      const a = api({ editor: true, url: "https://office.test/sheets/", name: "b.xlsx" });
      render(
        <CanvasHeaderSlot.Provider value={{ start: null, end }}>
          <SheetsEditorView url="https://office.test/sheets/" path="b.xlsx" name="b.xlsx" api={a} />
        </CanvasHeaderSlot.Provider>);
      const frame = document.querySelector("iframe")!;
      const button = await waitFor(() => within(end).getByRole("button", { name: "Full screen" }));
      await act(async () => { fireEvent.click(button); await new Promise((r) => setTimeout(r, 0)); });
      const box = screen.getByTestId("sheets-editor");
      expect(document.fullscreenElement).toBe(box);
      expect(document.querySelector("iframe")).toBe(frame);                    // the same editor, not reloaded
      expect(box.contains(screen.getByTestId("sheets-status"))).toBe(true);    // the header is left behind: its row comes in
      expect(box.contains(screen.getByRole("button", { name: /Open/ }))).toBe(true);
      expect(within(end).queryByRole("button", { name: "Full screen" })).toBeNull();

      await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Exit full screen" })); });
      expect(exit).toHaveBeenCalledOnce();
      expect(end.contains(screen.getByTestId("sheets-status"))).toBe(true);    // back in the canvas header
      expect(within(end).getByRole("button", { name: "Full screen" })).toBeTruthy();
      expect(document.querySelector("iframe")).toBe(frame);
    } finally {
      end.remove();
      for (const k of ["fullscreenElement", "fullscreenEnabled", "exitFullscreen"]) delete (document as unknown as Record<string, unknown>)[k];
      delete (Element.prototype as unknown as Record<string, unknown>).requestFullscreen;
    }
  });
});

describe("saving from Cycls Sheets", () => {
  async function opened(a: OfficeEditorApi) {
    render(<SheetsEditorView url="https://office.test/sheets/" path="b.xlsx" name="b.xlsx" api={a} />);
    const posted: Array<[unknown, string]> = [];
    const frame = frameWith(posted);
    await waitFor(() => expect(a.sheetsOpen).toHaveBeenCalled());
    say("https://office.test", frame.contentWindow, { type: "ready", protocol: 1 });
    await waitFor(() => expect(posted.some(([m]) => (m as { type: string }).type === "load")).toBe(true));
    const doc = (posted.find(([m]) => (m as { type: string }).type === "load")![0] as { doc: string }).doc;
    return { posted, frame, doc };
  }
  const types = (posted: Array<[unknown, string]>) => posted.map(([m]) => (m as { type: string }).type);

  test("a save goes to the file with the version it was opened at, and the editor hears it was written", async () => {
    const a = api({ editor: true, url: "https://office.test/sheets/", name: "b.xlsx" });
    const { posted, frame, doc } = await opened(a);
    say("https://office.test", frame.contentWindow, { type: "dirty", doc, dirty: true });
    expect(await screen.findByText("Unsaved changes")).toBeTruthy();
    say("https://office.test", frame.contentWindow, { type: "saved", doc, id: "1", snapshot: { sheetOrder: ["s1"] } });
    await waitFor(() => expect(a.sheetsSave).toHaveBeenCalledWith("b.xlsx", "abc123", { snapshot: { sheetOrder: ["s1"] }, ops: [] }, false));
    await waitFor(() => expect(posted.some(([m]) => (m as { type: string; ok?: boolean }).type === "written" && (m as { ok?: boolean }).ok)).toBe(true));
    expect(await screen.findByText("Saved")).toBeTruthy();

    // The next save names the version the last one made.
    say("https://office.test", frame.contentWindow, { type: "saved", doc, id: "2", snapshot: { sheetOrder: ["s1"], n: 2 } });
    await waitFor(() => expect(a.sheetsSave).toHaveBeenLastCalledWith("b.xlsx", "v2", { snapshot: { sheetOrder: ["s1"], n: 2 }, ops: [] }, false));
  });

  test("a file changed elsewhere asks; Keep mine saves over it", async () => {
    const a = api({ editor: true, url: "https://office.test/sheets/", name: "b.xlsx" });
    (a.sheetsSave as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ conflict: "v9" });
    const { posted, frame, doc } = await opened(a);
    say("https://office.test", frame.contentWindow, { type: "saved", doc, id: "1", snapshot: { sheetOrder: ["s1"] } });
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText("Couldn't save")).toBeTruthy();
    expect(posted.some(([m]) => (m as { type: string; ok?: boolean }).type === "written" && (m as { ok?: boolean }).ok === false)).toBe(true);

    fireEvent.click(screen.getByText("Keep mine"));
    expect(types(posted)).toContain("save");
    say("https://office.test", frame.contentWindow, { type: "saved", doc, id: "2", snapshot: { sheetOrder: ["s1"] } });
    await waitFor(() => expect(a.sheetsSave).toHaveBeenLastCalledWith("b.xlsx", "abc123", { snapshot: { sheetOrder: ["s1"] }, ops: [] }, true));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  test("an editor left open takes in a change made elsewhere when the page comes back into view", async () => {
    const a = { ...api({ editor: true, url: "https://office.test/sheets/", name: "b.xlsx" }), sheetsVersion: vi.fn(async () => ({ version: "abc123" })) };
    const { frame, doc } = await opened(a);
    say("https://office.test", frame.contentWindow, { type: "loaded", doc });
    act(() => { window.dispatchEvent(new Event("focus")); });
    await waitFor(() => expect(a.sheetsVersion).toHaveBeenCalledTimes(1));
    expect(a.sheetsOpen).toHaveBeenCalledTimes(1);   // the same version: nothing to do

    a.sheetsVersion.mockResolvedValue({ version: "v7" });   // someone else saved it
    act(() => { window.dispatchEvent(new Event("focus")); });
    await waitFor(() => expect(a.sheetsOpen).toHaveBeenCalledTimes(2));   // opened again, quietly
    expect(screen.queryByText("This workbook changed since you opened it.")).toBeNull();
  });

  test("taking in a change quietly leaves the person typing where they were", async () => {
    const a = { ...api({ editor: true, url: "https://office.test/sheets/", name: "b.xlsx" }), sheetsVersion: vi.fn(async () => ({ version: "abc123" })) };
    const { posted, frame, doc } = await opened(a);
    say("https://office.test", frame.contentWindow, { type: "loaded", doc });
    const box = document.createElement("textarea");
    document.body.appendChild(box);
    box.focus();
    a.sheetsVersion.mockResolvedValue({ version: "v7" });
    (a.sheetsOpen as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ ...OPENED, version: "v7" });
    act(() => { window.dispatchEvent(new Event("focus")); });
    await waitFor(() => expect(posted.some(([m]) => (m as { doc?: string }).doc === "b.xlsx@v7")).toBe(true));
    expect(document.activeElement).toBe(box);
    frame.focus();   // the editor takes focus as the workbook loads
    expect(document.activeElement).toBe(frame);
    say("https://office.test", frame.contentWindow, { type: "loaded", doc: doc.replace("abc123", "v7") });
    await waitFor(() => expect(document.activeElement).toBe(box));
    box.remove();
  });

  test("with changes not yet saved, a change made elsewhere shows the bar instead", async () => {
    const a = { ...api({ editor: true, url: "https://office.test/sheets/", name: "b.xlsx" }), sheetsVersion: vi.fn(async () => ({ version: "v7" })) };
    const { frame, doc } = await opened(a);
    say("https://office.test", frame.contentWindow, { type: "loaded", doc });
    say("https://office.test", frame.contentWindow, { type: "dirty", doc, dirty: true });
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(await screen.findByText("This workbook changed since you opened it.")).toBeTruthy();
    expect(a.sheetsOpen).toHaveBeenCalledTimes(1);
  });
});

describe("the agent's edits in Cycls Sheets", () => {
  const types = (posted: Array<[unknown, string]>) => posted.map(([m]) => (m as { type: string }).type);
  const last = (posted: Array<[unknown, string]>, type: string) =>
    [...posted].reverse().find(([m]) => (m as { type: string }).type === type)?.[0] as Record<string, unknown> | undefined;
  async function opened(a: OfficeEditorApi, live = false) {
    const view = render(<SheetsEditorView url="https://office.test/sheets/" path="b.xlsx" name="b.xlsx" api={a} live={live} />);
    const posted: Array<[unknown, string]> = [];
    const frame = frameWith(posted);
    await waitFor(() => expect(a.sheetsOpen).toHaveBeenCalled());
    say("https://office.test", frame.contentWindow, { type: "ready", protocol: 1 });
    await waitFor(() => expect(types(posted)).toContain("load"));
    const doc = (last(posted, "load") as { doc: string }).doc;
    say("https://office.test", frame.contentWindow, { type: "loaded", doc });
    return { posted, frame, doc, view };
  }
  const command = (detail: Record<string, unknown>) => act(() => {
    window.dispatchEvent(new CustomEvent("cycls:sheets-command", { detail: { path: "b.xlsx", reload: false, ...detail } }));
  });

  test("while the agent works the editor is read-only under a banner, and editable again after", async () => {
    const a = api({ editor: true, url: "https://office.test/sheets/", name: "b.xlsx" });
    const { posted, view } = await opened(a, true);
    expect(last(posted, "load")).toMatchObject({ readonly: true });
    expect(last(posted, "readonly")).toMatchObject({ readonly: true });
    expect(screen.getByTestId("sheets-live")).toBeTruthy();
    command({ mutations: [], intent: "Totals added" });
    expect(await screen.findByText(/Totals added/)).toBeTruthy();

    view.rerender(<SheetsEditorView url="https://office.test/sheets/" path="b.xlsx" name="b.xlsx" api={a} live={false} />);
    await waitFor(() => expect(last(posted, "readonly")).toMatchObject({ readonly: false }));
    expect(screen.queryByTestId("sheets-live")).toBeNull();
  });

  test("an edit is replayed in the editor; once applied, the next save bases on the agent's version", async () => {
    const a = api({ editor: true, url: "https://office.test/sheets/", name: "b.xlsx" });
    const { posted, frame, doc } = await opened(a);
    const mutations = [{ id: "sheet.mutation.set-range-values", params: { unitId: "book" } }];
    command({ mutations, version: "agent1" });
    command({ path: "other.xlsx", mutations, version: "x" });    // another file's: not this editor's
    const sent = posted.filter(([m]) => (m as { type: string }).type === "command");
    expect(sent).toHaveLength(1);
    expect(sent[0][0]).toMatchObject({ doc, mutations });
    say("https://office.test", frame.contentWindow, { type: "applied", doc, id: (sent[0][0] as { id: string }).id, ok: true });
    say("https://office.test", frame.contentWindow, { type: "saved", doc, id: "1", snapshot: { sheetOrder: ["s1"] } });
    await waitFor(() => expect(a.sheetsSave).toHaveBeenCalledWith("b.xlsx", "agent1", { snapshot: { sheetOrder: ["s1"] }, ops: [] }, false));
  });

  test("an edit that does not replay, or one sent to reload, reopens the saved file", async () => {
    const a = api({ editor: true, url: "https://office.test/sheets/", name: "b.xlsx" });
    const { posted, frame, doc } = await opened(a);
    expect(a.sheetsOpen).toHaveBeenCalledTimes(1);
    command({ mutations: [{ id: "sheet.mutation.x", params: {} }], version: "agent1" });
    const id = (last(posted, "command") as { id: string }).id;
    say("https://office.test", frame.contentWindow, { type: "applied", doc, id, ok: false });
    await waitFor(() => expect(a.sheetsOpen).toHaveBeenCalledTimes(2));
    command({ mutations: [], reload: true });
    await waitFor(() => expect(a.sheetsOpen).toHaveBeenCalledTimes(3));
  });

  test("what the person selects is offered to the composer, the sheet as its page", async () => {
    const a = api({ editor: true, url: "https://office.test/sheets/", name: "b.xlsx" });
    const { frame, doc, view } = await opened(a);
    say("https://office.test", frame.contentWindow, { type: "selection", doc, sheet: "الميزانية",
      ranges: [{ a1: "B8:E8" }, { a1: "B4", text: "47,000.00" }, { nope: 1 }] });
    expect(designSelection("b.xlsx")).toEqual({ path: "b.xlsx", frame: null, page: "الميزانية",
      nodes: [{ name: "B8:E8", type: "cells" }, { name: "B4", type: "cell", text: "47,000.00" }] });
    say("https://office.test", frame.contentWindow, { type: "selection", doc: "other@v", sheet: "x", ranges: [{ a1: "A1" }] });
    expect(designSelection("b.xlsx")?.page).toBe("الميزانية");     // another document's: not heard
    view.unmount();
    expect(designSelection("b.xlsx")).toBeNull();                   // closed: nothing selected there
  });

  test("before a message is sent, an open editor saves what is unsaved", async () => {
    const a = api({ editor: true, url: "https://office.test/sheets/", name: "b.xlsx" });
    const { posted, frame } = await opened(a);
    let done: boolean | undefined;
    void flushAllSheetsEditors(2000).then((ok) => { done = ok; });
    await waitFor(() => expect(types(posted)).toContain("flush"));
    expect(done).toBeUndefined();
    say("https://office.test", frame.contentWindow, { type: "flushed", id: (last(posted, "flush") as { id: string }).id, ok: true });
    await waitFor(() => expect(done).toBe(true));
  });
});
