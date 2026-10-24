// Cycls Sheets in the canvas: a file opens in the editor only when the workspace has it; the editor is
// framed with the theme and language, gets the workbook once it says it is ready, and only its own
// origin and frame are heard.
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { OfficeEditorApi, SheetsOpened } from "../src/hooks/use-files";
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
