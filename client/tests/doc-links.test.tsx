import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup, screen, act, fireEvent } from "@testing-library/react";
import { CanvasDoc } from "../src/components/canvas";
import { workspacePath } from "../src/components/parts/text-part";

// A link in a markdown document to another workspace file opens that file in the canvas, read as markdown means
// it: from the document's folder, or from the workspace root when it says so.

afterEach(cleanup);
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

describe("a document's links", () => {
  it("are from its folder, unless they start from the workspace root", () => {
    expect(workspacePath("appendix.md", "docs/")).toBe("docs/appendix.md");
    expect(workspacePath("./appendix.md", "docs/")).toBe("docs/appendix.md");
    expect(workspacePath("../plan.md", "docs/q3/")).toBe("docs/plan.md");
    expect(workspacePath("my%20notes.md", "docs/")).toBe("docs/my notes.md");
    for (const h of ["/workspace/reports/q3.md", "/reports/q3.md", "file:///workspace/reports/q3.md", `${location.origin}/files/reports/q3.md`])
      expect(workspacePath(h, "docs/")).toBe("reports/q3.md");
    expect(workspacePath("https://example.com/a.md", "docs/")).toBeNull();
  });

  const doc = { path: "docs/plan.md", name: "plan.md" };
  const text = "See [the appendix](appendix.md), [Q3](reports/q3.md) and [the brief](/workspace/brief.md).";

  it("open in the canvas: beside the document, else from the root, as agents write them", async () => {
    const open = vi.fn();
    const readFile = vi.fn(async (p: string) => { if (p === "docs/appendix.md") return "# Appendix"; throw new Error("404"); });
    render(<CanvasDoc file={doc} content={text} error={false} readFile={readFile} onOpenFile={open} />);
    fireEvent.click(screen.getByText("the appendix"));
    await settle();
    expect(open).toHaveBeenLastCalledWith("docs/appendix.md");
    fireEvent.click(screen.getByText("Q3"));   // not beside it: the workspace's reports/
    await settle();
    expect(open).toHaveBeenLastCalledWith("reports/q3.md");
    fireEvent.click(screen.getByText("the brief"));
    await settle();
    expect(open).toHaveBeenLastCalledWith("brief.md");
    expect(readFile).not.toHaveBeenCalledWith("brief.md", true);   // from the root by its own word: nothing to look up
  });

  it("stay links on a shared page, which has no workspace to open them in", () => {
    render(<CanvasDoc file={doc} content={text} error={false} shared />);
    expect(screen.getByText("the appendix").closest("a")!.getAttribute("target")).toBe("_blank");
  });
});
