import { useEffect, useMemo, useRef, useState } from "react";
import { DropdownMenu } from "./files";
import { flushDesignEditor, reloadDesignEditors } from "./design-editor-view";
import { PresentMode } from "./present-mode";
import { CommentButtons, CommentLayer, CommentsList, useCommentCounts } from "./comments";
import { useComments } from "../lib/comments";
import type { DeckPoll, PollApi } from "../lib/polls";
import { saveBlob } from "./canvas-utils";
import { useSlideNav } from "../hooks/use-slide-nav";
import { useEscape } from "../hooks/use-escape";
import { track } from "../lib/analytics";
import { t } from "../lib/i18n";
import { cn } from "../lib/utils";

// A multi-slide design on the canvas. `data` is its slide manifest (?as=slides on the .fig).

// Slide numbers are 1-based.
export type DeckOp =
  | { op: "move" | "duplicate" | "delete"; number: number; to?: number }
  | { op: "add"; number?: number; title?: string; text?: string }
  | { op: "notes"; number: number; notes: string };

// Saved on blur, reverted on Escape. Keys stay in the box so typing doesn't page the deck.
function NotesBox({ value, onSave }: { value: string; onSave: (notes: string) => void }) {
  const [draft, setDraft] = useState(value);
  const left = useRef(false);
  return (
    <textarea aria-label={t("speakerNotes")} dir="auto" rows={3} value={draft} placeholder={t("addNotes")}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                e.stopPropagation();
                if (e.key !== "Escape") return;
                e.preventDefault();
                left.current = true;
                setDraft(value);
                e.currentTarget.blur();
              }}
              onBlur={() => {
                if (left.current) { left.current = false; return; }
                if (draft.trim() !== value.trim()) onSave(draft.trim());
              }}
              className="block w-full resize-none bg-transparent text-xs text-foreground outline-none placeholder:text-muted-foreground" />
  );
}

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
  pages?: { name: string; frames: number }[];   // the design's pages (variants); a manifest is one of them
  page?: string;
  kind?: string;   // what the design is (its file's record): "document" (flowing paper pages), "deck", "carousel", "post"…
}

export function PageTabs({ pages, page, onPick }: { pages: string[]; page: string; onPick: (page: string) => void }) {
  return (
    <div role="tablist" aria-label={t("pages")} data-testid="design-pages"
         className="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-border bg-background px-3 py-1.5">
      {pages.map((name) => (
        <button key={name} role="tab" aria-selected={name === page} title={name} dir="auto"
                onClick={() => { if (name !== page) onPick(name); }}
                className={cn("max-w-[14rem] shrink-0 truncate rounded-md px-2.5 py-1 text-xs transition-colors cursor-pointer",
                              name === page ? "bg-secondary font-medium text-foreground" : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground")}>
          {name}
        </button>
      ))}
    </div>
  );
}

export function parseDeck(data: string): DeckManifest | null {
  try {
    const m = JSON.parse(data);
    return m && Array.isArray(m.slides) ? { ...m, count: m.slides.length } : null;
  } catch {
    return null;
  }
}

export function EditPreviewSwitch({ previewing, onEdit, onPreview }: {
  previewing: boolean;
  onEdit: () => void;
  onPreview: () => void;
}) {
  const item = (on: boolean) => cn("rounded-md px-2.5 py-1 text-xs transition-colors cursor-pointer",
    on ? "bg-background font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground");
  return (
    <div className="flex shrink-0 rounded-lg bg-secondary p-0.5" role="group" data-testid="edit-preview">
      <button aria-pressed={!previewing} onClick={() => { if (previewing) onEdit(); }} className={item(!previewing)}>{t("edit")}</button>
      <button aria-pressed={previewing} onClick={() => { if (!previewing) onPreview(); }} className={item(previewing)}>{t("preview")}</button>
    </div>
  );
}

const baseName = (path: string) => (path.split("/").pop() || path).replace(/\.fig$/i, "");

export function DeckView({ data, path, openFile, onReload, onSlideOp: changeSlides, pollsFor, onPage }: {
  data: string;
  path: string;                 // the design (.fig) this manifest is of
  openFile?: (path: string, silent?: boolean) => Promise<string>;   // authed blob URL: downloads
  onReload?: () => void;        // refetch the manifest (the deck was edited)
  onSlideOp?: (op: DeckOp) => Promise<void>;   // the owner reorders / duplicates / deletes in the grid
  pollsFor?: (deck: string) => PollApi;        // the owner's: poll slides run live when presented
  onPage?: (page: string) => void;             // show another page of the design (a comment is on it)
}) {
  const deck = useMemo(() => parseDeck(data), [data]);
  const count = deck?.count ?? 0;
  const nav = useSlideNav(count);
  // One object per deck — present mode's live poll reopens when this changes.
  const polls = useMemo(() => pollsFor?.(path), [pollsFor, path]);
  const [mode, setMode] = useState<"stage" | "grid">("stage");
  const [presenting, setPresenting] = useState<number | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [busy, setBusy] = useState(false);            // a slide change is on its way
  const [drag, setDrag] = useState<number | null>(null);
  const [over, setOver] = useState<number | null>(null);
  const [menuFor, setMenuFor] = useState<number | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const [goTo, setGoTo] = useState<number | null>(null);   // the slide just added, shown once the slides are back
  useEscape(() => setConfirmDelete(null), confirmDelete !== null);
  const railRef = useRef<HTMLDivElement>(null);
  const fig = deck?.fig;
  // A document's pages are numbered in its contents: no per-page edits.
  const onSlideOp = deck?.kind === "document" ? undefined : changeSlides;
  const name = baseName(fig || path);
  const hasNotes = !!deck?.notes?.some((n) => n && n.trim());
  // A comment pin names its slide, so it is found again after a reorder.
  const picture = useRef<HTMLImageElement>(null);
  const names = useMemo(() => Array.from({ length: count }, (_, i) => deck?.names?.[i] ?? ""), [deck, count]);
  const pageNames = useMemo(() => (deck?.pages ?? []).map((p) => p.name), [deck]);
  const page = deck?.page || undefined;
  const comments = useComments(fig);
  const pinned = useCommentCounts(fig, names, page, pageNames);

  useEffect(() => { if (count) track("deck_opened", { slides: count }); }, [path, count > 0]);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    railRef.current?.querySelector(`[data-slide="${nav.active}"]`)?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [nav.active]);

  // Go to an added slide once the refetched deck has it.
  useEffect(() => {
    if (goTo == null || goTo >= count) return;
    nav.go(goTo);
    setGoTo(null);
  }, [goTo, count]);   // eslint-disable-line react-hooks/exhaustive-deps

  // An agent edit is saved server-side before its event arrives: just refetch.
  useEffect(() => {
    if (!fig || !onReload) return;
    const onCommand = (e: Event) => {
      if ((e as CustomEvent<{ path?: string }>).detail?.path === fig) onReload();
    };
    window.addEventListener("cycls:design-command", onCommand);
    return () => window.removeEventListener("cycls:design-command", onCommand);
  }, [fig, onReload]);

  if (!deck || count === 0) {
    return <div className="flex h-full items-center justify-center text-sm text-muted-foreground">{t("deckUnavailable")}</div>;
  }

  const present = (from: number) => {
    track("deck_presented", { slides: count, from: from === 0 ? "start" : "current" });
    setPresenting(from);
  };
  const download = (format: "pptx" | "pdf" | "images") => {
    if (!openFile) return;
    track("deck_exported", { format });
    // A multi-page design exports only the page on screen.
    const page = deck.pages && deck.pages.length > 1 ? deck.page : undefined;
    openFile(`${path}?as=${format}${page ? `&page=${encodeURIComponent(page)}` : ""}`)
      .then((url) => saveBlob(url, `${name}${page ? `-${page}` : ""}.${format === "images" ? "zip" : format}`)).catch(() => {});
  };
  // A document lists PDF first; a carousel (square or portrait) lists images first.
  const [w, h] = deck.sizes?.[0] ?? [16, 9];
  const paper = deck.kind === "document";
  const images = { label: t("imagesZip"), onClick: () => download("images") };
  const pdf = { label: t("pdfFile"), onClick: () => download("pdf") };
  const downloads = [
    ...(paper ? [pdf] : []),
    ...(w <= h && !paper ? [images] : []),
    { label: t("pptxFile"), onClick: () => download("pptx") },
    ...(paper ? [] : [pdf]),
    ...(w <= h && !paper ? [] : [images]),
  ];
  // An editor open on this .fig saves first and reloads after, so its next save doesn't undo the change.
  const slideOp = async (op: DeckOp) => {
    if (!onSlideOp || busy) return;
    setBusy(true);
    try {
      if (fig) await flushDesignEditor(fig, 3000);
      await onSlideOp(op);
      if (fig) reloadDesignEditors(fig);
      track("deck_slide_changed", { op: op.op });
      if (op.op === "add") { setMode("stage"); setGoTo(op.number ?? count); }
      onReload?.();
    } catch { /* the toast said why */ } finally {
      setBusy(false);
    }
  };
  const addSlide = (after: number) => void slideOp({ op: "add", number: after, title: t("newSlideTitle"), text: t("newSlideText") });
  const tool = "flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors cursor-pointer";
  const note = deck.notes?.[nav.active]?.trim();

  return (
    <div className="relative flex h-full flex-col outline-none" tabIndex={0} data-testid="deck-view"
         onKeyDown={(e) => {
           // C toggles comment mode: the next click on the slide pins one.
           if (comments && e.key.toLowerCase() === "c" && !e.metaKey && !e.ctrlKey && !e.altKey) {
             e.preventDefault();
             setMode("stage");
             comments.store.set({ adding: !comments.adding, draft: null });
             return;
           }
           if (mode === "stage") nav.onKey(e);
         }}>
      {/* Toolbar */}
      <div className="flex shrink-0 items-center gap-1 border-b border-border px-3 py-1.5">
        <div className="flex rounded-lg bg-secondary p-0.5">
          {(["stage", "grid"] as const).map((m) => (
            <button key={m} onClick={() => setMode(m)} aria-pressed={mode === m}
                    className={cn("rounded-md px-2.5 py-1 text-xs transition-colors cursor-pointer",
                                  mode === m ? "bg-background font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
              {m === "stage" ? t(paper ? "pages" : "slidesStage") : t("slidesGrid")}
            </button>
          ))}
        </div>
        <span className="ml-2 text-xs text-muted-foreground tabular-nums">
          {count === 1 ? t(paper ? "onePage" : "oneSlide") : `${count} ${t(paper ? "pages" : "slidesStage").toLowerCase()}`}
        </span>
        {onSlideOp && (
          <button onClick={() => addSlide(mode === "stage" ? nav.active + 1 : count)} disabled={busy}
                  aria-label={t("addSlide")} title={t("addSlide")} data-testid="add-slide"
                  className="ml-1 flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary/80 hover:text-foreground disabled:opacity-50 cursor-pointer">
            <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" d="M12 5v14M5 12h14" /></svg>
          </button>
        )}
        {busy && <span className="ml-2 text-xs text-muted-foreground">{t("saving")}</span>}
        <div className="flex-1" />
        {fig && <CommentButtons path={fig} onComment={(adding) => { if (adding) setMode("stage"); }} />}
        {openFile && (
          <div className="relative">
            <button onClick={() => setMenuOpen((o) => !o)} className={cn(tool, "text-muted-foreground hover:bg-secondary/80 hover:text-foreground")}>
              {t("download")}
            </button>
            {menuOpen && (
              <DropdownMenu onClose={() => setMenuOpen(false)} items={downloads} />
            )}
          </div>
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
                    {pinned[i] > 0 && <span className="ml-auto shrink-0 rounded-full bg-red-500 px-1.5 text-[10px] font-semibold text-white tabular-nums" data-testid="slide-comments">{pinned[i]}</span>}
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
                        { label: t("addSlideAfter"), onClick: () => addSlide(i + 1) },
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
                  <span className="relative min-w-0 flex-1">
                    <img src={src} alt={`Slide ${i + 1}`} loading="lazy"
                         className={cn("block w-full rounded border", i === nav.active ? "border-primary ring-1 ring-primary" : "border-border hover:border-muted-foreground")} />
                    {pinned[i] > 0 && <span className="absolute -right-1 -top-1 size-2.5 rounded-full border border-background bg-red-500" data-testid="slide-comments" />}
                  </span>
                </button>
              ))}
            </div>
          )}
          {/* Stage + notes */}
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="relative flex min-h-0 flex-1 items-center justify-center bg-neutral-200 p-4 dark:bg-neutral-800">
              <img ref={picture} src={deck.slides[nav.active]} alt={deck.titles?.[nav.active] || `Slide ${nav.active + 1}`}
                   className="max-h-full max-w-full object-contain shadow-lg" onDoubleClick={() => present(nav.active)} />
              {fig && <CommentLayer path={fig} picture={picture} size={deck.sizes?.[nav.active]} frame={nav.active}
                                    names={names} page={page} pages={pageNames} />}
              {count > 1 && (
                <div className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1 rounded-full bg-background/85 px-1.5 py-0.5 text-xs text-muted-foreground shadow backdrop-blur">
                  <button onClick={() => nav.go(nav.active - 1)} className="rounded-full px-1.5 hover:text-foreground cursor-pointer" aria-label={t("previous")}>‹</button>
                  <span className="tabular-nums" data-testid="deck-counter">{nav.active + 1} / {count}</span>
                  <button onClick={() => nav.go(nav.active + 1)} className="rounded-full px-1.5 hover:text-foreground cursor-pointer" aria-label={t("next")}>›</button>
                </div>
              )}
            </div>
            {onSlideOp ? (
              <div className="max-h-32 shrink-0 overflow-y-auto border-t border-border px-4 py-2 text-xs">
                <div className="mb-0.5 text-[10px] uppercase tracking-wider text-muted-foreground">{t("speakerNotes")}</div>
                <NotesBox key={`${nav.active}:${note ?? ""}`} value={note ?? ""}
                          onSave={(notes) => void slideOp({ op: "notes", number: nav.active + 1, notes })} />
              </div>
            ) : hasNotes && (
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

      {fig && <CommentsList path={fig} names={names} page={page} pages={pageNames} paper={paper} onPage={onPage}
                            onGo={(i) => { setMode("stage"); nav.go(i); }} />}

      {presenting != null && (
        <PresentMode deck={deck} start={presenting} onClose={(last) => { setPresenting(null); nav.go(last); }} polls={polls} />
      )}
    </div>
  );
}
