// A stand-in for the chat host: the real shim + the real bridge, the real Studio
// bundle, and a tiny server for files + the real studio_router.
import { injectShim } from "@client/components/app-shim";
import { attachBridge, APP_COMMAND_EVENT } from "@client/components/app-bridge";

declare global { interface Window { __log: unknown[]; __appData: Record<string, unknown>; __push: (c: unknown) => void; __asks: string[] } }
window.__log = [];
window.__appData = {};
window.__asks = [];
const log = (...a: unknown[]) => { window.__log.push(a); if (window.__log.length > 500) window.__log.shift(); };

async function main() {
  const html = await (await fetch("/studio.html")).text();
  const frame = document.getElementById("app") as HTMLIFrameElement;
  attachBridge({
    frame,
    appPath: "apps/studio/index.html",
    readFile: async (p) => {
      const r = await fetch(`/files/${p}`);
      log("read", p, r.status);
      if (!r.ok) throw Object.assign(new Error(`HTTP ${r.status}`), { status: r.status });
      return r.text();
    },
    writeFile: async (p, text) => {
      const r = await fetch(`/files/${p}`, { method: "PUT", body: text });
      log("write", p, text.length, r.status);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
    },
    appData: async (slug, op) => {
      log("data", slug, op);
      const key = `${op.who || "me"}:${op.key}`;
      if (op.op === "put") { window.__appData[key] = op.value; return { ok: true }; }
      return window.__appData[key] ?? null;
    },
    callEngine: async (slug, op, payload) => {
      const t0 = performance.now();
      const res = await fetch(`/apps/${slug}/engine`, {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...payload, op }),
      });
      log("engine", op, res.status, Math.round(performance.now() - t0));
      if (!res.ok) {
        let detail = "";
        try { detail = (await res.json()).detail ?? ""; } catch { /* not JSON */ }
        throw Object.assign(new Error(detail || `HTTP ${res.status}`), { status: res.status });
      }
      return res.json();
    },
    onAsk: (t) => { window.__asks.push(t); },
    onError: (m) => log("crash", m),
    context: { theme: "dark", locale: "en" },
  });
  const late = new URLSearchParams(location.search).get("late");
  if (late) { frame.style.width = "0px"; frame.style.height = "0px"; setTimeout(() => { frame.style.width = ""; frame.style.height = ""; }, +late); }
  frame.srcdoc = injectShim(html);
  window.__push = (command) => dispatchEvent(new CustomEvent(APP_COMMAND_EVENT, { detail: { path: "apps/studio/index.html", command } }));
}
main();
