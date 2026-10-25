// Cycls Docs in the canvas: the Sheets view given product="docs" — a .docx opens in the editor only when the
// workspace has it, talks on its own channel, saves through the docs calls, and a document with tracked
// changes opens view only.
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { OfficeEditorApi, SheetsOpened } from "../src/hooks/use-files";
import { DocsOrPreview, SheetsEditorView } from "../src/components/sheets-editor-view";

afterEach(cleanup);

const OPENED: SheetsOpened = {
  version: "d1",
  modified: new Date().toISOString(),
  snapshot: { id: "doc", body: { dataStream: "Hello\r\n" } },
  notices: [],
};

const api = (answer: Awaited<ReturnType<NonNullable<OfficeEditorApi["docs"]>>>, opened: SheetsOpened = OPENED): OfficeEditorApi => ({
  sheets: vi.fn(async () => ({ editor: false as const, reason: "off" })),
  sheetsOpen: vi.fn(async () => { throw new Error("not a workbook"); }),
  sheetsSave: vi.fn(async () => ({ version: "x", unchanged: true })),
  pdf: vi.fn(async () => "blob:pdf"),
  docs: vi.fn(async () => answer),
  docsOpen: vi.fn(async () => opened),
  docsSave: vi.fn(async () => ({ version: "d2", unchanged: false })),
});

function frameWith(posted: Array<[unknown, string]>) {
  const frame = document.querySelector("iframe")!;
  Object.defineProperty(frame, "contentWindow", {
    value: { postMessage: (m: unknown, o: string) => posted.push([m, o]) },
    configurable: true,
  });
  return frame;
}

const say = (source: unknown, data: Record<string, unknown>, channel = "cycls-docs") => act(() => {
  window.dispatchEvent(new MessageEvent("message", { origin: "https://office.test", source: source as Window, data: { source: channel, ...data } }));
});
const types = (posted: Array<[unknown, string]>) => posted.map(([m]) => (m as { type: string }).type);

describe("Cycls Docs in the canvas", () => {
  test("a workspace without Docs keeps the preview", async () => {
    render(<DocsOrPreview path="r.docx" name="r.docx" api={api({ editor: false, reason: "off" })} preview={<p>preview</p>} />);
    expect(await screen.findByText("preview")).toBeTruthy();
    expect(document.querySelector("iframe")).toBeNull();
  });

  test("a host without the docs calls keeps the preview without asking", async () => {
    const { docs: _d, docsOpen: _o, docsSave: _s, ...sheetsOnly } = api({ editor: true, url: "https://office.test/docs/", name: "r.docx" });
    render(<DocsOrPreview path="r.docx" name="r.docx" api={sheetsOnly} preview={<p>preview</p>} />);
    expect(await screen.findByText("preview")).toBeTruthy();
  });

  test("the editor is framed, hears only its own channel, gets the document and saves through the docs calls", async () => {
    const a = api({ editor: true, url: "https://office.test/docs/", name: "r.docx" });
    render(<DocsOrPreview path="notes/r.docx" name="r.docx" api={a} onDownload={() => {}} preview={<p>preview</p>} />);
    await waitFor(() => expect(document.querySelector("iframe")).not.toBeNull());
    expect(new URL(document.querySelector("iframe")!.getAttribute("src")!).pathname).toBe("/docs/");
    expect(document.querySelector('[data-testid="docs-editor"]')).not.toBeNull();
    const posted: Array<[unknown, string]> = [];
    const frame = frameWith(posted);
    await waitFor(() => expect(a.docsOpen).toHaveBeenCalledWith("notes/r.docx"));
    say(frame.contentWindow, { type: "ready", protocol: 1 }, "cycls-sheets");    // the other editor's channel
    expect(posted).toHaveLength(0);
    say(frame.contentWindow, { type: "ready", protocol: 1, features: ["load", "save"] });
    await waitFor(() => expect(types(posted)).toContain("load"));
    const load = posted.find(([m]) => (m as { type: string }).type === "load")![0] as Record<string, unknown>;
    expect(load).toMatchObject({ target: "cycls-docs", snapshot: OPENED.snapshot, readonly: false });

    say(frame.contentWindow, { type: "saved", doc: load.doc, id: "1", snapshot: { body: { dataStream: "Hi\r\n" } } });
    await waitFor(() => expect(a.docsSave).toHaveBeenCalledWith("notes/r.docx", "d1", { snapshot: { body: { dataStream: "Hi\r\n" } }, ops: [] }, false));
    expect(a.sheetsSave).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Open/ }));
    expect(screen.getByRole("menuitem", { name: /Word/ })).toBeTruthy();
  });

  test("a save carries the editor's trail to the server (lines only, at most 60)", async () => {
    const a = api({ editor: true, url: "https://office.test/docs/", name: "r.docx" });
    render(<SheetsEditorView url="https://office.test/docs/" path="r.docx" name="r.docx" api={a} product="docs" />);
    const posted: Array<[unknown, string]> = [];
    const frame = frameWith(posted);
    await waitFor(() => expect(a.docsOpen).toHaveBeenCalled());
    say(frame.contentWindow, { type: "ready", protocol: 1 });
    await waitFor(() => expect(types(posted)).toContain("load"));
    const doc = (posted.find(([m]) => (m as { type: string }).type === "load")![0] as { doc: string }).doc;
    const trail = ["0.0 load r.docx@d1", "4.2 operation.set-selections 12-12", 7, "4.3 mutation.rich-text-editing r12 i1"];
    say(frame.contentWindow, { type: "saved", doc, id: "1", snapshot: { body: { dataStream: "x\r\n" } }, trail });
    await waitFor(() => expect(a.docsSave).toHaveBeenCalledWith("r.docx", "d1", { snapshot: { body: { dataStream: "x\r\n" } }, ops: [] }, false,
      ["0.0 load r.docx@d1", "4.2 operation.set-selections 12-12", "4.3 mutation.rich-text-editing r12 i1"]));
  });

  test("the agent's Word edit opens the new file at once, its changed paragraphs marked and the view kept", async () => {
    const a = api({ editor: true, url: "https://office.test/docs/", name: "r.docx" });
    render(<SheetsEditorView url="https://office.test/docs/" path="r.docx" name="r.docx" api={a} product="docs" live />);
    const posted: Array<[unknown, string]> = [];
    const frame = frameWith(posted);
    await waitFor(() => expect(a.docsOpen).toHaveBeenCalledTimes(1));
    say(frame.contentWindow, { type: "ready", protocol: 1 });
    await waitFor(() => expect(types(posted)).toContain("load"));
    const loads = () => posted.filter(([m]) => (m as { type: string }).type === "load").map(([m]) => m as Record<string, unknown>);
    expect(loads()[0].keepView).toBeUndefined();

    // the file open already: nothing to do
    act(() => { window.dispatchEvent(new CustomEvent("cycls:docs-command", { detail: { path: "r.docx", version: "d1", touched: ["p1"] } })); });
    expect(a.docsOpen).toHaveBeenCalledTimes(1);

    (a.docsOpen as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ ...OPENED, version: "d2" });
    act(() => { window.dispatchEvent(new CustomEvent("cycls:docs-command", { detail: { path: "r.docx", version: "d2", touched: ["p1", "p7"], intent: "Tighten the summary" } })); });
    await waitFor(() => expect(loads()).toHaveLength(2));
    expect(loads()[1]).toMatchObject({ readonly: true, keepView: true, marks: ["p1", "p7"] });
    expect(String(loads()[1].doc)).toContain("@d2");
    expect(await screen.findByText(/Tighten the summary/)).toBeTruthy();

    // another file's edit is not this editor's
    act(() => { window.dispatchEvent(new CustomEvent("cycls:docs-command", { detail: { path: "other.docx", version: "x", touched: [] } })); });
    expect(a.docsOpen).toHaveBeenCalledTimes(2);
  });

  test("a document with tracked changes opens view only", async () => {
    const a = api({ editor: true, url: "https://office.test/docs/", name: "r.docx" }, { ...OPENED, readonly: true });
    render(<SheetsEditorView url="https://office.test/docs/" path="r.docx" name="r.docx" api={a} product="docs" />);
    const posted: Array<[unknown, string]> = [];
    const frame = frameWith(posted);
    await waitFor(() => expect(a.docsOpen).toHaveBeenCalled());
    say(frame.contentWindow, { type: "ready", protocol: 1 });
    await waitFor(() => expect(types(posted)).toContain("load"));
    expect((posted.find(([m]) => (m as { type: string }).type === "load")![0] as { readonly: boolean }).readonly).toBe(true);
    expect(await screen.findByText("View only")).toBeTruthy();
  });
});
