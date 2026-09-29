import { useEffect, useMemo, useRef, useState } from "react";
import { DropdownMenu } from "./files";
import { DesignEditorView, flushDesignEditor, reloadDesignEditors, type DesignHost } from "./design-editor-view";
import { PresentMode } from "./present-mode";
import type { DeckPoll, PollApi } from "../lib/polls";
import type { WriteFile } from "../hooks/use-files";
import { saveBlob } from "./canvas-utils";
import { useSlideNav } from "../hooks/use-slide-nav";
import { track } from "../lib/analytics";
import { t } from "../lib/i18n";
import { cn } from "../lib/utils";

// A design deck on the canvas — what a multi-slide Design render opens. `data` is
// the deck's slide manifest (?as=slides on its deck document or .fig — rendered by
// the design service, cached by the server):
//   { count, slides: [data-URI], sizes, names, titles, notes, transitions, fig }
// Two ways to look at it — a filmstrip beside the current slide (with its speaker
// notes), or a grid of every slide — plus Present (full screen, present-mode.tsx),
// the whole deck as PowerPoint or PDF, and Edit, which swaps in the design editor
// on the deck's .fig (the same editor a single design opens in).
//
// An agent `edit` of this deck is applied and saved on the server before its UI
// event arrives; while the deck (not the editor) is showing, that event just means
// "the slides changed" — refetch the manifest.

// A deck viewer's own slide change (slides from 1): reorder by drag, duplicate, delete.
export type DeckOp = { op: "move" | "duplicate" | "delete"; number: number; to?: number };

export interface DeckManifest {
  count: number;
  slides: string[];
  sizes?: number[][];
  names?: string[];
  titles?: string[];
  notes?: string[];
  transitions?: string[];
  polls?: (DeckPoll | null)[];   // a poll slide's live poll
  fig?: string;
}

export function parseDeck(data: string): DeckManifest | null {
  try {
    const m = JSON.parse(data);
    return m && Array.isArray(m.slides) ? { ...m, count: m.slides.length } : null;
  } catch {
    return null;
  }
}

const baseName = (path: string) => (path.split("/").pop() || path).replace(/\.deck\.json$|\.fig$/i, "");

export function DeckView({ data, path, openFile, writeFile, designEditorUrl, designHost, onReload, onSlideOp, pollsFor }: {
  data: string;
  path: string;                 // the deck document (or .fig) this manifest is of
  openFile?: (path: string, silent?: boolean) => Promise<string>;   // authed blob URL: downloads, the editor's .fig
  writeFile?: WriteFile;
  designEditorUrl?: string;     // with writeFile + openFile: Edit opens the design editor
  designHost?: DesignHost;      // what the editor asks of Cycls (new designs, copies, exports, brand)
  onReload?: () => void;        // refetch the manifest (the deck was edited)
  onSlideOp?: (op: DeckOp) => Promise<void>;   // the owner reorders / duplicates / deletes in the grid
  pollsFor?: (deck: string) => PollApi;        // the owner's: poll slides run live when presented
}) {
  const deck = useMemo(() => parseDeck(data), [data]);
  const count = deck?.count ?? 0;
  const nav = useSlideNav(count);
  // One object per deck — present mode's live poll reopens when this changes.
  const polls = useMemo(() => pollsFor?.(path), [pollsFor, path]);
  const [mode, setMode] = useState<"stage" | "grid">("stage");
  const [presenting, setPresenting] = useState<number | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);   // the .fig's blob URL while editing
  const [busy, setBusy] = useState(false);            // a slide change is on its way
  const [drag, setDrag] = useState<number | null>(null);
  const [over, setOver] = useState<number | null>(null);
  const [menuFor, setMenuFor] = useState<number | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const railRef = useRef<HTMLDivElement>(null);
  const fig = deck?.fig;
  const name = baseName(fig || path);
  const canEdit = !!(designEditorUrl && writeFile && openFile && fig);
  const hasNotes = !!deck?.notes?.some((n) => n && n.trim());

  useEffect(() => { if (count) track("deck_opened", { slides: count }); }, [path, count > 0]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Keep the current thumbnail in view while paging.
  useEffect(() => {
    railRef.current?.querySelector(`[data-slide="${nav.active}"]`)?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [nav.active]);

  // An agent edit of this deck landed (the server already saved it): new slides.
  useEffect(() => {
    if (!fig || !onReload || editing) return;
    const onCommand = (e: Event) => {
      if ((e as CustomEvent<{ path?: string }>).detail?.path === fig) onReload();
    };
    window.addEventListener("cycls:design-command", onCommand);
    return () => window.removeEventListener("cycls:design-command", onCommand);
  }, [fig, onReload, editing]);

  if (!deck || count === 0) {
    return <div className="flex h-full items-center justify-center text-sm text-muted-foreground">{t("deckUnavailable")}</div>;
  }

  const present = (from: number) => {
    track("deck_presented", { slides: count, from: from === 0 ? "start" : "current" });
    setPresenting(from);
  };
  const download = (format: "pptx" | "pdf") => {
    if (!openFile) return;
    track("deck_exported", { format });
    openFile(`${path}?as=${format}`).then((url) => saveBlob(url, `${name}.${format}`)).catch(() => {});
  };
  const edit = async () => {
    if (!canEdit || !fig) return;
    try { setEditing(await openFile!(fig)); } catch { /* the toast already said why */ }
  };
  // A slide change runs on the deck's .fig on the server; then the slides are fetched
  // again. An editor open on that .fig elsewhere saves first and reopens after, so its
  // next save isn't taken for someone else's change.
  const slideOp = async (op: DeckOp) => {
    if (!onSlideOp || busy) return;
    setBusy(true);
    try {
      if (fig) await flushDesignEditor(fig, 3000);
      await onSlideOp(op);
      if (fig) reloadDesignEditors(fig);
      track("deck_slide_changed", { op: op.op });
      onReload?.();
    } catch { /* the toast said why */ } finally {
      setBusy(false);
    }
  };
  // Done: the editor saves what's unsaved first, so the slides reload with it.
  const doneEditing = async () => {
    if (fig) await flushDesignEditor(fig, 5000);
    if (editing) URL.revokeObjectURL(editing);
    setEditing(null);
    onReload?.();
  };

  if (editing && fig && canEdit) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex items-center gap-2 border-b border-border px-3 py-1.5 text-xs text-muted-foreground">
          <span className="min-w-0 truncate">{fig}</span>
          <div className="flex-1" />
          <button onClick={doneEditing} className="rounded-md bg-secondary px-3 py-1 font-medium text-foreground hover:bg-secondary/80 cursor-pointer">
            {t("done")}
          </button>
        </div>
        <div className="min-h-0 flex-1">
          <DesignEditorView url={editing} path={fig} name={`${name}.fig`} editorUrl={designEditorUrl!}
                            writeFile={writeFile!} reload={() => openFile!(fig)} host={designHost} />
        </div>
      </div>
    );
  }

  const tool = "flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors cursor-pointer";
  const note = deck.notes?.[nav.active]?.trim();

  return (
    <div className="flex h-full flex-col outline-none" tabIndex={0} data-testid="deck-view"
         onKeyDown={(e) => { if (mode === "stage") nav.onKey(e); }}>
      {/* Toolbar */}
      <div className="flex shrink-0 items-center gap-1 border-b border-border px-3 py-1.5">
        <div className="flex rounded-lg bg-secondary p-0.5">
          {(["stage", "grid"] as const).map((m) => (
            <button key={m} onClick={() => setMode(m)} aria-pressed={mode === m}
                    className={cn("rounded-md px-2.5 py-1 text-xs transition-colors cursor-pointer",
                                  mode === m ? "bg-background font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
              {m === "stage" ? t("slidesStage") : t("slidesGrid")}
            </button>
          ))}
        </div>
        <span className="ml-2 text-xs text-muted-foreground tabular-nums">{count} {t("slidesStage").toLowerCase()}</span>
        {busy && <span className="ml-2 text-xs text-muted-foreground">{t("saving")}</span>}
        <div className="flex-1" />
        {openFile && (
          <div className="relative">
            <button onClick={() => setMenuOpen((o) => !o)} className={cn(tool, "text-muted-foreground hover:bg-secondary/80 hover:text-foreground")}>
              {t("download")}
            </button>
            {menuOpen && (
              <DropdownMenu onClose={() => setMenuOpen(false)} items={[
                { label: t("pptxFile"), onClick: () => download("pptx") },
                { label: t("pdfFile"), onClick: () => download("pdf") },
              ]} />
            )}
          </div>
        )}
        {canEdit && (
          <button onClick={edit} className={cn(tool, "text-muted-foreground hover:bg-secondary/80 hover:text-foreground")}>{t("edit")}</button>
        )}
        <button onClick={() => present(mode === "stage" ? nav.active : 0)}
                className={cn(tool, "bg-foreground text-background hover:opacity-90")}>
          <svg className="size-3" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
          {t("present")}
        </button>
      </div>

      {mode === "grid" ? (
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
            {deck.slides.map((src, i) => (
              // The owner drags a card onto another to move it there.
              <div key={i} data-testid="grid-slide" draggable={!!onSlideOp && !busy}
                   onDragStart={(e) => { setDrag(i); e.dataTransfer.effectAllowed = "move"; }}
                   onDragOver={(e) => { if (drag != null) { e.preventDefault(); setOver(i); } }}
                   onDragLeave={() => setOver((o) => (o === i ? null : o))}
                   onDragEnd={() => { setDrag(null); setOver(null); }}
                   onDrop={(e) => {
                     e.preventDefault();
                     if (drag != null && drag !== i) void slideOp({ op: "move", number: drag + 1, to: i + 1 });
                     setDrag(null); setOver(null);
                   }}
                   className={cn("group relative overflow-hidden rounded-lg border text-left transition-colors",
                                 over === i && drag !== i ? "border-primary ring-2 ring-primary" : "border-border hover:border-muted-foreground",
                                 drag === i && "opacity-50")}>
                <button onClick={() => { nav.go(i); setMode("stage"); }} onDoubleClick={() => present(i)} className="block w-full cursor-pointer text-left">
                  <img src={src} alt={`Slide ${i + 1}`} className="w-full bg-neutral-200 dark:bg-neutral-800" loading="lazy" draggable={false} />
                  <span className="flex items-center gap-1.5 px-2 py-1 text-[11px] text-muted-foreground">
                    <span className="tabular-nums">{i + 1}</span>
                    {deck.titles?.[i] && <span className="min-w-0 truncate" dir="auto">{deck.titles[i]}</span>}
                  </span>
                </button>
                {onSlideOp && (
                  <div className="absolute right-1.5 top-1.5">
                    <button onClick={() => setMenuFor((m) => (m === i ? null : i))} aria-label={t("slideActions")} title={t("slideActions")}
                            className="flex size-6 items-center justify-center rounded-md bg-background/85 text-muted-foreground opacity-0 shadow backdrop-blur transition-opacity hover:text-foreground group-hover:opacity-100 focus:opacity-100 cursor-pointer">
                      <svg className="size-3.5" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" /></svg>
                    </button>
                    {menuFor === i && (
                      <DropdownMenu onClose={() => setMenuFor(null)} items={[
                        { label: t("duplicate"), onClick: () => void slideOp({ op: "duplicate", number: i + 1 }) },
                        ...(count > 1 ? [{ label: t("delete"), danger: true, onClick: () => setConfirmDelete(i) }] : []),
                      ]} />
                    )}
                  </div>
                )}
                {confirmDelete === i && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-background/90 backdrop-blur-sm">
                    <span className="text-xs text-foreground">{t("deleteSlideQ").replace("{n}", String(i + 1))}</span>
                    <div className="flex gap-2">
                      <button onClick={() => { setConfirmDelete(null); void slideOp({ op: "delete", number: i + 1 }); }}
                              className="rounded-md bg-red-500 px-2.5 py-1 text-xs font-medium text-white hover:bg-red-600 cursor-pointer">{t("delete")}</button>
                      <button onClick={() => setConfirmDelete(null)}
                              className="rounded-md border border-border px-2.5 py-1 text-xs text-foreground hover:bg-secondary cursor-pointer">{t("cancel")}</button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1">
          {/* Filmstrip */}
          {count > 1 && (
            <div ref={railRef} className="hidden w-32 shrink-0 space-y-2 overflow-y-auto border-r border-border bg-background/60 p-2 sm:block">
              {deck.slides.map((src, i) => (
                <button key={i} data-slide={i} onClick={() => nav.go(i)}
                        className={cn("flex w-full items-start gap-1 rounded-md transition-colors cursor-pointer",
                                      i === nav.active ? "text-foreground" : "text-muted-foreground")}>
                  <span className="w-3 shrink-0 pt-0.5 text-right text-[10px] tabular-nums">{i + 1}</span>
                  <img src={src} alt={`Slide ${i + 1}`} loading="lazy"
                       className={cn("min-w-0 flex-1 rounded border", i === nav.active ? "border-primary ring-1 ring-primary" : "border-border hover:border-muted-foreground")} />
                </button>
              ))}
            </div>
          )}
          {/* Stage + notes */}
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="relative flex min-h-0 flex-1 items-center justify-center bg-neutral-200 p-4 dark:bg-neutral-800">
              <img src={deck.slides[nav.active]} alt={deck.titles?.[nav.active] || `Slide ${nav.active + 1}`}
                   className="max-h-full max-w-full object-contain shadow-lg" onDoubleClick={() => present(nav.active)} />
              {count > 1 && (
                <div className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1 rounded-full bg-background/85 px-1.5 py-0.5 text-xs text-muted-foreground shadow backdrop-blur">
                  <button onClick={() => nav.go(nav.active - 1)} className="rounded-full px-1.5 hover:text-foreground cursor-pointer" aria-label={t("previous")}>‹</button>
                  <span className="tabular-nums" data-testid="deck-counter">{nav.active + 1} / {count}</span>
                  <button onClick={() => nav.go(nav.active + 1)} className="rounded-full px-1.5 hover:text-foreground cursor-pointer" aria-label={t("next")}>›</button>
                </div>
              )}
            </div>
            {hasNotes && (
              <div className="max-h-32 shrink-0 overflow-y-auto border-t border-border px-4 py-2 text-xs">
                <div className="mb-0.5 text-[10px] uppercase tracking-wider text-muted-foreground">{t("speakerNotes")}</div>
                <div className={cn("whitespace-pre-wrap", note ? "text-foreground" : "text-muted-foreground")} dir="auto">
                  {note || t("noNotes")}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {presenting != null && (
        <PresentMode deck={deck} start={presenting} onClose={(last) => { setPresenting(null); nav.go(last); }} polls={polls} />
      )}
    </div>
  );
}
