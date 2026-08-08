import { describe, it, expect, vi, afterEach } from "vitest";
import { appScope, inScope, canWrite, attachBridge, MSG, MAX_WRITE_BYTES } from "../src/components/mini-app-bridge";

const APP = "apps/burnup/index.html";
const scope = appScope(APP)!;

describe("appScope", () => {
  it("is the app's folder", () => expect(scope).toBe("apps/burnup"));

  it("stays the app folder for a nested page", () =>
    expect(appScope("apps/burnup/reports/index.html")).toBe("apps/burnup"));

  // The canvas renders every html file. Anything that is not a mini app must
  // get no bridge at all: a root file used to scope to "" (the whole
  // workspace), and unlike a built app it carries no CSP, so it could read
  // everything and POST it anywhere.
  it("refuses anything that is not a mini app", () => {
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
  it("allows any file inside the app's folder", () => {
    for (const p of [
      "apps/burnup/state.json", "apps/burnup/notes.md", "apps/burnup/out/rows.csv",
      "apps/burnup/log.txt", "apps/burnup/report.html", "apps/burnup/chart.svg",
      "apps/burnup/noext", "apps/burnup/reports/index.html",
    ]) {
      expect(canWrite(scope, p), p).toBe(true);
    }
  });

  it("refuses the app's own entry and manifest, whatever the casing", () => {
    for (const p of [
      "apps/burnup/index.html", "apps/burnup/app.json",
      "apps/burnup/APP.JSON", "apps/burnup/Index.HTML",
    ]) {
      expect(canWrite(scope, p), p).toBe(false);
    }
  });

  it("inherits every scope rule", () => {
    for (const p of ["apps/other/state.json", "../escape.json", "/abs.json", scope, 42]) {
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

  it("attaches nothing for a file that is not a mini app", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    const readFile = vi.fn(async () => "secret");
    detach = attachBridge({ frame, appPath: "report.html", readFile });
    send(contentWindow, { type: MSG.ready });
    send(contentWindow, { type: MSG.read, id: 1, path: "apps/injaz/data/PRJ-001.json" });
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
    send(contentWindow, { type: MSG.write, id: 5, path: "apps/burnup/state.json", content: '{"a":1}' });
    await settle();
    expect(writeFile).toHaveBeenCalledWith("apps/burnup/state.json", '{"a":1}');
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
    send(contentWindow, { type: MSG.write, id: 7, path: "apps/burnup/state.json", content: "{}" });
    await settle();
    expect(sent).toEqual([
      { type: MSG.writeResult, id: 7, ok: false, error: "writes are not enabled here" },
    ]);
  });

  it("refuses non-string and oversized content", async () => {
    const { frame, sent, contentWindow } = fakeFrame();
    const writeFile = vi.fn(async () => {});
    detach = attachBridge({ frame, appPath: APP, readFile: async () => "", writeFile });
    send(contentWindow, { type: MSG.write, id: 8, path: "apps/burnup/state.json", content: { a: 1 } });
    send(contentWindow, {
      type: MSG.write, id: 9, path: "apps/burnup/state.json", content: "x".repeat(MAX_WRITE_BYTES + 1),
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
    send(contentWindow, { type: MSG.write, id: 10, path: "apps/burnup/state.json", content: "{}" });
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
