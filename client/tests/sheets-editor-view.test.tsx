// Cycls Sheets in the canvas: a file opens in the editor only when the workspace has it; the editor is
// framed with the theme and language, and only its own origin and frame are heard.
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { OfficeEditorApi } from "../src/hooks/use-files";
import { SheetsEditorView, SheetsOrPreview } from "../src/components/sheets-editor-view";

afterEach(cleanup);

const api = (answer: Awaited<ReturnType<OfficeEditorApi["sheets"]>> | Error): OfficeEditorApi => ({
  sheets: vi.fn(async () => {
    if (answer instanceof Error) throw answer;
    return answer;
  }),
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

  test("a workspace with Sheets frames the editor with the theme and language", async () => {
    const a = api({ editor: true, url: "https://office.test/sheets/", name: "b.xlsx" });
    render(<SheetsOrPreview path="b.xlsx" name="b.xlsx" api={a} preview={<p>preview</p>} />);
    await waitFor(() => expect(document.querySelector("iframe")).not.toBeNull());
    const src = new URL(document.querySelector("iframe")!.getAttribute("src")!);
    expect(src.origin + src.pathname).toBe("https://office.test/sheets/");
    expect(src.searchParams.get("embed")).toBe("cycls");
    expect(["light", "dark"]).toContain(src.searchParams.get("theme"));
    expect(a.sheets).toHaveBeenCalledWith("b.xlsx");
    expect(screen.queryByText("preview")).toBeNull();
  });

  test("only the editor's own origin and frame are heard; replies go to that origin only", async () => {
    render(<SheetsEditorView url="https://office.test/sheets/" path="b.xlsx" name="b.xlsx" />);
    const frame = document.querySelector("iframe")!;
    const posted: Array<[unknown, string]> = [];
    Object.defineProperty(frame, "contentWindow", {
      value: { postMessage: (m: unknown, o: string) => posted.push([m, o]) },
      configurable: true,
    });
    const send = (origin: string, source: unknown) => act(() => {
      window.dispatchEvent(new MessageEvent("message", { origin, source: source as Window, data: { source: "cycls-sheets", type: "ready" } }));
    });
    send("https://evil.test", frame.contentWindow);
    send("https://office.test", window);
    expect(posted).toHaveLength(0);
    send("https://office.test", frame.contentWindow);
    await waitFor(() => expect(posted.length).toBeGreaterThan(0));
    expect(posted.every(([, origin]) => origin === "https://office.test")).toBe(true);
    expect(posted.map(([m]) => (m as { type: string }).type).sort()).toEqual(["locale", "theme"]);
  });
});
