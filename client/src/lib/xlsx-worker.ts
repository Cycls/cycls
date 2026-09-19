/// <reference lib="webworker" />
// Parses spreadsheets off the main thread. Isolating the parser keeps the UI
// responsive and contains a malicious/huge file (a crash kills the worker, not
// the app).
//
// SECURITY: pinned to the patched SheetJS CDN build (0.20.3) — not the stale
// npm `xlsx` (0.18.5, which carries prototype-pollution/ReDoS advisories).
// Parsing also runs here in a Worker as defense-in-depth.
import * as XLSX from "xlsx";

const ROW_CAP = 300;   // rows rendered per sheet
const COL_CAP = 50;    // columns rendered per sheet

let wb: XLSX.WorkBook | null = null;

self.onmessage = (e: MessageEvent) => {
  const msg = e.data || {};
  try {
    if (msg.buffer) {
      // sheetRows caps PARSING itself (memory/CPU) — the real guard against
      // huge files. +1 so a sheet with more rows reads as truncated.
      wb = XLSX.read(new Uint8Array(msg.buffer), { type: "array", sheetRows: ROW_CAP + 1 });
      const rtl = !!(wb.Workbook?.Views?.[0] as { RTL?: boolean } | undefined)?.RTL;
      self.postMessage({ type: "init", sheetNames: wb.SheetNames, rtl });
      return;
    }
    if (typeof msg.sheet === "number" && wb) {
      const ws = wb.Sheets[wb.SheetNames[msg.sheet]];
      let rowsTrunc = false, colsTrunc = false;
      if (ws && ws["!ref"]) {
        const r = XLSX.utils.decode_range(ws["!ref"]);
        if (r.e.r - r.s.r + 1 > ROW_CAP) { r.e.r = r.s.r + ROW_CAP - 1; rowsTrunc = true; }
        if (r.e.c - r.s.c + 1 > COL_CAP) { r.e.c = r.s.c + COL_CAP - 1; colsTrunc = true; }
        ws["!ref"] = XLSX.utils.encode_range(r);
      }
      // sheet_to_html escapes cell content and preserves merged cells.
      const html = ws ? XLSX.utils.sheet_to_html(ws) : "";
      self.postMessage({ type: "sheet", index: msg.sheet, html, rowsTrunc, colsTrunc });
    }
  } catch (err) {
    self.postMessage({ type: "error", error: String(err) });
  }
};
