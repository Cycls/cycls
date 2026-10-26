// Typed access to window.cycls (the host shim, _ref/app-shim.branch.ts) and the React
// hooks every default app uses. Read kit/README.md first; the traps below are real.
//
// MODE is decided ONCE per document:
//   live        the shim answered ready AND a data call answered
//   gallery     the shim is there but data is refused (shared / gallery view), or the
//               host never answers data (the mobile host has no cycls:data yet)
//   standalone  no window.cycls, or `ready` did not resolve within 2.5 s
// In gallery/standalone the hooks serve the app's demo data, read-only: writes land in
// memory and a "demo" toast says so.
//
// Traps in the shim this file works around (verified against the reference code):
//  1. cycls.get/all() load the shared shelf ONCE and never re-read it; a load that fails
//     is cached as an empty shelf. So the shared shelf cannot be re-read in place: on a
//     turn_end the kit reloads the document (see requestRefresh), keeping view state.
//  2. cycls.get/all() never reject, even in a gallery view: they cannot detect the mode.
//     The probe uses cycls.me.get, which does reject.
//  3. users.all(prefix) matches `prefix` against "<user>/<key>", i.e. the USER ID first.
//     Call users.all() with no prefix and filter keys yourself (allMembers below).
//  4. update(key, fn) runs fn on a FRESH read — and if fn throws, nothing is written.
//     The kit uses that for create-only (throw if present) and patch (throw if gone).
//  5. cycls.ask and cycls.onCommand only exist on the feat/agent-design-extensions host.
import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { plain } from "./format";

// ---- the shim's surface --------------------------------------------------------------

export type HostTokens = { light: Record<string, string>; dark: Record<string, string> };
// `tokens`: the workspace's app theme (shadcn variables, light and dark), from a host that has one.
export interface CyclsCtx { path: string; scope: string; theme?: string; locale?: string; canWrite: boolean; tokens?: HostTokens | null }
export interface Row<T = unknown> { key: string; value: T }
export interface MemberRow<T = unknown> { user: string; key: string; value: T }
export interface Page<R> { rows: R[]; truncated: boolean }
interface Shelf {
  get<T>(key: string, fallback?: T): Promise<T | undefined>;
  set(key: string, value: unknown): Promise<unknown>;
  remove(key: string): Promise<unknown>;
  all<T>(prefix?: string): Promise<Page<Row<T>>>;
}
export interface CyclsApi {
  ctx: CyclsCtx | null;
  ready: Promise<CyclsCtx>;
  read(path: string): Promise<string>;
  write(path: string, content: string): Promise<void>;
  save(name: string, content: string): Promise<string>;
  get<T>(key: string, fallback?: T): Promise<T | undefined>;
  set(key: string, value: unknown): Promise<void>;
  update<T>(key: string, fn: (cur: T | undefined) => T | Promise<T>): Promise<T>;
  all(): Promise<Record<string, unknown>>;
  keys(): Promise<string[]>;
  flush(): Promise<void>;
  me: Shelf;
  users: {
    all<T>(prefix?: string): Promise<Page<MemberRow<T>>>;
    get<T>(user: string, key: string): Promise<T | undefined>;
    set(user: string, key: string, value: unknown): Promise<unknown>;
    remove(user: string, key: string): Promise<unknown>;
  };
  connector(name: string): {
    fetch(path: string, init?: { method?: string; headers?: Record<string, string>; body?: string }): Promise<{ status: number; body: string; contentType: string }>;
    json<T = unknown>(path: string, init?: { method?: string; headers?: Record<string, string>; body?: string }): Promise<T>;
  };
  resize(h: number): void;
  onCommand?: (fn: (command: { type?: string; [k: string]: unknown }) => void) => () => void;
  ask?: (text: string) => Promise<void>;
  engine?: (op: string, payload?: Record<string, unknown>) => Promise<unknown>;
}

declare global { interface Window { cycls?: CyclsApi } }

export const cycls = (): CyclsApi | undefined => (typeof window !== "undefined" ? window.cycls : undefined);
export const features = {
  get onCommand() { return typeof cycls()?.onCommand === "function"; },
  get ask() { return typeof cycls()?.ask === "function"; },
  get engine() { return typeof cycls()?.engine === "function"; },
};

// ---- mode ----------------------------------------------------------------------------

export type Mode = "live" | "gallery" | "standalone";
export type ModeReason = "ok" | "no-shim" | "no-ready" | "no-workspace" | "no-answer";
export interface Detected { mode: Mode; reason: ModeReason; ctx: CyclsCtx | null }

export const READY_TIMEOUT_MS = 2500;
const PROBE_TIMEOUT_MS = 6000;
const CALL_TIMEOUT_MS = 15000;

class Timeout extends Error { constructor(what: string) { super(`${what}: the host did not answer`); this.name = "Timeout"; } }
export function withTimeout<T>(p: Promise<T>, ms: number, what = "cycls"): Promise<T> {
  return new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Timeout(what)), ms);
    p.then((v) => { clearTimeout(t); res(v); }, (e) => { clearTimeout(t); rej(e); });
  });
}

let detecting: Promise<Detected> | null = null;
let lateLive: Promise<Detected | null> | null = null;
/** Decides the mode once per document. Every hook awaits the same answer. */
export function detectMode(): Promise<Detected> {
  if (detecting) return detecting;
  detecting = (async (): Promise<Detected> => {
    const c = cycls();
    if (!c) return { mode: "standalone", reason: "no-shim", ctx: null };
    let ctx: CyclsCtx;
    try { ctx = await withTimeout(c.ready, READY_TIMEOUT_MS, "ready"); }
    catch { return { mode: "standalone", reason: "no-ready", ctx: null }; }
    const probe = c.me.get("kit:probe");
    try {
      await withTimeout(probe, PROBE_TIMEOUT_MS, "probe");
      return { mode: "live", reason: "ok", ctx };
    } catch (e) {
      if (e instanceof Timeout) {
        // Not final: a slow host that answers later turns the app live (CyclsProvider
        // listens). A host that never answers (mobile, no cycls:data yet) stays in demo.
        lateLive = probe.then(() => ({ mode: "live" as Mode, reason: "ok" as ModeReason, ctx }), () => null);
        return { mode: "gallery", reason: "no-answer", ctx };
      }
      // A gallery bridge refuses with no HTTP status ("this view has no workspace").
      // A status means a live workspace that errored (401, 500…): stay live, say so.
      const status = (e as { status?: number }).status;
      if (typeof status === "number") return { mode: "live", reason: "ok", ctx };
      return { mode: "gallery", reason: "no-workspace", ctx };
    }
  })();
  return detecting;
}

let adminProbe: Promise<boolean> | null = null;
/** Lazy: users.all rejects (403) for a non-admin. The prefix matches no user id. */
export function checkAdmin(): Promise<boolean> {
  if (!adminProbe) adminProbe = detectMode().then(async (d) => {
    if (d.mode !== "live") return false;
    try { await withTimeout(cycls()!.users.all("~kit-admin-probe"), CALL_TIMEOUT_MS, "users.all"); return true; }
    catch { return false; }
  });
  return adminProbe;
}

// ---- errors --------------------------------------------------------------------------

export class KitError extends Error {
  code: "exists" | "gone" | "demo" | "no-host";
  constructor(code: KitError["code"], message: string) { super(message); this.code = code; this.name = "KitError"; }
}
/** One readable line for a toast. */
export function errorText(e: unknown): string {
  const m = String((e as Error)?.message ?? e ?? "error");
  const json = /\{"detail":"([^"]+)"\}/.exec(m);
  return (json ? json[1] : m).slice(0, 200);
}

// ---- view state that survives the refresh reload --------------------------------------
// window.name belongs to the browsing context, so it survives location.reload() of the
// sandboxed srcdoc frame (nothing else does: storage is in-memory there).

type ViewState = Record<string, unknown>;
const NAME_TAG = "cycls-kit:";
function readName(): ViewState {
  try { return window.name.startsWith(NAME_TAG) ? JSON.parse(window.name.slice(NAME_TAG.length)) : {}; } catch { return {}; }
}
const viewState: ViewState = readName();
function writeName() { try { window.name = NAME_TAG + JSON.stringify(viewState); } catch { /* ignore */ } }
export function getView<T>(key: string, fallback: T): T { return (key in viewState ? viewState[key] : fallback) as T; }
export function setView(key: string, value: unknown) { viewState[key] = value; writeName(); }

/** useState that survives the turn_end reload (filters, tab, open record…). */
export function useViewState<T>(key: string, initial: T): [T, (v: T | ((p: T) => T)) => void] {
  const [v, setV] = useState<T>(() => getView(key, initial));
  const set = useCallback((next: T | ((p: T) => T)) => {
    setV((prev) => {
      const value = typeof next === "function" ? (next as (p: T) => T)(prev) : next;
      setView(key, value);
      return value;
    });
  }, [key]);
  return [v, set];
}

// ---- refresh on turn_end ---------------------------------------------------------------

let sharedReaders = 0;           // mounted hooks that read the shared shelf
let busy = 0;                    // writes in flight
const holds = new Set<symbol>(); // open dialogs, drags…
const refetchers = new Set<() => void>();
let refreshWanted = false;
let commandsWired = false;
export const REFRESH_SCROLL_KEY = "kit:scroll";

/** Keep the document from reloading while the person is mid-gesture. Returns a release. */
export function holdRefresh(): () => void {
  const s = Symbol("hold");
  holds.add(s);
  return () => { holds.delete(s); maybeRefresh(); };
}
function editing(): boolean {
  const a = document.activeElement as HTMLElement | null;
  return !!a && (a.tagName === "INPUT" || a.tagName === "TEXTAREA" || a.tagName === "SELECT" || a.isContentEditable);
}
async function maybeRefresh() {
  if (!refreshWanted || busy > 0 || holds.size > 0 || editing()) return;
  refreshWanted = false;
  if (sharedReaders === 0) { refetchers.forEach((f) => f()); return; }
  try { await cycls()?.flush(); } catch { /* the failed write already toasted */ }
  setView(REFRESH_SCROLL_KEY, { x: window.scrollX, y: window.scrollY });
  setView("kit:theme-boot", document.documentElement.dataset.theme ?? null);
  location.reload();
}
/** Ask for fresh data: in-place for cycls.me, a state-keeping reload for the shared shelf. */
export function requestRefresh() { refreshWanted = true; void maybeRefresh(); }
if (typeof document !== "undefined") document.addEventListener("focusout", () => setTimeout(maybeRefresh, 50));

function wireCommands() {
  if (commandsWired) return;
  commandsWired = true;
  const c = cycls();
  if (!c?.onCommand) return;
  c.onCommand((cmd) => { if (cmd?.type === "turn_end" || cmd?.type === "data_changed") requestRefresh(); });
}

async function track<T>(p: Promise<T>): Promise<T> {
  busy++;
  try { return await p; } finally { busy--; setTimeout(maybeRefresh, 0); }
}

// ---- context -------------------------------------------------------------------------

export interface CyclsState extends Detected {
  /** true until the mode is known */
  pending: boolean;
  /** mode !== "live": hooks serve demo data and writes stay in memory */
  demo: boolean;
  locale: string;
  theme: "light" | "dark" | null;
  canWrite: boolean;
  isAdmin: boolean | null;
  checkAdmin: () => Promise<boolean>;
}

const Ctx = createContext<CyclsState | null>(null);

export function CyclsProvider({ children }: { children: ReactNode }) {
  const [d, setD] = useState<Detected | null>(null);
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  useEffect(() => {
    let live = true;
    const apply = (r: Detected) => {
      if (!live) return;
      setD(r);
      if (r.mode === "live") wireCommands();
      document.documentElement.dataset.cyclsMode = r.mode;
    };
    detectMode().then((r) => {
      apply(r);
      if (r.reason === "no-answer") lateLive?.then((l) => { if (l) apply(l); });
    });
    return () => { live = false; };
  }, []);
  const doCheck = useCallback(() => checkAdmin().then((a) => { setIsAdmin(a); return a; }), []);
  const value = useMemo<CyclsState>(() => {
    const det = d ?? { mode: "standalone" as Mode, reason: "no-ready" as ModeReason, ctx: null };
    const t = det.ctx?.theme;
    return {
      ...det, pending: !d, demo: det.mode !== "live",
      locale: det.ctx?.locale || (typeof navigator !== "undefined" ? navigator.language : "en") || "en",
      theme: t === "dark" || t === "light" ? t : null,
      canWrite: !!det.ctx?.canWrite && det.mode === "live",
      isAdmin, checkAdmin: doCheck,
    };
  }, [d, isAdmin, doCheck]);
  return createElement(Ctx.Provider, { value }, children);
}

export function useCycls(): CyclsState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useCycls() needs <CyclsProvider> (AppShell includes it)");
  return v;
}

/** Mounting it triggers the admin probe; null while unknown. */
export function useIsAdmin(): boolean | null {
  const { isAdmin, checkAdmin: check, mode, pending } = useCycls();
  useEffect(() => { if (!pending && mode === "live" && isAdmin === null) void check(); }, [pending, mode, isAdmin, check]);
  return mode === "live" ? isAdmin : false;
}

// ---- demo writes -----------------------------------------------------------------------

let demoToastText = "Demo — changes are not saved";
export function setDemoToastText(text: string) { demoToastText = text; }
function demoToast() { toast.info(demoToastText, { id: "kit-demo" }); }

// ---- useCollection: one row per record -------------------------------------------------

export type Status = "loading" | "ready" | "error";
export interface Record_ { id: string }
export interface CollectionOptions<T> {
  /** Demo records, shown in gallery/standalone (and loadable into an empty live shelf). */
  demo?: T[] | (() => T[]);
  /** Stamped on every write by the app (updatedAt/updatedBy). Default adds updatedAt + updatedBy:"user". */
  stamp?: (value: T) => T;
  /** Records the app cannot read are dropped (and counted in `invalid`). */
  validate?: (value: unknown) => value is T;
}
export interface Collection<T extends Record_> {
  items: T[];
  status: Status;
  error: string | null;
  demo: boolean;
  /** rows under the prefix that failed `validate` */
  invalid: number;
  add(value: T): Promise<T | undefined>;
  update(id: string, patch: Partial<T> | ((cur: T) => T)): Promise<T | undefined>;
  remove(id: string): Promise<void>;
  /** Writes the demo records into an empty live shelf (the "load example" button). */
  loadDemo(): Promise<void>;
  keyOf(id: string): string;
}

const defaultStamp = <T,>(v: T): T => ({ ...(v as object), updatedAt: new Date().toISOString(), updatedBy: "user" } as T);

/** cycls-default-apps: some models (DeepSeek on Fireworks, measured 2026-10-22) send the database
 *  tool's `value` as a JSON-encoded string ("{\"id\":…}"); the tool stores it as text and the
 *  row looked unreadable. A string that is exactly a JSON object or array is decoded; any other
 *  string is left as it is (and still flagged by the app). */
export function decodeStored(v: unknown): unknown {
  if (typeof v !== "string") return v;
  const t = v.trim();
  if (!((t.startsWith("{") && t.endsWith("}")) || (t.startsWith("[") && t.endsWith("]")))) return v;
  try { const j = JSON.parse(t); return j && typeof j === "object" ? j : v; } catch { return v; }
}

export function useCollection<T extends Record_>(prefix: string, opts: CollectionOptions<T> = {}): Collection<T> {
  const { mode, pending } = useCycls();
  const demoMode = mode !== "live";
  const [items, setItemsState] = useState<T[]>([]);
  // The ref is the truth; React state follows it. Updaters passed to setState run
  // lazily, so "what was there before this write" must not be read inside one.
  const itemsRef = useRef<T[]>([]);
  const commit = useCallback((next: T[]) => { itemsRef.current = next; setItemsState(next); }, []);
  const [status, setStatus] = useState<Status>("loading");
  const [error, setError] = useState<string | null>(null);
  const [invalid, setInvalid] = useState(0);
  const optsRef = useRef(opts);
  optsRef.current = opts;
  const demoList = useCallback((): T[] => {
    const d = optsRef.current.demo;
    return (typeof d === "function" ? d() : d ?? []).map((x) => ({ ...x }));
  }, []);
  const stamp = useCallback((v: T) => (optsRef.current.stamp ?? defaultStamp)(v), []);
  const keyOf = useCallback((id: string) => prefix + id, [prefix]);
  const demoKey = typeof opts.demo === "function" ? opts.demo : null;

  // live read: cycls.all() — the shim's one-time snapshot (trap 1)
  useEffect(() => {
    if (pending) return;
    if (demoMode) { commit(demoList()); setStatus("ready"); return; }
    sharedReaders++;
    let alive = true;
    withTimeout(cycls()!.all(), CALL_TIMEOUT_MS, "cycls.all").then((all) => {
      if (!alive) return;
      const v = optsRef.current.validate;
      let bad = 0;
      const out: T[] = [];
      for (const [k, raw] of Object.entries(all)) {
        if (!k.startsWith(prefix)) continue;
        const value = decodeStored(raw);
        if (!value || typeof value !== "object" || (v && !v(value))) { bad++; continue; }
        // cycls-default-apps: the KEY decides the id. A row whose value.id differs from its key
        // (hand- or agent-written) used to be written back under value.id — a second row.
        out.push({ ...(value as T), id: k.slice(prefix.length) });
      }
      commit(out); setInvalid(bad); setStatus("ready");
    }, (e) => { if (alive) { setError(errorText(e)); setStatus("error"); } });
    return () => { alive = false; sharedReaders--; };
  }, [pending, demoMode, prefix, demoList, commit]);

  // demo data that depends on the language is re-made when it changes
  useEffect(() => { if (!pending && demoMode && demoKey) commit(demoList()); }, [demoKey, pending, demoMode, demoList, commit]);

  const put = useCallback((id: string, v: T | null) => {
    const xs = itemsRef.current;
    commit(v === null ? xs.filter((x) => x.id !== id) : xs.some((x) => x.id === id) ? xs.map((x) => (x.id === id ? v : x)) : [...xs, v]);
  }, [commit]);

  const add = useCallback(async (value: T) => {
    const v = stamp(value);
    put(v.id, v);
    if (demoMode) { demoToast(); return v; }
    try {
      const saved = await track(cycls()!.update<T>(keyOf(v.id), (cur) => {
        if (cur !== undefined && cur !== null) throw new KitError("exists", `${keyOf(v.id)} already exists`);
        return v;
      }));
      put(v.id, saved);
      return saved;
    } catch (e) { put(v.id, null); toast.error(errorText(e)); return undefined; }
  }, [demoMode, keyOf, stamp, put]);

  const update = useCallback(async (id: string, patch: Partial<T> | ((cur: T) => T)) => {
    const apply = (cur: T) => stamp(typeof patch === "function" ? patch(cur) : { ...cur, ...patch, id });
    const before = itemsRef.current.find((x) => x.id === id);
    if (before) put(id, apply(before));
    if (demoMode) { demoToast(); return before ? apply(before) : undefined; }
    try {
      const next = await track(cycls()!.update<T>(keyOf(id), (cur) => {
        if (cur === undefined || cur === null) throw new KitError("gone", "This record was deleted elsewhere");
        // the FRESH value: a concurrent edit to another field survives. Raw as stored, so decoded
        // like on read — spreading a JSON-encoded string would write {"0":"{","1":"\"",...}.
        return apply({ ...(decodeStored(cur) as T), id });
      }));
      put(id, next);
      return next;
    } catch (e) {
      if (e instanceof KitError && e.code === "gone") put(id, null);
      else if (before) put(id, before);
      toast.error(errorText(e));
      return undefined;
    }
  }, [demoMode, keyOf, stamp, put]);

  const remove = useCallback(async (id: string) => {
    const before = itemsRef.current.find((x) => x.id === id);
    put(id, null);
    if (demoMode) { demoToast(); return; }
    try {
      // set(key, undefined) is the shim's delete; it resolves when the debounced flush lands.
      await track(withTimeout(cycls()!.set(keyOf(id), undefined), CALL_TIMEOUT_MS, "delete"));
    } catch (e) { if (before) put(id, before); toast.error(errorText(e)); }
  }, [demoMode, keyOf, put]);

  const loadDemo = useCallback(async () => {
    const list = demoList();
    if (demoMode) { commit(list); return; }
    const now = new Date().toISOString();
    const stamped = list.map((v) => ({ ...(v as object), updatedAt: now, updatedBy: "user" } as unknown as T));
    commit([...itemsRef.current, ...stamped.filter((d) => !itemsRef.current.some((x) => x.id === d.id))]);
    const res = await Promise.allSettled(stamped.map((v) => track(cycls()!.update<T>(keyOf(v.id), (cur) => {
      if (cur !== undefined && cur !== null) throw new KitError("exists", "exists");
      return v;
    }))));
    const failed = res.filter((r) => r.status === "rejected" && !((r as PromiseRejectedResult).reason instanceof KitError));
    if (failed.length) toast.error(errorText((failed[0] as PromiseRejectedResult).reason));
  }, [demoMode, demoList, keyOf, commit]);

  return { items, status: pending ? "loading" : status, error, demo: demoMode, invalid, add, update, remove, loadDemo, keyOf };
}

// ---- useDoc: one shared key -------------------------------------------------------------

export interface Doc<T> {
  value: T | undefined;
  status: Status;
  demo: boolean;
  set(value: T): Promise<void>;
  update(fn: (cur: T | undefined) => T): Promise<T | undefined>;
}

export function useDoc<T>(key: string, opts: { demo?: T; fallback?: T } = {}): Doc<T> {
  const { mode, pending } = useCycls();
  const demoMode = mode !== "live";
  const [value, setValue] = useState<T | undefined>(undefined);
  const [status, setStatus] = useState<Status>("loading");
  const optsRef = useRef(opts);
  optsRef.current = opts;

  useEffect(() => {
    if (pending) return;
    if (demoMode) { setValue(optsRef.current.demo ?? optsRef.current.fallback); setStatus("ready"); return; }
    sharedReaders++;
    let alive = true;
    withTimeout(cycls()!.all(), CALL_TIMEOUT_MS, "cycls.all").then((all) => {
      if (!alive) return;
      setValue(key in all ? (decodeStored(all[key]) as T) : optsRef.current.fallback);
      setStatus("ready");
    }, () => { if (alive) setStatus("error"); });
    return () => { alive = false; sharedReaders--; };
  }, [pending, demoMode, key]);

  const update = useCallback(async (fn: (cur: T | undefined) => T) => {
    // cycls-default-apps: run fn once outside the state updater — a fn that throws (the README's
    // "write nothing" signal) must not crash the render.
    let optimistic: T;
    try { optimistic = fn(value); } catch { return undefined; }
    setValue(optimistic);
    if (demoMode) { demoToast(); return undefined; }
    try {
      // cur is the raw stored value: decoded like on read, so a JSON-encoded doc stays editable
      // (fn would otherwise see the string and drop or refuse every stored field).
      const next = await track(cycls()!.update<T>(key, (cur) => fn((decodeStored(cur) as T | undefined) ?? optsRef.current.fallback)));
      setValue(next);
      return next;
    } catch (e) { toast.error(errorText(e)); return undefined; }
  }, [demoMode, key, value]);
  const set = useCallback(async (v: T) => { await update(() => v); }, [update]);
  return { value, status: pending ? "loading" : status, demo: demoMode, set, update };
}

// ---- useMine: the viewer's own row (cycls.me) ---------------------------------------------

export interface Mine<T> { value: T | undefined; status: Status; demo: boolean; set(v: T): Promise<void>; remove(): Promise<void> }

export function useMine<T>(key: string, opts: { demo?: T; fallback?: T } = {}): Mine<T> {
  const { mode, pending } = useCycls();
  const demoMode = mode !== "live";
  const [value, setValue] = useState<T | undefined>(undefined);
  const [status, setStatus] = useState<Status>("loading");
  const [tick, setTick] = useState(0);
  const optsRef = useRef(opts);
  optsRef.current = opts;

  useEffect(() => {
    const f = () => setTick((t) => t + 1);
    refetchers.add(f);
    return () => { refetchers.delete(f); };
  }, []);

  useEffect(() => {
    if (pending) return;
    if (demoMode) { setValue((v) => v ?? optsRef.current.demo ?? optsRef.current.fallback); setStatus("ready"); return; }
    let alive = true;
    withTimeout(cycls()!.me.get<T>(key), CALL_TIMEOUT_MS, "cycls.me.get").then((v) => {
      if (!alive) return;
      setValue(v === undefined || v === null ? optsRef.current.fallback : (decodeStored(v) as T));
      setStatus("ready");
    }, () => { if (alive) setStatus("error"); });
    return () => { alive = false; };
  }, [pending, demoMode, key, tick]);

  const set = useCallback(async (v: T) => {
    setValue(v);
    if (demoMode) return;     // a viewer's own preference: no toast, it is just not kept
    try { await track(withTimeout(cycls()!.me.set(key, v), CALL_TIMEOUT_MS, "cycls.me.set")); }
    catch (e) { toast.error(errorText(e)); }
  }, [demoMode, key]);
  const remove = useCallback(async () => {
    setValue(optsRef.current.fallback);
    if (demoMode) return;
    try { await track(withTimeout(cycls()!.me.remove(key), CALL_TIMEOUT_MS, "cycls.me.remove")); }
    catch (e) { toast.error(errorText(e)); }
  }, [demoMode, key]);
  return { value, status: pending ? "loading" : status, demo: demoMode, set, remove };
}

// ---- admin: every member's rows ----------------------------------------------------------

/** All members' rows whose KEY starts with `keyPrefix` (filtered here — trap 3). */
export async function allMembers<T>(keyPrefix = ""): Promise<{ rows: MemberRow<T>[]; truncated: boolean }> {
  const page = await withTimeout(cycls()!.users.all<T>(), CALL_TIMEOUT_MS, "cycls.users.all");
  return { rows: (page.rows || []).filter((r) => r.key.startsWith(keyPrefix)), truncated: !!page.truncated };
}

export function useMembers<T>(keyPrefix: string): { rows: MemberRow<T>[]; status: Status; truncated: boolean } {
  const admin = useIsAdmin();
  const [state, setState] = useState<{ rows: MemberRow<T>[]; status: Status; truncated: boolean }>({ rows: [], status: "loading", truncated: false });
  const [tick, setTick] = useState(0);
  useEffect(() => { const f = () => setTick((t) => t + 1); refetchers.add(f); return () => { refetchers.delete(f); }; }, []);
  useEffect(() => {
    if (!admin) { setState({ rows: [], status: admin === false ? "ready" : "loading", truncated: false }); return; }
    let alive = true;
    allMembers<T>(keyPrefix).then((r) => alive && setState({ ...r, status: "ready" }), () => alive && setState({ rows: [], status: "error", truncated: false }));
    return () => { alive = false; };
  }, [admin, keyPrefix, tick]);
  return state;
}

// ---- ask / copy ------------------------------------------------------------------------------

export const ASK_MAX = 1000;
/** Pre-fills the chat composer (never sends). Resolves false when this host cannot.
 *  Bidi isolates (from t()/num()) are stripped first, then the text is cut at ASK_MAX. */
export async function askAgent(text: string): Promise<boolean> {
  const c = cycls();
  const d = await detectMode();
  if (d.mode !== "live" || typeof c?.ask !== "function") return false;
  try { await withTimeout(c.ask(plain(text).slice(0, ASK_MAX)), CALL_TIMEOUT_MS, "ask"); return true; }
  catch { return false; }
}

/** Copies through a textarea + execCommand: the Clipboard API is not delegated to the
 *  sandboxed frame. Must run inside a user gesture. */
export function copyText(text: string): boolean {
  const ta = document.createElement("textarea");
  ta.value = plain(text);   // no invisible bidi isolates in what the person pastes
  ta.setAttribute("readonly", "");
  ta.style.cssText = "position:fixed;inset-inline-start:-9999px;top:0;opacity:0";
  document.body.appendChild(ta);
  const prev = document.activeElement as HTMLElement | null;
  ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch { ok = false; }
  ta.remove();
  prev?.focus?.();
  return ok;
}

/** Export through the host's save dialog (the only way out of the app folder). */
export async function saveFile(name: string, content: string): Promise<string | null> {
  const d = await detectMode();
  if (d.mode !== "live") throw new KitError("demo", "Saving needs the app opened in a workspace");
  try { return await cycls()!.save(plain(name), plain(content)); }
  catch (e) { if (errorText(e) === "cancelled") return null; throw e; }
}

/** A short unique id, safe in a key: [a-z0-9]. */
export function newId(prefix = ""): string {
  const rnd = crypto.getRandomValues(new Uint32Array(2));
  return prefix + Date.now().toString(36) + rnd[0].toString(36).slice(0, 4) + rnd[1].toString(36).slice(0, 2);
}

// ---- the workspace's app theme --------------------------------------------------------------
// The host's shim wears the tokens itself (a <style id="cycls-theme"> that out-ranks theme.css). This
// is the fallback for a host that passes `ctx.tokens` without wearing them (a phone shim that lags the
// web one): the same rules, written once, never over the shim's own.
const TOKEN = /^--[a-z0-9-]{1,40}$/, VALUE = /^[^;{}<>\\]{1,120}$/;
const rules = (sel: string, set: Record<string, string>) => {
  const out = Object.entries(set || {}).filter(([k, v]) => TOKEN.test(k) && typeof v === "string" && VALUE.test(v)).map(([k, v]) => `${k}:${v}`);
  return out.length ? `${sel}{${out.join(";")}}` : "";
};
export function wearHostTokens(tokens: HostTokens | null | undefined) {
  if (typeof document === "undefined") return;
  const el = document.getElementById("cycls-theme");
  if (!tokens) { if (el?.dataset.kit) el.remove(); return; }
  if (el && !el.dataset.kit) return;                     // the shim already did
  const style = el ?? Object.assign(document.createElement("style"), { id: "cycls-theme" });
  style.dataset.kit = "1";
  style.textContent = rules(":root:root", tokens.light) + rules(`:root:root.dark,:root:root[data-theme="dark"]`, tokens.dark);
  if (!el) document.head.appendChild(style);
  document.documentElement.setAttribute("data-cycls-theme", "");
}
