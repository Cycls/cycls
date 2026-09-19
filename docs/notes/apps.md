# Apps

An app is a folder in the user's workspace holding one self-contained HTML file. The agent writes
its source, a build service bundles it, the canvas runs it in a sandboxed iframe, and the host page
does every privileged thing on its behalf. Nothing about an app is a new primitive: it rides the
workspace, `/files`, the canvas, the trash and the connector relay that all already existed.

## What an app is

```
{volume}/{org}/ws/{ws}/apps/<slug>/
  index.html      the built bundle — everything inlined, one file
  app.json        name, icon, description, and `built` provenance
  README.md       what the app reads and the shape of it — written at build time
  src/            the source the agent wrote; stays, so a rebuild is possible
  data/           the ONLY path the app may write
    state.json      the key-value store behind cycls.get / cycls.set
```

`canWrite` is an allowlist: the app writes under `data/` and nowhere else. As a denylist it
allowed `scripts/` and `components/` — code the browser writes and the shell later runs. The
agent has no such limit; it reaches the whole folder with `edit` and with `bash` (which has
`jq`).

**The path is the whole access-control story.** `appScope()` (`client/src/components/app-bridge.ts`)
grants the bridge to any HTML at `apps/<slug>/index.html` — not to an app the builder produced, to
an app that *sits there*. A hand-written `index.html` gets the identical bridge, which is deliberate:
it makes the builder replaceable rather than load-bearing, and it makes the bridge testable without
one. Every other HTML file in the workspace opens in the canvas as an inert document with no bridge
at all, because opening a document must never hand that document your workspace.

**An app is shared by the whole workspace.** `workspace()` returns
`root = {volume}/{org}/ws/{ws}` with **no user segment** (`workspace()` in `cycls/_app/db.py`), and every
`/files` route resolves against `ws.root`. So the bundle, the source and the data are one copy that
every member reads and writes. This is the settled requirement, and it is the reason app data lives
in the folder rather than in the agent KV — the KV path is `{slot}/{user}`, which is per person.

## What the agent knows about an app

Two things, and both are cheap because neither is stored in the prompt by default.

**A catalog, on a 30 s TTL.** `app_catalog()` emits one line per app from the `name` and
`description` in its `app.json`, both set by `build_app` —
nothing at all in a workspace with no apps. The TTL is not optional: the volume is gcsfuse, and
a scan per turn is the pattern `plugins-connectors.md` warns about.

**A README, written when the shape is known.** The agent that builds an app knows its data
model; three weeks later, in another chat, it does not. So `build_app`'s success message asks
for `apps/<slug>/README.md`. Before it did, one injaz session spent **51 of 66 bash calls**
grepping a 2.4 MB minified bundle to reverse-engineer a schema — and got it wrong, which is
where a duplicate-ID corruption came from.

## The build

`build_app` (`_exec_build_app` in `cycls/_agent/tools/__init__.py`) collects the text files under it
and hands them to a deployed Cycls function, `miniapp-build`. The service is **not in this repo** —
it lives at `~/Desktop/code/remote_build_function` and has its own git history.

It is remote on purpose, for three reasons:

1. **Vite executes the source it bundles.** Running that inside the agent container would execute
   model-authored code in a process holding `ANTHROPIC_API_KEY`, `CYCLS_SECRET_KEY` — which decrypts
   every connector grant in the deployment — and full ADC, *outside* bwrap. The build service has
   none of them.
2. **Dependencies are baked, never supplied.** `npm install` runs at image-build time against a
   pinned `toolchain/package.json`. A caller passes source only and cannot name a package, so no
   build reaches npm: no postinstall hook, no supply-chain fetch. Adding a library means editing the
   toolchain and redeploying, which is the point — the dependency set is reviewed, not requested.
3. **It stamps the CSP** (below).

| | |
|---|---|
| contract | `build(files, entry) -> {ok, html, bytes, stray, log, version, packages}`; `version` and `packages` ride failures too |
| limits | 400 files · 2 MB per file · 12 MB total · 300 s vite, 420 s function — all mirrored SDK-side so they fail here, naming the file |
| toolchain | React 19, Tailwind v4, 29 packages — `toolchain/package.json` is the only source of truth |
| drift | `tests/agent/scenarios/test_build_contract.py --live` fails when the tool description and the toolchain disagree |

`app.json` records `built: {at, source, builder}`, so a bundle left stale by a toolchain
redeploy is identifiable. A rebuild trashes the bundle it replaces, as `edit` does an overwrite.

**Every built app carries a CSP**, injected by `toolchain/vite.config.mjs`:

```
default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline';
img-src data: blob:; font-src data:; connect-src 'none';
object-src 'none'; base-uri 'none'; form-action 'none'
```

`'unsafe-inline'` is not a concession — the bundle *is* inline. What the policy buys is
`connect-src 'none'`: the app reaches its workspace only over postMessage, so it needs no network
and cannot phone home. This does **not** break connectors: `cycls.connector(x).json(...)` is a
postMessage to the host, which makes the HTTP call itself. A future maintainer tempted to loosen the
CSP so "fetch works" would be removing the only thing that bounds a generated page.

## The dance

```
 1  the agent writes source          apps/<slug>/src/*        (edit tool)
 2  build_app(slug, source)          → miniapp-build          → apps/<slug>/index.html

 3  the user opens the app           Apps tab → canvas
 4  GET /files/apps/<slug>/index.html                         Authorization: Bearer <JWT>
 5  injectShim(html)                 prepend window.cycls      canvas.tsx, HtmlDoc
 6  <iframe sandbox="allow-scripts allow-popups" srcDoc={html}>

 7  frame → host    cycls:ready                               on the window, once
 8  host checks     e.source === frame.contentWindow           (opaque origin has no e.origin)
 9  host → frame    cycls:init + a transferred MessagePort

10  app calls       cycls.read("data/x.json")
11  frame → host    cycls:read                                 over the port, not the window
12  host checks     inScope(scope, path)                       app-bridge.ts
13  host fetches    GET /files/apps/<slug>/data/x.json         with the USER's JWT
14  host → frame    cycls:read:result
```

**Everything after the handshake rides a private port.** A window reply needs
`targetOrigin: "*"` — an opaque origin has none to name — and a sandboxed frame may navigate
*itself*, with `frame.contentWindow` following it, so the identity check still passed and the
replacement document received workspace data. A port belongs to the document that received it:
navigate away and it is gone. A host that sends no port (an older mobile build) still works on
the window alone.

**The sandbox is load-bearing.** `sandbox="allow-scripts"` with no `allow-same-origin` gives the
document an opaque origin. Without it, model-written HTML embedded in the agent's own page would be
same-origin with the host: it could read the Clerk JWT out of localStorage and call every authed
route as that person, across every workspace they belong to. That is a capability the agent itself
does not have — the agent holds a workspace, never a browser session — so this is the one boundary
that cannot be traded away.

**The shim exists because the room is bare.** In an opaque origin, merely *reading*
`window.localStorage` throws `SecurityError`, and most libraries touch storage during render — so an
app without the shim is a blank white frame with no message. `app-shim.ts` installs an in-memory
`localStorage`/`sessionStorage` replacement (it forgets on reload, which beats not rendering) and a
typed API — `read`, `write`, `save`, `get`/`set`, `connector`, `resize` — so an app calls a function
instead of hand-rolling the postMessage protocol.

**`cycls.get`/`set`** coalesce: `set` mutates memory and schedules one write 250 ms later, so a
burst of updates costs one PUT. The flush then **re-reads and merges only the keys this frame
touched** — writing the whole cached object meant a second tab, another device or the agent lost
everything it had changed. A key removed locally is removed in the merge, so a delete carries.
It is still not compare-and-swap: two writers touching the same key inside one GET→PUT window
lose one.

**An app that throws says so.** The shim posts `cycls:loaderror` from `error` and
`unhandledrejection`, and the canvas shows it. A crashed app used to be a white rectangle.

**`cycls.save(name, content)`** is the only way out of the folder, and it opens a host dialog every
time. An app never holds standing permission to write elsewhere.

## Connectors from inside an app

`cycls.connector("salla").json(path, init)` → `cycls:fetch` → the host calls
`/connectors/{name}/fetch/{path}` with the signed-in user's JWT → `connectors.relay()` resolves that
user's grant, bounds the host to the connector's declared `api` base, and attaches the credential
server-side.

The page never holds a token, inherits a refreshed one for free, and keeps working after the chat
that built it has ended. Grant resolution is user → workspace, so two members opening the same shared
app each act with their own credential.

An app is a second, non-LLM caller of the same grant, so the relay carries what the tool path
carries: a `relay` audit line naming the connector and the caller, the org and personal switches,
a per-minute budget, and `never` on the reserved `_relay` key for a person who does not want
their apps reaching a connector at all. `ask` is not offered — an HTTP route has no chat to ask in.

**A connector with a REST base and no MCP server** contributes one `{name}_request` tool, handled
by the same `relay`. Without it a pasted key could be stored, encrypted, scoped and listed in the
directory while the agent never learned it existed, because the loop only ever walks servers.
`auth=` picks how the credential is presented: `bearer` (default), `basic`, `header`, `query`.
Declare it on `cycls.Web().connectors(...)` as usual **and** on `cycls.LLM().connectors(...)`, which
is how the loop sees a connector that has no server to walk.

## Known limitations

Current behaviour, not aspiration. Each is a real constraint someone will hit.

**Storage**
- No browser storage of any kind works in the frame — opaque origin means `localStorage`,
  `sessionStorage`, IndexedDB, Cache API and OPFS all fail by spec. **SQLite in the browser is
  therefore impossible**, in every persistence flavour.
- The bridge is **text-only in both directions**. `readFile` decodes as UTF-8, so binary cannot
  round-trip; an image or a database must be base64 at rest.
- A bridge write is capped at 1,000,000 UTF-16 units and rewrites the whole file. There is no
  append, no delete and no directory listing.
- No compare-and-swap anywhere: `PUT /files` is an unconditional whole-file replace. The shim's
  merge narrows the loss to one key inside one GET→PUT window; it does not remove it.
- A flush that cannot re-read writes nothing rather than clobbering, so a tab closing on a dead
  connection can lose its last 250 ms.

**The frame**
- A shared or gallery view has no workspace. The app now gets the shim, so it renders, but every
  `cycls.read` rejects — an app that needs its data shows nothing in a share.
- On mobile the app is staged to a `file://` URI in a WebView with `originWhitelist: ["*"]`, and
  Android truncates `loadData` past roughly 2 MB — a 2.4 MB bundle rendered blank in production.
- The mobile host has not been ported yet: it sends no MessagePort (so that frame still talks on
  the window), keeps the old `state.json` path, and does not merge on flush. Until it ships,
  the same app on web and on a phone writes two different files.

**The build**
- `_collect_source` skips binaries, so an app cannot ship an image file; icons must be data URIs.
- Vite tree-shakes an unused bad import, so a build can succeed with a dependency that was never
  resolvable. Only a *used* import fails the build.
- The service is a separate deployment in another repo. `--live` covers the contract; nothing
  covers it on every commit.

**Access control**
- An app may write `data/` only, but the **agent** may write anything in the folder, and an
  injected agent writing `src/` then rebuilding is not gated.
- `RELAY_PER_MINUTE` is per instance. Cloud Run runs several, so it bounds a runaway, not a
  determined caller.

**Fixed, and worth not regressing**
- A failed tool used to log `ok=true`: `log("tool_call")` derived it from whether an exception was
  raised, while every tool in this codebase reports failure by *returning* `Error: …`. One injaz
  agent ran broken for eight weeks behind 1063 rows and a single recorded failure.
- `PUT /files` staged through a deterministic `<name>.part`, so two concurrent writers interleaved
  into a torn file while one of them got HTTP 200. Now a unique name under `.tmp/`.
- The canvas unmounted the open document at the end of every agent turn, destroying an open app and
  any write inside the debounce. A reload now keeps what is on screen; only a different file blanks.
- `fork_share` copied a public link's files over whatever the forker already had, `AGENT.md`
  included — which is prompt injection that persists. A fork now only adds, and never copies
  `AGENT.md`.
- The admin-only app delete keyed on a two-segment *directory*, so `apps/<slug>/index.html` slipped
  through as an ordinary file, and `PATCH /files` had no check at all. Both use
  `trash.owned_by_app` now.

## The next architecture

Serving apps from a **separate origin** — `a-<hash>.cyclsusercontent.com`, one static shell shared by
every app, the HTML handed across by postMessage — removes most of the storage section above. The app
gets a real origin: `localStorage`, IndexedDB and OPFS work, SQLite becomes possible, `e.origin`
replaces window-handle identity, and storage is isolated per app and per workspace.

It needs no per-app deployment: one wildcard DNS record, one wildcard certificate, one shell file
that holds no data and authenticates nobody. A different registrable domain, not a subdomain of the
agent's, for the reason `githubusercontent.com` exists.

**The trigger is a product decision, not a technical one: do apps need real local state?** Until they
do, the sandbox above is correct and the shim's polyfill is enough. Note that origin storage is
per browser and per device — invisible to the agent and to other members — so it is a second tier
beside `apps/<slug>/data/`, never a replacement for it.
