"""Cycls browser service — a shared real-Chrome service deployed as a cycls
function (the office-render sibling for browsing).

A small FastAPI + Playwright app that owns real Chromium and exposes a REST API
agents call over HTTP: create a session, navigate, read (text + numbered refs),
click/type by ref, screenshot, download, evaluate. The SDK's `cycls` browser
provider (`cycls/_agent/browser/client.py`, `RestSession`) is a thin client of
this — so all the browser work happens server-side and the AGENT never ships
Playwright/Chromium.

Stealth is applied here (this is where WE launch Chrome): launch flags, a
normalized User-Agent, a set locale/viewport/timezone, and the shared init-script
patches — see `cycls/_agent/browser/stealth.py` for the rationale (and why TLS is
deliberately left alone). It is NOT a Cloudflare bypass; good for non-hostile
sites and authenticated flows.

Deploy:      python examples/browser_service/browser_service.py     # uses CYCLS_API_KEY
Run locally: python examples/browser_service/browser_service.py --local 9400
"""
import os
import secrets as _secrets

import cycls

# Bearer secret the service requires (agents send it as BROWSER_SECRET). Baked
# into the deployed function (the container has no env-var mechanism); generated
# per deploy unless BROWSER_SECRET is set. Printed at deploy time.
_SECRET = os.environ.get("BROWSER_SECRET") or _secrets.token_urlsafe(24)

# Real Chromium lives in the image (installed at build); agents never download a
# browser — they call this service over HTTP.
image = (cycls.Image()
         .pip("fastapi", "hypercorn", "playwright")
         # headless launches use chrome-headless-shell — install it too.
         .run("playwright install --with-deps chromium chromium-headless-shell"))

# Tags visible interactive elements with data-cy-ref="N" and returns descriptors,
# so the model acts by number. KEPT IN SYNC with client._SNAPSHOT_JS.
_SNAPSHOT_JS = r"""() => {
  const sel = 'a[href], button, input:not([type=hidden]), textarea, select,' +
    ' [role=button], [role=link], [role=textbox], [role=checkbox], [onclick],' +
    ' [contenteditable=""], [contenteditable=true]';
  const out = []; let i = 0;
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect(), st = getComputedStyle(el);
    if (r.width <= 0 || r.height <= 0 || st.visibility === 'hidden' || st.display === 'none') continue;
    el.setAttribute('data-cy-ref', i);
    const label = (el.innerText || el.value || el.getAttribute('aria-label') ||
      el.getAttribute('placeholder') || el.getAttribute('name') || el.getAttribute('title') || '')
      .trim().replace(/\s+/g, ' ').slice(0, 80);
    out.push({ ref: i, tag: el.tagName.toLowerCase(),
               type: el.getAttribute('type') || '', label });
    i++;
  }
  return out;
}"""

# Stealth init-script patches. KEPT IN SYNC with cycls/_agent/browser/stealth.py
# (STEALTH_JS) — byte-identical. Runs before page scripts on every navigation.
_STEALTH_JS = r"""() => {
  // Make every patched native report "[native code]" via toString, so a detector
  // calling fn.toString() (or a getter's .toString()) can't spot the override —
  // this is what makes the patches below undetectable rather than just present.
  const _orig = Function.prototype.toString;
  const _patched = new WeakMap();
  function _fakeToString() {
    return _patched.has(this) ? _patched.get(this) : _orig.call(this);
  }
  try { _patched.set(_fakeToString, 'function toString() { [native code] }'); } catch (e) {}
  try { Function.prototype.toString = _fakeToString; } catch (e) {}
  const mark = (fn, str) => { try { _patched.set(fn, str); } catch (e) {} return fn; };

  const NavProto = Object.getPrototypeOf(navigator);
  // Define on Navigator.prototype (where real Chrome exposes these) with a
  // native-looking getter — NOT an own-property on the instance, which is itself
  // a tell (bot.sannysoft flags instance-shadowed navigator properties).
  const defNav = (prop, get) => {
    try {
      Object.defineProperty(NavProto, prop, {
        get: mark(get, 'function get ' + prop + '() { [native code] }'),
        configurable: true, enumerable: true });
    } catch (e) {
      try { Object.defineProperty(navigator, prop, { get, configurable: true }); } catch (e2) {}
    }
  };

  // navigator.webdriver: rely on the --disable-blink-features=AutomationControlled
  // launch flag (native `false`, identical to a real browser); only strip it from
  // the prototype if something still left it truthy.
  try {
    if (navigator.webdriver && Object.getOwnPropertyDescriptor(NavProto, 'webdriver'))
      delete NavProto.webdriver;
  } catch (e) {}

  // Identity a real Chrome reports, kept consistent with the (possibly overridden)
  // UA — a platform that disagrees with the UA is itself a tell.
  const ua = navigator.userAgent || '';
  const platform = /Win/i.test(ua) ? 'Win32' : /Mac/i.test(ua) ? 'MacIntel' : 'Linux x86_64';
  defNav('vendor', () => 'Google Inc.');
  defNav('platform', () => platform);
  defNav('languages', () => ['en-US', 'en']);
  defNav('hardwareConcurrency', () => 8);
  defNav('deviceMemory', () => 8);

  // window.chrome: real Chrome exposes app/csi/loadTimes/runtime; headless lacks it.
  try {
    const c = (window.chrome = window.chrome || {});
    c.runtime = c.runtime || {};
    if (!c.app) c.app = { isInstalled: false,
      InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
      RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' } };
    if (!c.csi) c.csi = mark(function csi() { return {}; }, 'function csi() { [native code] }');
    if (!c.loadTimes) c.loadTimes = mark(function loadTimes() { return {}; }, 'function loadTimes() { [native code] }');
  } catch (e) {}

  // Notification-permission query returns a consistent state (a classic tell is
  // permission 'denied' while Notification.permission is 'default').
  try {
    const perms = navigator.permissions, q = perms && perms.query;
    if (q) perms.query = mark(function query(p) {
      return (p && p.name === 'notifications')
        ? Promise.resolve({ state: Notification.permission })
        : q.call(perms, p);
    }, 'function query() { [native code] }');
  } catch (e) {}

  // WebGL vendor/renderer (WebGL1 + WebGL2): headless returns Google SwiftShader —
  // report a real GPU, with a native-looking getParameter.
  const gl = (proto) => {
    if (!proto) return;
    const gp = proto.getParameter;
    proto.getParameter = mark(function getParameter(p) {
      if (p === 37445) return 'Intel Inc.';                 // UNMASKED_VENDOR_WEBGL
      if (p === 37446) return 'Intel Iris OpenGL Engine';   // UNMASKED_RENDERER_WEBGL
      return gp.apply(this, arguments);
    }, 'function getParameter() { [native code] }');
  };
  try { gl(WebGLRenderingContext.prototype); } catch (e) {}
  try { gl(WebGL2RenderingContext.prototype); } catch (e) {}

  // Headless reports outerWidth/outerHeight = 0; a real window matches its content.
  try {
    if (!window.outerWidth) Object.defineProperty(window, 'outerWidth', { get: () => window.innerWidth || 1280, configurable: true });
    if (!window.outerHeight) Object.defineProperty(window, 'outerHeight', { get: () => window.innerHeight || 800, configurable: true });
  } catch (e) {}
}"""

# Launch flags that drop the loudest automation tell (navigator.webdriver /
# automation banner). KEPT IN SYNC with stealth.LAUNCH_ARGS.
_STEALTH_ARGS = ["--disable-blink-features=AutomationControlled"]

_DL_MAX = 50 * 1024 * 1024   # bytes — download size cap
_EVAL_MAX = 50_000           # chars — cap on a serialized evaluate() result

# Human-like input tunables. KEPT IN SYNC with cycls/_agent/browser/behavior.py.
_MOVE_STEPS = (10, 22)
_TYPE_DELAY_MS = (35, 110)
_PRE_DELAY_MS = (40, 160)
_CLICK_JITTER = 0.28


def _humanize_on():
    return os.environ.get("BROWSER_HUMANIZE", "1") != "0"


def _chrome_ua(version):
    """A normal Chrome UA (HeadlessChrome token dropped) for the running build.
    KEPT IN SYNC with stealth.chrome_ua."""
    major = str(version or "").split(".")[0] or "120"
    return (f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{major}.0.0.0 Safari/537.36")


def _env_proxy():
    """A Playwright proxy dict from the service's own env — a fallback when the
    caller didn't forward one in the session-create body. The operator supplies
    the proxy (a residential/mobile pool); we only plumb it through."""
    server = os.environ.get("BROWSER_PROXY_SERVER")
    if not server:
        return None
    cfg = {"server": server}
    if os.environ.get("BROWSER_PROXY_USERNAME"):
        cfg["username"] = os.environ["BROWSER_PROXY_USERNAME"]
    if os.environ.get("BROWSER_PROXY_PASSWORD"):
        cfg["password"] = os.environ["BROWSER_PROXY_PASSWORD"]
    return cfg


# Captured at deploy/module-load time and baked into the deployed function's
# closure — like _SECRET. A Cloud Run container has no env-var mechanism, so a
# proxy set at `cycls deploy` time must ride along in the pickle, not be read
# from the container's env. (Locally, --local passes proxy=None and create()
# falls back to reading the live env, so BROWSER_PROXY_* still works there.)
_PROXY = _env_proxy()


def _proxy_domains():
    """Hosts that should route through the proxy — comma-separated, glob-ish
    suffixes in BROWSER_PROXY_DOMAINS (e.g. '*.gov.sa,my.gov.sa'). Empty list =
    proxy EVERY site (the pre-routing behaviour)."""
    raw = os.environ.get("BROWSER_PROXY_DOMAINS", "")
    return [p.strip().lstrip("*").lstrip(".").lower() for p in raw.split(",") if p.strip()]


_PROXY_DOMAINS = _proxy_domains()   # baked at deploy, like _PROXY


def _should_proxy(url, domains):
    """Whether this navigation goes through the proxy. No list → every site.
    URL unknown (an older client that doesn't forward it) → yes, so proxy-only
    sites keep working during a rollout. Otherwise only when the host matches."""
    if not domains or not url:
        return True
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


def _dlname(url, cdisp):
    """Best filename for a download: Content-Disposition (incl. RFC-5987
    `filename*`), else the URL's last path segment."""
    import re
    from urllib.parse import urlparse, unquote
    if cdisp:
        m = (re.search(r"filename\*=(?:UTF-8'')?([^;]+)", cdisp, re.I)
             or re.search(r'filename="?([^";]+)"?', cdisp, re.I))
        if m:
            return unquote(m.group(1).strip().strip('"')) or "download"
    return unquote(os.path.basename(urlparse(url).path)) or "download"


# Human-like input helpers. KEPT IN SYNC with cycls/_agent/browser/behavior.py.
async def _b_sleep(lo, hi):
    import asyncio
    import random
    await asyncio.sleep(random.uniform(lo, hi) / 1000)


async def _b_move(page, x, y):
    import random
    await page.mouse.move(x + random.uniform(-60, 60), y + random.uniform(-60, 60),
                          steps=random.randint(*_MOVE_STEPS))
    await page.mouse.move(x, y, steps=random.randint(*_MOVE_STEPS))


async def _human_click(page, selector, timeout):
    import random
    el = page.locator(selector).first
    await el.scroll_into_view_if_needed(timeout=timeout)
    try:
        box = await el.bounding_box()
        if box:
            x = box["x"] + box["width"] * (0.5 + random.uniform(-_CLICK_JITTER, _CLICK_JITTER))
            y = box["y"] + box["height"] * (0.5 + random.uniform(-_CLICK_JITTER, _CLICK_JITTER))
            await _b_move(page, x, y)
    except Exception:
        pass
    await _b_sleep(*_PRE_DELAY_MS)
    await el.click(timeout=timeout)


async def _human_type(page, selector, text, timeout):
    el = page.locator(selector).first
    await el.scroll_into_view_if_needed(timeout=timeout)
    await _b_sleep(*_PRE_DELAY_MS)
    try:
        await el.click(timeout=timeout)
    except Exception:
        pass
    try:
        await el.fill("")
    except Exception:
        pass
    for ch in text:
        await page.keyboard.type(ch)
        await _b_sleep(*_TYPE_DELAY_MS)


async def _human_settle(page):
    import random
    try:
        vp = page.viewport_size or {"width": 1280, "height": 800}
        await page.mouse.move(random.uniform(100, vp["width"] - 100),
                              random.uniform(100, vp["height"] - 100),
                              steps=random.randint(*_MOVE_STEPS))
        await _b_sleep(*_PRE_DELAY_MS)
        await page.mouse.wheel(0, random.randint(120, 480))
    except Exception:
        pass


def build_app(secret=None, default_proxy=None, proxy_domains=None):
    _domains = proxy_domains if proxy_domains is not None else _PROXY_DOMAINS
    import asyncio
    import time
    import uuid
    from urllib.parse import quote

    from fastapi import FastAPI, Request, HTTPException, Response
    # Prefer the CDP-leak-hardened Playwright fork (rebrowser-playwright) when it's
    # installed in the image — it fixes the Runtime.enable leak stock Playwright
    # exposes to bot-management. Falls back to stock Playwright otherwise.
    try:
        from rebrowser_playwright.async_api import async_playwright, Error as PWError
    except Exception:
        from playwright.async_api import async_playwright, Error as PWError

    # Split timeouts: click/type fail fast (a stuck element shouldn't hang a
    # worker); navigation/screenshot/download/evaluate get real headroom.
    ACT = 15_000        # ms — click / type
    NAV = 45_000        # ms — goto / back / press / screenshot / download / evaluate
    IDLE = 300          # s  — idle-session sweep
    app = FastAPI()
    st = {"pw": None, "browser": None, "ua": None, "sessions": {}}   # id -> {context, page, last}

    async def _browser():
        if st["browser"] is None:
            st["pw"] = await async_playwright().start()
            st["browser"] = await st["pw"].chromium.launch(
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                      *_STEALTH_ARGS])
            st["ua"] = _chrome_ua(st["browser"].version)
        return st["browser"]

    def _auth(request):
        if secret and request.headers.get("authorization", "") != f"Bearer {secret}":
            raise HTTPException(401, "bad or missing secret")

    async def _sweep():
        now = time.time()
        for sid, s in list(st["sessions"].items()):
            if now - s["last"] > IDLE:
                try:
                    await s["context"].close()
                except Exception:
                    pass
                st["sessions"].pop(sid, None)

    def _sess(sid):
        s = st["sessions"].get(sid)
        if not s:
            raise HTTPException(404, "no such session")
        s["last"] = time.time()
        return s

    def _page(sid):
        return _sess(sid)["page"]

    async def _snapshot(page):
        refs = await page.evaluate(_SNAPSHOT_JS)
        try:
            text = await page.inner_text("body")
        except Exception:
            text = ""
        return {"url": page.url, "title": await page.title(),
                "text": text[:4000], "text_truncated": len(text) > 4000,
                "refs": refs[:120], "refs_truncated": len(refs) > 120}

    # Every action handler runs its Playwright work through this: a 404 (bad
    # session) still propagates, but any Playwright/timeout error becomes a clean
    # 409 with a readable detail instead of a 500 that takes the worker down.
    async def _guard(label, coro):
        try:
            return await coro
        except HTTPException:
            raise
        except (PWError, asyncio.TimeoutError) as e:
            raise HTTPException(409, f"{label}: {str(e).splitlines()[0][:300]}")

    @app.get("/v1/health")
    async def health():
        return {"ok": True, "sessions": len(st["sessions"])}

    @app.post("/v1/sessions")
    async def create(request: Request):
        _auth(request)
        await _sweep()
        browser = await _browser()
        try:
            body = await request.json()
        except Exception:
            body = {}
        # proxy (the IP layer): the caller's forwarded proxy wins; else the baked/
        # env proxy, but only when this navigation's host is on the routing list
        # (BROWSER_PROXY_DOMAINS) — so ordinary sites browse free/direct and only
        # geo/hard domains pay for the proxy. `url` is the first goto, forwarded by
        # the client at session-create. Applied per-context.
        proxy = (body or {}).get("proxy")
        if not proxy:
            baked = default_proxy or _env_proxy()
            if baked and _should_proxy((body or {}).get("url"), _domains):
                proxy = baked
        # accept_downloads for the download action; UA + locale + viewport +
        # init-script stealth so the page looks like an ordinary browser.
        kw = dict(accept_downloads=True, user_agent=st["ua"], locale="en-US",
                  timezone_id="America/New_York", viewport={"width": 1280, "height": 800})
        if proxy:
            kw["proxy"] = proxy
        ctx = await browser.new_context(**kw)
        try:
            await ctx.add_init_script(f"({_STEALTH_JS})();")
        except Exception:
            pass
        page = await ctx.new_page()
        page.set_default_timeout(NAV)
        sid = uuid.uuid4().hex
        st["sessions"][sid] = {"context": ctx, "page": page, "last": time.time()}
        return {"id": sid}

    @app.post("/v1/sessions/{sid}/goto")
    async def goto(sid: str, request: Request):
        _auth(request)
        page = _page(sid)
        body = await request.json()

        async def _go():
            await page.goto(body["url"], wait_until=body.get("wait_until", "load"), timeout=NAV)
            if _humanize_on():
                await _human_settle(page)
            return {"url": page.url, "title": await page.title()}
        return await _guard("goto", _go())

    @app.post("/v1/sessions/{sid}/snapshot")
    async def snapshot(sid: str, request: Request):
        _auth(request)
        return await _guard("read", _snapshot(_page(sid)))

    @app.post("/v1/sessions/{sid}/click")
    async def click(sid: str, request: Request):
        _auth(request)
        page = _page(sid)
        ref = int((await request.json())["ref"])
        sel = f'[data-cy-ref="{ref}"]'
        act = _human_click(page, sel, ACT) if _humanize_on() else page.click(sel, timeout=ACT)
        await _guard(f"click [{ref}]", act)
        return {"ok": True}

    @app.post("/v1/sessions/{sid}/type")
    async def type_(sid: str, request: Request):
        _auth(request)
        page = _page(sid)
        body = await request.json()
        ref = int(body["ref"])
        sel = f'[data-cy-ref="{ref}"]'
        act = (_human_type(page, sel, body["text"], ACT) if _humanize_on()
               else page.fill(sel, body["text"], timeout=ACT))
        await _guard(f"type [{ref}]", act)
        return {"ok": True}

    @app.post("/v1/sessions/{sid}/press")
    async def press(sid: str, request: Request):
        _auth(request)
        page = _page(sid)
        key = (await request.json()).get("key", "Enter")

        async def _press():
            await page.keyboard.press(key)
            return {"url": page.url, "title": await page.title()}
        return await _guard(f"press {key}", _press())

    @app.post("/v1/sessions/{sid}/back")
    async def back(sid: str, request: Request):
        _auth(request)
        page = _page(sid)

        async def _back():
            await page.go_back(timeout=NAV)
            return {"url": page.url, "title": await page.title()}
        return await _guard("back", _back())

    @app.post("/v1/sessions/{sid}/screenshot")
    async def screenshot(sid: str, request: Request):
        _auth(request)
        png = await _guard("screenshot",
                           _page(sid).screenshot(full_page=False, timeout=NAV))
        return Response(content=png, media_type="image/png")

    @app.post("/v1/sessions/{sid}/download")
    async def download(sid: str, request: Request):
        _auth(request)
        s = _sess(sid)
        page, ctx = s["page"], s["context"]
        body = await request.json()
        url, ref = body.get("url"), body.get("ref")

        async def _dl():
            if url:
                # context.request shares the page's cookies/session (authed
                # downloads work) and isn't CORS-bound — see the TLS note in the
                # module docstring for why we don't route this through the page.
                resp = await ctx.request.get(url, timeout=NAV)
                if not resp.ok:
                    raise HTTPException(409, f"download {url}: HTTP {resp.status}")
                return _dlname(url, resp.headers.get("content-disposition")), await resp.body()
            import pathlib
            async with page.expect_download(timeout=NAV) as di:
                await page.click(f'[data-cy-ref="{int(ref)}"]', timeout=ACT)
            dl = await di.value
            data = await asyncio.to_thread(pathlib.Path(await dl.path()).read_bytes)
            return (dl.suggested_filename or _dlname(dl.url, None)), data

        name, data = await _guard("download", _dl())
        if len(data) > _DL_MAX:
            raise HTTPException(409, f"download too large ({len(data) // (1024 * 1024)} MB > 50 MB)")
        return Response(content=data, media_type="application/octet-stream",
                        headers={"X-Cycls-Filename": quote(name)})

    @app.post("/v1/sessions/{sid}/evaluate")
    async def evaluate(sid: str, request: Request):
        _auth(request)
        page = _page(sid)
        script = (await request.json())["script"]

        async def _eval():
            import json
            result = await asyncio.wait_for(page.evaluate(script), NAV / 1000)
            try:
                out = json.dumps(result, ensure_ascii=False, default=str)
            except Exception:
                out = str(result)
            return {"result": out[:_EVAL_MAX], "truncated": len(out) > _EVAL_MAX}
        return await _guard("evaluate", _eval())

    @app.delete("/v1/sessions/{sid}")
    async def close(sid: str, request: Request):
        _auth(request)
        s = st["sessions"].pop(sid, None)
        if s:
            try:
                await s["context"].close()
            except Exception:
                pass
        return {"ok": True}

    return app


def _serve(port, secret=None, proxy=None, domains=None):
    import asyncio

    from hypercorn.asyncio import serve
    from hypercorn.config import Config
    cfg = Config()
    cfg.bind = [f"0.0.0.0:{port}"]
    asyncio.run(serve(build_app(secret, proxy, domains), cfg))


@cycls.function(name="cycls-browser", image=image, memory="4Gi", cpu=2, concurrency=30)
def serve(port):
    _serve(port, _SECRET, _PROXY, _PROXY_DOMAINS)   # baked secret + proxy + routing (closure)

# max_instances=1 is REQUIRED: sessions are in-memory + instance-local, so a
# second instance would 404 sessions created on the first (multi-step flows
# break). One instance serves many isolated sessions concurrently (each an
# isolated browser context), bounded by its RAM — hence the headroom above. The
# decorator doesn't expose max_instances, so set it on the spec directly.
serve.spec["max_instances"] = 1


if __name__ == "__main__":
    import sys
    if "--local" in sys.argv:
        _serve(int(sys.argv[-1]), None)   # local, no auth
    else:
        print("=" * 60)
        print("BROWSER_SECRET (set this on agents):", _SECRET)
        if _PROXY:
            print("PROXY baked in       :", _PROXY.get("server"),
                  "(user:", (_PROXY.get("username") or "-").split(":")[0] + ")")
            print("PROXY routing        :",
                  (", ".join(_PROXY_DOMAINS) if _PROXY_DOMAINS else "ALL sites (no BROWSER_PROXY_DOMAINS)"))
        else:
            print("PROXY                : none (set BROWSER_PROXY_* to route through one)")
        print("=" * 60)
        serve.deploy()
