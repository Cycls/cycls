import { describe, it, expect } from "vitest";
import { fileKind } from "../src/components/canvas";
import { isHtml, isMd, isPdf, codeLang, ext, editWorkingPath } from "../src/components/canvas-utils";

// A mini app's canvas tab is titled by its manifest, so the display name has no
// extension. Every renderer check must therefore key off the path — keyed off
// the name, an app falls through to the "no preview for this file type" card.
describe("fileKind", () => {
  const app = { path: "apps/injaz/index.html", name: "Injaz Portfolio" };

  it("resolves a mini app to its entry, not its title", () => {
    expect(fileKind(app)).toBe("apps/injaz/index.html");
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
