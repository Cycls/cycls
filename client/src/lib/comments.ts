import { createContext, useContext, useEffect, useSyncExternalStore } from "react";

// Comments on a design (cycls/_agent/design/comments.py): a pin on a spot of a slide,
// and the thread under it. The workspace keeps them, so everyone it lets in reads and
// answers the same ones; nothing is pushed to a browser, so an open design asks again
// every few seconds, naming the version it has — and is told "unchanged" nearly always.
//
// One store a design, shared by whatever shows it — the slide's pins, the list, the
// buttons in the header, the editor — so they agree on what is open and ask once.

export interface CommentAuthor { id: string; name: string; image?: string; agent?: boolean }
export interface CommentReply { id: string; author: CommentAuthor; text: string; at: string; edited?: string }
// Where a pin is: a slide — its place on the page from 0, and its name, which outlives
// a reorder — and a point on it, in the slide's own pixels.
export interface CommentSpot { page?: string; frame: number; frame_name?: string; x: number; y: number }
export interface CommentThread extends CommentSpot {
  id: string;
  n: number;                    // its number in the design: given once, never again
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
export type CommentChange =
  | { op: "reply"; text: string }
  | { op: "resolve" | "reopen" }
  | { op: "edit"; text: string; reply?: string }
  | { op: "delete"; reply?: string }
  | ({ op: "move" } & CommentSpot);

type Named = { name?: string; image?: string };
export interface CommentsApi {
  list: (path: string, version?: string) => Promise<{ threads?: CommentThread[]; version: string; me?: string; unchanged?: boolean }>;
  add: (path: string, body: CommentSpot & { text: string } & Named) => Promise<{ thread: CommentThread }>;
  change: (path: string, id: string, body: CommentChange & Named) => Promise<{ thread: CommentThread | null }>;
}
// What a page of the app gives its designs to comment with: the routes, who this is
// (their name is the browser's — the server knows only an id), and the agent's name.
export interface CommentsHost { api: CommentsApi; me?: { id: string; name: string; image?: string }; agent?: string }
export const CommentsContext = createContext<CommentsHost | null>(null);

// Which of a page's slides — `names`, in order — a thread is on now, from 0, or null
// when its slide is gone. A slide's name is given once and kept, so the name finds the
// slide wherever it is now — and a name no slide has is a slide that was deleted, not
// whichever slide took its place. A page of one slide has everything pinned on it; a
// thread that names no slide, or a name several share, goes by the place. (As the
// server's `comments.place`.)
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

// The threads pinned on `page` of a design whose pages are `pages`, in order. A design
// of one page has them all — its page renamed is still its page.
export function onPage(threads: CommentThread[], page: string | undefined, pages: string[]): CommentThread[] {
  if (pages.length <= 1) return threads;
  return threads.filter((t) => (t.page || pages[0]) === (page || pages[0]));
}

export interface CommentsState {
  threads: CommentThread[];
  version: string;
  loaded: boolean;
  me?: string;                  // this person's id, as the server has it
  adding: boolean;              // a click on the slide pins a new comment
  listing: boolean;             // the list of threads is open
  showResolved: boolean;
  active: string | null;        // the thread that is open
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

  // Something on the page shows this design's comments: ask now, then keep asking while
  // it does and the tab is looked at.
  watch = () => {
    if (++this.watchers === 1) {
      void this.refresh();
      this.timer = setInterval(() => { if (document.visibilityState !== "hidden") void this.refresh(); }, EVERY_MS);
      document.addEventListener("visibilitychange", this.onSeen);
      window.addEventListener("cycls:design-command", this.onCommand);
    }
    return () => {
      if (--this.watchers > 0) return;
      if (this.timer) clearInterval(this.timer);
      this.timer = null;
      document.removeEventListener("visibilitychange", this.onSeen);
      window.removeEventListener("cycls:design-command", this.onCommand);
    };
  };

  private onSeen = () => { if (document.visibilityState !== "hidden") void this.refresh(); };
  // The agent just changed this design: it may have answered a comment on its way.
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
      } catch { /* out of reach for a moment: what is shown stays, and it asks again */ } finally {
        this.asking = null;
      }
    })();
    return this.asking;
  };

  private who(): Named {
    const me = this.host.me;
    return me ? { name: me.name, ...(me.image ? { image: me.image } : {}) } : {};
  }

  // What the server answered is shown at once; the list is then asked for whole, with
  // the version this page had before — so a teammate's change made meanwhile isn't
  // skipped by taking the newer version on the strength of one thread.
  private took(thread: CommentThread | null, id: string) {
    const rest = this.state.threads.filter((t) => t.id !== (thread?.id ?? id));
    this.set({ threads: thread ? [...rest, thread].sort((a, b) => a.n - b.n) : rest,
               active: thread ? this.state.active : this.state.active === id ? null : this.state.active });
    void this.refresh();
  }

  async add(spot: CommentSpot, text: string): Promise<CommentThread> {
    const { thread } = await this.host.api.add(this.path, { ...spot, text, ...this.who() });
    this.took(thread, thread.id);
    this.set({ draft: null, active: thread.id });
    return thread;
  }

  async change(id: string, body: CommentChange): Promise<void> {
    const { thread } = await this.host.api.change(this.path, id, { ...body, ...this.who() });
    this.took(thread, id);
  }

  // Start a new comment at `spot`: whatever was open closes.
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
// (For tests: every design starts with nothing known.)
export function forgetComments() { stores.clear(); }

const nothing = () => () => {};
const none = () => START;

// A design's comments, where the page can comment (null where it can't — a shared
// page, a deployment signed out). `path` is the design's `.fig`.
export function useComments(path: string | undefined): (CommentsState & { store: CommentStore; host: CommentsHost }) | null {
  const host = useContext(CommentsContext);
  const store = path && host ? commentStore(path, host) : null;
  const state = useSyncExternalStore(store?.subscribe ?? nothing, store?.get ?? none);
  useEffect(() => store?.watch(), [store]);
  return store && host ? { ...state, store, host } : null;
}
