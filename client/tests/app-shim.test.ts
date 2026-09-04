import { describe, it, expect } from "vitest";
import { injectShim, STATE_FILE } from "../src/components/app-shim";

const shimOf = (html: string) => injectShim(html).match(/<script>[\s\S]*?<\/script>/)?.[0] ?? "";

describe("injectShim", () => {
  it("lands inside head, after the doctype", () => {
    const out = injectShim('<!doctype html><html lang="en"><head><title>x</title></head><body>hi</body></html>');
    expect(out.indexOf("<!doctype html>")).toBe(0);
    expect(out.indexOf("<script>")).toBeLessThan(out.indexOf("<title>"));
  });

  it("falls back to the html tag, then to the front", () => {
    expect(injectShim("<html><body>hi</body></html>").indexOf("<script>")).toBe("<html>".length);
    expect(injectShim("<p>bare</p>").indexOf("<script>")).toBe(0);
  });

  it("tolerates attributes and casing on head", () => {
    const out = injectShim('<HTML><HEAD data-x="1"><meta charset="utf-8"></HEAD></HTML>');
    expect(out.indexOf("<script>")).toBeLessThan(out.indexOf("<meta"));
  });

  it("closes its own tag so the document keeps parsing", () => {
    const out = injectShim("<html><head></head><body>hi</body></html>");
    expect(out.match(/<script>/g)).toHaveLength(1);
    expect(out.match(/<\/script>/g)).toHaveLength(1);
    expect(out).toContain("<body>hi</body>");
  });

  it("keeps the app's own markup byte for byte", () => {
    const html = "<html><head></head><body><div>a &amp; b</div></body></html>";
    expect(injectShim(html).replace(shimOf(html), "")).toBe(html);
  });

  it("is syntactically valid JavaScript", () => {
    const js = shimOf("<html><head></head></html>").replace(/^<script>|<\/script>$/g, "");
    expect(() => new Function(js)).not.toThrow();
  });

  it("persists through one JSON file in the app's folder", () => {
    expect(STATE_FILE).toBe("state.json");
    expect(shimOf("<html><head></head></html>")).toContain('"state.json"');
  });
});

describe("the injected cycls api", () => {
  function load(scope: string) {
    const js = shimOf("<html><head></head></html>").replace(/^<script>|<\/script>$/g, "");
    const posted: Record<string, unknown>[] = [];
    const listeners: ((e: { data: unknown }) => void)[] = [];
    const win: Record<string, unknown> = {};
    const scope_ = {
      window: win,
      parent: { postMessage: (m: Record<string, unknown>) => posted.push(m) },
      addEventListener: (t: string, fn: (e: { data: unknown }) => void) => t === "message" && listeners.push(fn),
      setTimeout: (fn: () => void) => setTimeout(fn, 0),
      clearTimeout,
    };
    new Function(...Object.keys(scope_), js)(...Object.values(scope_));
    const api = win.cycls as Record<string, (...a: unknown[]) => Promise<unknown>> & { ctx: unknown };
    const deliver = (data: unknown) => listeners.forEach((fn) => fn({ data }));
    deliver({ type: "cycls:init", path: `${scope}/index.html`, scope, theme: "dark", canWrite: true });
    return { api, posted, deliver };
  }

  // A sandboxed frame throws on localStorage access; an app that reads it while
  // rendering dies before it can talk to the host at all.
  it("replaces a throwing localStorage with a working in-memory one", () => {
    const js = shimOf("<html><head></head></html>").replace(/^<script>|<\/script>$/g, "");
    const win: Record<string, unknown> = {};
    Object.defineProperty(win, "localStorage", {
      get() { throw new Error("SecurityError"); },
      configurable: true,
    });
    const scope = {
      window: win,
      parent: { postMessage: () => {} },
      addEventListener: () => {},
      setTimeout: () => 0,
      clearTimeout: () => {},
    };
    new Function(...Object.keys(scope), js)(...Object.values(scope));

    const ls = win.localStorage as Storage;
    expect(() => ls.getItem("k")).not.toThrow();
    expect(ls.getItem("k")).toBeNull();
    ls.setItem("k", "v");
    expect(ls.getItem("k")).toBe("v");
    expect(ls.length).toBe(1);
    expect(ls.key(0)).toBe("k");
    ls.removeItem("k");
    expect(ls.getItem("k")).toBeNull();
    ls.setItem("a", "1");
    ls.clear();
    expect(ls.length).toBe(0);
    expect(win.sessionStorage).toBeDefined();
  });

  it("leaves a working localStorage alone", () => {
    const js = shimOf("<html><head></head></html>").replace(/^<script>|<\/script>$/g, "");
    const real = { getItem: () => "real", setItem: () => {} };
    const win: Record<string, unknown> = { localStorage: real };
    const scope = {
      window: win,
      parent: { postMessage: () => {} },
      addEventListener: () => {},
      setTimeout: () => 0,
      clearTimeout: () => {},
    };
    new Function(...Object.keys(scope), js)(...Object.values(scope));
    expect(win.localStorage).toBe(real);
  });

  it("hands the app its context once the host answers", async () => {
    const { api } = load("apps/burnup");
    await expect(api.ready as unknown as Promise<unknown>).resolves.toMatchObject({ scope: "apps/burnup", canWrite: true });
    expect(api.ctx).toMatchObject({ theme: "dark" });
  });

  it("announces itself until the host replies", () => {
    const { posted } = load("apps/burnup");
    expect(posted[0]).toEqual({ type: "cycls:ready" });
  });

  it("resolves a bare filename against the app's own folder", async () => {
    const { api, posted, deliver } = load("apps/burnup");
    const p = api.read("data.json");
    await Promise.resolve();
    const sent = posted.find((m) => m.type === "cycls:read");
    expect(sent).toMatchObject({ path: "apps/burnup/data.json" });
    deliver({ type: "cycls:read:result", id: sent!.id, ok: true, content: "hi" });
    await expect(p).resolves.toBe("hi");
  });

  it("leaves an already-scoped path alone", async () => {
    const { api, posted } = load("apps/burnup");
    void api.read("apps/burnup/nested/data.json");
    await Promise.resolve();
    expect(posted.find((m) => m.type === "cycls:read")).toMatchObject({
      path: "apps/burnup/nested/data.json",
    });
  });

  it("rejects when the host refuses", async () => {
    const { api, posted, deliver } = load("apps/burnup");
    const p = api.read("data.json");
    await Promise.resolve();
    const sent = posted.find((m) => m.type === "cycls:read")!;
    deliver({ type: "cycls:read:result", id: sent.id, ok: false, error: "nope" });
    await expect(p).rejects.toThrow("nope");
  });

  it("coalesces a burst of sets into one write", async () => {
    const { api, posted, deliver } = load("apps/burnup");
    const done = Promise.all([api.set("a", 1), api.set("b", 2), api.set("a", 3)]);
    await new Promise((r) => setTimeout(r, 0));
    const read = posted.find((m) => m.type === "cycls:read")!;
    deliver({ type: "cycls:read:result", id: read.id, ok: true, content: "{}" });
    await new Promise((r) => setTimeout(r, 20));
    const writes = posted.filter((m) => m.type === "cycls:write");
    expect(writes).toHaveLength(1);
    expect(JSON.parse(writes[0].content as string)).toEqual({ a: 3, b: 2 });
    deliver({ type: "cycls:write:result", id: writes[0].id, ok: true });
    await expect(done).resolves.toBeDefined();
  });

  it("reads back what it set, and falls back for a missing key", async () => {
    const { api, posted, deliver } = load("apps/burnup");
    const p = api.get("missing", "dflt");
    await new Promise((r) => setTimeout(r, 0));
    const read = posted.find((m) => m.type === "cycls:read")!;
    deliver({ type: "cycls:read:result", id: read.id, ok: true, content: '{"kept":7}' });
    await expect(p).resolves.toBe("dflt");
    await expect(api.get("kept")).resolves.toBe(7);
    await expect(api.keys()).resolves.toEqual(["kept"]);
  });

  it("starts empty when state.json is absent or not an object", async () => {
    for (const body of [null, '["a"]', "not json"]) {
      const { api, posted, deliver } = load("apps/burnup");
      const p = api.keys();
      await new Promise((r) => setTimeout(r, 0));
      const read = posted.find((m) => m.type === "cycls:read")!;
      if (body === null) deliver({ type: "cycls:read:result", id: read.id, ok: false, error: "404" });
      else deliver({ type: "cycls:read:result", id: read.id, ok: true, content: body });
      await expect(p).resolves.toEqual([]);
    }
  });
});
