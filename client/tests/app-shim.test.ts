import { describe, it, expect, beforeAll, afterAll, beforeEach, afterEach } from "vitest";
import { injectShim } from "../src/components/app-shim";

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

  it("persists as rows in the store, not as a file", () => {
    const js = shimOf("<html><head></head></html>");
    expect(js).toContain("cycls:data");
    expect(js).not.toContain("data/state.json");
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

  it("announces itself until the host replies, naming its document", () => {
    const { posted } = load("apps/burnup");
    expect(posted[0]).toMatchObject({ type: "cycls:ready" });
    expect(typeof posted[0].doc).toBe("string");
    expect((posted[0].doc as string).length).toBeGreaterThan(8);
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

  // A set() leaves at once, with no timer a closed or backgrounded WebView would never run. One write per
  // key is on its way at a time, so a burst sends its first value and then its latest, never out of order.
  it("sends each set at once, and a burst on one key as its first and latest value", async () => {
    const { api, posted, deliver } = load("apps/burnup");
    const done = Promise.all([api.set("a", 1), api.set("b", 2), api.set("a", 3)]);
    await new Promise((r) => setTimeout(r, 0));
    const list = posted.find((m) => m.type === "cycls:data")!;
    deliver({ type: "cycls:data:result", id: list.id, ok: true, result: { rows: [] } });
    await new Promise((r) => setTimeout(r, 0));
    const puts = () => posted.filter((m) => m.op === "put");
    expect(puts().map((m) => [m.key, m.value])).toEqual([["a", 1], ["b", 2]]);
    puts().forEach((m) => deliver({ type: "cycls:data:result", id: m.id, ok: true, result: { ok: true } }));
    await new Promise((r) => setTimeout(r, 0));
    expect(puts().map((m) => [m.key, m.value])).toEqual([["a", 1], ["b", 2], ["a", 3]]);
    deliver({ type: "cycls:data:result", id: puts()[2].id, ok: true, result: { ok: true } });
    await expect(done).resolves.toBeDefined();
    await expect(api.flush()).resolves.toBeUndefined();
  });

  it("carries a delete through as its own row", async () => {
    const { api, posted, deliver } = load("apps/burnup");
    const done = api.set("gone", undefined);
    await new Promise((r) => setTimeout(r, 0));
    const list = posted.find((m) => m.type === "cycls:data")!;
    deliver({ type: "cycls:data:result", id: list.id, ok: true, result: { rows: [{ key: "gone", value: 1 }] } });
    await new Promise((r) => setTimeout(r, 0));
    const del = posted.find((m) => m.op === "delete")!;
    expect(del.key).toBe("gone");
    deliver({ type: "cycls:data:result", id: del.id, ok: true, result: { ok: true } });
    await expect(done).resolves.toBeUndefined();
  });

  it("reads back what it set, and falls back for a missing key", async () => {
    const { api, posted, deliver } = load("apps/burnup");
    const p = api.get("missing", "dflt");
    await new Promise((r) => setTimeout(r, 0));
    const list = posted.find((m) => m.type === "cycls:data")!;
    deliver({ type: "cycls:data:result", id: list.id, ok: true, result: { rows: [{ key: "kept", value: 7 }] } });
    await expect(p).resolves.toBe("dflt");
    await expect(api.get("kept")).resolves.toBe(7);
    await expect(api.keys()).resolves.toEqual(["kept"]);
  });

  it("starts empty when the shelf has no rows or the list fails", async () => {
    for (const ok of [true, false]) {
      const { api, posted, deliver } = load("apps/burnup");
      const p = api.keys();
      await new Promise((r) => setTimeout(r, 0));
      const list = posted.find((m) => m.type === "cycls:data")!;
      deliver({ type: "cycls:data:result", id: list.id, ok, result: { rows: [] }, error: "403" });
      await expect(p).resolves.toEqual([]);
    }
  });

  // The frame names an audience, never a person: the server fills in the viewer
  // from the session, so there is no id here to get wrong.
  it("sends me/ and users/ reads with who, and no user id of its own", async () => {
    const { api, posted, deliver } = load("apps/burnup");
    const shelves = api as unknown as {
      me: { get: (k: string) => Promise<unknown>; set: (k: string, v: unknown) => Promise<unknown> };
      users: { all: (p?: string) => Promise<unknown>; set: (u: string, k: string, v: unknown) => Promise<unknown> };
    };
    shelves.me.set("draft", "half a sen");
    shelves.users.all("");
    shelves.users.set("user_2", "sep", { approved: true });
    await new Promise((r) => setTimeout(r, 0));
    const sent = posted.filter((m) => m.type === "cycls:data");
    expect(sent.map((m) => [m.op, m.who])).toEqual([
      ["put", "me"], ["list", "all"], ["put", "user_2"],
    ]);
    expect(sent[0].key).toBe("draft");
    expect(sent.some((m) => "user" in m)).toBe(false);
    deliver({ type: "cycls:data:result", id: sent[0].id, ok: true, result: { ok: true } });
  });
});

describe("the store's two safety rails", () => {
  function load(scope: string) {
    const js = injectShim("<html><head></head></html>").match(/<script>([\s\S]*)<\/script>/)![1];
    const posted: Record<string, unknown>[] = [];
    const listeners: ((e: { data: unknown }) => void)[] = [];
    const win: Record<string, unknown> = {};
    new Function("window", "parent", "addEventListener", "setTimeout", "clearTimeout", js)(
      win,
      { postMessage: (m: Record<string, unknown>) => posted.push(m) },
      (t: string, fn: (e: { data: unknown }) => void) => t === "message" && listeners.push(fn),
      (fn: () => void) => setTimeout(fn, 0),
      clearTimeout,
    );
    const api = win.cycls as Record<string, (...a: unknown[]) => Promise<unknown>>;
    const deliver = (data: unknown) => listeners.forEach((fn) => fn({ data }));
    deliver({ type: "cycls:init", path: `${scope}/index.html`, scope, canWrite: true });
    return { api, posted, deliver };
  }
  const tick = () => new Promise((r) => setTimeout(r, 0));

  // A truncated shelf makes "absent" meaningless: the key may well exist in the
  // page that was cut. Returning the fallback would be a confident wrong answer.
  it("refuses to answer get() from a page it knows is incomplete", async () => {
    const { api, posted, deliver } = load("apps/burnup");
    const p = api.get("maybe", "dflt");
    await tick();
    const list = posted.find((m) => m.type === "cycls:data")!;
    deliver({ type: "cycls:data:result", id: list.id, ok: true,
              result: { rows: [{ key: "here", value: 1 }], truncated: true } });
    await expect(p).rejects.toThrow(/too many keys/);
    await expect(api.get("here")).resolves.toBe(1);   // a key it did see is still fine
  });

  it("update() re-reads and re-applies when someone wrote first", async () => {
    const { api, posted, deliver } = load("apps/burnup");
    const done = (api.update as (k: string, f: (v: unknown) => unknown) => Promise<unknown>)(
      "items", (cur) => [...((cur as number[]) ?? []), 9]);
    const sent = (op: string, n: number) => posted.filter((m) => m.op === op)[n];

    await tick();
    deliver({ type: "cycls:data:result", id: sent("get", 0).id, ok: true,
              result: { value: [1], version: "v1" } });
    await tick();
    expect(sent("put", 0).version).toBe("v1");
    expect(sent("put", 0).value).toEqual([1, 9]);

    // someone else landed a write in between
    deliver({ type: "cycls:data:result", id: sent("put", 0).id, ok: false, error: "412", status: 412 });
    await tick();
    deliver({ type: "cycls:data:result", id: sent("get", 1).id, ok: true,
              result: { value: [1, 2], version: "v2" } });
    await tick();
    // re-applied onto what is actually there — nobody's write is lost
    expect(sent("put", 1).value).toEqual([1, 2, 9]);
    expect(sent("put", 1).version).toBe("v2");
    deliver({ type: "cycls:data:result", id: sent("put", 1).id, ok: true, result: { ok: true } });
    await expect(done).resolves.toEqual([1, 2, 9]);
  });
});


describe("hearing that the data changed", () => {
  function load() {
    const js = injectShim("<html><head></head></html>").match(/<script>([\s\S]*)<\/script>/)![1];
    const posted: Record<string, unknown>[] = [];
    const listeners: ((e: { data: unknown }) => void)[] = [];
    const win: Record<string, unknown> = {};
    new Function("window", "parent", "addEventListener", "setTimeout", "clearTimeout", js)(
      win,
      { postMessage: (m: Record<string, unknown>) => posted.push(m) },
      (t: string, fn: (e: { data: unknown }) => void) => t === "message" && listeners.push(fn),
      (fn: () => void) => setTimeout(fn, 0),
      clearTimeout,
    );
    const api = win.cycls as Record<string, (...a: unknown[]) => Promise<unknown>> & {
      onChange: (fn: (e: unknown) => void) => () => void;
    };
    const deliver = (data: unknown) => listeners.forEach((fn) => fn({ data }));
    deliver({ type: "cycls:init", path: "apps/burnup/index.html", scope: "apps/burnup", canWrite: true });
    const answer = (op: string, result: unknown, n = 0) => {
      const m = posted.filter((p) => p.type === "cycls:data" && p.op === op)[n];
      deliver({ type: "cycls:data:result", id: m.id, ok: true, result });
    };
    return { api, posted, deliver, answer };
  }
  const tick = () => new Promise((r) => setTimeout(r, 0));

  it("asks the host to be told once, after the handshake", async () => {
    const { api, posted } = load();
    api.onChange(() => {});
    api.onChange(() => {});
    await tick();
    expect(posted.filter((m) => m.type === "cycls:listen")).toHaveLength(1);
  });

  it("reads the named keys again, then calls the listener with the new values in place", async () => {
    const { api, deliver, answer, posted } = load();
    const first = api.get("a");
    await tick();
    answer("list", { rows: [{ key: "a", value: 1 }, { key: "b", value: 1 }] });
    await expect(first).resolves.toBe(1);
    const heard: unknown[] = [];
    api.onChange(async (e) => heard.push([e, await api.get("a"), await api.get("b")]));
    deliver({ type: "cycls:changed", source: "agent", keys: ["a"] });
    await tick();
    expect(posted.filter((m) => m.op === "get").map((m) => m.key)).toEqual(["a"]);
    answer("get", { value: 2, version: "v2" });
    await tick(); await tick();
    expect(heard).toEqual([[{ source: "agent", keys: ["a"] }, 2, 1]]);
  });

  it("drops a key that is gone", async () => {
    const { api, deliver, answer } = load();
    const first = api.get("a");
    await tick();
    answer("list", { rows: [{ key: "a", value: 1 }] });
    await first;
    deliver({ type: "cycls:changed", source: "agent", keys: ["a"] });
    await tick();
    answer("get", null);
    await tick();
    await expect(api.get("a", "gone")).resolves.toBe("gone");
  });

  it("keeps a value of its own that is still on its way", async () => {
    const { api, deliver, answer } = load();
    const first = api.get("a");
    await tick();
    answer("list", { rows: [{ key: "a", value: 1 }] });
    await first;
    void api.set("a", 5);   // not landed yet
    await tick();
    deliver({ type: "cycls:changed", source: "poll", keys: ["a"] });
    await tick();
    answer("get", { value: 1, version: "v1" });   // what the store had before it landed
    await tick();
    await expect(api.get("a")).resolves.toBe(5);
  });

  it("lists everything again when no key is named", async () => {
    const { api, deliver, answer, posted } = load();
    const first = api.get("a");
    await tick();
    answer("list", { rows: [{ key: "a", value: 1 }] });
    await first;
    const heard: unknown[] = [];
    api.onChange((e) => heard.push(e));
    deliver({ type: "cycls:changed", source: "agent" });
    await tick();
    expect(posted.filter((m) => m.op === "list")).toHaveLength(2);
    answer("list", { rows: [{ key: "a", value: 3 }, { key: "n", value: 1 }] }, 1);
    await tick(); await tick();
    expect(heard).toEqual([{ source: "agent" }]);
    await expect(api.get("a")).resolves.toBe(3);
    await expect(api.keys()).resolves.toEqual(["a", "n"]);
  });

  it("passes the files on, and reads nothing before the app has", async () => {
    const { api, deliver, posted } = load();
    const heard: unknown[] = [];
    api.onChange((e) => heard.push(e));
    deliver({ type: "cycls:changed", source: "turn", keys: [], files: ["data/rows.json"] });
    await tick();
    expect(heard).toEqual([{ source: "turn", keys: [], files: ["data/rows.json"] }]);
    expect(posted.filter((m) => m.type === "cycls:data")).toEqual([]);
  });

  it("stops calling a listener that unsubscribed", async () => {
    const { api, deliver } = load();
    const heard: unknown[] = [];
    const off = api.onChange((e) => heard.push(e));
    off();
    deliver({ type: "cycls:changed", source: "poll", keys: [] });
    await tick();
    expect(heard).toEqual([]);
  });

  it("refresh() lists again without waiting to be told", async () => {
    const { api, answer, posted } = load();
    const first = api.get("a");
    await tick();
    answer("list", { rows: [{ key: "a", value: 1 }] });
    await first;
    const done = api.refresh();
    await tick();
    answer("list", { rows: [{ key: "a", value: 9 }] }, 1);
    await done;
    await expect(api.get("a")).resolves.toBe(9);
    expect(posted.filter((m) => m.op === "list")).toHaveLength(2);
  });
});


// The canvas frame has no allow-forms, so the browser blocks a submission before the submit event:
// every <form onSubmit> in an app did nothing. The shim fires the event itself.
describe("forms in a sandboxed frame", () => {
  function install() {
    const js = injectShim("<html><head></head></html>").match(/<script>([\s\S]*)<\/script>/)![1];
    const scope = {
      window, parent: { postMessage: () => {} },
      addEventListener: window.addEventListener.bind(window),
      setTimeout: () => 0, clearTimeout: () => {},
    };
    new Function(...Object.keys(scope), js)(...Object.values(scope));
  }
  const saved = HTMLFormElement.prototype.requestSubmit;
  let form: HTMLFormElement;
  let heard: (string | null)[];
  beforeAll(install);
  afterAll(() => { HTMLFormElement.prototype.requestSubmit = saved; });
  beforeEach(() => {
    document.body.innerHTML = `<form><input name="t" /><textarea></textarea>
      <button type="button" id="plain">plain</button><button id="go">go</button></form>`;
    form = document.querySelector("form")!;
    heard = [];
    form.addEventListener("submit", (e) => { e.preventDefault(); heard.push((e as SubmitEvent).submitter?.id ?? null); });
  });

  it("a submit button's click fires submit, with the button as submitter", () => {
    document.getElementById("go")!.click();
    expect(heard).toEqual(["go"]);
  });

  it("a type=button click does not", () => {
    document.getElementById("plain")!.click();
    expect(heard).toEqual([]);
  });

  it("an app handler that prevented the click wins", () => {
    document.getElementById("go")!.addEventListener("click", (e) => e.preventDefault());
    document.getElementById("go")!.click();
    expect(heard).toEqual([]);
  });

  it("Enter in a text field submits; Enter in a textarea does not", () => {
    const enter = (el: Element) => el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
    enter(form.querySelector("textarea")!);
    expect(heard).toEqual([]);
    enter(form.querySelector("input")!);
    expect(heard).toEqual(["go"]);
  });

  it("requestSubmit() fires it too", () => {
    form.requestSubmit();
    expect(heard).toEqual([null]);
  });

  it("a form that fails its own validation is not submitted", () => {
    form.querySelector("input")!.required = true;
    document.getElementById("go")!.click();
    expect(heard).toEqual([]);
  });
});


describe("following the chat's light or dark mode", () => {
  function install() {
    const js = injectShim("<html><head></head></html>").match(/<script>([\s\S]*)<\/script>/)![1];
    const listeners: ((e: { data: unknown }) => void)[] = [];
    const win: Record<string, unknown> = {};
    new Function("window", "parent", "addEventListener", "setTimeout", "clearTimeout", js)(
      win, { postMessage: () => {} },
      (t: string, fn: (e: { data: unknown }) => void) => t === "message" && listeners.push(fn),
      (fn: () => void) => setTimeout(fn, 0), clearTimeout,
    );
    const deliver = (data: unknown) => listeners.forEach((fn) => fn({ data }));
    return { api: win.cycls as { ctx: { theme?: string }; onTheme: (fn: (t: string) => void) => () => void }, deliver };
  }
  afterEach(() => document.documentElement.classList.remove("dark"));

  it("sets the dark class at init and on every switch, and tells the listeners", () => {
    const { api, deliver } = install();
    deliver({ type: "cycls:init", path: "apps/x/index.html", scope: "apps/x", theme: "dark" });
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    const heard: string[] = [];
    const off = api.onTheme((t) => heard.push(t));
    deliver({ type: "cycls:theme", theme: "light" });
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(api.ctx.theme).toBe("light");
    off();
    deliver({ type: "cycls:theme", theme: "dark" });
    expect(heard).toEqual(["light"]);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("ignores a mode it does not know", () => {
    const { deliver } = install();
    deliver({ type: "cycls:init", path: "apps/x/index.html", scope: "apps/x", theme: "light" });
    deliver({ type: "cycls:theme", theme: "sepia" });
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});


describe("who is using it", () => {
  function load(user: unknown) {
    const js = injectShim("<html><head></head></html>").match(/<script>([\s\S]*)<\/script>/)![1];
    const posted: Record<string, unknown>[] = [];
    const listeners: ((e: { data: unknown }) => void)[] = [];
    const win: Record<string, unknown> = {};
    new Function("window", "parent", "addEventListener", "setTimeout", "clearTimeout", js)(
      win,
      { postMessage: (m: Record<string, unknown>) => posted.push(m) },
      (t: string, fn: (e: { data: unknown }) => void) => t === "message" && listeners.push(fn),
      (fn: () => void) => setTimeout(fn, 0),
      clearTimeout,
    );
    const api = win.cycls as Record<string, (...a: unknown[]) => Promise<unknown>> & {
      ctx: { user: unknown }; onChange: (fn: (e: unknown) => void) => () => void;
    };
    const deliver = (data: unknown) => listeners.forEach((fn) => fn({ data }));
    deliver({ type: "cycls:init", path: "apps/burnup/index.html", scope: "apps/burnup", canWrite: true, user });
    const answer = (op: string, result: unknown) => {
      const m = posted.filter((p) => p.type === "cycls:data" && p.op === op)[0];
      deliver({ type: "cycls:data:result", id: m.id, ok: true, result });
    };
    return { api, posted, deliver, answer };
  }
  const tick = () => new Promise((r) => setTimeout(r, 0));

  it("knows the viewer from the start, and nobody on a shared link", () => {
    expect(load({ id: "u_me", name: "Me", role: "admin" }).api.ctx.user).toEqual({ id: "u_me", name: "Me", role: "admin" });
    expect(load(undefined).api.ctx.user).toBeNull();
    expect(load("u_me").api.ctx.user).toBeNull();   // only a person the host sends
  });

  it("asks the host for the members and for who changed a key", async () => {
    const { api, posted, answer } = load({ id: "u_me" });
    const people = api.people();
    const who = api.who("tasks");
    await tick();
    expect(posted.filter((m) => m.type === "cycls:data").map((m) => [m.op, m.key]))
      .toEqual([["people", undefined], ["who", "tasks"]]);
    answer("people", [{ id: "u_me", you: true }]);
    answer("who", { by: { id: "u_sara", name: "Sara" }, at: "T" });
    await expect(people).resolves.toEqual([{ id: "u_me", you: true }]);
    await expect(who).resolves.toEqual({ by: { id: "u_sara", name: "Sara" }, at: "T" });
  });

  it("says you changed a key you just wrote, before the host has looked again", async () => {
    const { api, posted, deliver, answer } = load({ id: "u_me", name: "Me" });
    const first = api.get("a");
    await tick();
    answer("list", { rows: [{ key: "a", value: 1 }] });
    await first;
    const done = api.set("a", 2);
    await tick();
    const put = posted.find((m) => m.op === "put")!;
    deliver({ type: "cycls:data:result", id: put.id, ok: true, result: { ok: true, version: "v2" } });
    await done;
    const who = api.who("a");
    await tick();
    answer("who", { by: { id: "u_sara" }, at: "2000-01-01T00:00:00+00:00" });   // the host's look predates the write
    expect(await who).toMatchObject({ by: { id: "u_me", name: "Me", you: true } });
  });

  it("says you changed it just now, when the host still has your earlier change", async () => {
    const { api, posted, deliver, answer } = load({ id: "u_me", name: "Me" });
    const first = api.get("a");
    await tick();
    answer("list", { rows: [{ key: "a", value: 1 }] });
    await first;
    const done = api.set("a", 2);
    await tick();
    const put = posted.find((m) => m.op === "put")!;
    deliver({ type: "cycls:data:result", id: put.id, ok: true, result: { ok: true, version: "v2" } });
    await done;
    const who = api.who("a");
    await tick();
    answer("who", { by: { id: "u_me", name: "Me", image: "data:image/webp;base64,AA" }, at: "2000-01-01T00:00:00+00:00" });
    const got = (await who) as { by: { image?: string; you?: boolean }; at: string };
    expect(got.by).toMatchObject({ image: "data:image/webp;base64,AA", you: true });   // the host's picture
    expect(Date.parse(got.at)).toBeGreaterThan(Date.parse("2020-01-01"));             // this write's time, not the old one
  });

  it("passes on who changed each key", async () => {
    const { api, deliver } = load({ id: "u_me" });
    const heard: unknown[] = [];
    api.onChange((e) => heard.push(e));
    deliver({ type: "cycls:changed", source: "poll", keys: ["a"], who: { a: { by: { id: "u_sara" }, at: "T" } } });
    await tick(); await tick();
    expect(heard).toEqual([{ source: "poll", keys: ["a"], who: { a: { by: { id: "u_sara" }, at: "T" } } }]);
  });
});
