import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Icon } from "./icon";
import { LoadingBar } from "./loading-bar";
import { DropdownMenu } from "./files";
import { ShareDialog } from "./share-dialog";
import { TextPart } from "./parts/text-part";
import { HighlightedCode } from "./parts/code-part";
import { isHtml, isMd, isPdf, isImage, isAudio, isVideo, isSpreadsheet, codeLang, saveBlob } from "./canvas-utils";
import { SpreadsheetView } from "./spreadsheet-view";
import { cn } from "../lib/utils";
import { t } from "../lib/i18n";

export interface CanvasFile {
  path: string;
  name: string;
}

// Fetch a file's content for the canvas. pdf → blob URL (native viewer);
// other types → source text. Revokes the blob URL on change/unmount. Pass
// file=null to fetch nothing (e.g. unrenderable file shown as a download card).
export function useFileContent(
  file: CanvasFile | null,
  readFile: (p: string) => Promise<string>,
  openFile: (p: string) => Promise<string>,
) {
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!file) { setContent(null); setError(false); return; }
    let cancelled = false;
    let blobUrl: string | null = null;
    setContent(null);
    setError(false);
    // Binary formats (pdf, images, spreadsheets) need bytes → fetch as a blob
    // URL; text formats fetch source.
    const load = isPdf(file.name) || isImage(file.name) || isAudio(file.name) || isVideo(file.name) || isSpreadsheet(file.name)
      ? openFile(file.path).then((url) => { blobUrl = url; return url; })
      : readFile(file.path);
    load.then((v) => { if (!cancelled) setContent(v); })
        .catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; if (blobUrl) URL.revokeObjectURL(blobUrl); };
  }, [file?.path, file?.name, readFile, openFile]);

  return { content, setContent, error };
}

// Read-only body — renders a loaded file by type. `shared` tightens the html
// sandbox (drop allow-popups) for content that's untrusted to the viewer.
export function CanvasDoc({ file, content, error, shared = false }: {
  file: CanvasFile;
  content: string | null;
  error: boolean;
  shared?: boolean;
}) {
  const lang = codeLang(file.name);
  if (content == null && !error) return <LoadingBar />;
  if (error) {
    return <div className="flex h-full items-center justify-center text-sm text-muted-foreground">Couldn't load this file.</div>;
  }
  if (isHtml(file.name)) {
    return (
      <iframe
        sandbox={shared ? "allow-scripts" : "allow-scripts allow-popups"}
        srcDoc={content ?? ""}
        title={file.name}
        className="h-full w-full border-0 bg-white"
      />
    );
  }
  if (isPdf(file.name)) {
    // Desktop's native inline viewer is the best PDF UX (search, zoom, print).
    // Phones can't EMBED PDFs (iOS iframes render page 1 only) but render them
    // fine on direct navigation — so on small screens the iframe doubles as a
    // first-page preview with an open button on top. Zero dependencies.
    return (
      <div className="relative h-full w-full">
        <iframe src={content ?? ""} title={file.name} className="h-full w-full border-0" />
        <a
          href={content ?? ""}
          target="_blank"
          rel="noopener noreferrer"
          className="sm:hidden absolute bottom-6 left-1/2 -translate-x-1/2 rounded-full border border-border bg-background/90 px-4 py-2 text-sm font-medium text-foreground shadow-lg backdrop-blur transition-colors hover:bg-secondary"
        >
          {t("openInTab")}
        </a>
      </div>
    );
  }
  if (isImage(file.name)) {
    return (
      <div className="flex h-full items-center justify-center overflow-auto p-4">
        <img src={content ?? ""} alt={file.name} className="max-h-full max-w-full object-contain" />
      </div>
    );
  }
  if (isVideo(file.name)) {
    return (
      <div className="flex h-full items-center justify-center bg-black">
        <video src={content ?? ""} controls className="max-h-full max-w-full" />
      </div>
    );
  }
  if (isAudio(file.name)) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <audio src={content ?? ""} controls className="w-full max-w-xl" />
      </div>
    );
  }
  if (isSpreadsheet(file.name)) {
    return content ? <SpreadsheetView url={content} name={file.name} /> : null;
  }
  if (isMd(file.name)) {
    return (
      <div className="h-full overflow-y-auto px-6 py-5 sm:px-8">
        <TextPart text={content ?? ""} />
      </div>
    );
  }
  return (
    <div className="h-full overflow-auto">
      <HighlightedCode code={content ?? ""} language={lang ?? "text"} />
    </div>
  );
}

export function Canvas({ file, onClose, readFile, openFile, writeFile, onShareFile }: {
  file: CanvasFile | null;
  onClose: () => void;
  readFile: (path: string) => Promise<string>;   // authed text fetch (md/html/code source)
  openFile: (path: string) => Promise<string>;    // authed blob URL (pdf / download)
  writeFile: (path: string, text: string) => Promise<void>;  // overwrite (editor)
  onShareFile?: (path: string, audience: string) => Promise<string>;
}) {
  return (
    <AnimatePresence>
      {file && (
        <CanvasPanel key={file.path} file={file} onClose={onClose}
          readFile={readFile} openFile={openFile} writeFile={writeFile} onShareFile={onShareFile} />
      )}
    </AnimatePresence>
  );
}

function CanvasPanel({ file, onClose, readFile, openFile, writeFile, onShareFile }: {
  file: CanvasFile;
  onClose: () => void;
  readFile: (path: string) => Promise<string>;
  openFile: (path: string) => Promise<string>;
  writeFile: (path: string, text: string) => Promise<void>;
  onShareFile?: (path: string, audience: string) => Promise<string>;
}) {
  const { content, setContent, error } = useFileContent(file, readFile, openFile);
  const [menuOpen, setMenuOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const md = isMd(file.name);
  const lang = codeLang(file.name);
  const isText = md || lang != null;   // text-based: editable + copyable

  const copy = () => {
    if (content == null) return;
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const download = () => openFile(file.path).then((url) => saveBlob(url, file.name)).catch(() => {});

  // Open HTML as a standalone page (its own browsing context) — a stable,
  // full-window render that doesn't reflow with the drawer, plus print/PDF.
  const openInTab = () => {
    if (content == null) return;
    window.open(URL.createObjectURL(new Blob([content], { type: "text/html" })), "_blank");
  };

  const startEdit = () => { setDraft(content ?? ""); setEditing(true); };

  const save = async () => {
    setSaving(true);
    try {
      await writeFile(file.path, draft);
      setContent(draft);
      setEditing(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  };

  // Tab inserts two spaces instead of moving focus.
  const onEditorKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== "Tab") return;
    e.preventDefault();
    const el = e.currentTarget;
    const s = el.selectionStart, en = el.selectionEnd;
    setDraft((d) => d.slice(0, s) + "  " + d.slice(en));
    requestAnimationFrame(() => { el.selectionStart = el.selectionEnd = s + 2; });
  };

  const headerBtn = "flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer";

  return (
    <>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.15 }}
        className="fixed inset-0 z-[55] bg-black/30 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <motion.div
        initial={{ x: "100%" }}
        animate={{ x: 0 }}
        exit={{ x: "100%" }}
        transition={{ type: "spring", damping: 25, stiffness: 200 }}
        className={cn(
          "fixed z-[60] rounded-xl border border-border bg-background flex flex-col overflow-hidden",
          expanded ? "inset-2" : "top-1 right-1 bottom-1 w-[calc(100%-0.5rem)] sm:w-[720px] lg:w-[60vw] lg:max-w-[960px]",
        )}
        dir="ltr"
      >
        {/* Header */}
        <div className="flex items-center gap-2 border-b border-border px-4 sm:px-6 py-3">
          <span className="min-w-0 truncate text-sm font-medium text-foreground">{file.name}</span>
          {lang && lang !== "text" && (
            <span className="shrink-0 rounded-md bg-secondary px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">{lang}</span>
          )}
          <div className="flex-1" />
          {editing ? (
            <>
              <button onClick={() => setEditing(false)} className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer px-2 py-1">
                {t("cancel")}
              </button>
              <button onClick={save} disabled={saving} className="text-xs font-medium text-foreground bg-secondary hover:bg-secondary/80 rounded-md px-3 py-1.5 transition-colors cursor-pointer disabled:opacity-50">
                {saving ? t("saving") : t("save")}
              </button>
            </>
          ) : (
            <>
              {saved && <span className="text-xs text-muted-foreground">{t("saved")}</span>}
              {onShareFile && (
                <button onClick={() => setShareOpen(true)} className={headerBtn} aria-label={t("share")} title={t("share")}>
                  <Icon name="link" className="size-4" />
                </button>
              )}
              {isText && content != null && (
                <button onClick={copy} className={headerBtn} aria-label={copied ? t("copied") : t("copy")} title={copied ? t("copied") : t("copy")}>
                  <Icon name={copied ? "check" : "copy"} className="size-4" />
                </button>
              )}
              {isText && content != null && (
                <button onClick={startEdit} className={headerBtn} aria-label={t("edit")} title={t("edit")}>
                  <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" />
                  </svg>
                </button>
              )}
              {isHtml(file.name) && content != null && (
                <button onClick={openInTab} className={headerBtn} aria-label={t("openInTab")} title={t("openInTab")}>
                  <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                  </svg>
                </button>
              )}
              {/* Extra export options (md → PDF) get a menu; otherwise the
                  icon downloads directly — no single-item dropdown. */}
              {md ? (
                <div className="relative shrink-0">
                  <button onClick={() => setMenuOpen((o) => !o)} className={headerBtn} aria-label={t("export")} title={t("export")}>
                    <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                    </svg>
                  </button>
                  {menuOpen && (
                    <DropdownMenu
                      onClose={() => setMenuOpen(false)}
                      items={[
                        { label: t("exportPdf"), onClick: () => window.print() },
                        { label: t("download"), onClick: download },
                      ]}
                    />
                  )}
                </div>
              ) : (
                <button onClick={download} className={headerBtn} aria-label={t("download")} title={t("download")}>
                  <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                  </svg>
                </button>
              )}
            </>
          )}
          <button onClick={() => setExpanded((e) => !e)} className={headerBtn} aria-label={expanded ? t("collapse") : t("expand")} title={expanded ? t("collapse") : t("expand")}>
            {expanded ? (
              <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M9 9V4.5M9 9H4.5M9 9L3.75 3.75M15 9h4.5M15 9V4.5M15 9l5.25-5.25M9 15v4.5M9 15H4.5M9 15l-5.25 5.25M15 15h4.5M15 15v4.5m0-4.5l5.25 5.25" /></svg>
            ) : (
              <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M3.75 8.25V3.75h4.5M8.25 3.75L3.75 8.25M20.25 8.25V3.75h-4.5M15.75 3.75l4.5 4.5M3.75 15.75v4.5h4.5M8.25 20.25l-4.5-4.5M20.25 15.75v4.5h-4.5M15.75 20.25l4.5-4.5" /></svg>
            )}
          </button>
          <button onClick={onClose} className={headerBtn} aria-label="Close">
            <Icon name="x" className="size-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-hidden">
          {editing ? (
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onEditorKey}
              spellCheck={false}
              className="h-full w-full resize-none border-0 bg-background px-4 py-4 sm:px-6 font-mono text-[13px] leading-relaxed text-foreground focus:outline-none"
            />
          ) : (
            <CanvasDoc file={file} content={content} error={error} />
          )}
        </div>
      </motion.div>

      {/* Print-only copy for Export PDF (md). Lives at body level so the drawer's
          fixed/transform layout doesn't distort it; hidden except when printing. */}
      {md && content != null && createPortal(
        <div className="print-root">
          <div className="prose mx-auto max-w-[46rem] p-8">
            <TextPart text={content} />
          </div>
        </div>,
        document.body,
      )}

      {shareOpen && onShareFile && (
        <ShareDialog
          onClose={() => setShareOpen(false)}
          mode="file"
          subtitle={file.name}
          onShare={(audience) => onShareFile(file.path, audience)}
        />
      )}
    </>
  );
}
