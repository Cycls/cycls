import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Icon } from "./icon";
import { LoadingBar } from "./loading-bar";
import { DropdownMenu } from "./files";
import { ShareDialog } from "./share-dialog";
import { TextPart } from "./parts/text-part";
import { HighlightedCode } from "./parts/code-part";
import { isHtml, isMd, isPdf, isImage, isAudio, isVideo, isSpreadsheet, is3d, codeLang, extTint, saveBlob } from "./canvas-utils";
import { SpreadsheetView } from "./spreadsheet-view";
import { usePaneWidth } from "../hooks/use-pane-width";
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
    const load = isPdf(file.name) || isImage(file.name) || isAudio(file.name) || isVideo(file.name) || isSpreadsheet(file.name) || is3d(file.name)
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
  if (is3d(file.name)) {
    // model-viewer from CDN inside our own iframe shell — no npm dependency.
    // No sandbox: the srcDoc is our template, and an opaque origin couldn't
    // fetch the parent's blob URL.
    return content ? (
      <iframe
        srcDoc={`<!doctype html><html><head><meta charset="utf-8">
<script type="module" src="https://unpkg.com/@google/model-viewer/dist/model-viewer.min.js"></script>
<style>html,body{margin:0;height:100%;overflow:hidden}
model-viewer{width:100vw;height:100vh;background:radial-gradient(ellipse at center,#1a1a1a 0%,#0a0a0a 100%)}</style>
</head><body><model-viewer src="${content}" camera-controls auto-rotate shadow-intensity="1" exposure="1.1" environment-image="neutral"></model-viewer></body></html>`}
        title={file.name}
        className="h-full w-full border-0"
      />
    ) : null;
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

// Open files as tabs, docked (desktop split pane) or as the overlay drawer.
export function Canvas({ tabs, active, docked, hidden, expanded, onToggleExpand, onSelectTab, onCloseTab, onHide, onAddFile, searchFiles, readFile, openFile, writeFile, onShareFile }: {
  tabs: CanvasFile[];
  active: string | null;
  docked: boolean;
  hidden?: boolean;
  expanded: boolean;
  onToggleExpand: () => void;
  onSelectTab: (path: string) => void;
  onCloseTab: (path: string) => void;
  onHide: () => void;
  onAddFile?: (path: string) => void;
  searchFiles?: (q: string) => Promise<{ name: string; path: string }[]>;
  readFile: (path: string) => Promise<string>;   // authed text fetch (md/html/code source)
  openFile: (path: string) => Promise<string>;    // authed blob URL (pdf / download)
  writeFile: (path: string, text: string) => Promise<void>;  // overwrite (editor)
  onShareFile?: (path: string, audience: string) => Promise<string>;
}) {
  const file = hidden ? null : tabs.find((f) => f.path === active) ?? tabs[tabs.length - 1] ?? null;
  const { width, startResize, resizing } = usePaneWidth("cycls_canvas_width", 560, 380, 480);

  const stripBtn = "flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer";
  const inner = file && (
    <>
      <div className="flex shrink-0 items-center gap-1 border-b border-border px-2 py-1.5">
        <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {tabs.map((f) => {
            const on = f.path === file.path;
            const tint = extTint(f.name);
            return (
              <div
                key={f.path}
                role="button"
                onClick={() => onSelectTab(f.path)}
                className={cn(
                  "group flex shrink-0 cursor-pointer items-center gap-1.5 rounded-lg py-1 pl-2.5 pr-1 text-xs transition-colors",
                  on ? "bg-secondary text-foreground font-medium" : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground",
                )}
              >
                {tint && <span className="size-1.5 rounded-full" style={{ backgroundColor: tint }} />}
                <span className="max-w-40 truncate">{f.name}</span>
                <button
                  onClick={(e) => { e.stopPropagation(); onCloseTab(f.path); }}
                  className={cn("rounded p-0.5 hover:bg-accent/20", on ? "" : "opacity-0 group-hover:opacity-100")}
                  aria-label={`Close ${f.name}`}
                >
                  <Icon name="x" className="size-3" />
                </button>
              </div>
            );
          })}
          {onAddFile && searchFiles && <AddTab onAdd={onAddFile} searchFiles={searchFiles} />}
        </div>
        <button onClick={onToggleExpand} className={cn(stripBtn, "hidden sm:flex")} aria-label={expanded ? t("collapse") : t("expand")} title={expanded ? t("collapse") : t("expand")}>
          <Icon name={expanded ? "collapse" : "expand"} className="size-3.5" />
        </button>
        <button onClick={onHide} className={stripBtn} aria-label="Hide canvas" title="Hide canvas">
          <Icon name="chevron-right" className="size-4" />
        </button>
      </div>
      <CanvasFileView
        key={file.path}
        file={file}
        onClose={() => onCloseTab(file.path)}
        readFile={readFile}
        openFile={openFile}
        writeFile={writeFile}
        onShareFile={onShareFile}
      />
    </>
  );

  if (docked) {
    // Expanded fills the content row; chat.tsx hides the chat column.
    if (file && expanded) {
      return (
        <aside dir="ltr" className="relative min-w-0 flex-1">
          <div className="absolute inset-x-1 bottom-1 top-1 flex flex-col overflow-hidden rounded-xl border border-border bg-background">
            {inner}
          </div>
        </aside>
      );
    }
    return (
      <AnimatePresence initial={false}>
        {file && (
          <motion.aside
            key="canvas"
            dir="ltr"
            initial={{ width: 0 }}
            animate={{ width }}
            exit={{ width: 0 }}
            transition={resizing ? { duration: 0 } : { type: "spring", damping: 30, stiffness: 300 }}
            className="relative shrink-0 overflow-hidden"
          >
            {/* Right-anchored fixed-width card so content doesn't squish while the pane animates. */}
            <div className="absolute bottom-1 right-1 top-1 flex flex-col overflow-hidden rounded-xl border border-border bg-background" style={{ width: width - 8 }}>
              <div
                onMouseDown={startResize}
                className="absolute bottom-0 left-0 top-0 z-20 w-1.5 cursor-ew-resize hover:bg-accent/30"
                aria-label="Resize canvas"
              />
              {inner}
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
    );
  }

  if (file && expanded) {
    return (
      <>
        <div className="fixed inset-0 z-[55] bg-black/30 backdrop-blur-[2px]" onClick={onHide} />
        <div dir="ltr" className="fixed inset-2 z-[60] flex flex-col overflow-hidden rounded-xl border border-border bg-background">
          {inner}
        </div>
      </>
    );
  }

  return (
    <AnimatePresence>
      {file && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="fixed inset-0 z-[55] bg-black/30 backdrop-blur-[2px]"
            onClick={onHide}
          />
          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 25, stiffness: 200 }}
            className="fixed bottom-1 right-1 top-1 z-[60] flex w-[calc(100%-0.5rem)] flex-col overflow-hidden rounded-xl border border-border bg-background sm:w-[720px] lg:w-[60vw] lg:max-w-[960px]"
            dir="ltr"
          >
            {inner}
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

// The menu is position:fixed from the button's rect so the pane's
// overflow-hidden can't clip it.
function AddTab({ onAdd, searchFiles }: {
  onAdd: (path: string) => void;
  searchFiles: (q: string) => Promise<{ name: string; path: string }[]>;
}) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<{ name: string; path: string }[]>([]);

  useEffect(() => {
    if (!pos) return;
    let dead = false;
    searchFiles(q).then((r) => { if (!dead) setResults(r); });
    return () => { dead = true; };
  }, [pos != null, q, searchFiles]);

  const toggle = (e: React.MouseEvent<HTMLButtonElement>) => {
    if (pos) { setPos(null); return; }
    const r = e.currentTarget.getBoundingClientRect();
    setQ("");
    setPos({ x: r.left, y: r.bottom + 4 });
  };

  return (
    <>
      <button
        onClick={toggle}
        className="flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
        aria-label="Open a file"
        title="Open a file"
      >
        <svg className="size-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
        </svg>
      </button>
      {pos && createPortal(
        <>
          <div className="fixed inset-0 z-[70]" onClick={() => setPos(null)} />
          <div className="fixed z-[70] w-72 overflow-hidden rounded-xl border border-border bg-background shadow-xl" style={{ left: pos.x, top: pos.y }}>
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search files…"
              className="w-full border-b border-border bg-transparent px-3 py-2 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none"
            />
            <div className="max-h-64 overflow-y-auto py-1">
              {results.length === 0 ? (
                <div className="px-3 py-3 text-center text-xs text-muted-foreground">—</div>
              ) : results.map((r) => {
                const tint = extTint(r.name);
                return (
                  <button
                    key={r.path}
                    onClick={() => { onAdd(r.path); setPos(null); }}
                    className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-left text-xs text-foreground transition-colors hover:bg-secondary/80"
                  >
                    <span className="size-1.5 shrink-0 rounded-full" style={{ backgroundColor: tint || "var(--color-muted-foreground)" }} />
                    <span className="truncate" dir="ltr">{r.path}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </>,
        document.body,
      )}
    </>
  );
}

// Keyed by path from the parent, so per-file state resets on tab switch.
function CanvasFileView({ file, onClose, readFile, openFile, writeFile, onShareFile }: {
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
  const [shareOpen, setShareOpen] = useState(false);
  const md = isMd(file.name);
  const lang = codeLang(file.name);
  const isText = md || lang != null;   // text-based: editable + copyable
  const dirs = file.path.split("/").slice(0, -1);

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
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-border px-4 sm:px-6 py-3">
        <div className="flex min-w-0 items-center gap-1 text-sm">
          {dirs.map((seg, i) => (
            <span key={i} className="flex shrink-0 items-center gap-1 text-muted-foreground">
              <span className="max-w-24 truncate">{seg}</span>
              <Icon name="chevron-right" className="size-3 text-muted-foreground/50" strokeWidth={2.5} />
            </span>
          ))}
          <span className="min-w-0 truncate font-medium text-foreground">{file.name}</span>
        </div>
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
        <button onClick={onClose} className={headerBtn} aria-label="Close file" title="Close file">
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
