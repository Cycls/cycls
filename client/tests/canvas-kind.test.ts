import { describe, it, expect } from "vitest";
import { fileKind } from "../src/components/canvas";
import { isHtml, isMd, isPdf, codeLang, ext, editWorkingPath, liveApps, takesKeysOnHover } from "../src/components/canvas-utils";

// An app's canvas tab is titled by its manifest, so the display name has no
// extension. Every renderer check must therefore key off the path — keyed off
// the name, an app falls through to the "no preview for this file type" card.
describe("fileKind", () => {
  const app = { path: "apps/burnup/index.html", name: "Sales Portfolio" };

  it("resolves an app to its entry, not its title", () => {
    expect(fileKind(app)).toBe("apps/burnup/index.html");
    expect(isHtml(fileKind(app))).toBe(true);
    expect(isHtml(app.name)).toBe(false);   // the bug this guards
  });

  it("leaves ordinary files unchanged", () => {
    for (const [path, check] of [
      ["reports/status.md", isMd],
      ["reports/plan.pdf", isPdf],
      ["notes/index.html", isHtml],
    ] as const) {
      expect(check(fileKind({ path, name: path.split("/").pop()! })), path).toBe(true);
    }
    expect(codeLang(fileKind({ path: "src/main.ts", name: "main.ts" }))).toBeTruthy();
  });

  it("still yields an extension for the unsupported-file card", () => {
    expect(ext(fileKind({ path: "a/b/report.docx", name: "report.docx" }))).toBe("docx");
    expect(ext(fileKind(app))).toBe("html");
  });

  it("falls back to the name when there is no path", () => {
    expect(fileKind({ path: "", name: "loose.md" })).toBe("loose.md");
  });
});

// The canvas "working" trigger: a live edit step names its target either in
// the finished step label or inside the partial-JSON arg stream. Only
// deliverable extensions open the pane — helper scripts never do.
describe("editWorkingPath", () => {
  it("reads the path from the finished step label", () => {
    expect(editWorkingPath("report.html", undefined)).toBe("report.html");
    expect(editWorkingPath("notes/plan.md", undefined)).toBe("notes/plan.md");
  });

  it("extracts the path from partial streamed args", () => {
    expect(editWorkingPath("", '{"path": "site.html", "command": "create", "file_text": "<!doct'))
      .toBe("site.html");
    expect(editWorkingPath(undefined, '{"path": "data.csv"')).toBe("data.csv");
  });

  it("ignores non-deliverable files and absent paths", () => {
    expect(editWorkingPath("analyze.py", undefined)).toBeNull();
    expect(editWorkingPath("", '{"path": "run.sh", "command"')).toBeNull();
    expect(editWorkingPath("", '{"command": "create"')).toBeNull();
    expect(editWorkingPath(undefined, undefined)).toBeNull();
  });
});

// Switching tabs mustn't restart an app: the canvas keeps the last few mounted, hidden.
describe("liveApps", () => {
  const isApp = (p: string) => p.startsWith("apps/");
  const open = ["apps/studio/index.html", "renders/a.png", "apps/sales/index.html", "apps/x/index.html", "apps/y/index.html"];

  it("keeps apps once shown, most recent last, and leaves files out", () => {
    let live: string[] = [];
    live = liveApps(live, "apps/studio/index.html", isApp, open);
    live = liveApps(live, "renders/a.png", isApp, open);
    expect(live).toEqual(["apps/studio/index.html"]);           // still alive behind the render
    live = liveApps(live, "apps/sales/index.html", isApp, open);
    expect(live).toEqual(["apps/studio/index.html", "apps/sales/index.html"]);
  });

  it("drops closed tabs and the least recent past the limit, and is stable when nothing changes", () => {
    let live = ["apps/studio/index.html", "apps/sales/index.html", "apps/x/index.html"];
    expect(liveApps(live, "apps/x/index.html", isApp, open)).toBe(live);
    live = liveApps(live, "apps/y/index.html", isApp, open);
    expect(live).toEqual(["apps/sales/index.html", "apps/x/index.html", "apps/y/index.html"]);
    expect(liveApps(live, "renders/a.png", isApp, open.filter((p) => p !== "apps/x/index.html")))
      .toEqual(["apps/sales/index.html", "apps/y/index.html"]);
  });
});

// An app frame the pointer enters takes the keyboard — never from someone typing.
describe("takesKeysOnHover", () => {
  it("takes the keys from nothing in particular, never from a field being typed in", () => {
    expect(takesKeysOnHover(null)).toBe(true);
    expect(takesKeysOnHover(document.body)).toBe(true);
    expect(takesKeysOnHover(document.createElement("button"))).toBe(true);
    for (const tag of ["input", "textarea", "select"]) expect(takesKeysOnHover(document.createElement(tag))).toBe(false);
    const editor = document.createElement("div");
    editor.setAttribute("contenteditable", "true");
    expect(takesKeysOnHover(editor)).toBe(false);
  });
});
