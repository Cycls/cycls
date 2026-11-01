// Small file-kind icons for office files: a green sheet for spreadsheets, a blue page for documents.
// Our own drawings (a grid, ruled lines), not the Office logos.

export function SheetGlyph({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" focusable="false">
      <rect x="2" y="2" width="20" height="20" rx="5" fill="#16A34A" />
      <rect x="5.5" y="6" width="13" height="12" rx="1.6" fill="#FFFFFF" />
      <rect x="5.5" y="6" width="13" height="3.4" rx="1.4" fill="#BBF7D0" />
      <path d="M5.5 9.4h13M5.5 13.7h13M10.2 6v12M14.4 6v12" stroke="#16A34A" strokeWidth="1.2" fill="none" />
    </svg>
  );
}

export function DocGlyph({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" focusable="false">
      <rect x="2" y="2" width="20" height="20" rx="5" fill="#2563EB" />
      <rect x="6.5" y="5.5" width="11" height="13" rx="1.6" fill="#FFFFFF" />
      <path d="M8.8 9h6.4M8.8 11.8h6.4M8.8 14.6h4.2" stroke="#2563EB" strokeWidth="1.3" strokeLinecap="round" fill="none" />
    </svg>
  );
}

const SHEET_EXTS = new Set(["xlsx", "xlsm", "xls", "ods", "csv", "tsv"]);
const DOC_EXTS = new Set(["docx", "doc", "odt", "rtf"]);

/** The office glyph for a file name, or null when it is not an office file. */
export function officeGlyphFor(name: string, className?: string) {
  const ext = name.toLowerCase().split(".").pop() ?? "";
  if (SHEET_EXTS.has(ext)) return <SheetGlyph className={className} />;
  if (DOC_EXTS.has(ext)) return <DocGlyph className={className} />;
  return null;
}
