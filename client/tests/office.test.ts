import { describe, it, expect } from "vitest";
import { isOffice, isSpreadsheet, isDocx, isPresentation, isRenderable, isPdf } from "../src/components/canvas-utils";

// Office files render natively on the canvas by type rather than as one flat
// PDF: spreadsheets → interactive grid, .docx → formatted HTML (docx-preview),
// presentations → slide viewer. What's left (older/other word formats, flat-XML
// ODS, epub) still converts to PDF. These predicates decide the routing; every
// office file must also read as renderable so a click opens the canvas.
describe("office document classification", () => {
  it("routes spreadsheets to the interactive grid (csv/tsv and binary alike)", () => {
    for (const p of ["data.csv", "data.tsv", "book.xlsx", "book.xls", "book.xlsm", "calc.ods"])
      expect(isSpreadsheet(p), p).toBe(true);
    // Flat-XML ODS stays on the PDF path — SheetJS doesn't read it.
    expect(isSpreadsheet("calc.fods")).toBe(false);
    expect(isOffice("calc.fods")).toBe(true);
  });

  it("routes .docx to the native document view, other word formats to PDF", () => {
    expect(isDocx("report.docx")).toBe(true);
    expect(isDocx("a/b/report.DOCX")).toBe(true);
    for (const p of ["old.doc", "book.odt", "notes.rtf", "flat.fodt"]) {
      expect(isDocx(p), p).toBe(false);
      expect(isOffice(p), p).toBe(true);   // PDF fallback
    }
  });

  it("routes presentations to the slide viewer", () => {
    for (const p of ["deck.pptx", "a/b/deck.ppt", "slides.odp", "flat.fodp"])
      expect(isPresentation(p), p).toBe(true);
    expect(isPresentation("report.docx")).toBe(false);
    expect(isPresentation("sheet.xlsx")).toBe(false);
  });

  it("keeps the render classes disjoint — a file takes exactly one path", () => {
    // Spreadsheets, .docx and presentations are NOT in the PDF-fallback class.
    for (const p of ["book.xlsx", "report.docx", "deck.pptx", "data.csv"])
      expect(isOffice(p), p).toBe(false);
    // The PDF fallback is the remainder.
    for (const p of ["old.doc", "notes.rtf", "manual.epub", "calc.fods"])
      expect(isOffice(p), p).toBe(true);
  });

  it("makes every office file renderable (a click opens the canvas)", () => {
    for (const p of ["report.docx", "deck.pptx", "sheet.xlsx", "old.doc", "old.ppt",
                     "old.xls", "book.odt", "slides.odp", "calc.ods", "notes.rtf", "manual.epub"])
      expect(isRenderable(p), p).toBe(true);
    // The server's `kind` still wins when present: office is renderable, opaque is not.
    expect(isRenderable("mystery.bin", "office")).toBe(true);
    expect(isRenderable("report.docx", "opaque")).toBe(false);
  });

  it("keeps PDFs on the direct PDF path (not office conversion)", () => {
    expect(isPdf("plan.pdf")).toBe(true);
    expect(isOffice("plan.pdf")).toBe(false);
    expect(isDocx("plan.pdf")).toBe(false);
    expect(isPresentation("plan.pdf")).toBe(false);
    expect(isSpreadsheet("plan.pdf")).toBe(false);
  });
});
