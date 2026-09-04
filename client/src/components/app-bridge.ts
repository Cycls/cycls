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
} as const;

// An app may not rewrite its own source or manifest. Its OWN pair only, so a
// nested reports/index.html is fine.
const RESERVED = ["index.html", "app.json"];

export const MAX_WRITE_BYTES = 1_000_000;

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
  if (!inScope(scope, target)) return false;
  const lower = target.toLowerCase();
  return !RESERVED.some((f) => lower === `${scope.toLowerCase()}/${f}`);
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
}

export function attachBridge({
  frame, appPath, readFile, writeFile, requestSave, context, onResize,
}: BridgeOptions) {
  const folder = appScope(appPath);
  if (folder === null) return () => {};
  const scope: string = folder;

  async function onMessage(e: MessageEvent) {
    // Sandboxed frames report origin "null", so identity is the window handle.
    if (!frame.contentWindow || e.source !== frame.contentWindow) return;
    const msg = e.data as {
      type?: string; id?: unknown; path?: unknown; content?: unknown; height?: unknown;
    };
    if (typeof msg?.type !== "string") return;
    const post = (p: unknown) => frame.contentWindow?.postMessage(p, "*");

    if (msg.type === MSG.ready) {
      return post({ type: MSG.init, path: appPath, scope, canWrite: !!writeFile, ...context });
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
      if (msg.content.length > MAX_WRITE_BYTES) return fail("too large");
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
      if (msg.content.length > MAX_WRITE_BYTES) return fail("too large");
      try {
        const path = await requestSave(name, msg.content);
        if (!path) return fail("cancelled");
        post({ type: MSG.saveResult, id: msg.id, ok: true, path });
      } catch (err) {
        fail((err as Error).message);
      }
      return;
    }

    if (msg.type === MSG.resize && typeof msg.height === "number") {
      onResize?.(Math.min(Math.max(msg.height, 120), 4000));
    }
  }

  window.addEventListener("message", onMessage);
  return () => window.removeEventListener("message", onMessage);
}
