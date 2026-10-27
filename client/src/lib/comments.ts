import { createContext, useContext, useEffect, useSyncExternalStore } from "react";

// Design comments (cycls/_agent/design/comments.py). Nothing is pushed: an open design polls
// with its version and is nearly always told "unchanged". One store per design, shared by
// every view of it, so they agree on what is open and poll once.

export interface CommentAuthor { id: string; name: string; image?: string; agent?: boolean }
// `word`: a Word document's reply, by its Word comment id (the file names it so too).
export interface CommentReply { id: string; author: CommentAuthor; text: string; at: string; edited?: string; word?: string }
// A slide (index, and name, which survives a reorder) and a point in its own pixels.
export interface CommentSpot { page?: string; frame: number; frame_name?: string; x: number; y: number }
// A workbook's cell: the sheet's id (its name beside it, for people), and the cell — null once its row or
// column was removed (the thread stays, on no cell).
export interface CellSpot { sheet: string; sheet_name?: string; cell: string | null }
export interface CommentThread extends CommentSpot {
  id: string;
  n: number;                    // its number in the design, never reused
  author: CommentAuthor;
  text: string;
  at: string;
  updated: string;
  edited?: string;
  resolved: boolean;
  resolved_by?: CommentAuthor;
  resolved_at?: string;
  replies: CommentReply[];
}
// A workbook's thread: the same record, pinned to a cell instead of a slide's spot.
export type SheetCommentThread = Omit<CommentThread, keyof CommentSpot> & CellSpot;
// A Word document's words: the paragraph (its id), the words, and the Word comment id the file names it by. The
// file holds the comment too (for Word); this record mirrors it (cycls/_agent/office/docs_comments.py).
export interface DocSpot { para?: string; quote?: string; word?: string }
export type DocCommentThread = Omit<CommentThread, keyof CommentSpot> & DocSpot;
export type CommentChange =
  | { op: "reply"; text: string; word?: string }
  | { op: "resolve" | "reopen" }
  | { op: "edit"; text: string; reply?: string }
  | { op: "delete"; reply?: string }
  | ({ op: "move" } & (CommentSpot | CellSpot));

type Named = { name?: string; image?: string };
export interface CommentsApi {
  list: (path: string, version?: string) => Promise<{ threads?: CommentThread[]; version: string; me?: string; unchanged?: boolean }>;
  add: (path: string, body: (CommentSpot | CellSpot | DocSpot) & { text: string } & Named) => Promise<{ thread: CommentThread }>;
  change: (path: string, id: string, body: CommentChange & Named) => Promise<{ thread: CommentThread | null }>;
}
// `me.name` comes from the browser: the server knows only an id.
export interface CommentsHost { api: CommentsApi; me?: { id: string; name: string; image?: string }; agent?: string }
export const CommentsContext = createContext<CommentsHost | null>(null);

// The slide a thread is on now, or null if deleted (as the server's `comments.place`). Names
// outlive reorders, so an unknown name is a deleted slide; no name, or a shared one, uses the index.
export function placeOf(thread: Pick<CommentThread, "frame" | "frame_name">, names: string[]): number | null {
  const { frame, frame_name: name } = thread;
  if (names.length === 1) return 0;
  if (name && !(frame >= 0 && frame < names.length && names[frame] === name)) {
    const named = names.flatMap((n, i) => (n === name ? [i] : []));
    if (named.length === 1) return named[0];
    if (!named.length) return null;
  }
  return frame >= 0 && frame < names.length ? frame : null;
}

// A one-page design has every thread: its page renamed is still its page.
export function onPage(threads: CommentThread[], page: string | undefined, pages: string[]): CommentThread[] {
  if (pages.length <= 1) return threads;
  return threads.filter((t) => (t.page || pages[0]) === (page || pages[0]));
}

export interface CommentsState {
  threads: CommentThread[];
  version: string;
  loaded: boolean;
  me?: string;                  // this person's id, as the server has it
  adding: boolean;              // comment mode: a click on the slide pins a new comment
  listing: boolean;
  showResolved: boolean;
  active: string | null;
  draft: CommentSpot | null;    // where a comment being written will be pinned
}

const EVERY_MS = 5000;
const START: CommentsState = { threads: [], version: "", loaded: false, adding: false, listing: false, showResolved: false, active: null, draft: null };

export class CommentStore {
  private state: CommentsState = START;
  private readonly listeners = new Set<() => void>();
  private watchers = 0;
  private timer: ReturnType<typeof setInterval> | null = null;
  private asking: Promise<void> | null = null;

  constructor(readonly path: string, public host: CommentsHost) {}

  get = () => this.state;

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  set(patch: Partial<CommentsState>) {
    this.state = { ...this.state, ...patch };
    for (const listener of this.listeners) listener();
  }

  // Poll while anything shows this design and the tab is visible.
  watch = () => {
    if (++this.watchers === 1) {
      void this.refresh();
      this.timer = setInterval(() => { if (document.visibilityState !== "hidden") void this.refresh(); }, EVERY_MS);
      document.addEventListener("visibilitychange", this.onSeen);
      window.addEventListener("cycls:design-command", this.onCommand);
      window.addEventListener("cycls:sheets-command", this.onCommand);
    }
    return () => {
      if (--this.watchers > 0) return;
      if (this.timer) clearInterval(this.timer);
      this.timer = null;
      document.removeEventListener("visibilitychange", this.onSeen);
      window.removeEventListener("cycls:design-command", this.onCommand);
      window.removeEventListener("cycls:sheets-command", this.onCommand);
    };
  };

  private onSeen = () => { if (document.visibilityState !== "hidden") void this.refresh(); };
  // An agent edit may have answered a comment.
  private onCommand = (e: Event) => {
    if ((e as CustomEvent<{ path?: string }>).detail?.path === this.path) void this.refresh();
  };

  refresh = (): Promise<void> => {
    this.asking ??= (async () => {
      try {
        const got = await this.host.api.list(this.path, this.state.version || undefined);
        if (got.unchanged || !got.threads) {
          if (!this.state.loaded) this.set({ loaded: true });
          return;
        }
        const here = new Set(got.threads.map((t) => t.id));
        this.set({ threads: got.threads, version: got.version, me: got.me, loaded: true,
                   active: this.state.active && here.has(this.state.active) ? this.state.active : null });
      } catch { /* offline for a moment: keep what's shown */ } finally {
        this.asking = null;
      }
    })();
    return this.asking;
  };

  private who(): Named {
    const me = this.host.me;
    return me ? { name: me.name, ...(me.image ? { image: me.image } : {}) } : {};
  }

  // Show the answer now, then refetch with the old version: taking the new one from a
  // single thread would skip a teammate's change made meanwhile.
  private took(thread: CommentThread | null, id: string) {
    const rest = this.state.threads.filter((t) => t.id !== (thread?.id ?? id));
    this.set({ threads: thread ? [...rest, thread].sort((a, b) => a.n - b.n) : rest,
               active: thread ? this.state.active : this.state.active === id ? null : this.state.active });
    void this.refresh();
  }

  async add(spot: CommentSpot | CellSpot | DocSpot, text: string): Promise<CommentThread> {
    const { thread } = await this.host.api.add(this.path, { ...spot, text, ...this.who() });
    this.took(thread, thread.id);
    this.set({ draft: null, active: thread.id });
    return thread;
  }

  async change(id: string, body: CommentChange): Promise<void> {
    const { thread } = await this.host.api.change(this.path, id, { ...body, ...this.who() });
    this.took(thread, id);
  }

  pin(spot: CommentSpot) { this.set({ draft: spot, active: null }); }
  open(id: string | null) { this.set({ active: id, draft: null }); }
}

const stores = new Map<string, CommentStore>();
export function commentStore(path: string, host: CommentsHost): CommentStore {
  let store = stores.get(path);
  if (!store) stores.set(path, (store = new CommentStore(path, host)));
  store.host = host;
  return store;
}
// For tests.
export function forgetComments() { stores.clear(); }

const nothing = () => () => {};
const none = () => START;

// null where the page can't comment (a shared page, signed out).
export function useComments(path: string | undefined): (CommentsState & { store: CommentStore; host: CommentsHost }) | null {
  const host = useContext(CommentsContext);
  const store = path && host ? commentStore(path, host) : null;
  const state = useSyncExternalStore(store?.subscribe ?? nothing, store?.get ?? none);
  useEffect(() => store?.watch(), [store]);
  return store && host ? { ...state, store, host } : null;
}
