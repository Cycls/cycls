"""Stealth patches that make a headless Chrome look like an ordinary browser.

This is the FREE, open-source layer of anti-detection: patch the JavaScript/DOM
tells a plain automated Chrome leaves — `navigator.webdriver`, a SwiftShader
WebGL renderer, a missing `window.chrome`, a `vendor`/`platform` that disagrees
with the UA, `outerWidth/Height == 0` — and, crucially, make every patch
*undetectable*: each is defined on the prototype (where real Chrome puts it) and
reports `[native code]` from `toString()`, so a detector calling
`getParameter.toString()` can't spot the override. Also normalizes the User-Agent
(drops the `HeadlessChrome` token) and sets a believable locale / viewport /
timezone. (`navigator.plugins` is deliberately left native — an honest empty
`PluginArray` beats a fake.)

It is NOT an anti-bot bypass, and deliberately so:
  - TLS fingerprint (JA3/JA4): a real Chromium already sends a genuine Chrome
    ClientHello. There is nothing to spoof — spoofing would make it LESS
    authentic. So this module does not touch TLS.
  - Residential proxies and CAPTCHA solving are paid, out-of-scope concerns.
On its own this will not defeat Cloudflare / DataDome; it is meant for
non-hostile sites and authenticated flows you are allowed to automate. See the
Risks section of docs/notes/browser.md.

Single source of truth: the SDK client (the steel/cdp providers) imports
`STEALTH_JS` / `apply` from here. The `cycls` browser service is a standalone
deployable file, so it duplicates `STEALTH_JS` with a "kept in sync" note — the
same convention `_SNAPSHOT_JS` already follows.
"""

# Chrome launch flags that drop the loudest tells: the `AutomationControlled`
# blink feature is what sets `navigator.webdriver` and the "browser is being
# controlled by automated software" banner. Only usable when WE launch Chrome
# (the cycls service) — a client connecting over CDP to an already-launched
# browser can't change how it was started.
LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]


def chrome_ua(version, platform="X11; Linux x86_64"):
    """A normal Chrome User-Agent for `version` (full "141.0.7390.54" or just
    "141"), with the `HeadlessChrome` token replaced by `Chrome` — the single
    biggest header-level tell. Defaults to a Linux platform (the service and
    Steel both run Linux)."""
    major = str(version or "").split(".")[0] or "120"
    return (f"Mozilla/5.0 ({platform}) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{major}.0.0.0 Safari/537.36")


def context_kwargs(user_agent=None):
    """`new_context(**kwargs)` that round out a believable browser: a real UA (so
    the HTTP `User-Agent`/`sec-ch-ua` and `navigator.userAgent` all agree), a
    normal viewport, and an explicit locale + timezone (an unset locale, and the
    `Accept-Language`-less request it produces, is itself a tell)."""
    kw = {"locale": "en-US", "timezone_id": "America/New_York",
          "viewport": {"width": 1280, "height": 800}, "device_scale_factor": 1}
    if user_agent:
        kw["user_agent"] = user_agent
    return kw


# Runs BEFORE any page script on every navigation (registered via
# add_init_script), so a site's fingerprinting reads the patched values. Every
# patch guards itself so re-running on a reused context can't throw.
STEALTH_JS = r"""() => {
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


async def apply(context):
    """Register the stealth patches on a Playwright context so they run before
    page scripts on every navigation. The JS is an arrow function, so it's
    wrapped in an IIFE to actually execute (add_init_script runs the source as-is
    rather than calling it). Best-effort — the caller wraps this so a stealth
    hiccup never breaks browsing."""
    await context.add_init_script(f"({STEALTH_JS})();")
