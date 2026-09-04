import { describe, it, expect } from "vitest";
import { workspacePath, linkifyPaths } from "../src/components/parts/text-part";

describe("workspace links", () => {
  it("opens every shape the model writes as one path", () => {
    for (const h of ["reports/report.md", "./reports/report.md", "/workspace/reports/report.md", "workspace/reports/report.md",
                     "file:///workspace/reports/report.md", "sandbox:/workspace/reports/report.md",
                     `${location.origin}/files/reports/report.md`, "reports/my%20report.md".replace("my%20report", "report")])
      expect(workspacePath(h)).toBe("reports/report.md");
  });

  it("leaves the web alone", () => {
    expect(workspacePath("https://example.com/files/x.md")).toBeNull();
    expect(workspacePath("mailto:a@b.c")).toBeNull();
    expect(workspacePath("#top")).toBeNull();
  });

  it("links bare paths in prose, not inside code or existing links", () => {
    const tree = { type: "root", children: [
      { type: "paragraph", children: [{ type: "text", value: "Saved to reports/report.md, see site.html or file:///workspace/a.md." }] },
      { type: "paragraph", children: [{ type: "inlineCode", value: "x.md" }, { type: "link", url: "a.md", children: [{ type: "text", value: "b.md" }] }] },
    ] };
    linkifyPaths(tree);
    const first = tree.children[0].children as { type: string; url?: string; value?: string }[];
    expect(first.map((n) => n.type)).toEqual(["text", "link", "text", "link", "text", "link", "text"]);
    expect(first[1].url).toBe("reports/report.md");
    expect(first[3].url).toBe("site.html");
    expect(first[5].url).toBe("a.md");   // normalised, so the sanitiser keeps the href
    expect(tree.children[1].children.map((n) => n.type)).toEqual(["inlineCode", "link"]);
  });
});
