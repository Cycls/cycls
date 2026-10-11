import { useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { DropdownMenu } from "./files";
import { peerColor } from "../lib/people";
import { useEscape } from "../hooks/use-escape";
import { onPage, placeOf, useComments, type CommentAuthor, type CommentThread } from "../lib/comments";
import { track } from "../lib/analytics";
import { t, timeAgo } from "../lib/i18n";
import { cn } from "../lib/utils";

// Comment UI for a design (state in lib/comments.ts). A pin is a point in the slide's own
// pixels, so it stays put at any scale, here and in the editor.

type Comments = NonNullable<ReturnType<typeof useComments>>;

const initial = (name: string) => (name.trim()[0] ?? "?").toUpperCase();
const round = (v: number) => Math.round(v * 10) / 10;

function nameOf(c: Comments, author: CommentAuthor) {
  return author.agent ? c.host.agent || author.name : author.name || t("someone");
}

function Avatar({ c, author, className }: { c: Comments; author: CommentAuthor; className?: string }) {
  if (author.image) return <img src={author.image} alt="" className={cn("size-6 shrink-0 rounded-full object-cover", className)} />;
  return (
    <span style={{ background: author.agent ? undefined : peerColor(author.id) }}
          className={cn("flex size-6 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold text-white",
                        author.agent && "bg-foreground text-background", className)}>
      {initial(nameOf(c, author))}
    </span>
  );
}

// Enter sends, Shift+Enter is a new line; keys stop here so none reach the deck.
function Writer({ placeholder, start = "", focus, onSend, onCancel }: {
  placeholder: string;
  start?: string;
  focus?: boolean;
  onSend: (text: string) => Promise<void>;
  onCancel?: () => void;
}) {
  const [text, setText] = useState(start);
  const [busy, setBusy] = useState(false);
  const send = async () => {
    const words = text.trim();
    if (!words || busy) return;
    setBusy(true);
    try {
      await onSend(words);
      setText("");
    } catch { /* the toast said why; the text stays */ } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex items-end gap-1.5">
      <textarea dir="auto" rows={Math.min(5, Math.max(1, text.split("\n").length))} value={text} placeholder={placeholder}
                autoFocus={focus} aria-label={placeholder} maxLength={4000}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  e.stopPropagation();
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); }
                  if (e.key === "Escape" && onCancel) { e.preventDefault(); onCancel(); }
                }}
                className="min-w-0 flex-1 resize-none rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:border-muted-foreground" />
      <button onClick={() => void send()} disabled={!text.trim() || busy} aria-label={t("commentPost")} title={t("commentPost")}
              className="flex size-7 shrink-0 items-center justify-center rounded-full bg-foreground text-background transition-opacity disabled:opacity-30 cursor-pointer">
        <svg className="size-3.5" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M12 19V5m0 0l-6 6m6-6l6 6" /></svg>
      </button>
    </div>
  );
}

// One comment or reply; its author can edit or delete it.
function Said({ c, author, text, at, edited, onEdit, onDelete }: {
  c: Comments;
  author: CommentAuthor;
  text: string;
  at: string;
  edited?: string;
  onEdit?: (text: string) => Promise<void>;
  onDelete?: () => void;
}) {
  const [menu, setMenu] = useState(false);
  const [editing, setEditing] = useState(false);
  return (
    <div className="group flex gap-2" data-testid="comment-said">
      <Avatar c={c} author={author} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-1.5">
          <span className="min-w-0 truncate text-xs font-medium text-foreground" dir="auto">{nameOf(c, author)}</span>
          <span className="shrink-0 text-[10px] text-muted-foreground">{timeAgo(at)}{edited ? ` · ${t("commentEdited")}` : ""}</span>
          <div className="flex-1" />
          {(onEdit || onDelete) && !editing && (
            <span className="relative shrink-0">
              <button onClick={() => setMenu((m) => !m)} aria-label={t("more")} title={t("more")}
                      className="flex size-5 items-center justify-center rounded text-muted-foreground opacity-0 transition-opacity hover:text-foreground focus:opacity-100 group-hover:opacity-100 cursor-pointer">
                <svg className="size-3.5" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="19" cy="12" r="1.6" /></svg>
              </button>
              {menu && <DropdownMenu onClose={() => setMenu(false)} items={[
                ...(onEdit ? [{ label: t("edit"), onClick: () => setEditing(true) }] : []),
                ...(onDelete ? [{ label: t("delete"), danger: true, onClick: onDelete }] : []),
              ]} />}
            </span>
          )}
        </div>
        {editing && onEdit
          ? <div className="mt-1"><Writer placeholder={t("comment")} start={text} focus onCancel={() => setEditing(false)}
                                          onSend={async (words) => { await onEdit(words); setEditing(false); }} /></div>
          : <div className="whitespace-pre-wrap break-words text-xs leading-relaxed text-foreground" dir="auto">{text}</div>}
      </div>
    </div>
  );
}

function ThreadCard({ c, thread }: { c: Comments; thread: CommentThread }) {
  const me = c.me ?? c.host.me?.id;
  const own = (author: CommentAuthor) => !!me && author.id === me;
  const change = (body: Parameters<Comments["store"]["change"]>[1]) => c.store.change(thread.id, body);
  return (
    <div data-testid="comment-thread" role="dialog" aria-label={`${t("comment")} ${thread.n}`}>
      <div className="flex items-center gap-1 border-b border-border px-3 py-1.5">
        <span className="text-[11px] font-medium text-muted-foreground tabular-nums">#{thread.n}</span>
        <div className="flex-1" />
        <button onClick={() => { track("design_comment_resolved", { resolved: !thread.resolved }); void change({ op: thread.resolved ? "reopen" : "resolve" }).catch(() => {}); }}
                aria-pressed={thread.resolved} title={t(thread.resolved ? "commentReopen" : "commentResolve")}
                className={cn("flex h-6 items-center gap-1 rounded-md px-1.5 text-[11px] transition-colors cursor-pointer",
                              thread.resolved ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400" : "text-muted-foreground hover:bg-secondary hover:text-foreground")}>
          <svg className="size-3.5" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M5 12.5l4.5 4.5L19 7.5" /></svg>
          {t(thread.resolved ? "commentResolved" : "commentResolve")}
        </button>
        <button onClick={() => c.store.open(null)} aria-label={t("close")} title={t("close")}
                className="flex size-6 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground cursor-pointer">
          <svg className="size-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" /></svg>
        </button>
      </div>
      <div className="max-h-64 space-y-3 overflow-y-auto px-3 py-2.5">
        <Said c={c} author={thread.author} text={thread.text} at={thread.at} edited={thread.edited}
              onEdit={own(thread.author) ? (text) => change({ op: "edit", text }) : undefined}
              onDelete={own(thread.author) ? () => void change({ op: "delete" }).catch(() => {}) : undefined} />
        {thread.replies.map((r) => (
          <Said key={r.id} c={c} author={r.author} text={r.text} at={r.at} edited={r.edited}
                onEdit={own(r.author) ? (text) => change({ op: "edit", text, reply: r.id }) : undefined}
                onDelete={own(r.author) ? () => void change({ op: "delete", reply: r.id }).catch(() => {}) : undefined} />
        ))}
        {thread.resolved && thread.resolved_by && (
          <div className="text-[10px] text-muted-foreground" dir="auto">{t("commentResolvedBy").replace("{name}", nameOf(c, thread.resolved_by))}</div>
        )}
      </div>
      <div className="border-t border-border p-2">
        <Writer placeholder={t("commentReply")} onSend={async (text) => { await change({ op: "reply", text }); track("design_comment_replied", {}); }} />
      </div>
    </div>
  );
}

const PIN = 28;   // px; its tip, the point it marks, is the bottom-left corner

// A card beside the pin: right, else left, else below (above if no room), inside `within`.
export function beside(at: { x: number; y: number }, card: { w: number; h: number }, within: { w: number; h: number }) {
  const gap = 8, edge = 8;
  const clamp = (v: number, most: number) => Math.max(edge, Math.min(v, Math.max(edge, most)));
  const right = at.x + PIN + gap, left = at.x - gap - card.w;
  if (right + card.w <= within.w - edge || left >= edge) {
    return { left: right + card.w <= within.w - edge ? right : left, top: clamp(at.y - PIN - 6, within.h - card.h - edge) };
  }
  const under = at.y + gap, over = at.y - PIN - gap - card.h;
  return { left: clamp(at.x - 12, within.w - card.w - edge),
           top: under + card.h > within.h - edge && over >= edge ? over : clamp(under, within.h - card.h - edge) };
}

function Beside({ at, within, children }: { at: { x: number; y: number }; within: { w: number; h: number }; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const { left, top } = beside(at, { w: el.offsetWidth || 288, h: el.offsetHeight }, within);
    setPos((was) => (was && Math.abs(was.left - left) < 0.5 && Math.abs(was.top - top) < 0.5 ? was : { left, top }));
  });
  return (
    // Opacity 0 until placed, not `visibility: hidden`, which would block the autofocus.
    <div ref={ref} style={{ left: pos?.left ?? 0, top: pos?.top ?? 0, opacity: pos ? undefined : 0 }}
         onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}
         className="pointer-events-auto absolute z-20 w-72 max-w-[calc(100%-16px)] overflow-hidden rounded-xl border border-border bg-background text-start shadow-xl">
      {children}
    </div>
  );
}

// The open draft or thread as a card at `at`, for a design drawn elsewhere (the editor).
export function OpenComment({ path, at, within }: { path: string; at: { x: number; y: number }; within: { w: number; h: number } }) {
  const c = useComments(path);
  if (!c) return null;
  const draft = c.draft;
  const thread = c.active ? c.threads.find((t) => t.id === c.active) : null;
  if (draft) {
    return (
      <Beside at={at} within={within}>
        <div className="p-2" data-testid="comment-new">
          <Writer placeholder={t("addComment")} focus onCancel={() => c.store.set({ draft: null })}
                  onSend={async (text) => { await c.store.add(draft, text); track("design_comment_added", {}); }} />
        </div>
      </Beside>
    );
  }
  return thread ? <Beside at={at} within={within}><ThreadCard c={c} thread={thread} /></Beside> : null;
}

// The editor's `comments` message: the pins of its page (a spot, a letter, a colour; no threads).
export type EditorPin = { id: string; frame: number; x: number; y: number; label: string; color: string; image?: string; dim?: boolean };
export function editorComments(c: Comments, names: string[], page: string | undefined, pages: string[]) {
  const pins: EditorPin[] = [];
  for (const thread of onPage(c.threads, page, pages)) {
    const frame = placeOf(thread, names);
    if (frame === null || (thread.resolved && thread.id !== c.active)) continue;
    const agent = !!thread.author.agent;
    pins.push({ id: thread.id, frame, x: thread.x, y: thread.y, label: initial(nameOf(c, thread.author)),
                color: agent ? "#111827" : peerColor(thread.author.id),
                ...(thread.author.image && !agent ? { image: thread.author.image } : {}), ...(thread.resolved ? { dim: true } : {}) });
  }
  const draft = c.draft && (pages.length <= 1 || (c.draft.page ?? pages[0]) === (page ?? pages[0])) ? c.draft : null;
  return { pins, adding: c.adding, active: pins.some((p) => p.id === c.active) ? c.active : null,
           draft: draft ? { frame: draft.frame, x: draft.x, y: draft.y } : null,
           me: { label: initial(c.host.me?.name ?? "+"), color: c.host.me ? peerColor(c.host.me.id) : "#111827" } };
}

type Box = { left: number; top: number; width: number; height: number; w: number; h: number };

// The picture's box in the layer's pixels: a slide drawn to fit rarely fills its stage.
function usePictureBox(picture: RefObject<HTMLImageElement | null>, layer: RefObject<HTMLDivElement | null>, on: boolean): Box | null {
  const [box, setBox] = useState<Box | null>(null);
  useLayoutEffect(() => {
    const img = picture.current, el = layer.current;
    if (!on || !img || !el) return;
    const measure = () => {
      const a = img.getBoundingClientRect(), b = el.getBoundingClientRect();
      const next: Box = { left: a.left - b.left, top: a.top - b.top, width: a.width, height: a.height, w: b.width, h: b.height };
      setBox((was) => (was && (Object.keys(next) as (keyof Box)[]).every((k) => Math.abs(was[k] - next[k]) < 0.5) ? was : next));
    };
    measure();
    img.addEventListener("load", measure);
    window.addEventListener("resize", measure);
    const seen = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    seen?.observe(img);
    seen?.observe(el);
    return () => {
      img.removeEventListener("load", measure);
      window.removeEventListener("resize", measure);
      seen?.disconnect();
    };
  }, [picture, layer, on]);
  return box;
}

// One slide's pins over its picture; only what it draws takes the pointer.
export function CommentLayer({ path, picture, size, frame, names, page, pages = [] }: {
  path: string;                                  // the design (.fig)
  picture: RefObject<HTMLImageElement | null>;
  size?: number[];                               // the slide's own size, in its pixels
  frame: number;                                 // the slide's index on the page
  names: string[];                               // the page's slides by name, in order
  page?: string;
  pages?: string[];
}) {
  const c = useComments(path);
  const layer = useRef<HTMLDivElement>(null);
  const box = usePictureBox(picture, layer, !!c);
  const open = !!c && (c.active !== null || c.draft !== null);
  useEscape(() => c?.store.set({ active: null, draft: null }), open);
  useEscape(() => c?.store.set({ adding: false }), !!c?.adding && !open);
  if (!c) return null;

  const [W, H] = size && size[0] > 0 && size[1] > 0 ? size : [picture.current?.naturalWidth || 1920, picture.current?.naturalHeight || 1080];
  const here = onPage(c.threads, page, pages).filter((thread) => placeOf(thread, names) === frame);
  const shown = here.filter((thread) => !thread.resolved || thread.id === c.active);
  const active = here.find((thread) => thread.id === c.active) ?? null;
  const draft = c.draft && c.draft.frame === frame && (c.draft.page ?? "") === (page ?? "") ? c.draft : null;
  const at = (spot: { x: number; y: number }) => (box ? { x: box.left + (spot.x / W) * box.width, y: box.top + (spot.y / H) * box.height } : { x: 0, y: 0 });
  const pin = "pointer-events-auto absolute flex size-7 -translate-y-full items-center justify-center rounded-full rounded-bl-none border-2 border-white text-[11px] font-semibold text-white shadow-md";

  return (
    <div ref={layer} className="pointer-events-none absolute inset-0" data-testid="comment-layer" dir="ltr">
      {c.adding && box && (
        <div data-testid="comment-target" title={t("commentHint")} className="pointer-events-auto absolute cursor-crosshair"
             style={{ left: box.left, top: box.top, width: box.width, height: box.height }}
             onDoubleClick={(e) => e.stopPropagation()}
             onClick={(e) => {
               const r = e.currentTarget.getBoundingClientRect();
               if (!r.width || !r.height) return;
               c.store.pin({ ...(page ? { page } : {}), frame, ...(names[frame] ? { frame_name: names[frame] } : {}),
                             x: round(((e.clientX - r.left) / r.width) * W), y: round(((e.clientY - r.top) / r.height) * H) });
             }} />
      )}
      {box && shown.map((thread) => {
        const p = at(thread);
        const who = nameOf(c, thread.author);
        return (
          <button key={thread.id} data-testid="comment-pin" data-thread={thread.id}
                  aria-label={`${t("comment")} ${thread.n} — ${who}`} title={`${who}: ${thread.text.slice(0, 120)}`}
                  aria-expanded={thread.id === c.active}
                  onClick={(e) => { e.stopPropagation(); c.store.open(thread.id === c.active ? null : thread.id); }}
                  onDoubleClick={(e) => e.stopPropagation()}
                  style={{ left: p.x, top: p.y, background: thread.author.agent ? "#111827" : peerColor(thread.author.id) }}
                  className={cn(pin, "transition-transform hover:z-10 hover:scale-110 cursor-pointer",
                                thread.resolved && "opacity-60", thread.id === c.active && "z-10 scale-110 ring-2 ring-foreground/50")}>
            {thread.author.image && !thread.author.agent
              ? <img src={thread.author.image} alt="" className="size-full rounded-full rounded-bl-none object-cover" />
              : initial(who)}
          </button>
        );
      })}
      {box && draft && (
        <>
          <span data-testid="comment-draft-pin" style={{ left: at(draft).x, top: at(draft).y, background: c.host.me ? peerColor(c.host.me.id) : "#111827" }}
                className={cn(pin, "z-10 animate-pulse")}>{initial(c.host.me?.name ?? "+")}</span>
          <Beside at={at(draft)} within={box}>
            <div className="p-2" data-testid="comment-new">
              <Writer placeholder={t("addComment")} focus onCancel={() => c.store.set({ draft: null })}
                      onSend={async (text) => { await c.store.add(draft, text); track("design_comment_added", {}); }} />
            </div>
          </Beside>
        </>
      )}
      {box && active && !draft && <Beside at={at(active)} within={box}><ThreadCard c={c} thread={active} /></Beside>}
    </div>
  );
}

// Open comments per slide, for the filmstrip's and grid's badges.
export function useCommentCounts(path: string | undefined, names: string[], page?: string, pages: string[] = []): number[] {
  const c = useComments(path);
  const counts = names.map(() => 0);
  for (const thread of c ? onPage(c.threads, page, pages) : []) {
    const place = thread.resolved ? null : placeOf(thread, names);
    if (place !== null) counts[place] += 1;
  }
  return counts;
}

export function CommentButtons({ path, onComment, onList, className }: {
  path: string;
  onComment?: (adding: boolean) => void;   // comment mode toggled (the caller may switch to the preview)
  onList?: () => void;
  className?: string;
}) {
  const c = useComments(path);
  if (!c) return null;
  const open = c.threads.filter((thread) => !thread.resolved).length;
  const button = "relative flex size-7 shrink-0 items-center justify-center rounded-md transition-colors cursor-pointer";
  return (
    <div className={cn("flex shrink-0 items-center gap-0.5", className)} data-testid="comment-buttons">
      <button aria-pressed={c.adding} aria-label={t("addComment")} title={`${t("addComment")} (C)`}
              onClick={() => { const adding = !c.adding; c.store.set({ adding, draft: null, listing: false }); onComment?.(adding); }}
              className={cn(button, c.adding ? "bg-foreground text-background" : "text-muted-foreground hover:bg-secondary/80 hover:text-foreground")}>
        <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 11.5a8.4 8.4 0 01-8.5 8.5 8.6 8.6 0 01-3.9-.9L3 21l1.9-5.6A8.4 8.4 0 0112.5 3 8.4 8.4 0 0121 11.5z" />
          <path strokeLinecap="round" d="M12.5 8.5v6m-3-3h6" />
        </svg>
      </button>
      <button aria-pressed={c.listing} aria-label={t("comments")} title={t("comments")} data-testid="comments-open"
              onClick={() => { const listing = !c.listing; c.store.set({ listing }); if (listing) onList?.(); }}
              className={cn(button, c.listing ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary/80 hover:text-foreground")}>
        <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h10" />
        </svg>
        {open > 0 && (
          <span data-testid="comments-count" className="absolute -end-1 -top-1 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-red-500 px-0.5 text-[9px] font-semibold leading-none text-white tabular-nums">
            {open > 99 ? "99+" : open}
          </span>
        )}
      </button>
    </div>
  );
}

// Every thread, open or resolved, in a side sheet; a row opens its thread on its slide.
export function CommentsList({ path, names, page, pages = [], paper, onGo, onPage: goToPage }: {
  path: string;
  names: string[];                       // the slides of the page in view, by name
  page?: string;
  pages?: string[];
  paper?: boolean;                       // a document: its slides are pages
  onGo?: (frame: number) => void;        // show that slide
  onPage?: (page: string) => void;       // show that page of the design
}) {
  const c = useComments(path);
  const [tab, setTab] = useState<"open" | "resolved">("open");
  useEscape(() => c?.store.set({ listing: false }), !!c?.listing);
  if (!c?.listing) return null;
  const close = () => c.store.set({ listing: false });
  const here = new Set(onPage(c.threads, page, pages).map((thread) => thread.id));
  const opened = c.threads.filter((thread) => !thread.resolved), closed = c.threads.filter((thread) => thread.resolved);
  const rows = (tab === "open" ? opened : closed).slice().sort((a, b) => b.n - a.n);
  const where = (thread: CommentThread) => {
    if (!here.has(thread.id)) return thread.page ?? "";
    const place = placeOf(thread, names);
    if (place === null) return t(paper ? "commentPageGone" : "commentSlideGone");
    return names.length > 1 ? `${t(paper ? "commentOnPage" : "commentOnSlide").replace("{n}", String(place + 1))}` : "";
  };
  const pick = (thread: CommentThread) => {
    if (here.has(thread.id)) {
      const place = placeOf(thread, names);
      if (place !== null) onGo?.(place);
    } else if (thread.page) {
      goToPage?.(thread.page);
    }
    c.store.set({ active: thread.id, draft: null, listing: false });
  };
  const ask = () => {
    // Prefills the composer; the agent reads the comments with its Design tool.
    window.dispatchEvent(new CustomEvent("cycls:compose", { detail: { text: t("commentsAskText").replace("{path}", path) } }));
    track("design_comments_asked", { open: opened.length });
    close();
  };
  const item = (on: boolean) => cn("rounded-md px-2.5 py-1 text-xs transition-colors cursor-pointer",
    on ? "bg-background font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground");
  return (
    <div className="absolute inset-0 z-20 flex justify-end bg-black/20" onClick={close}>
      <div className="flex h-full w-80 max-w-full flex-col border-s border-border bg-background shadow-xl"
           role="dialog" aria-label={t("comments")} data-testid="comments-list" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="text-sm font-medium text-foreground">{t("comments")}</div>
          <button onClick={close} aria-label={t("close")} className="flex size-6 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground">
            <svg className="size-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>
        <div className="flex items-center gap-2 border-b border-border px-3 py-2">
          <div className="flex rounded-lg bg-secondary p-0.5" role="group">
            <button aria-pressed={tab === "open"} onClick={() => setTab("open")} className={item(tab === "open")}>{t("commentsOpen")} {opened.length || ""}</button>
            <button aria-pressed={tab === "resolved"} onClick={() => setTab("resolved")} className={item(tab === "resolved")}>{t("commentResolved")} {closed.length || ""}</button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {!c.loaded && <div className="p-3 text-xs text-muted-foreground">{t("loading")}</div>}
          {c.loaded && rows.length === 0 && (
            <div className="p-3 text-xs leading-relaxed text-muted-foreground">
              {t(tab === "resolved" ? "commentsNoneResolved" : closed.length ? "commentsNoneOpen" : "commentsNone")}
            </div>
          )}
          {rows.map((thread) => (
            <button key={thread.id} onClick={() => pick(thread)} data-testid="comment-row"
                    className="flex w-full gap-2 rounded-lg px-2.5 py-2 text-start hover:bg-secondary/60 cursor-pointer">
              <Avatar c={c} author={thread.author} />
              <span className="min-w-0 flex-1">
                <span className="flex items-baseline gap-1.5">
                  <span className="min-w-0 truncate text-xs font-medium text-foreground" dir="auto">{nameOf(c, thread.author)}</span>
                  <span className="shrink-0 text-[10px] text-muted-foreground">{timeAgo(thread.updated)}</span>
                  <span className="flex-1" />
                  <span className="shrink-0 text-[10px] text-muted-foreground tabular-nums">#{thread.n}</span>
                </span>
                <span className="line-clamp-2 block whitespace-pre-wrap break-words text-xs text-foreground" dir="auto">{thread.text}</span>
                <span className="mt-0.5 flex items-center gap-2 text-[10px] text-muted-foreground">
                  {where(thread) && <span className="min-w-0 truncate" dir="auto">{where(thread)}</span>}
                  {thread.replies.length > 0 && (
                    <span className="shrink-0">{thread.replies.length === 1 ? t("commentOneReply") : t("commentReplies").replace("{n}", String(thread.replies.length))}</span>
                  )}
                </span>
              </span>
            </button>
          ))}
        </div>
        {opened.length > 0 && (
          <div className="border-t border-border p-2">
            <button onClick={ask} data-testid="comments-ask"
                    className="w-full cursor-pointer rounded-lg bg-secondary px-3 py-2 text-xs font-medium text-foreground transition-colors hover:bg-secondary/80">
              {t("commentsAsk").replace("{agent}", c.host.agent || t("commentsTheAgent"))}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
