import { describe, it, expect } from "vitest";
import { fileKind } from "../src/components/canvas";
import { isHtml, isMd, isPdf, codeLang, ext } from "../src/components/canvas-utils";

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
