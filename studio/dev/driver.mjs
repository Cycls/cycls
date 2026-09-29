// A long-lived headless-Chrome driver for the Studio dev host (server.py). POST a JS
// function body to http://127.0.0.1:9400 (drive.sh does) — it runs with helpers in scope
// (goto, evalApp, evalHost, shot, click, drag, key, send, sleep) and its return value
// comes back as JSON. The app frame is sandboxed, so it is its own process (OOPIF);
// evalApp finds its context through auto-attach.
//   node studio/dev/driver.mjs [url]      CHROME=<path to chrome> to override
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { writeFileSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const URL0 = process.argv[2] || "http://127.0.0.1:8094/";
const PORT = 9333;
const CHROME = process.env.CHROME || {
  win32: "C:/Program Files/Google/Chrome/Application/chrome.exe",
  darwin: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
}[process.platform] || "google-chrome";
const extra = (process.env.CHROME_FLAGS || "").split(" ").filter(Boolean);
mkdirSync(join(HERE, "shots"), { recursive: true });
const chrome = spawn(CHROME, [
  "--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${join(HERE, ".chrome")}`,
  "--window-size=1400,900", "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
  "--ignore-gpu-blocklist", ...extra, "about:blank",
], { stdio: "ignore" });
process.on("exit", () => chrome.kill());

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let info;
for (let i = 0; i < 50; i++) {
  try { info = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json(); break; } catch { await sleep(200); }
}
const ws = new WebSocket(info.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let seq = 0;
const pending = new Map(), handlers = [];
ws.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) {
    const { res, rej } = pending.get(m.id);
    pending.delete(m.id);
    m.error ? rej(new Error(`${m.error.message} ${m.error.data || ""}`)) : res(m.result);
  } else if (m.method) handlers.forEach((h) => h(m));
});
const send = (method, params = {}, sessionId) => new Promise((res, rej) => {
  const id = ++seq;
  pending.set(id, { res, rej });
  ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
});

// The page, and the sandboxed app frame (in-process or an OOPIF).
const { targetId } = await send("Target.createTarget", { url: "about:blank" });
const { sessionId: page } = await send("Target.attachToTarget", { targetId, flatten: true });
const contexts = [];                                  // {id, frameId, session, origin, aux}
const console_ = [];
let mainFrameId = null;
handlers.push((m) => {
  if (m.method === "Runtime.executionContextCreated") contexts.push({ ...m.params.context, session: m.sessionId });
  if (m.method === "Runtime.executionContextsCleared") for (let i = contexts.length - 1; i >= 0; i--) if (contexts[i].session === m.sessionId) contexts.splice(i, 1);
  if (m.method === "Runtime.executionContextDestroyed") { const i = contexts.findIndex((c) => c.id === m.params.executionContextId && c.session === m.sessionId); if (i >= 0) contexts.splice(i, 1); }
  if (m.method === "Runtime.consoleAPICalled") console_.push(`[${m.params.type}] ${m.params.args.map((a) => a.value ?? a.description ?? "").join(" ")}`.slice(0, 500));
  if (m.method === "Runtime.exceptionThrown") console_.push(`[exception] ${m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text}`.slice(0, 800));
  if (m.method === "Target.attachedToTarget") {
    const s = m.params.sessionId;
    send("Runtime.enable", {}, s).catch(() => {});
    send("Runtime.runIfWaitingForDebugger", {}, s).catch(() => {});
  }
});
await send("Page.enable", {}, page);
await send("Runtime.enable", {}, page);
await send("Target.setAutoAttach", { autoAttach: true, waitForDebuggerOnStart: false, flatten: true }, page);
await send("Emulation.setDeviceMetricsOverride", { width: 1400, height: 900, deviceScaleFactor: 1, mobile: false }, page);

async function goto(url) {
  await send("Page.navigate", { url }, page);
  mainFrameId = (await send("Page.getFrameTree", {}, page)).frameTree.frame.id;
}

function appContext() {
  return contexts.filter((c) => c.auxData?.isDefault && c.auxData.frameId !== mainFrameId).at(-1);
}
async function evalIn(ctx, expr) {
  const r = await send("Runtime.evaluate", { expression: expr, contextId: ctx.id, awaitPromise: true, returnByValue: true }, ctx.session);
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
  return r.result.value;
}
const evalApp = async (expr) => { const c = appContext(); if (!c) throw new Error("no app context yet"); return evalIn(c, expr); };
const evalHost = (expr) => evalIn(contexts.find((c) => c.auxData?.isDefault && c.auxData.frameId === mainFrameId && c.session === page), expr);

async function shot(name, clip) {
  const r = await send("Page.captureScreenshot", { format: "png", ...(clip ? { clip: { ...clip, scale: 1 } } : {}) }, page);
  const f = join(HERE, "shots", `${name}.png`);
  writeFileSync(f, Buffer.from(r.data, "base64"));
  return f;
}
const mouse = (type, x, y, extra = {}) => send("Input.dispatchMouseEvent", { type, x, y, button: "left", buttons: type === "mouseReleased" ? 0 : 1, clickCount: 1, pointerType: "mouse", ...extra }, page);
async function click(x, y, modifiers = 0) {
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y, modifiers }, page);
  await mouse("mousePressed", x, y, { modifiers });
  await mouse("mouseReleased", x, y, { modifiers });
}
async function drag(x0, y0, x1, y1, steps = 12) {
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: x0, y: y0 }, page);
  await sleep(50);
  await mouse("mousePressed", x0, y0);
  for (let i = 1; i <= steps; i++) {
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: x0 + ((x1 - x0) * i) / steps, y: y0 + ((y1 - y0) * i) / steps, button: "left", buttons: 1 }, page);
    await sleep(16);
  }
  await mouse("mouseReleased", x1, y1);
}
const KEYS = { Tab: 9, Escape: 27, Delete: 46, F12: 123, Home: 36 };
async function key(code, keyName, modifiers = 0) {
  keyName = keyName || (code.startsWith("Key") ? code.slice(3).toLowerCase() : code.startsWith("Digit") ? code.slice(5) : code);
  const vk = KEYS[code] || (keyName.length === 1 ? keyName.toUpperCase().charCodeAt(0) : 0);
  await send("Input.dispatchKeyEvent", { type: "keyDown", code, key: keyName, windowsVirtualKeyCode: vk, modifiers }, page);
  await send("Input.dispatchKeyEvent", { type: "keyUp", code, key: keyName, windowsVirtualKeyCode: vk, modifiers }, page);
}

await goto(URL0);

createServer(async (req, res) => {
  let body = "";
  for await (const chunk of req) body += chunk;
  let out;
  try {
    const fn = new Function("h", `return (async () => { const {send,page,goto,evalApp,evalHost,shot,mouse,click,drag,key,sleep,contexts,console_} = h; ${body} })()`);
    out = { ok: true, value: await fn({ send, page, goto, evalApp, evalHost, shot, mouse, click, drag, key, sleep, contexts, console_ }) };
  } catch (e) {
    out = { ok: false, error: String(e && e.stack || e) };
  }
  res.setHeader("content-type", "application/json");
  res.end(JSON.stringify(out, null, 1));
}).listen(9400, "127.0.0.1", () => console.log("driver on :9400"));
