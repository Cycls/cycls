import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, cleanup, screen, fireEvent } from "@testing-library/react";
import { SharedView, shareOffice } from "../src/components/shared-view";
import { getThemeMode } from "../src/lib/utils";

// A shared page's way in: "Sign in" for a visitor (the sign-in page), "Go to <agent>" once signed in, and no
// theme toggle, since a shared page follows the system.

beforeEach(() => {
  window.history.pushState({}, "", "/shared/u/tok1");
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));   // the share stays loading: the bar is what's tested
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.pushState({}, "", "/"); });

describe("the shared page's bar", () => {
  it("offers a visitor the sign-in page", () => {
    const onSignIn = vi.fn();
    render(<SharedView agent="Super" onSignIn={onSignIn} />);
    fireEvent.click(screen.getByText("Sign in"));
    expect(onSignIn).toHaveBeenCalledOnce();
    expect(screen.queryByLabelText("Toggle theme")).toBeNull();
  });

  it("leads a signed-in reader to the agent", () => {
    render(<SharedView agent="Super" signedIn onSignIn={() => {}} />);
    expect(screen.getByText("Go to Super").closest("a")?.getAttribute("href")).toBe("/");
    expect(screen.queryByText("Sign in")).toBeNull();
  });

  it("follows the system theme, whatever the app saved", () => {
    localStorage.setItem("cycls_theme", "dark");
    expect(getThemeMode()).toBe("system");
    window.history.pushState({}, "", "/");
    expect(getThemeMode()).toBe("dark");
    localStorage.removeItem("cycls_theme");
  });
});

describe("a shared workbook or document", () => {
  it("opens in the owner's editor over the share, view only", async () => {
    const asked: string[] = [];
    const get = vi.fn(async (rest: string) => {
      asked.push(rest);
      return new Response(JSON.stringify(rest.includes("/open") ? { version: "v1", snapshot: {}, notices: [] } : { editor: true }),
                          { headers: { "X-Modified": "2026-11-01T10:00:00Z" } });
    });
    const api = shareOffice(get);
    expect(api.readonly).toBe(true);
    expect(await api.sheets("reports/الأرباح.xlsx")).toEqual({ editor: true });
    expect((await api.docsOpen!("memo.docx")).modified).toBe("2026-11-01T10:00:00Z");
    expect(asked).toEqual([`office/sheets?path=${encodeURIComponent("reports/الأرباح.xlsx")}`, "office/docs/open?path=memo.docx"]);
    await expect(api.sheetsSave("b.xlsx", "v1", { snapshot: {}, ops: [] })).rejects.toThrow("view only");
    expect(api.sheetsVersion).toBeUndefined();   // nothing polls the owner's file
  });
});
