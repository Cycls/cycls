// Cycls Sheets in the canvas: a file opens in the editor only when the workspace has it; the editor is
// framed with the theme and language, gets the workbook once it says it is ready, and only its own
// origin and frame are heard.
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { OfficeEditorApi, SheetsOpened } from "../src/hooks/use-files";
import { SheetsEditorView, SheetsOrPreview } from "../src/components/sheets-editor-view";

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
    await waitFor(() => expect(a.sheetsSave).toHaveBeenCalledWith("b.xlsx", "abc123", { sheetOrder: ["s1"] }, false));
    await waitFor(() => expect(posted.some(([m]) => (m as { type: string; ok?: boolean }).type === "written" && (m as { ok?: boolean }).ok)).toBe(true));
    expect(await screen.findByText("Saved")).toBeTruthy();

    // The next save names the version the last one made.
    say("https://office.test", frame.contentWindow, { type: "saved", doc, id: "2", snapshot: { sheetOrder: ["s1"], n: 2 } });
    await waitFor(() => expect(a.sheetsSave).toHaveBeenLastCalledWith("b.xlsx", "v2", { sheetOrder: ["s1"], n: 2 }, false));
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
    await waitFor(() => expect(a.sheetsSave).toHaveBeenLastCalledWith("b.xlsx", "abc123", { sheetOrder: ["s1"] }, true));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });
});
