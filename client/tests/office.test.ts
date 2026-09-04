import { describe, it, expect } from "vitest";
import { isOffice, isSpreadsheet, isRenderable, isPdf } from "../src/components/canvas-utils";

// Office documents (Word/PowerPoint/Excel) can't render in a browser, so the
// canvas converts them to PDF on the server and shows that. These predicates
// decide the routing: isOffice marks the convert-to-PDF class, and the file
// must read as renderable so a click opens the canvas instead of downloading.
describe("office document classification", () => {
  const office = ["report.docx", "a/b/deck.pptx", "sheet.xlsx", "old.doc",
                  "old.ppt", "old.xls", "book.odt", "slides.odp", "calc.ods",
                  "notes.rtf", "manual.epub"];

  it("recognises Office documents", () => {
    for (const p of office) expect(isOffice(p), p).toBe(true);
  });

  it("does not treat non-Office files as Office", () => {
    for (const p of ["a.pdf", "b.csv", "c.tsv", "d.md", "e.png", "f.txt", "g.numbers"])
      expect(isOffice(p), p).toBe(false);
  });

  it("routes binary spreadsheets to Office (PDF), leaving csv/tsv on the grid", () => {
    expect(isSpreadsheet("data.csv")).toBe(true);
    expect(isSpreadsheet("data.tsv")).toBe(true);
    // xls/xlsx/ods moved from the in-browser grid to Office → PDF.
    for (const p of ["book.xlsx", "book.xls", "book.ods"]) {
      expect(isSpreadsheet(p), p).toBe(false);
      expect(isOffice(p), p).toBe(true);
    }
  });

  it("makes Office files renderable (a click opens the canvas)", () => {
    for (const p of office) expect(isRenderable(p), p).toBe(true);
    // The server's `kind` still wins when present: an office kind is renderable,
    // opaque is not — independent of the extension table.
    expect(isRenderable("mystery.bin", "office")).toBe(true);
    expect(isRenderable("report.docx", "opaque")).toBe(false);
  });

  it("keeps PDFs on the direct PDF path (not Office conversion)", () => {
    expect(isPdf("plan.pdf")).toBe(true);
    expect(isOffice("plan.pdf")).toBe(false);
  });
});
