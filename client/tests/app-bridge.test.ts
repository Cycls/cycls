import { describe, it, expect, vi, afterEach } from "vitest";
import { appScope, inScope, canWrite, attachBridge, MSG, MAX_WRITE_BYTES, overWriteLimit, utf8Bytes,
         APP_DATA_EVENT, TURN_END_EVENT } from "../src/components/app-bridge";

const APP = "apps/burnup/index.html";
const scope = appScope(APP)!;

describe("appScope", () => {
  it("is the app's folder", () => expect(scope).toBe("apps/burnup"));

  it("stays the app folder for a nested page", () =>
    expect(appScope("apps/burnup/reports/index.html")).toBe("apps/burnup"));

  // The canvas renders every html file. Anything that is not an app must
  // get no bridge at all: a root file used to scope to "" (the whole
  // workspace), and unlike a built app it carries no CSP, so it could read
  // everything and POST it anywhere.
  it("refuses anything that is not an app", () => {
    for (const p of [
      "report.html",                    // workspace root
      "projects/PRJ-001/report.html",   // inside a project
      "apps/index.html",                // directly in apps/
      "notapps/burnup/index.html",
      "index.html",
      "",
    ]) {
      expect(appScope(p), p).toBeNull();
    }
  });
});

describe("inScope", () => {
  it("allows files beside the app and below", () => {
    expect(inScope(scope, "apps/burnup/data.json")).toBe(true);
    expect(inScope(scope, "apps/burnup/assets/logo.svg")).toBe(true);
  });

  it("refuses the folder itself", () => expect(inScope(scope, scope)).toBe(false));

  it("refuses anything outside", () => {
    for (const p of [
      "apps/other/data.json",
      "projects/PRJ-001/.state/commercial.json",
      "apps/burnup/../other/data.json",
      "../../etc/passwd",
      "apps/burnupX/data.json",
    ]) {
      expect(inScope(scope, p), p).toBe(false);
    }
  });

  it("refuses absolute paths, traversal and junk", () => {
    const bad = ["/etc/passwd", "a\\b", "a//b", "./a", "", 42, null, undefined, {}, []];
    for (const p of bad) expect(inScope(scope, p as unknown), String(p)).toBe(false);
  });

  it("caps length", () => expect(inScope(scope, `${scope}/${"a".repeat(1100)}`)).toBe(false));

});

describe("canWrite", () => {
  it("allows data files, and nothing else in the app's folder", () => {
    for (const p of [
      "apps/burnup/data/state.json", "apps/burnup/data/rows.csv", "apps/burnup/data/a/b.json",
      "apps/burnup/data/noext",
    ]) {
      expect(canWrite(scope, p), p).toBe(true);
    }
  });

  it("refuses everything outside data/, so the browser cannot write code", () => {
    for (const p of [
      "apps/burnup/index.html", "apps/burnup/app.json",
      "apps/burnup/APP.JSON", "apps/burnup/Index.HTML",
    ]) {
      expect(canWrite(scope, p), p).toBe(false);
    }
  });

  it("inherits every scope rule", () => {
    for (const p of ["apps/burnup/index.html", "apps/burnup/app.json", "apps/burnup/scripts/x.py",
                     "apps/burnup/notes.md", "apps/other/data/s.json", "../escape.json",
                     "/abs.json", scope, 42]) {
      expect(canWrite(scope, p as unknown), String(p)).toBe(false);
    }
  });
});

/** A stand-in for the frame: jsdom won't give us a real cross-document handle. */
function fakeFrame() {
  const sent: unknown[] = [];
  const contentWindow = { postMessage: (m: unknown) => sent.push(m) };
  return { frame: { contentWindow } as unknown as HTMLIFrameElement, sent, contentWindow };
}

function send(source: unknown, data: unknown) {
  const e = new MessageEvent("message", { data });
  Object.defineProperty(e, "source", { value: source });
  window.dispatchEvent(e);
}

const settle = () => new Promise((r) => setTimeout(r, 0));

describe("attachBridge", () => {
  let detach: () => void;
  afterEach(() => detach?.());

  it("attaches nothing for a file that is not an app", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    const readFile = vi.fn(async () => "secret");
    detach = attachBridge({ frame, appPath: "report.html", readFile });
    send(contentWindow, { type: MSG.ready });
    send(contentWindow, { type: MSG.read, id: 1, path: "apps/burnup/data/report.json" });
    await settle();
    expect(readFile).not.toHaveBeenCalled();
    expect(sent).toEqual([]);
  });

  it("answers ready with the app path, scope and context", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    detach = attachBridge({ frame, appPath: APP, readFile: async () => "", context: { theme: "dark" } });
    send(contentWindow, { type: MSG.ready });
    await settle();
    expect(sent).toEqual([{ type: MSG.init, path: APP, scope, canWrite: false, theme: "dark" }]);
  });

  it("reads a file inside the scope", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    const readFile = vi.fn(async () => "{}");
    detach = attachBridge({ frame, appPath: APP, readFile });
    send(contentWindow, { type: MSG.read, id: 1, path: "apps/burnup/data.json" });
    await settle();
    expect(readFile).toHaveBeenCalledWith("apps/burnup/data.json");
    expect(sent).toEqual([{ type: MSG.readResult, id: 1, ok: true, content: "{}" }]);
  });

  it("refuses a read outside the scope without touching readFile", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    const readFile = vi.fn(async () => "secret");
    detach = attachBridge({ frame, appPath: APP, readFile });
    send(contentWindow, { type: MSG.read, id: 2, path: "projects/PRJ-001/.state/commercial.json" });
    await settle();
    expect(readFile).not.toHaveBeenCalled();
    expect(sent).toEqual([
      { type: MSG.readResult, id: 2, ok: false, error: "outside this app's folder" },
    ]);
  });

  it("reports a read failure without leaking a stack", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    detach = attachBridge({
      frame,
      appPath: APP,
      readFile: async () => {
        throw new Error("not found");
      },
    });
    send(contentWindow, { type: MSG.read, id: 3, path: "apps/burnup/missing.json" });
    await settle();
    expect(sent).toEqual([{ type: MSG.readResult, id: 3, ok: false, error: "not found" }]);
  });

  it("writes a data file inside the scope", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    const writeFile = vi.fn(async () => {});
    detach = attachBridge({ frame, appPath: APP, readFile: async () => "", writeFile });
    send(contentWindow, { type: MSG.write, id: 5, path: "apps/burnup/data/state.json", content: '{"a":1}' });
    await settle();
    expect(writeFile).toHaveBeenCalledWith("apps/burnup/data/state.json", '{"a":1}');
    expect(sent).toEqual([{ type: MSG.writeResult, id: 5, ok: true }]);
  });

  it("refuses a write the guard rejects without touching writeFile", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    const writeFile = vi.fn(async () => {});
    detach = attachBridge({ frame, appPath: APP, readFile: async () => "", writeFile });
    send(contentWindow, { type: MSG.write, id: 6, path: "apps/burnup/index.html", content: "<b>" });
    await settle();
    expect(writeFile).not.toHaveBeenCalled();
    expect(sent).toEqual([
      { type: MSG.writeResult, id: 6, ok: false, error: "not a writable path for this app" },
    ]);
  });

  it("refuses every write when the host passes no writeFile", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    detach = attachBridge({ frame, appPath: APP, readFile: async () => "" });
    send(contentWindow, { type: MSG.write, id: 7, path: "apps/burnup/data/state.json", content: "{}" });
    await settle();
    expect(sent).toEqual([
      { type: MSG.writeResult, id: 7, ok: false, error: "writes are not enabled here" },
    ]);
  });

  it("refuses non-string and oversized content", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    const writeFile = vi.fn(async () => {});
    detach = attachBridge({ frame, appPath: APP, readFile: async () => "", writeFile });
    send(contentWindow, { type: MSG.write, id: 8, path: "apps/burnup/data/state.json", content: { a: 1 } });
    send(contentWindow, {
      type: MSG.write, id: 9, path: "apps/burnup/data/state.json", content: "x".repeat(MAX_WRITE_BYTES + 1),
    });
    await settle();
    expect(writeFile).not.toHaveBeenCalled();
    expect(sent).toEqual([
      { type: MSG.writeResult, id: 8, ok: false, error: "content must be a string" },
      { type: MSG.writeResult, id: 9, ok: false, error: "too large" },
    ]);
  });

  it("reports a write failure", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    detach = attachBridge({
      frame, appPath: APP, readFile: async () => "",
      writeFile: async () => { throw new Error("disk full"); },
    });
    send(contentWindow, { type: MSG.write, id: 10, path: "apps/burnup/data/state.json", content: "{}" });
    await settle();
    expect(sent).toEqual([{ type: MSG.writeResult, id: 10, ok: false, error: "disk full" }]);
  });

  it("saves wherever the person chose, not where the app asked", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    const requestSave = vi.fn(async () => "projects/PRJ-001/report.html");
    detach = attachBridge({ frame, appPath: APP, readFile: async () => "", requestSave });
    send(contentWindow, { type: MSG.save, id: 11, name: "../../etc/report.html", content: "<h1>r</h1>" });
    await settle();
    // The app's path is reduced to a bare name before the dialog ever sees it.
    expect(requestSave).toHaveBeenCalledWith("report.html", "<h1>r</h1>");
    expect(sent).toEqual([
      { type: MSG.saveResult, id: 11, ok: true, path: "projects/PRJ-001/report.html" },
    ]);
  });

  it("reports a cancelled dialog as a failure", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    detach = attachBridge({
      frame, appPath: APP, readFile: async () => "", requestSave: async () => null,
    });
    send(contentWindow, { type: MSG.save, id: 12, name: "r.md", content: "x" });
    await settle();
    expect(sent).toEqual([{ type: MSG.saveResult, id: 12, ok: false, error: "cancelled" }]);
  });

  it("refuses saving when the host offers no dialog", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    detach = attachBridge({ frame, appPath: APP, readFile: async () => "" });
    send(contentWindow, { type: MSG.save, id: 13, name: "r.md", content: "x" });
    await settle();
    expect(sent).toEqual([
      { type: MSG.saveResult, id: 13, ok: false, error: "saving is not enabled here" },
    ]);
  });

  it("rejects unusable names and oversized content before prompting", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    const requestSave = vi.fn(async () => "x/y.md");
    detach = attachBridge({ frame, appPath: APP, readFile: async () => "", requestSave });
    send(contentWindow, { type: MSG.save, id: 14, name: "..", content: "x" });
    send(contentWindow, { type: MSG.save, id: 15, name: "   ", content: "x" });
    send(contentWindow, { type: MSG.save, id: 16, name: "r.md", content: 42 });
    send(contentWindow, {
      type: MSG.save, id: 17, name: "r.md", content: "x".repeat(MAX_WRITE_BYTES + 1),
    });
    await settle();
    expect(requestSave).not.toHaveBeenCalled();
    expect(sent.map((m) => (m as { error: string }).error)).toEqual([
      "a file name is required", "a file name is required", "content must be a string", "too large",
    ]);
  });

  it("ignores messages from any other window", async () => {
    const { frame, sent } = fakeFrame();
    const readFile = vi.fn(async () => "secret");
    detach = attachBridge({ frame, appPath: APP, readFile });
    send({ postMessage: () => {} }, { type: MSG.read, id: 4, path: "apps/burnup/data.json" });
    send(null, { type: MSG.ready });
    await settle();
    expect(readFile).not.toHaveBeenCalled();
    expect(sent).toEqual([]);
  });

  it("ignores malformed messages", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    detach = attachBridge({ frame, appPath: APP, readFile: async () => "" });
    for (const m of [null, undefined, 0, "ready", { type: 42 }, { nope: true }]) send(contentWindow, m);
    await settle();
    expect(sent).toEqual([]);
  });

  it("clamps resize and ignores a non-numeric height", async () => {
    const { frame, contentWindow } = fakeFrame();
    const onResize = vi.fn();
    detach = attachBridge({ frame, appPath: APP, readFile: async () => "", onResize });
    send(contentWindow, { type: MSG.resize, height: 10 });
    send(contentWindow, { type: MSG.resize, height: 99999 });
    send(contentWindow, { type: MSG.resize, height: 500 });
    send(contentWindow, { type: MSG.resize, height: "tall" });
    await settle();
    expect(onResize.mock.calls.flat()).toEqual([120, 4000, 500]);
  });

  it("stops listening after detach", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    const off = attachBridge({ frame, appPath: APP, readFile: async () => "" });
    off();
    detach = () => {};
    send(contentWindow, { type: MSG.ready });
    await settle();
    expect(sent).toEqual([]);
  });
});

// `.length` is UTF-16 code units, so the old check passed ~2 MB of Arabic under a
// cap that called itself bytes. Bytes are never fewer than units and never more
// than 3× them, which is how this settles most writes without encoding 25 MB.
describe("the write limit counts bytes, not characters", () => {
  it("passes ASCII up to the cap and rejects one past it", () => {
    expect(overWriteLimit("x".repeat(MAX_WRITE_BYTES))).toBe(false);
    expect(overWriteLimit("x".repeat(MAX_WRITE_BYTES + 1))).toBe(true);
  });

  it("rejects text that fits in units but not in bytes", () => {
    const arabic = "ا".repeat(Math.ceil(MAX_WRITE_BYTES * 0.6));   // 1 unit, 2 bytes each
    expect(arabic.length).toBeLessThan(MAX_WRITE_BYTES);
    expect(overWriteLimit(arabic)).toBe(true);
  });

  it("counts UTF-8 as the browser writes it, lone surrogates included", () => {
    const enc = new TextEncoder();
    const high = String.fromCharCode(0xd800);
    const low = String.fromCharCode(0xdc00);
    for (const s of ["abc", "مرحبا", "€uro", "😀 ok", `a${high}b`, low, `${high}${low}`]) {
      expect(utf8Bytes(s)).toBe(enc.encode(s).length);
    }
  });
});

// The frame picks a connector and a path; everything that decides whether the
// call is allowed, and the credential itself, stay on this side of the bridge.
describe("cycls:fetch — an app calling a connector", () => {
  function wired(fetchConnector?: unknown) {
    const posted: Record<string, unknown>[] = [];
    const frame = { contentWindow: { postMessage: (m: Record<string, unknown>) => posted.push(m) } };
    const stop = attachBridge({
      frame: frame as unknown as HTMLIFrameElement,
      appPath: "apps/burnup/index.html",
      readFile: async () => "",
      fetchConnector: fetchConnector as never,
    });
    return { posted, send: (msg: Record<string, unknown>) => send(frame.contentWindow, msg), stop };
  }
  const settle = () => new Promise((r) => setTimeout(r, 0));

  it("passes a valid call through and returns what the host got", async () => {
    const calls: unknown[][] = [];
    const { posted, send, stop } = wired(async (...a: unknown[]) => {
      calls.push(a);
      return { status: 200, body: '{"ok":1}', contentType: "application/json" };
    });
    send({ type: MSG.fetch, id: 1, name: "salla", path: "orders", method: "get",
           headers: { accept: "application/json", authorization: "Bearer mine" } });
    await settle();
    expect(calls[0][0]).toBe("salla");
    expect(calls[0][1]).toBe("orders");
    // the app may set content-type and accept; Authorization is the server's alone
    expect((calls[0][2] as { headers: Record<string, string> }).headers).toEqual({ accept: "application/json" });
    expect((calls[0][2] as { method: string }).method).toBe("GET");
    expect(posted.at(-1)).toMatchObject({ type: MSG.fetchResult, id: 1, ok: true, status: 200 });
    stop();
  });

  it("refuses a bad connector, a climbing path, an odd method, and a shared view", async () => {
    const { posted, send, stop } = wired(async () => ({ status: 200, body: "", contentType: "" }));
    send({ type: MSG.fetch, id: 2, name: "../../etc", path: "x" });
    send({ type: MSG.fetch, id: 3, name: "salla", path: "../../../secrets" });
    send({ type: MSG.fetch, id: 4, name: "salla", path: "x", method: "TRACE" });
    await settle();
    expect(posted.map((m) => m.error)).toEqual([
      "a connector name is required", "a valid path is required", "method not allowed"]);
    stop();

    const shared = wired(undefined);
    shared.send({ type: MSG.fetch, id: 5, name: "salla", path: "x" });
    await settle();
    expect(shared.posted.at(-1)).toMatchObject({ ok: false, error: "connectors are not available here" });
    shared.stop();
  });
});


// An app loads its data once. The agent, a teammate or another tab could change it and the open app
// showed the old copy until it was reopened. The bridge compares versions and tells the app.
describe("keeping an open app in step", () => {
  let detach: () => void;
  afterEach(() => { detach?.(); vi.useRealTimers(); });

  type Versions = { keys?: Record<string, string>; files?: Record<string, string> };
  function setup(start: Versions, extra: { visible?: () => boolean } = {}) {
    vi.useFakeTimers();
    const { frame, sent, contentWindow } = fakeFrame();
    let now: Versions = start;
    const ops: Record<string, unknown>[] = [];
    const appData = vi.fn(async (_slug: string, op: Record<string, unknown>) => {
      ops.push(op);
      if (op.op === "versions") return now;
      if (op.op === "put") return { ok: true, version: `own-${String(op.key)}` };
      return null;
    });
    const reload = vi.fn();
    detach = attachBridge({ frame, appPath: APP, readFile: async () => "", writeFile: async () => {},
                            appData, reload, pollMs: 1000, visible: () => true, ...extra });
    return {
      sent, contentWindow, appData, reload, ops,
      set: (v: Versions) => { now = v; },
      checks: () => ops.filter((o) => o.op === "versions").length,
    };
  }
  const changes = (sent: unknown[]) => sent.filter((m) => (m as { type?: string }).type === MSG.changed);
  const agent = (detail: Record<string, unknown>) =>
    window.dispatchEvent(new CustomEvent(APP_DATA_EVENT, { detail: { slug: "burnup", ...detail } }));
  const wait = (ms: number) => vi.advanceTimersByTimeAsync(ms);

  it("tells a listening app at once which keys the agent changed", async () => {
    const t = setup({ keys: { a: "1" } });
    await wait(0);
    send(t.contentWindow, { type: MSG.listen });
    agent({ key: "a", version: "2" });
    agent({ key: "b", version: "1" });
    await wait(300);
    expect(changes(t.sent)).toEqual([{ type: MSG.changed, source: "agent", keys: ["a", "b"] }]);
    expect(t.reload).not.toHaveBeenCalled();
    // the turn ends: the agent's versions were taken in, so the same change is not told twice
    t.set({ keys: { a: "2", b: "1" } });
    window.dispatchEvent(new Event(TURN_END_EVENT));
    await wait(10);
    expect(changes(t.sent)).toHaveLength(1);
  });

  it("names no key when the agent removed a whole subtree", async () => {
    const t = setup({ keys: {} });
    await wait(0);
    send(t.contentWindow, { type: MSG.listen });
    agent({});
    await wait(300);
    expect(changes(t.sent)).toEqual([{ type: MSG.changed, source: "agent" }]);
  });

  it("ignores another app's changes", async () => {
    const t = setup({ keys: {} });
    await wait(0);
    send(t.contentWindow, { type: MSG.listen });
    window.dispatchEvent(new CustomEvent(APP_DATA_EVENT, { detail: { slug: "other", key: "a" } }));
    await wait(1500);
    expect(changes(t.sent)).toEqual([]);
  });

  it("reloads an app that does not listen when the agent changes its data", async () => {
    const t = setup({ keys: {} });
    await wait(0);
    agent({ key: "a", version: "1" });
    agent({ key: "b", version: "1" });
    await wait(1200);
    expect(t.reload).toHaveBeenCalledTimes(1);
    expect(changes(t.sent)).toEqual([]);
  });

  it("reloads it when a turn changed a data file it reads", async () => {
    const t = setup({ files: { "data/rows.json": "1-a" } });
    await wait(0);
    t.set({ files: { "data/rows.json": "2-b" } });
    window.dispatchEvent(new Event(TURN_END_EVENT));
    await wait(1000);
    expect(t.reload).toHaveBeenCalledTimes(1);
  });

  it("never reloads an app that does not listen for a teammate's change", async () => {
    const t = setup({ keys: { a: "1" } });
    await wait(0);
    t.set({ keys: { a: "2" } });
    window.dispatchEvent(new Event("focus"));
    await wait(5000);
    expect(t.reload).not.toHaveBeenCalled();
    expect(t.checks()).toBe(1);   // and does not poll it either: only the first look
  });

  it("polls a listening app while it is on screen and reports a teammate's change", async () => {
    const t = setup({ keys: { a: "1" } });
    await wait(0);
    send(t.contentWindow, { type: MSG.listen });
    await wait(2600);   // it just came into view: one look
    t.set({ keys: { a: "2", c: "1" } });
    await wait(2600);
    expect(changes(t.sent)).toEqual([{ type: MSG.changed, source: "poll", keys: ["a", "c"], files: [] }]);
  });

  it("does not poll an app that is off screen", async () => {
    const t = setup({ keys: {} }, { visible: () => false });
    await wait(0);
    send(t.contentWindow, { type: MSG.listen });
    await wait(10_000);
    expect(t.checks()).toBe(1);
  });

  it("does not tell the app about its own writes", async () => {
    const t = setup({ keys: { a: "1" }, files: {} });
    await wait(0);
    send(t.contentWindow, { type: MSG.listen });
    send(t.contentWindow, { type: MSG.data, id: 1, op: "put", key: "a", value: 2 });
    send(t.contentWindow, { type: MSG.write, id: 2, path: "apps/burnup/data/mine.json", content: "{}" });
    await wait(10);
    t.set({ keys: { a: "own-a" }, files: { "data/mine.json": "9-9", "data/theirs.json": "1-1" } });
    window.dispatchEvent(new Event(TURN_END_EVENT));
    await wait(10);
    expect(changes(t.sent)).toEqual([{ type: MSG.changed, source: "turn", keys: [], files: ["data/theirs.json"] }]);
  });

  it("throws away a check that overlapped a write of the app's own", async () => {
    const t = setup({ keys: { a: "1" } });
    await wait(0);
    send(t.contentWindow, { type: MSG.listen });
    let land: (v: unknown) => void = () => {};
    t.appData.mockImplementationOnce(async (_s: string, op: Record<string, unknown>) => {
      t.ops.push(op);
      return new Promise((r) => { land = r; });   // the check is slow to answer
    });
    window.dispatchEvent(new Event(TURN_END_EVENT));
    send(t.contentWindow, { type: MSG.data, id: 3, op: "put", key: "a", value: 2 });
    land({ keys: { a: "1" } });   // what the store said before the write landed
    await wait(10);
    t.set({ keys: { a: "own-a" } });
    await wait(1000);
    expect(changes(t.sent)).toEqual([]);
  });

  it("keeps its own versions call from the app", async () => {
    const t = setup({ keys: {} });
    send(t.contentWindow, { type: MSG.data, id: 4, op: "versions" });
    await wait(10);
    expect(t.sent).toContainEqual({ type: MSG.dataResult, id: 4, ok: false, error: "unknown op" });
  });

  it("makes a new document ask again before it is told rather than reloaded", async () => {
    const t = setup({ keys: {} });
    await wait(0);
    send(t.contentWindow, { type: MSG.listen });
    send(t.contentWindow, { type: MSG.ready });   // the app reloaded itself
    agent({ key: "a", version: "1" });
    await wait(1200);
    expect(t.reload).toHaveBeenCalledTimes(1);
  });

  it("stops everything when detached", async () => {
    const t = setup({ keys: {} });
    await wait(0);
    send(t.contentWindow, { type: MSG.listen });
    detach();
    agent({ key: "a", version: "1" });
    await wait(10_000);
    expect(t.reload).not.toHaveBeenCalled();
    expect(t.checks()).toBe(1);
  });
});


describe("the handshake", () => {
  let detach: () => void;
  afterEach(() => detach?.());

  // A busy frame announces twice before it hears back. A second channel replaced the one it took,
  // so every reply went where nobody listened and the app waited for its data forever.
  it("answers a document once, however often it announces", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    detach = attachBridge({ frame, appPath: APP, readFile: async () => "" });
    send(contentWindow, { type: MSG.ready, doc: "d1" });
    send(contentWindow, { type: MSG.ready, doc: "d1" });
    await settle();
    expect(sent.filter((m) => (m as { type?: string }).type === MSG.init)).toHaveLength(1);
  });

  it("answers a new document again", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    detach = attachBridge({ frame, appPath: APP, readFile: async () => "" });
    send(contentWindow, { type: MSG.ready, doc: "d1" });
    send(contentWindow, { type: MSG.ready, doc: "d2" });
    await settle();
    expect(sent.filter((m) => (m as { type?: string }).type === MSG.init)).toHaveLength(2);
  });
});


// The chat's mode used to reach an app once, at init: an open app stayed light after the person went dark.
describe("the chat's light or dark mode", () => {
  let detach: () => void;
  afterEach(() => { detach?.(); document.body.classList.remove("dark"); });

  it("tells an open app when the chat switches, and only when it does", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    detach = attachBridge({ frame, appPath: APP, readFile: async () => "", context: { theme: "light" } });
    void contentWindow;   // no handshake: messages stay on the window, where the test reads them
    document.body.classList.add("dark");
    await settle();
    document.body.classList.add("something-else");
    await settle();
    document.body.classList.remove("dark");
    await settle();
    expect(sent.filter((m) => (m as { type?: string }).type === MSG.theme)).toEqual([
      { type: MSG.theme, theme: "dark" }, { type: MSG.theme, theme: "light" },
    ]);
  });

  it("hands a reloaded app the mode it is in now, not the one it opened in", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    detach = attachBridge({ frame, appPath: APP, readFile: async () => "", context: { theme: "light" } });
    document.body.classList.add("dark");
    await settle();
    send(contentWindow, { type: MSG.ready, doc: "d2" });
    await settle();
    expect(sent.find((m) => (m as { type?: string }).type === MSG.init)).toMatchObject({ theme: "dark" });
  });
});


// Who is using an app: the viewer at its start, the workspace's members, and who last changed a key, as the
// server stamped it on the row (never what an app says about itself).
describe("who is using it", () => {
  let detach: () => void;
  afterEach(() => { detach?.(); vi.useRealTimers(); });
  const ME = { id: "u_me", name: "Me", role: "admin", you: true };
  const SARA = { id: "u_sara", name: "Sara", image: "data:image/webp;base64,AAAA", role: "editor" };
  type V = { keys?: Record<string, string>; who?: Record<string, unknown>; files?: Record<string, string> };

  function setup(opts: { people?: () => Promise<unknown[]>; versions?: V } = {}) {
    const { frame, sent, contentWindow } = fakeFrame();
    let now: V = opts.versions ?? { keys: {}, who: {} };
    const appData = vi.fn(async (_s: string, op: Record<string, unknown>) => (op.op === "versions" ? now : null));
    detach = attachBridge({ frame, appPath: APP, readFile: async () => "", appData, reload: vi.fn(),
                            people: opts.people as never, pollMs: 1000, visible: () => true,
                            context: { user: { id: "u_me", name: "Me", role: "admin" } } });
    return { sent, contentWindow, set: (v: V) => { now = v; } };
  }
  const answer = (sent: unknown[], id: number) =>
    sent.find((m) => (m as { type?: string; id?: number }).type === MSG.dataResult && (m as { id?: number }).id === id);
  const changed = (sent: unknown[]) => sent.filter((m) => (m as { type?: string }).type === MSG.changed);
  const ticks = () => new Promise((r) => setTimeout(r, 5));

  it("tells the app at its start who is viewing", async () => {
    const t = setup();
    send(t.contentWindow, { type: MSG.ready, doc: "d1" });
    await settle();
    expect(t.sent.find((m) => (m as { type?: string }).type === MSG.init))
      .toMatchObject({ user: { id: "u_me", name: "Me", role: "admin" } });
  });

  it("answers people() with the workspace's members, and refuses where there is no workspace", async () => {
    const t = setup({ people: async () => [ME, SARA] });
    send(t.contentWindow, { type: MSG.data, id: 1, op: "people" });
    await ticks();
    expect(answer(t.sent, 1)).toEqual({ type: MSG.dataResult, id: 1, ok: true, result: [ME, SARA] });
    detach();
    const shared = setup();
    send(shared.contentWindow, { type: MSG.data, id: 2, op: "people" });
    await ticks();
    expect(answer(shared.sent, 2)).toEqual({ type: MSG.dataResult, id: 2, ok: false, error: "this view has no workspace" });
  });

  it("answers who(key) with the person, when, and the agent that did it for them", async () => {
    const t = setup({ people: async () => [ME, SARA], versions: {
      keys: { a: "1", b: "2", old: "3" },
      who: { a: { by: "u_sara", at: "2026-11-11T10:00:00+00:00" },
             b: { by: "u_left", at: "2026-11-11T11:00:00+00:00", agent: "Super" } } } });
    send(t.contentWindow, { type: MSG.data, id: 1, op: "who", key: "a" });
    send(t.contentWindow, { type: MSG.data, id: 2, op: "who", key: "b" });
    send(t.contentWindow, { type: MSG.data, id: 3, op: "who", key: "old" });
    await ticks();
    expect(answer(t.sent, 1)).toMatchObject({ ok: true, result: { by: SARA, at: "2026-11-11T10:00:00+00:00" } });
    // someone no longer in the workspace is their id alone
    expect(answer(t.sent, 2)).toMatchObject({ ok: true, result: { by: { id: "u_left" }, agent: "Super" } });
    expect(answer(t.sent, 3)).toMatchObject({ ok: true, result: null });   // written before rows said who
  });

  it("says who changed each key when it tells a listening app", async () => {
    vi.useFakeTimers();
    const t = setup({ people: async () => [ME, SARA], versions: { keys: { a: "1" }, who: {} } });
    await vi.advanceTimersByTimeAsync(0);
    send(t.contentWindow, { type: MSG.listen });
    t.set({ keys: { a: "2" }, who: { a: { by: "u_sara", at: "T" } } });
    window.dispatchEvent(new Event(TURN_END_EVENT));
    await vi.advanceTimersByTimeAsync(10);
    expect(changed(t.sent)).toEqual([{ type: MSG.changed, source: "turn", keys: ["a"], files: [], who: { a: { by: SARA, at: "T" } } }]);
  });

  it("never holds a change back for a name", async () => {
    vi.useFakeTimers();
    const t = setup({ people: () => new Promise(() => {}), versions: { keys: { a: "1" }, who: {} } });
    await vi.advanceTimersByTimeAsync(0);
    send(t.contentWindow, { type: MSG.listen });
    t.set({ keys: { a: "2" }, who: { a: { by: "u_sara", at: "T" } } });
    window.dispatchEvent(new Event(TURN_END_EVENT));
    await vi.advanceTimersByTimeAsync(1600);
    expect(changed(t.sent)).toEqual([{ type: MSG.changed, source: "turn", keys: ["a"], files: [], who: { a: { by: { id: "u_sara" }, at: "T" } } }]);
  });
});
