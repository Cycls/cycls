// Host side of the canvas <-> sandboxed-app channel. The app has an opaque
// origin, so the host reads and writes for it, within its own folder only.

export const MSG = {
  ready: "cycls:ready",
  init: "cycls:init",
  read: "cycls:read",
  readResult: "cycls:read:result",
  write: "cycls:write",
  writeResult: "cycls:write:result",
  save: "cycls:save",
  saveResult: "cycls:save:result",
  resize: "cycls:resize",
  fetch: "cycls:fetch",
  fetchResult: "cycls:fetch:result",
  loadError: "cycls:loaderror",
  data: "cycls:data",
  dataResult: "cycls:data:result",
  listen: "cycls:listen",     // app -> host: it has a change listener, so tell it instead of reloading it
  changed: "cycls:changed",   // host -> app: its data changed (the agent, a teammate, another tab)
} as const;

// Window events the chat sends the open apps: the agent changed an app's data (the `app_data` tool
// event), and a turn ended (anything else it wrote under data/ shows up in the check that follows).
export const APP_DATA_EVENT = "cycls:app-data";
export const TURN_END_EVENT = "cycls:app-turn-end";

export type ChangeSource = "agent" | "turn" | "poll" | "focus";
type Versions = { keys?: Record<string, string>; files?: Record<string, string> };

export const RELAY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"];
// The app may set these; Authorization is the server's alone.
const RELAY_HEADERS = ["content-type", "accept"];

export function relayHeaders(raw: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  if (raw && typeof raw === "object") {
    for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
      if (RELAY_HEADERS.includes(k.toLowerCase()) && typeof v === "string") out[k] = v;
    }
  }
  return out;
}

// An app writes its data and nothing else. As a denylist this allowed scripts/ and
// components/ — code the browser writes and the agent later runs.
export const DATA_DIR = "data";

export const MAX_WRITE_BYTES = 25_000_000;

// It counts UTF-8 bytes, which is what the name always claimed: `.length` is
// UTF-16 code units, so the old cap was ~1 MB of English and ~2 MB of Arabic.
// Bytes are never fewer than units and never more than 3× them, so the two
// bounds settle almost every write without encoding 25 MB to measure it.
export function overWriteLimit(text: string): boolean {
  if (text.length > MAX_WRITE_BYTES) return true;
  if (text.length * 3 <= MAX_WRITE_BYTES) return false;
  return utf8Bytes(text, MAX_WRITE_BYTES) > MAX_WRITE_BYTES;
}

/** The text's size in UTF-8, counted without encoding it (a copy of up to 75 MB otherwise); stops past `stop`. */
export function utf8Bytes(text: string, stop = Infinity): number {
  let n = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    if (c < 0x80) n += 1;
    else if (c < 0x800) n += 2;
    else if (c >= 0xd800 && c <= 0xdbff && i + 1 < text.length && (text.charCodeAt(i + 1) & 0xfc00) === 0xdc00) { n += 4; i++; }
    else n += 3;   // the rest of the BMP, and a lone surrogate (written as U+FFFD)
    if (n > stop) return n;
  }
  return n;
}

// A save leaves the app's folder, so the app proposes a name and nothing else.
export function safeName(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const name = raw.trim().split(/[/\\]/).pop()?.slice(0, 120).trim();
  if (!name || name === "." || name === ".." || name.includes("\0")) return null;
  return name;
}

export const APPS_DIR = "apps";

// The folder an app may reach, or null if this file is not one. The canvas
// renders every HTML file, but only apps/<slug>/ gets a bridge: opening a
// document must never hand that document your workspace.
export function appScope(appPath: string): string | null {
  const parts = appPath.split("/");
  if (parts.length < 3 || parts[0] !== APPS_DIR || !parts[1]) return null;
  return `${parts[0]}/${parts[1]}`;
}

export function inScope(scope: string, target: unknown): target is string {
  if (typeof target !== "string" || !target || target.length > 1024) return false;
  if (target.startsWith("/") || target.includes("\\") || target.includes("\0")) return false;
  const parts = target.split("/");
  if (parts.some((p) => p === "" || p === "." || p === "..")) return false;
  const base = scope.split("/");
  return base.every((seg, i) => parts[i] === seg) && parts.length > base.length;
}

export function canWrite(scope: string, target: unknown): target is string {
  return inScope(scope, target) && target.startsWith(`${scope}/${DATA_DIR}/`);
}

export interface BridgeOptions {
  frame: HTMLIFrameElement;
  appPath: string;
  readFile: (path: string) => Promise<string>;
  writeFile?: (path: string, text: string) => Promise<void>;
  // Resolves to the path the person picked, or null if they cancelled.
  requestSave?: (name: string, content: string) => Promise<string | null>;
  context?: Record<string, unknown>;
  onResize?: (height: number) => void;
  onError?: (message: string) => void;
  // Calls the connector relay as the signed-in user; the app never sees a token.
  fetchConnector?: (name: string, path: string,
                    init: { method: string; headers: Record<string, string>; body?: string })
                   => Promise<{ status: number; body: string; contentType: string }>;
  // The app's rows in the object store. `who` picks the audience; the server
  // resolves the viewer and the role, so the frame cannot name someone else.
  // `{op: "versions"}` is the host's own call: what the change check compares.
  appData?: (slug: string, op: Record<string, unknown>) => Promise<unknown>;
  // Keeping an open app in step. Each has a default; tests replace them.
  pollMs?: number;               // how often a visible, listening app checks for changes
  visible?: () => boolean;       // on screen: the active tab of a shown canvas in a shown page
  reload?: () => void;           // an app with no change listener is reloaded instead
}

/** Keys or files whose version differs between two looks, either way. */
function changedIn(was: Map<string, string>, now: Map<string, string>): string[] {
  const out = new Set<string>();
  for (const [k, v] of now) if (was.get(k) !== v) out.add(k);
  for (const k of was.keys()) if (!now.has(k)) out.add(k);
  return [...out].sort();
}

// What an app hears when a call fails. Offline, just that: the error a sign-in token throws then is a vendor's,
// its name in it, and an app may well show it.
const said = (e: unknown) => (navigator.onLine ? String((e as Error)?.message ?? e) : "offline");

export function attachBridge({
  frame, appPath, readFile, writeFile, requestSave, context, onResize, onError, fetchConnector, appData,
  pollMs = 15_000, visible, reload,
}: BridgeOptions) {
  const folder = appScope(appPath);
  if (folder === null) return () => {};
  const scope: string = folder;
  const slug = scope.split("/")[1];
  let port: MessagePort | null = null;
  let answered: unknown = null;   // the document the channel was opened for
  // Once the channel is up everything goes down it. A window post needs targetOrigin
  // "*" — an opaque origin has none to name — and a frame that navigated itself away
  // would still receive it.
  const post = (p: unknown) => (port ? port.postMessage(p) : frame.contentWindow?.postMessage(p, "*"));

  // ---- Keeping an open app in step with its data ----
  // An app loads its data once. Before this, a change made by the agent, a teammate or another tab
  // showed only after the app was reopened. Now the host compares versions (one listing, no values)
  // and tells the app what changed. An app that never asked to be told is reloaded instead, and only
  // for the agent's changes, so a teammate's change never reloads an app someone is typing in.
  let listening = false;
  let known: { keys: Map<string, string>; files: Map<string, string> } | null = null;
  let busy = 0;     // the app's own writes on their way
  let moved = 0;    // bumps as one starts and lands: a check that overlapped one is thrown away
  const ownFiles = new Set<string>();   // data/ files the app wrote, so the check does not report them back
  let agentKeys = new Set<string>(), agentAll = false;
  let agentTimer: ReturnType<typeof setTimeout> | undefined;
  let reloadTimer: ReturnType<typeof setTimeout> | undefined;
  let laterTimer: ReturnType<typeof setTimeout> | undefined;
  let lastCheck = 0, shown = false, closed = false;
  const onScreen = visible ?? (() => document.visibilityState === "visible" && frame.isConnected
    && frame.getClientRects().length > 0 && getComputedStyle(frame).visibility !== "hidden");
  // Setting srcdoc again, even to the same text, loads the document afresh.
  const reloadFrame = reload ?? (() => { const doc = frame.srcdoc; frame.srcdoc = doc; });

  function tell(source: ChangeSource, keys?: string[], files?: string[]) {
    if (listening) {
      post({ type: MSG.changed, source, ...(keys ? { keys } : {}), ...(files ? { files } : {}) });
    } else if (source === "agent" || source === "turn") {
      reloadSoon();
    }
  }

  function reloadSoon() {
    clearTimeout(reloadTimer);
    reloadTimer = setTimeout(() => {
      if (closed) return;
      if (listening) return tell("agent");   // it started listening meanwhile: tell it, keep its state
      if (busy) return reloadSoon();         // a write of its own is still on its way
      reloadFrame();
    }, 800);
  }

  async function check(source: ChangeSource) {
    if (!appData || closed) return;
    if (busy) return later(source);
    const at = moved;
    lastCheck = Date.now();
    let v: Versions;
    try {
      v = ((await appData(slug, { op: "versions" })) ?? {}) as Versions;
    } catch {
      return;   // offline, or an older server: the app keeps what it shows
    }
    if (closed) return;
    if (at !== moved || busy) return later(source);
    const next = { keys: new Map(Object.entries(v.keys ?? {})), files: new Map(Object.entries(v.files ?? {})) };
    const was = known;
    known = next;
    if (!was) return;   // the first look is what later ones compare with
    const keys = changedIn(was.keys, next.keys);
    const files = changedIn(was.files, next.files).filter((f) => !ownFiles.delete(f));
    if (keys.length || files.length) tell(source, keys, files);
  }

  function later(source: ChangeSource) {
    clearTimeout(laterTimer);
    laterTimer = setTimeout(() => void check(source), 600);
  }

  function onAgent(e: Event) {
    const d = ((e as CustomEvent).detail ?? {}) as { slug?: unknown; key?: unknown; version?: unknown; deleted?: unknown };
    if (d.slug !== slug || closed) return;
    if (typeof d.key === "string") {
      agentKeys.add(d.key);
      // Its new version, so the next check does not report the same change a second time.
      if (known && d.deleted) known.keys.delete(d.key);
      else if (known && typeof d.version === "string" && d.version) known.keys.set(d.key, d.version);
    } else {
      agentAll = true;
    }
    clearTimeout(agentTimer);
    agentTimer = setTimeout(() => {   // a burst of puts is one change
      const keys = agentAll ? undefined : [...agentKeys];
      agentKeys = new Set();
      agentAll = false;
      tell("agent", keys);
    }, 250);
  }

  const onTurnEnd = () => void check("turn");
  const onFocus = () => {
    if (listening && onScreen() && Date.now() - lastCheck > 2_000) void check("focus");
  };
  const onVisibility = () => { if (document.visibilityState === "visible") onFocus(); };
  // Cheap when nothing is due: no request unless the app listens, is on screen, and either just came
  // into view or has not looked for a while.
  const tick = setInterval(() => {
    const seen = listening && onScreen();
    if (seen && (!shown || Date.now() - lastCheck >= pollMs)) void check(shown ? "poll" : "focus");
    shown = seen;
  }, Math.min(2_500, pollMs));

  async function handle(raw: unknown) {
    const msg = raw as {
      type?: string; id?: unknown; path?: unknown; content?: unknown; height?: unknown;
    };
    if (typeof msg?.type !== "string") return;

    if (msg.type === MSG.loadError) {
      onError?.(String((msg as { message?: unknown }).message ?? "").slice(0, 500));
      return;
    }

    if (msg.type === MSG.listen) {
      listening = true;
      return;
    }

    if (msg.type === MSG.data) {
      const reply = (p: object) => post({ type: MSG.dataResult, id: msg.id, ...p });
      if (!appData) return reply({ ok: false, error: "this view has no workspace" });
      const op = msg as { op?: unknown; key?: unknown; who?: unknown };
      // The host's own call; an app has list, get, put and delete.
      if (op.op === "versions") return reply({ ok: false, error: "unknown op" });
      const shared = !op.who && typeof op.key === "string";
      const writes = shared && (op.op === "put" || op.op === "delete");
      if (writes) { busy++; moved++; }
      try {
        const result = await appData(slug, msg as Record<string, unknown>);
        if (shared && known) {
          const key = op.key as string;
          const version = (result as { version?: unknown } | null)?.version;
          if (op.op === "delete") known.keys.delete(key);
          else if ((op.op === "put" || (op.op === "get" && result)) && typeof version === "string" && version) {
            known.keys.set(key, version);   // what the app wrote, or has just read, is not news to it
          }
        }
        reply({ ok: true, result });
      } catch (e) {
        reply({ ok: false, error: said(e).slice(0, 300),
                status: (e as { status?: number })?.status });
      } finally {
        if (writes) { busy--; moved++; }
      }
      return;
    }

    if (msg.type === MSG.read) {
      const fail = (error: string) => post({ type: MSG.readResult, id: msg.id, ok: false, error });
      if (!inScope(scope, msg.path)) return fail("outside this app's folder");
      try {
        post({ type: MSG.readResult, id: msg.id, ok: true, content: await readFile(msg.path) });
      } catch (err) {
        fail(said(err));
      }
      return;
    }

    if (msg.type === MSG.write) {
      const fail = (error: string) => post({ type: MSG.writeResult, id: msg.id, ok: false, error });
      if (!writeFile) return fail("writes are not enabled here");
      if (!canWrite(scope, msg.path)) return fail("not a writable path for this app");
      if (typeof msg.content !== "string") return fail("content must be a string");
      if (overWriteLimit(msg.content)) return fail("too large");
      busy++; moved++;
      try {
        await writeFile(msg.path, msg.content);
        ownFiles.add(msg.path.slice(scope.length + 1));
        post({ type: MSG.writeResult, id: msg.id, ok: true });
      } catch (err) {
        fail(said(err));
      } finally {
        busy--; moved++;
      }
      return;
    }

    if (msg.type === MSG.save) {
      const fail = (error: string) => post({ type: MSG.saveResult, id: msg.id, ok: false, error });
      if (!requestSave) return fail("saving is not enabled here");
      const name = safeName((msg as { name?: unknown }).name);
      if (!name) return fail("a file name is required");
      if (typeof msg.content !== "string") return fail("content must be a string");
      if (overWriteLimit(msg.content)) return fail("too large");
      try {
        const path = await requestSave(name, msg.content);
        if (!path) return fail("cancelled");
        post({ type: MSG.saveResult, id: msg.id, ok: true, path });
      } catch (err) {
        fail(said(err));
      }
      return;
    }

    if (msg.type === MSG.fetch) {
      const fail = (error: string) => post({ type: MSG.fetchResult, id: msg.id, ok: false, error });
      if (!fetchConnector) return fail("connectors are not available here");
      const m = msg as { name?: unknown; path?: unknown; method?: unknown; headers?: unknown; body?: unknown };
      if (typeof m.name !== "string" || !/^[a-z0-9_-]{1,64}$/i.test(m.name)) return fail("a connector name is required");
      if (typeof m.path !== "string" || m.path.includes("..")) return fail("a valid path is required");
      const method = typeof m.method === "string" ? m.method.toUpperCase() : "GET";
      if (!RELAY_METHODS.includes(method)) return fail("method not allowed");
      if (m.body !== undefined && typeof m.body !== "string") return fail("body must be a string");
      try {
        const res = await fetchConnector(m.name, m.path, {
          method, headers: relayHeaders(m.headers), body: m.body as string | undefined,
        });
        post({ type: MSG.fetchResult, id: msg.id, ok: true, ...res });
      } catch (err) {
        fail(said(err));
      }
      return;
    }

    if (msg.type === MSG.resize && typeof msg.height === "number") {
      onResize?.(Math.min(Math.max(msg.height, 120), 4000));
    }
  }

  function onWindow(e: MessageEvent) {
    // Sandboxed frames report origin "null", so identity is the window handle.
    if (!frame.contentWindow || e.source !== frame.contentWindow) return;
    if ((e.data as { type?: string })?.type === MSG.ready) {
      // The same document announcing again before it heard back: it will hear the first answer.
      // A second channel used to replace the one it took, and every reply went where nobody listened.
      const doc = (e.data as { doc?: unknown }).doc;
      if (doc && doc === answered && port) return;
      answered = doc;
      listening = false;   // a new document: it has to ask again
      const ch = new MessageChannel();
      port = ch.port1;
      port.onmessage = (ev) => void handle(ev.data);
      frame.contentWindow.postMessage(
        { type: MSG.init, path: appPath, scope, canWrite: !!writeFile, ...context }, "*", [ch.port2]);
      return;
    }
    void handle(e.data);   // a shim that ignored the port still works
  }

  window.addEventListener("message", onWindow);
  window.addEventListener(APP_DATA_EVENT, onAgent);
  window.addEventListener(TURN_END_EVENT, onTurnEnd);
  window.addEventListener("focus", onFocus);
  document.addEventListener("visibilitychange", onVisibility);
  if (appData) void check("turn");   // the first look: what a later change is measured against
  return () => {
    closed = true;
    clearInterval(tick);
    clearTimeout(agentTimer);
    clearTimeout(reloadTimer);
    clearTimeout(laterTimer);
    window.removeEventListener("message", onWindow);
    window.removeEventListener(APP_DATA_EVENT, onAgent);
    window.removeEventListener(TURN_END_EVENT, onTurnEnd);
    window.removeEventListener("focus", onFocus);
    document.removeEventListener("visibilitychange", onVisibility);
    port?.close();
    port = null;
  };
}
