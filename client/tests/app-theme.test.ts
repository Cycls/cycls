import { describe, it, expect, afterEach } from "vitest";
import {
  BASES, COLORS, RADII, DEFAULT_CHOICE, themeTokens, normalize, onColor,
  setAppTheme, getAppTheme, subscribeAppTheme, appThemeContext,
} from "../src/lib/app-theme";
import { injectShim } from "../src/components/app-shim";
import { attachBridge, MSG } from "../src/components/app-bridge";

// The names shadcn/ui components read. An app built on them re-skins only if every one is sent.
const SHADCN = ["--radius", "--background", "--foreground", "--card", "--card-foreground", "--popover",
  "--popover-foreground", "--primary", "--primary-foreground", "--secondary", "--secondary-foreground",
  "--muted", "--muted-foreground", "--accent", "--accent-foreground", "--destructive", "--border", "--input",
  "--ring", "--chart-1", "--chart-2", "--chart-3", "--chart-4", "--chart-5", "--sidebar", "--sidebar-foreground",
  "--sidebar-primary", "--sidebar-primary-foreground", "--sidebar-accent", "--sidebar-accent-foreground",
  "--sidebar-border", "--sidebar-ring"].sort();

describe("themeTokens", () => {
  it("sends every shadcn token, light and dark, for every base and accent", () => {
    for (const base of BASES) for (const color of COLORS) {
      const t = themeTokens({ base, color, radius: 0.5 });
      expect(Object.keys(t.light).sort(), `${base}/${color} light`).toEqual(SHADCN);
      expect(Object.keys(t.dark).sort(), `${base}/${color} dark`).toEqual(SHADCN);
      for (const v of [...Object.values(t.light), ...Object.values(t.dark)]) expect(v).toMatch(/^(oklch\(|#|\d)/);
    }
  });

  it("an accent changes the primary family and nothing else", () => {
    const plain = themeTokens({ base: "zinc", color: "base", radius: 0.5 });
    const violet = themeTokens({ base: "zinc", color: "violet", radius: 0.5 });
    const changed = Object.keys(plain.light).filter((k) => plain.light[k] !== violet.light[k]).sort();
    expect(changed).toEqual(["--chart-1", "--primary", "--primary-foreground", "--ring",
      "--sidebar-primary", "--sidebar-primary-foreground", "--sidebar-ring"]);
  });

  it("a brand color wins over the accent, with readable text on it", () => {
    const t = themeTokens({ base: "stone", color: "blue", radius: 1, primary: "#0B6B5D" });
    expect(t.light["--primary"]).toBe("#0b6b5d");
    expect(t.dark["--primary"]).toBe("#0b6b5d");
    expect(t.light["--primary-foreground"]).toBe("#ffffff");
    expect(onColor("#facc15")).toBe("#0a0a0a");         // dark text on yellow
    expect(t.light["--radius"]).toBe("1rem");
  });
});

describe("normalize", () => {
  it("keeps what is known and drops what is not", () => {
    expect(normalize({ base: "slate", color: "rose", radius: 0.3, primary: "#ABCDEF" }))
      .toEqual({ base: "slate", color: "rose", radius: 0.3, primary: "#abcdef" });
    expect(normalize({ base: "purple", radius: 9, primary: "red" })).toEqual(DEFAULT_CHOICE);
    expect(normalize(null)).toBeNull();
    expect(RADII).toContain(DEFAULT_CHOICE.radius);
  });
});

describe("the host's current theme", () => {
  afterEach(() => setAppTheme(null));
  it("sends nothing until a theme exists, then tells every subscriber", () => {
    expect(appThemeContext()).toEqual({});
    let calls = 0;
    const off = subscribeAppTheme(() => calls++);
    setAppTheme({ base: "zinc", color: "green", radius: 0.5 });
    expect(getAppTheme()?.color).toBe("green");
    expect(appThemeContext().tokens?.light["--primary"]).toMatch(/^oklch/);
    off();
    setAppTheme(null);
    expect(calls).toBe(1);
  });
});

// ---- the shim wears the tokens ----------------------------------------------------------------

function boot(html = "<html><head></head></html>") {
  const js = injectShim(html).match(/<script>([\s\S]*?)<\/script>/)![1];
  const listeners: ((e: { data: unknown }) => void)[] = [];
  const win: Record<string, unknown> = {};
  const scope = {
    window: win,
    parent: { postMessage: () => {} },
    addEventListener: (t: string, fn: (e: { data: unknown }) => void) => t === "message" && listeners.push(fn),
    setTimeout: () => 0,
    clearTimeout: () => {},
  };
  new Function(...Object.keys(scope), js)(...Object.values(scope));
  const deliver = (data: unknown) => listeners.forEach((fn) => fn({ data }));
  return { api: win.cycls as { ctx: Record<string, unknown>; onCommand: (fn: (c: unknown) => void) => () => void }, deliver };
}
const style = () => document.getElementById("cycls-theme")?.textContent ?? "";

describe("the shim and the theme", () => {
  afterEach(() => { document.getElementById("cycls-theme")?.remove(); document.head.innerHTML = ""; });
  const tokens = themeTokens({ base: "zinc", color: "violet", radius: 0.5 });

  it("does nothing when the host sends no tokens — every app today", () => {
    const { deliver } = boot();
    deliver({ type: "cycls:init", path: "apps/x/index.html", scope: "apps/x", theme: "light" });
    expect(document.getElementById("cycls-theme")).toBeNull();
  });

  it("wears init's tokens, out-ranking the app's own :root and .dark", () => {
    const { deliver, api } = boot();
    deliver({ type: "cycls:init", path: "apps/x/index.html", scope: "apps/x", theme: "dark", tokens });
    expect(style()).toContain(":root:root{--radius:0.5rem;");
    expect(style()).toContain(`:root:root.dark,:root:root[data-theme="dark"]{`);
    expect(style()).toContain(`--primary:${tokens.dark["--primary"]}`);
    expect(api.ctx.tokens).toEqual(tokens);
  });

  it("re-skins in place on a theme command, and tells the app", () => {
    const { deliver, api } = boot();
    deliver({ type: "cycls:init", path: "apps/x/index.html", scope: "apps/x", theme: "light", tokens });
    const seen: unknown[] = [];
    api.onCommand((c) => seen.push(c));
    const green = themeTokens({ base: "stone", color: "green", radius: 1 });
    deliver({ type: MSG.command, command: { type: "theme", theme: "dark", tokens: green } });
    expect(document.querySelectorAll("#cycls-theme")).toHaveLength(1);
    expect(style()).toContain(`--primary:${green.light["--primary"]}`);
    expect(api.ctx.theme).toBe("dark");
    expect(seen).toEqual([{ type: "theme", theme: "dark", tokens: green }]);
    deliver({ type: MSG.command, command: { type: "theme", theme: "dark", tokens: null } });
    expect(document.getElementById("cycls-theme")).toBeNull();   // reset: the app's own look again
  });

  it("holds commands sent before the app listens", () => {
    const { deliver, api } = boot();
    deliver({ type: MSG.command, command: { type: "theme", theme: "light", tokens } });
    const seen: unknown[] = [];
    api.onCommand((c) => seen.push(c));
    expect(seen).toHaveLength(1);
  });

  it("refuses anything that is not a token, and a value that could close the rule", () => {
    const { deliver } = boot();
    deliver({ type: "cycls:init", path: "apps/x/index.html", scope: "apps/x", theme: "light",
              tokens: { light: { "--primary": "red}body{display:none", "color": "red", "--ok": "#fff", "--bs": "a\\7d" }, dark: {} } });
    expect(style()).toBe(":root:root{--ok:#fff}");
  });

  it("leaves an app that opted out alone", () => {
    const meta = document.createElement("meta");
    meta.name = "cycls-theme"; meta.content = "off";
    document.head.appendChild(meta);
    const { deliver } = boot();
    deliver({ type: "cycls:init", path: "apps/x/index.html", scope: "apps/x", theme: "light", tokens });
    expect(document.getElementById("cycls-theme")).toBeNull();
  });
});

// ---- the bridge pushes commands down the port -------------------------------------------------

describe("attachBridge commands", () => {
  it("sends a command down the app's port once it is linked, and stops on detach", async () => {
    let port: MessagePort | undefined;
    const contentWindow = { postMessage: (_m: unknown, _o: string, ports?: MessagePort[]) => { port = ports?.[0]; } };
    const frame = { contentWindow } as unknown as HTMLIFrameElement;
    let push: ((c: Record<string, unknown>) => void) | null = null;
    let unsubscribed = false;
    const detach = attachBridge({ frame, appPath: "apps/x/index.html", readFile: async () => "",
      commands: (send) => { push = send; return () => { unsubscribed = true; }; } });
    push!({ type: "theme" });                      // before the handshake: dropped, init carries the state
    const e = new MessageEvent("message", { data: { type: MSG.ready } });
    Object.defineProperty(e, "source", { value: contentWindow });
    window.dispatchEvent(e);
    const got: unknown[] = [];
    port!.onmessage = (ev) => got.push(ev.data);
    push!({ type: "theme", theme: "dark", tokens: null });
    await new Promise((r) => setTimeout(r, 20));
    expect(got).toEqual([{ type: MSG.command, command: { type: "theme", theme: "dark", tokens: null } }]);
    detach();
    expect(unsubscribed).toBe(true);
  });
});
