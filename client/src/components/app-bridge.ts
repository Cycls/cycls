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
  engine: "cycls:engine",
  engineResult: "cycls:engine:result",
  ask: "cycls:ask",
  askResult: "cycls:ask:result",
  command: "cycls:command",
} as const;

// The window event the chat raises for a tool's `app_command`; the bridge that
// holds the matching app's port forwards it. `path: "*"` reaches every open app.
export const APP_COMMAND_EVENT = "cycls:app-command";

export const MAX_ENGINE_BYTES = 2_000_000;
export const MAX_ASK_CHARS = 1000;
const ASK_EVERY_MS = 2000;

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
  return new Blob([text]).size > MAX_WRITE_BYTES;
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
  appData?: (slug: string, op: Record<string, unknown>) => Promise<unknown>;
  // A deployed service relayed as the signed-in user (Studio's Blender engine).
  // The server decides which apps get one and which ops they may run.
  callEngine?: (slug: string, op: string, payload: Record<string, unknown>) => Promise<unknown>;
  // Puts text in the composer for the person to send; never sends it.
  onAsk?: (text: string) => void;
  // Opens a workspace file on the canvas: an engine reply naming one it made (a render
  // from the app's history). Only renders/ and exports/ — what an engine route writes.
  onOpen?: (path: string) => void;
}

// What an engine reply may ask the host to open.
export const OPENABLE = /^(renders|exports)\/[^/\\]+$/;

export function attachBridge({
  frame, appPath, readFile, writeFile, requestSave, context, onResize, onError, fetchConnector, appData,
  callEngine, onAsk, onOpen,
}: BridgeOptions) {
  const folder = appScope(appPath);
  if (folder === null) return () => {};
  const scope: string = folder;
  // Every `ready` mints a channel, and a busy frame sends several before the first `init`
  // lands — the shim keeps only the first port it is handed. So a reply goes back on the
  // channel its request came in on, and `port` is whichever channel the app last spoke on.
  let port: MessagePort | null = null;
  const ports = new Set<MessagePort>();
  let lastAsk = 0;

  async function handle(raw: unknown, via?: MessagePort) {
    const msg = raw as {
      type?: string; id?: unknown; path?: unknown; content?: unknown; height?: unknown;
    };
    if (typeof msg?.type !== "string") return;
    // Once the channel is up everything goes down it. A window post needs targetOrigin
    // "*" — an opaque origin has none to name — and a frame that navigated itself away
    // would still receive it.
    const channel = via ?? port;
    const post = (p: unknown) => (channel ? channel.postMessage(p) : frame.contentWindow?.postMessage(p, "*"));

    if (msg.type === MSG.loadError) {
      onError?.(String((msg as { message?: unknown }).message ?? "").slice(0, 500));
      return;
    }

    if (msg.type === MSG.data) {
      const reply = (p: object) => post({ type: MSG.dataResult, id: msg.id, ...p });
      if (!appData) return reply({ ok: false, error: "this view has no workspace" });
      try {
        reply({ ok: true, result: await appData(scope.split("/")[1], msg as Record<string, unknown>) });
      } catch (e) {
        reply({ ok: false, error: String((e as Error)?.message ?? e).slice(0, 300),
                status: (e as { status?: number })?.status });
      }
      return;
    }

    if (msg.type === MSG.read) {
      const fail = (error: string) => post({ type: MSG.readResult, id: msg.id, ok: false, error });
      if (!inScope(scope, msg.path)) return fail("outside this app's folder");
      try {
        post({ type: MSG.readResult, id: msg.id, ok: true, content: await readFile(msg.path) });
      } catch (err) {
        fail((err as Error).message);
      }
      return;
    }

    if (msg.type === MSG.write) {
      const fail = (error: string) => post({ type: MSG.writeResult, id: msg.id, ok: false, error });
      if (!writeFile) return fail("writes are not enabled here");
      if (!canWrite(scope, msg.path)) return fail("not a writable path for this app");
      if (typeof msg.content !== "string") return fail("content must be a string");
      if (overWriteLimit(msg.content)) return fail("too large");
      try {
        await writeFile(msg.path, msg.content);
        post({ type: MSG.writeResult, id: msg.id, ok: true });
      } catch (err) {
        fail((err as Error).message);
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
        fail((err as Error).message);
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
        fail((err as Error).message);
      }
      return;
    }

    if (msg.type === MSG.engine) {
      const reply = (p: object) => post({ type: MSG.engineResult, id: msg.id, ...p });
      const { op, payload } = msg as { op?: unknown; payload?: unknown };
      if (!callEngine) return reply({ ok: false, error: "this view can't run the engine" });
      if (typeof op !== "string" || !/^[a-z_]{1,32}$/.test(op)) return reply({ ok: false, error: "bad op" });
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
        return reply({ ok: false, error: "payload must be an object" });
      }
      let size = 0;
      try { size = JSON.stringify(payload).length; } catch { return reply({ ok: false, error: "payload must be JSON" }); }
      if (size > MAX_ENGINE_BYTES) return reply({ ok: false, error: "payload too large" });
      try {
        const result = await callEngine(scope.split("/")[1], op, payload as Record<string, unknown>);
        const open = (result as { open?: unknown } | null)?.open;
        if (onOpen && typeof open === "string" && OPENABLE.test(open)) onOpen(open);
        reply({ ok: true, result });
      } catch (e) {
        reply({ ok: false, error: String((e as Error)?.message ?? e).slice(0, 500),
                status: (e as { status?: number })?.status });
      }
      return;
    }

    if (msg.type === MSG.ask) {
      const reply = (p: object) => post({ type: MSG.askResult, id: msg.id, ...p });
      const text = (msg as { text?: unknown }).text;
      if (!onAsk) return reply({ ok: false, error: "this view has no chat" });
      if (typeof text !== "string" || !text.trim()) return reply({ ok: false, error: "text required" });
      const now = Date.now();
      if (now - lastAsk < ASK_EVERY_MS) return reply({ ok: false, error: "too soon — one ask every 2 s" });
      lastAsk = now;
      onAsk(text.slice(0, MAX_ASK_CHARS));
      return reply({ ok: true });
    }

    if (msg.type === MSG.resize && typeof msg.height === "number") {
      onResize?.(Math.min(Math.max(msg.height, 120), 4000));
    }
  }

  function onWindow(e: MessageEvent) {
    // Sandboxed frames report origin "null", so identity is the window handle.
    if (!frame.contentWindow || e.source !== frame.contentWindow) return;
    if ((e.data as { type?: string })?.type === MSG.ready) {
      const ch = new MessageChannel();
      const mine = ch.port1;
      ports.add(mine);
      port = mine;
      mine.onmessage = (ev) => { port = mine; void handle(ev.data, mine); };
      frame.contentWindow.postMessage(
        { type: MSG.init, path: appPath, scope, canWrite: !!writeFile, ...context }, "*", [ch.port2]);
      return;
    }
    void handle(e.data);   // a shim that ignored the port still works
  }

  // A tool's push for this app (or for every app). Only a port carries it: with no
  // channel yet the app reads its data fresh when it starts, so nothing is lost.
  function onCommand(e: Event) {
    const d = (e as CustomEvent<{ path?: unknown; command?: unknown }>).detail;
    if (!d || (d.path !== "*" && d.path !== appPath) || !port) return;
    port.postMessage({ type: MSG.command, command: d.command });
  }

  window.addEventListener("message", onWindow);
  window.addEventListener(APP_COMMAND_EVENT, onCommand);
  return () => {
    window.removeEventListener("message", onWindow);
    window.removeEventListener(APP_COMMAND_EVENT, onCommand);
    ports.forEach((p) => p.close());
    ports.clear();
    port = null;
  };
}
