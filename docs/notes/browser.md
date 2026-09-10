# Built-in browser automation for Cycls agents

**Status: implemented.** Every Cycls agent can drive a real browser — navigate,
read, click, fill, log in, screenshot, multi-step flows — with **no Playwright
browsers and no Chromium in the agent image**. The heavy part (real Chrome) runs
**once, in a shared service**; the SDK ships only a thin client (`cycls/_agent/
browser`) and the built-in `Browser` tool. This is the same split we use for
office rendering: the heavy dependency lives in one service, not in every image.

Enable it by putting `"Browser"` in an agent's `allowed_tools` and pointing
`BROWSER_URL` / `BROWSER_SECRET` at a browser service (self-hosted Steel, or a
managed API). Validated end-to-end: the client drives real Chrome over CDP, the
`Browser` tool runs a stateful multi-step flow, a live agent turn drove a page
and its screenshot rendered on the canvas, and the `steel` provider was proven
against a real Steel Browser container.

## Why this shape (settled by research — see the deep-research report)

- **From-scratch engines (Obscura/Lightpanda) can't carry full automation.**
  Fidelity diverges from Chromium, CDP/Playwright compatibility breaks
  (Lightpanda segfaults on `connect_over_cdp`; Obscura's CDP is a subset), and
  their footprint wins are unverified. → we need **real Chrome**.
- **Real Chrome must be shared + isolated.** Untrusted web JS must not run in the
  agent's own process (V8's own guidance), and we won't bake a browser into every
  image. → a **service**, not an in-agent engine.
- **The SDK ships the client; the service is deployed once.** → the office-render
  precedent, reused verbatim.

## Non-goals

- Not building or bundling a browser engine.
- Not shipping Chromium per agent.
- Basic **stealth is applied** (JS/DOM fingerprint patches + a normalized UA +
  locale — see below), but hard anti-bot / Cloudflare-Turnstile is still out of
  scope: that needs residential proxies + CAPTCHA solving (paid, opt-in, later).

## Architecture

```
   agent container (tiny)                     shared browser service            
   ─────────────────────                      ──────────────────────            
   playwright-python (lib only,               Steel Browser (Apache-2.0)        
   NO browsers installed)                     = real Chrome, pooled sessions,   
        │                                        stealth + proxy, CDP endpoint   
        │  cycls Browser tool                                                    
        ▼                                                                        
   connect_over_cdp(wss://…)  ───────────────▶  create session → drive a page   
        ▲                                        navigate/click/type/screenshot  
        └──────── page text + refs + PNG ◀──────  teardown on turn end           
```

- **Agent side**: only the Playwright *library* (a few MB) sits in the base
  image. It never runs `playwright install`, so **no Chromium download, ever**.
  It connects to the remote Chrome over CDP.
- **Service side**: one deployment of Steel Browser (or a managed provider) runs
  real Chrome, pools sessions, and only pays browser memory when an agent is
  actually browsing.

## Configuration (env-gated, graceful — mirrors `office.configured()`)

| Env var            | Meaning                                                  |
|--------------------|----------------------------------------------------------|
| `BROWSER_URL`      | service base URL (self-hosted Steel, or a managed API)   |
| `BROWSER_SECRET`   | shared service secret (Bearer)                           |
| `BROWSER_PROVIDER` | optional: `cycls` · `steel` (default) · `cdp` · `browserbase` |
| `BROWSER_HUMANIZE` | optional: `0` disables human-like input (default on)     |
| `BROWSER_PROXY` *(or* `BROWSER_PROXY_SERVER` + `_USERNAME`/`_PASSWORD`*)* | optional: route browsing through a proxy — the IP layer; you supply the pool |

Providers:
- **`cycls`** — a REST browser service **deployed on Cycls infra** (`cycls deploy`,
  the office-render sibling). The agent talks plain HTTP; **no Playwright/Chromium
  in the agent** at all. This is the recommended shared backing (see below).
- **`steel`** (default) — a Steel Browser service (self-hosted or managed); the
  agent connects over CDP. `playwright` (library) rides in the base image.
- **`cdp`** — a raw CDP endpoint (`http://host:9222`); no secret needed. Dev.
- **`browserbase`** — managed (Phase 4 stub).

Unset `BROWSER_URL`/`BROWSER_SECRET` and `browser.configured()` is false: the
Browser tool is simply **not offered to the model**, and any direct call raises
`Unavailable` → a clear "browsing isn't configured" result. No crash, no
regression — exactly today's office behaviour. The workspace `subject` rides along
as `X-User-Id` for attribution/quota. (`cdp` needs only `BROWSER_URL`; the others
need the secret too.)

## Deploy the service

### `cycls` — a browser service deployed on Cycls infra (recommended)

The service lives in its own repo — **[`Cycls/cycls-browser`](https://github.com/Cycls/cycls-browser)** (the office-render sibling). It's a small FastAPI + Playwright app packaged as a `@cycls.function` (the image installs real Chromium at build). It owns Chrome and exposes a REST API — session create, goto, snapshot, click/type by ref, screenshot, download, evaluate — that the SDK's `cycls` provider (`RestSession`) calls over HTTP, and it applies stealth + behavior + proxy/routing server-side. Deploy it like office-render, with your `CYCLS_API_KEY`:

```bash
git clone https://github.com/Cycls/cycls-browser && cd cycls-browser
python browser_service.py        # → https://cycls-browser.cycls.ai
```

Then on agents: `BROWSER_PROVIDER=cycls`, `BROWSER_URL=https://cycls-browser.cycls.ai`,
`BROWSER_SECRET=<the baked secret>`.

**`max_instances=1` is required.** Sessions live in the instance's memory (an
isolated browser context each), and Cloud Run's router doesn't know which instance
owns a session — a second instance would 404 sessions made on the first, breaking
multi-step flows. One instance serves **many isolated sessions concurrently**
(3 agents → 3 separate contexts, no interference), bounded by its RAM (~15–20
sessions on 2–4 Gi). Scaling past one instance needs session-aware routing (a
control plane / affinity) — what managed services provide.

### `steel` — self-host Steel Browser (alternative)

Self-host **Steel Browser** (Apache-2.0) as the shared "office-render sibling":

```bash
docker run -d --name steel-browser --shm-size=2g --cap-add=SYS_ADMIN \
  -p 3000:3000 -p 9223:9223 ghcr.io/steel-dev/steel-browser
```

Then set `BROWSER_URL=http://<host>:3000` (+ any `BROWSER_SECRET`). The client
mints a session via `POST /v1/sessions`, reads the `websocketUrl` it returns, and
connects Playwright over CDP. `--shm-size=2g` + `--cap-add=SYS_ADMIN` are what let
Chrome launch in-container (without SYS_ADMIN the profile SingletonLock fails and
Chrome crash-loops; this was needed on Docker Desktop and is harmless on Linux).

For **zero-infra**, point `BROWSER_URL`/`BROWSER_SECRET` at a managed API (Steel
Cloud / Browserbase) with `BROWSER_PROVIDER=steel` — same client, no code change.
Managed providers also win for anti-bot sites (they bring stealth + proxies).

## Agent-facing surface

- **Enable via `allowed_tools`.** Put `"Browser"` in the LLM's
  `.allowed_tools([...])` (the Cycls-idiomatic way, alongside `Bash`/`Editor`/
  `Canvas`/`WebSearch`). `build_tools` offers it **only when `browser.configured()`**
  — else it's silently absent, exactly like an unconfigured office-render. No
  dedicated builder method; provider/URL come from env.
- **One stateful tool the model drives across a turn.** A single `browser` tool
  with an action verb: `open`, `read`, `click`, `type`, `press`, `back`,
  `screenshot`. The model calls it repeatedly within a turn to run a multi-step
  flow.
- **DOM/text-first, not pixels.** `read` returns the page as text + an indexed
  list of interactive elements (`ref`s), and the model acts by `ref`. This works
  for **text-only models** and is far cheaper in tokens than screenshot-loops.
  `screenshot` is for humans (renders on the canvas) and vision models.
- **State lives in the remote page.** Executors are stateless per call; the open
  page/DOM/cookies persist in the remote browser (or the Steel session) between
  the connect→act→disconnect cycles, and `ref`s are re-resolved by re-snapshotting
  each action. So a login/search/fill flow works step by step within a turn.
- **Streaming**: each action emits a `step` event; `screenshot` uses the
  two-channel `{"_model","_ui"}` result — the model gets a text ack, the client
  gets an `open_canvas` event that renders the PNG in the side panel (the same
  path office files use — no FE change).

## Pieces & files

| # | File | Role |
|---|------|------|
| 1 | `cycls/_agent/browser/client.py` | Service client — session create/connect (CDP + REST), the actions + `snapshot`/`click_ref`/`type_ref`/`download`/`evaluate`, `configured()` / `Unavailable`. Sibling of `web/office.py`. |
| 2 | `cycls/_agent/browser/stealth.py` | Fingerprint patches: the `STEALTH_JS` init script (webdriver/WebGL/plugins/…), `LAUNCH_ARGS`, `chrome_ua`, `context_kwargs`, `apply(context)`. Single source of truth; the service duplicates the JS with a "kept in sync" note. |
| 2b | `cycls/_agent/browser/behavior.py` | Human-like input: `human_click` (mouse approach path), `human_type` (per-key cadence), `human_settle` (move + scroll after load). Gated by `BROWSER_HUMANIZE` (default on). Tunables mirrored into the service. |
| 3 | `cycls/_agent/tools/__init__.py` | `_BROWSER_TOOL` schema, `_exec_browser` executor, `build_tools` gating on `configured()`, `_TOOLS["browser"]` + step label. |
| 4 | `cycls/_app/main.py` (`App._base_pip`) | `playwright==1.62.0` (library only) added to the base image. |
| 5 | `client/src/…` | **No change** — the screenshot reuses the existing `open_canvas` + image renderer. |
| 6 | `tests/agent/browser_test.py` · `scenarios/test_browser_live.py` | Mocked (26) + gated-live tests. |
| 7 | `docs/notes/browser.md` (this) · `docs/tutorial.md` · `examples/` | Docs. |
| 8 | [`Cycls/cycls-browser`](https://github.com/Cycls/cycls-browser) (separate repo) | The `cycls`-provider service (FastAPI + Playwright + real Chromium) — the "office-render sibling". Applies stealth + behavior + proxy/routing server-side. Deploy recipe above. |

## As built (decisions taken)

- **Enable via `allowed_tools(["Browser"])`, not a `.browser()` builder** — the
  idiomatic Cycls way; no redundant builder method (provider/URL are env).
- **`playwright` library in `_base_pip`** — best fidelity + auto-waiting; connects
  over CDP, never downloads a browser.
- **Ref-first (DOM), not pixels** — works for text-only models, cheap on tokens.
- **State in the remote page** (stateless executors) — fits the harness tool model
  and survives across calls; Steel's session provides isolation per turn.
- **Self-host Steel by default**; managed provider (Steel Cloud / Browserbase) via
  the same `steel` provider for zero-infra.

<details><summary>Original build plan (P1 client → P2 tool → P3 canvas → P4 service → P5 docs) — all done & validated</summary>

Placeholder-free reference kept for history: P1 the CDP client, P2 the stateful
`browser` tool (open/read/click/type/press/back/screenshot, act-by-ref), P3 the
screenshot → `open_canvas` two-channel event, P4 the Steel service + `steel`
provider, P5 docs/tests/example. Each phase was validated before the next.
</details>

<!--
1. **Client library**: `playwright-python` (library only, ~MBs, no browsers) —
   best fidelity + auto-waiting for full automation. *Alt: raw CDP-over-websocket
   (zero deps, much more code, less robust).* → **recommend Playwright-lib.**
2. **Interaction model**: DOM/accessibility **refs** primary (works for text-only
   models, cheap), screenshots secondary. → **recommend ref-first.**
3. **Session scope**: **per-turn** by default; opt-in persistent-per-chat for
   logins later.
4. **Service**: **self-host Steel** by default (Apache-2.0, sessions/stealth/proxy
   built in); managed provider via `BROWSER_PROVIDER` for zero-infra.
-->

## Stealth (fingerprint fidelity, not anti-bot bypass)

A real browser still leaks that it's *automated*. `cycls/_agent/browser/
stealth.py` applies the free, open-source layer that closes the loudest tells —
applied where Chrome is actually driven (the `cycls` service, and the client's
CDP `Session`):

- **JS/DOM patches** (`STEALTH_JS`, run before page scripts on every navigation):
  `navigator.webdriver` native-`false` (via the launch flag), `vendor` =
  `Google Inc.`, `platform` consistent with the UA, real `languages` /
  `hardwareConcurrency` / `deviceMemory`, a full `window.chrome`
  (`app`/`csi`/`loadTimes`/`runtime`), a consistent Notification-permission query,
  a spoofed WebGL vendor/renderer (headless otherwise reports Google SwiftShader),
  and non-zero `outerWidth/Height`. **The patches are made undetectable**: each is
  defined on `Navigator.prototype` (not the instance) and reports `[native code]`
  from `toString()`, so `getParameter.toString()` / the getter source / even
  `Function.prototype.toString.toString()` all look native. (`navigator.plugins`
  is deliberately left native — an honest empty `PluginArray`.)
- **Launch + context** (only where WE launch Chrome — the service): the
  `--disable-blink-features=AutomationControlled` flag, a **normalized
  User-Agent** (the `HeadlessChrome` token stripped — the biggest header tell),
  and an explicit locale / timezone / viewport (an unset locale, and its missing
  `Accept-Language`, is itself a tell). The client's CDP `Session` reuses the
  service's context, so it gets the JS patches but leaves UA/launch stealth to
  the service (or Steel, which brings its own).

### Behavioral emulation (`behavior.py`, `BROWSER_HUMANIZE`)

Pure `click()`/`fill()` flatten the behavioral signals bot-management scores on —
the cursor teleports, text appears instantly, nothing moves before an action.
`behavior.py` re-introduces motion and timing:

- **`human_click`** — scroll to the element, move the cursor to a jittered point
  inside it via a two-leg interpolated path, pause, then click through the locator
  (keeping Playwright's actionability checks, so the right element is still hit).
- **`human_type`** — focus the field (scroll + click), clear it, and type
  character-by-character with a randomized 35–110 ms cadence.
- **`human_settle`** — after a page loads, one cursor move + a small scroll (what
  Cloudflare's non-interactive challenge watches for).

Every step is best-effort (falls back to the plain action). On by default; set
`BROWSER_HUMANIZE=0` to disable (faster, but flatter behavioral signals). Validated
live: a full saucedemo login typed at ~114 ms/char and clicked via a mouse path,
landing authenticated. Applied both in the client `Session` (steel/cdp) and the
service (`/goto` · `/click` · `/type`).

### Proxy (the IP layer, `BROWSER_PROXY`)

Fingerprint and behavior are the *browser* layers; neither moves a block keyed to
the **IP/ASN** (a datacenter IP flagged by reputation, or a hard WAF rule — e.g.
`my.gov.sa` returns Cloudflare's `Sorry, you have been blocked` no matter how
clean the browser looks). That needs a different egress IP, which you **supply**
(a residential/mobile pool — it can't be manufactured, only pointed at).

Set `BROWSER_PROXY=scheme://user:pass@host:port` (or the split
`BROWSER_PROXY_SERVER` + `_USERNAME`/`_PASSWORD`) on the agent. The client reads
it and forwards it in the session-create body; the service applies it **per
context** (`new_context(proxy=…)`), so different callers on the one shared browser
can egress through different proxies. The service also honors the same env itself
as a fallback. Validated: a dead proxy surfaces `ERR_PROXY_CONNECTION_FAILED`,
confirming the config reaches real Chrome.

### CDP-leak hardening (`rebrowser-playwright`)

Stock Playwright drives Chrome with `Runtime.enable`, which bot-management can
detect (the `console.debug` / `Error.stack` probe) — a leak no init-script fully
closes. The fix is a **patched Playwright** that avoids it. Both the client and
the service import Playwright through a seam: `rebrowser_playwright` is used when
installed, else stock Playwright. To turn it on, add `rebrowser-playwright` to the
service image's `.pip(...)` (and the agent env if you use the `cdp`/`steel`
providers) — the import seam activates it automatically, no code change. (The
Selenium-style `cdc_` leak doesn't apply here — Playwright never injects it.)

### TLS

**TLS is deliberately untouched.** A real Chromium already sends a genuine Chrome
ClientHello (JA3/JA4); there is nothing to "spoof" — a spoofer would make it
*less* authentic. TLS-impersonation libraries (`curl_cffi`, `tls-client`) exist
only to make *non-browser HTTP clients* look like Chrome, which doesn't apply
here. The one non-Chrome network path is `download {url}` (Playwright's driver
HTTP via `context.request`); we keep it because it shares the page's cookies and
isn't CORS-bound — routing downloads through in-page `fetch` for a marginal TLS
gain would break cross-origin downloads.

This is enough for **non-hostile sites and authenticated flows you're allowed to
automate**. It will **not** defeat Cloudflare/DataDome on its own — that needs
residential proxies + CAPTCHA solving (paid, opt-in; see Risks).

## Security

- **Isolation is the whole point**: untrusted web JS runs in the *service*, never
  in the agent process (V8 separate-process guidance).
- **SSRF**: the service is network-isolated; optional URL allow/deny + block
  private ranges.
- **Auth**: shared `BROWSER_SECRET` + `X-User-Id` attribution (office-render
  parity).
- **Resource caps**: per-session idle/hard timeouts, max pages, force-teardown at
  turn end so a runaway flow can't leak browsers.

## Risks / open questions

- **Anti-bot / Cloudflare**: base stealth (above) closes the JS/UA/locale tells,
  but the hard cases still need **residential proxies + CAPTCHA solving** (paid)
  or a managed provider that specialises (Steel Cloud / Browserbase bring stealth
  + proxies). Opt-in, later, and budget for it. TLS itself is already authentic
  (real Chrome).
- **Service sizing / cost** under agent-platform load — measured empirically, like
  office-render (warm pool, session reuse).
- **Revisit Obscura in ~12 months** as a *local, trusted-JS, low-fidelity* fast
  path for trivial cases — never for untrusted JS or high fidelity.
