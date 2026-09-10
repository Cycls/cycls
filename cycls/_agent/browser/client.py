"""Browser automation for Cycls agents, via a shared real-Chrome service.

Agents drive a real browser WITHOUT shipping Chromium: the heavy engine (real
Chrome) runs in ONE shared service — Steel Browser, or a managed provider — and
this module is a thin client that connects to it over the Chrome DevTools
Protocol (CDP). Same split as office-render: the SDK ships the client, the
service is deployed once. Only the Playwright *library* rides in the agent image
(a few MB); it never downloads a browser, it connects to the remote one.

Configured by env an agent already sets to use the service:
  BROWSER_URL       the service base URL (self-hosted Steel, or a managed API)
  BROWSER_SECRET    the shared service secret (Bearer)
Optional:
  BROWSER_PROVIDER  steel (default) | cdp | browserbase
                    - steel:      create a session, then connect to its CDP url
                    - cdp:        BROWSER_URL is already a raw CDP endpoint
                                  (e.g. http://host:9222) — no secret required
                    - browserbase: managed provider (Phase 4)

If BROWSER_URL is unset (or the secret is missing for a secret-requiring
provider) the feature is simply off: `configured()` is False and `session()`
raises `Unavailable`, so the caller degrades to "browsing isn't configured"
instead of crashing — exactly the office-render behaviour.
"""
import os

import httpx

# A browse step (a service round-trip driving real Chrome) can be slow on a cold
# session or a heavy page; give CDP connect + navigation real headroom.
_CONNECT_TIMEOUT = 30_000     # ms — Playwright connect
_NAV_TIMEOUT = 45_000         # ms — page.goto / actions
_SESSION_TIMEOUT = 30         # s  — service session-create HTTP call
_EVAL_MAX = 50_000            # chars — cap on a serialized evaluate() result


# Tags every visible interactive element with `data-cy-ref="N"` (document order)
# and returns a compact descriptor list, so the model can act by number and a
# later click/type on the SAME persistent page resolves the element by that
# attribute. Runs in the page, no dependency.
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


class Unavailable(RuntimeError):
    """Raised when the browser service is unreachable or not configured, so the
    caller degrades gracefully instead of a hard error."""


def _provider():
    return (os.environ.get("BROWSER_PROVIDER") or "steel").lower()


# A service session holds page state (the open page, cookies, the `data-cy-ref`
# markers), so the SAME session is REUSED across the stateless connect/act/
# disconnect cycles a turn makes — else every call would mint a fresh blank page
# and multi-step flows (open → read → click → screenshot) would fall apart. Keyed
# by the caller's user_id; a stale entry is evicted and re-minted on the next
# connect failure. The `cdp` provider is one browser by design and needs no cache.
_STEEL_SESSIONS = {}
# Same idea for the `cycls` REST provider — cache the server-side session id.
_REST_SESSIONS = {}


def _skey(user_id):
    return str(user_id or "default")


def _evict_steel(user_id):
    _STEEL_SESSIONS.pop(_skey(user_id), None)


def _dlname(url, cdisp):
    """Best filename for a download: Content-Disposition (incl. RFC-5987
    `filename*`, so non-ASCII names survive), else the URL's last path segment."""
    import re
    from urllib.parse import urlparse, unquote
    if cdisp:
        m = (re.search(r"filename\*=(?:UTF-8'')?([^;]+)", cdisp, re.I)
             or re.search(r'filename="?([^";]+)"?', cdisp, re.I))
        if m:
            return unquote(m.group(1).strip().strip('"')) or "download"
    return unquote(os.path.basename(urlparse(url).path)) or "download"


def _proxy_config():
    """A Playwright proxy dict from env (the operator supplies the proxy — we only
    plumb it through), or None. Either `BROWSER_PROXY` as a full URL
    (`scheme://user:pass@host:port`) or the split `BROWSER_PROXY_SERVER` +
    `BROWSER_PROXY_USERNAME` / `BROWSER_PROXY_PASSWORD`. This is the IP layer —
    the only thing that moves a WAF/IP-level block (a residential/mobile pool you
    bring); it can't be manufactured, only pointed at."""
    server = os.environ.get("BROWSER_PROXY_SERVER")
    username = os.environ.get("BROWSER_PROXY_USERNAME")
    password = os.environ.get("BROWSER_PROXY_PASSWORD")
    if not server and (url := os.environ.get("BROWSER_PROXY")):
        from urllib.parse import urlparse
        p = urlparse(url if "://" in url else f"http://{url}")
        if p.hostname:
            server = f"{p.scheme or 'http'}://{p.hostname}" + (f":{p.port}" if p.port else "")
            username = username or p.username
            password = password or p.password
    if not server:
        return None
    cfg = {"server": server}
    if username:
        cfg["username"] = username
    if password:
        cfg["password"] = password
    return cfg


def _session_body():
    """The session-create request body — forwards the proxy config to the service
    so it applies per-context (each caller can browse through its own proxy)."""
    cfg = _proxy_config()
    return {"proxy": cfg} if cfg else {}


def configured():
    """Wired when a service URL is set — plus a secret for providers that need
    one. The raw `cdp` provider (a self-managed endpoint) needs only the URL."""
    if not os.environ.get("BROWSER_URL"):
        return False
    if _provider() == "cdp":
        return True
    return bool(os.environ.get("BROWSER_SECRET"))


async def _cdp_endpoint(user_id=None):
    """Resolve the CDP endpoint to connect to, creating a service-side session
    first when the provider needs it. `user_id` rides along as X-User-Id for
    attribution (not auth). Raises `Unavailable` on any miss."""
    url = os.environ.get("BROWSER_URL")
    secret = os.environ.get("BROWSER_SECRET")
    provider = _provider()
    if not url:
        raise Unavailable("browser not configured (BROWSER_URL)")

    if provider == "cdp":
        # BROWSER_URL is already a CDP endpoint (http://host:9222 or ws://…).
        return url

    if provider == "steel":
        # Steel: reuse this caller's live session (so page state persists across
        # calls); mint one on a miss and cache its CDP websocket.
        if not secret:
            raise Unavailable("browser not configured (BROWSER_SECRET)")
        if cached := _STEEL_SESSIONS.get(_skey(user_id)):
            return cached
        headers = {"Authorization": f"Bearer {secret}"}
        if user_id:
            headers["X-User-Id"] = str(user_id)
        try:
            async with httpx.AsyncClient(timeout=_SESSION_TIMEOUT) as client:
                resp = await client.post(f"{url.rstrip('/')}/v1/sessions", headers=headers, json={})
        except httpx.HTTPError as e:
            raise Unavailable(f"browser service unreachable: {e}") from e
        if resp.status_code not in (200, 201):
            raise Unavailable(f"browser service {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        ws = data.get("websocketUrl") or data.get("connectUrl") or data.get("wsEndpoint")
        if not ws:
            raise Unavailable(f"browser service returned no CDP url: {str(data)[:200]}")
        _STEEL_SESSIONS[_skey(user_id)] = ws
        return ws

    raise Unavailable(f"unknown BROWSER_PROVIDER: {provider!r}")


class Session:
    """One browser session driving a page over CDP. Async context manager:
    connects on enter, tears the page/context down on exit (the shared browser
    stays up for other sessions). The action set is deliberately small in
    Phase 1 — navigate, read, click, fill, screenshot — the DOM-ref snapshot the
    model drives comes in Phase 2."""

    def __init__(self, endpoint, user_id=None):
        self._endpoint = endpoint
        self._user_id = user_id
        self._pw = self._browser = self._context = self._page = None

    async def _connect(self):
        # Prefer the CDP-leak-hardened Playwright fork (rebrowser-playwright) when
        # it's installed — it fixes the Runtime.enable leak that stock Playwright
        # exposes to bot-management; falls back to stock Playwright otherwise.
        try:
            from rebrowser_playwright.async_api import async_playwright
        except Exception:
            from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.connect_over_cdp(
            self._endpoint, timeout=_CONNECT_TIMEOUT)
        # REUSE the endpoint's existing context + page, so page state (the open
        # page, cookies, DOM, the `data-cy-ref` markers we inject) PERSISTS across
        # the separate connect/act/disconnect cycles a stateless tool makes.
        # Isolation is the service's job — a Steel session per caller; a raw `cdp`
        # endpoint is one browser by design.
        self._context = (self._browser.contexts[0] if self._browser.contexts
                         else await self._browser.new_context())
        self._context.set_default_timeout(_NAV_TIMEOUT)
        # Reduce this browser's automation tells (navigator.webdriver, WebGL,
        # plugins, …) before we navigate. Registered per-connect: connect_over_cdp
        # opens a fresh CDP session each cycle, so a prior connect's init script is
        # gone — re-adding doesn't stack. UA / launch-flag / locale stealth needs a
        # context WE create; a reused CDP context can't take those, so that half is
        # the browser service's job (the cycls service and Steel both do it).
        try:
            from . import stealth
            await stealth.apply(self._context)
        except Exception:
            pass
        self._page = (self._context.pages[0] if self._context.pages
                      else await self._context.new_page())

    async def __aenter__(self):
        return self   # already connected by session()

    async def __aexit__(self, *exc):
        await self._safe_teardown()

    # ---- actions ----

    async def goto(self, url, wait_until="load"):
        await self._page.goto(url, wait_until=wait_until, timeout=_NAV_TIMEOUT)
        from . import behavior
        if behavior.enabled():
            await behavior.human_settle(self._page)
        return await self.info()

    async def info(self):
        return {"url": self._page.url, "title": await self._page.title()}

    async def text(self):
        """Visible text of the page body — the cheap 'read' for a text model."""
        return await self._page.inner_text("body")

    async def html(self):
        return await self._page.content()

    async def click(self, selector):
        await self._page.click(selector, timeout=_NAV_TIMEOUT)
        return await self.info()

    async def fill(self, selector, value):
        await self._page.fill(selector, value, timeout=_NAV_TIMEOUT)
        return await self.info()

    async def press(self, key):
        await self._page.keyboard.press(key)
        return await self.info()

    async def screenshot(self, full_page=False):
        """PNG bytes of the current page."""
        return await self._page.screenshot(full_page=full_page, timeout=_NAV_TIMEOUT)

    # ---- DOM snapshot the model drives (act-by-ref) ----

    async def snapshot(self, max_text=4000, max_refs=120):
        """The page as the model reads it: url + title + visible text, plus a
        numbered list of interactive elements it can act on by `ref`. Tags each
        element with `data-cy-ref` in the live DOM so a later `click_ref`/
        `type_ref` (a fresh connection to the same persistent page) resolves it."""
        refs = await self._page.evaluate(_SNAPSHOT_JS)
        try:
            text = await self._page.inner_text("body")
        except Exception:
            text = ""
        return {"url": self._page.url, "title": await self._page.title(),
                "text": text[:max_text], "text_truncated": len(text) > max_text,
                "refs": refs[:max_refs], "refs_truncated": len(refs) > max_refs}

    async def click_ref(self, ref):
        sel = f'[data-cy-ref="{int(ref)}"]'
        from . import behavior
        if behavior.enabled():
            await behavior.human_click(self._page, sel, _NAV_TIMEOUT)
        else:
            await self._page.click(sel, timeout=_NAV_TIMEOUT)

    async def type_ref(self, ref, value):
        sel = f'[data-cy-ref="{int(ref)}"]'
        from . import behavior
        if behavior.enabled():
            await behavior.human_type(self._page, sel, value, _NAV_TIMEOUT)
        else:
            await self._page.fill(sel, value, timeout=_NAV_TIMEOUT)

    async def back(self):
        await self._page.go_back(timeout=_NAV_TIMEOUT)
        return await self.info()

    async def download(self, ref=None, url=None):
        """Fetch a file → (filename, bytes). `url` uses the page's request context
        (its cookies/session apply, so authed downloads work); `ref` clicks the
        element and captures the download it triggers. Over a REMOTE cdp browser
        the `ref` path needs the file readable locally; the `url` path always works."""
        if url:
            resp = await self._context.request.get(url, timeout=_NAV_TIMEOUT)
            if not resp.ok:
                raise RuntimeError(f"download {url}: HTTP {resp.status}")
            return _dlname(url, resp.headers.get("content-disposition")), await resp.body()
        import pathlib
        async with self._page.expect_download(timeout=_NAV_TIMEOUT) as di:
            await self._page.click(f'[data-cy-ref="{int(ref)}"]', timeout=_NAV_TIMEOUT)
        dl = await di.value
        data = pathlib.Path(await dl.path()).read_bytes()
        return (dl.suggested_filename or _dlname(dl.url, None)), data

    async def evaluate(self, script):
        """Run JS in the page → {'result': <json string>, 'truncated': bool}. For
        scraping structured data the compact snapshot truncates."""
        import json
        result = await self._page.evaluate(script)
        try:
            s = json.dumps(result, ensure_ascii=False, default=str)
        except Exception:
            s = str(result)
        return {"result": s[:_EVAL_MAX], "truncated": len(s) > _EVAL_MAX}

    async def _safe_teardown(self):
        # Disconnect the client but leave the remote context/page ALIVE — its
        # state must survive to the next tool call in the turn. `close()` on a
        # connect_over_cdp browser drops our CDP connection; it does not kill the
        # remote Chrome / Steel session.
        for closer in (
            lambda: self._browser and self._browser.close(),
            lambda: self._pw and self._pw.stop(),
        ):
            try:
                r = closer()
                if r is not None:
                    await r
            except Exception:
                pass


class RestSession:
    """A session against the `cycls` browser service (a cycls-deployed FastAPI +
    Playwright service). Same method surface as the CDP `Session`, so the tool
    executor doesn't care which provider is live — but all the browser work
    happens SERVER-SIDE (the agent just makes HTTP calls; no Playwright needed).
    The service-side session id is cached per caller so page state persists across
    the stateless per-call cycles; a stale (404) session is re-minted once."""

    def __init__(self, base, secret, user_id=None, nav_url=None):
        self._base = base.rstrip("/")
        self._secret = secret
        self._user_id = user_id
        self._nav_url = nav_url   # first goto URL — forwarded so the service can
        self._sid = None          # route this session to the proxy by domain
        self._http = None

    def _headers(self):
        h = {}
        if self._secret:
            h["Authorization"] = f"Bearer {self._secret}"
        if self._user_id:
            h["X-User-Id"] = str(self._user_id)
        return h

    async def _ensure_session(self):
        if sid := _REST_SESSIONS.get(_skey(self._user_id)):
            self._sid = sid
            return
        body = _session_body()
        if self._nav_url:
            body["url"] = self._nav_url
        r = await self._http.post(f"{self._base}/v1/sessions", headers=self._headers(), json=body)
        if r.status_code not in (200, 201):
            raise Unavailable(f"browser service {r.status_code}: {r.text[:200]}")
        self._sid = r.json().get("id")
        if not self._sid:
            raise Unavailable("browser service returned no session id")
        _REST_SESSIONS[_skey(self._user_id)] = self._sid

    async def _connect(self):
        self._http = httpx.AsyncClient(timeout=_NAV_TIMEOUT / 1000 + 15)
        try:
            await self._ensure_session()
        except httpx.HTTPError as e:
            raise Unavailable(f"browser service unreachable: {e}") from e

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        if self._http:
            try:
                await self._http.aclose()
            except Exception:
                pass

    async def _act(self, path, **kw):
        """One action against the current session; a 404 (session expired
        server-side) evicts the cache and retries once with a fresh session. A
        non-200 that ISN'T a session miss is an action-level failure (e.g. a click
        timeout → 409): raised as a plain error so the tool reports "browser
        <action> failed — …" rather than "unavailable" (the service is up)."""
        for attempt in (1, 2):
            try:
                r = await self._http.post(f"{self._base}/v1/sessions/{self._sid}{path}",
                                          headers=self._headers(), **kw)
            except httpx.HTTPError as e:
                raise Unavailable(f"browser service unreachable: {e}") from e
            if r.status_code == 404 and attempt == 1:
                _REST_SESSIONS.pop(_skey(self._user_id), None)
                await self._ensure_session()
                continue
            if r.status_code == 200:
                return r
            try:
                detail = (r.json() or {}).get("detail")
            except Exception:
                detail = None
            raise RuntimeError(detail or f"browser service {r.status_code}: {r.text[:200]}")

    async def goto(self, url, wait_until="load"):
        return (await self._act("/goto", json={"url": url, "wait_until": wait_until})).json()

    async def info(self):
        s = await self.snapshot()
        return {"url": s.get("url"), "title": s.get("title")}

    async def snapshot(self):
        return (await self._act("/snapshot")).json()

    async def click_ref(self, ref):
        await self._act("/click", json={"ref": int(ref)})

    async def type_ref(self, ref, value):
        await self._act("/type", json={"ref": int(ref), "text": value})

    async def press(self, key):
        return (await self._act("/press", json={"key": key})).json()

    async def back(self):
        return (await self._act("/back")).json()

    async def screenshot(self, full_page=False):
        return (await self._act("/screenshot")).content

    async def download(self, ref=None, url=None):
        body = {}
        if url:
            body["url"] = url
        if ref is not None:
            body["ref"] = int(ref)
        r = await self._act("/download", json=body)
        from urllib.parse import unquote
        return (unquote(r.headers.get("X-Cycls-Filename", "")) or "download"), r.content

    async def evaluate(self, script):
        return (await self._act("/evaluate", json={"script": script})).json()


async def session(user_id=None, nav_url=None):
    """Open a connected browser session against the configured service. Raises
    `Unavailable` when unconfigured/unreachable. Use as an async context manager:
    `async with await browser.session(uid) as s: await s.goto(...)`.

    `nav_url` is the turn's first navigation target (the `open` URL); it's
    forwarded at session-create so the service can route this session through the
    proxy by domain (per-site routing). Connects here (not in __aenter__) so a
    stale cached session — whose server-side browser has since expired — is
    evicted and re-minted once, rather than failing the call."""
    if _provider() in ("cycls", "rest"):
        url = os.environ.get("BROWSER_URL")
        if not url:
            raise Unavailable("browser not configured (BROWSER_URL)")
        s = RestSession(url, os.environ.get("BROWSER_SECRET"), user_id, nav_url=nav_url)
        await s._connect()
        return s

    for attempt in (1, 2):
        endpoint = await _cdp_endpoint(user_id)
        s = Session(endpoint, user_id)
        try:
            await s._connect()
            return s
        except Exception as e:
            await s._safe_teardown()
            # A dead cached Steel session: drop it and retry with a fresh one.
            if _provider() == "steel" and _STEEL_SESSIONS.get(_skey(user_id)) == endpoint and attempt == 1:
                _evict_steel(user_id)
                continue
            if isinstance(e, Unavailable):
                raise
            raise Unavailable(f"browser connect failed: {e}") from e
