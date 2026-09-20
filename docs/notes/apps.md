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
                    (an app's own files; cycls.get/set is the `.apps` shelf, below)
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
every member reads and writes. This is the settled requirement, and it is why app data cannot sit in
`.database`, whose path ends `{slot}/{user}` and is therefore one shelf per person. The `.apps` slot
below is scoped per app instead.

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
and hands them to a deployed Cycls function, `app-build`. The service is **not in this repo** —
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

Nothing here is a new primitive. The host page holds the session; the frame holds none of it and
asks for everything. Six of these steps are unchanged from the file era — only 10–12 moved.

```
 1  the agent writes source          apps/<slug>/src/*        (edit tool)
 2  build_app(slug, source)          → app-build              → apps/<slug>/index.html

 3  the person opens the app         Apps tab → canvas
 4  GET /files/apps/<slug>/index.html                         Authorization: Bearer <JWT>
 5  injectShim(html)                 prepend window.cycls      canvas.tsx, HtmlDoc
 6  <iframe sandbox="allow-scripts allow-popups" srcDoc={html}>

 7  frame → host    cycls:ready                               on the window, retried 40× / 50 ms
 8  host checks     e.source === frame.contentWindow           (opaque origin has no e.origin)
 9  host → frame    cycls:init + a transferred MessagePort

10  app calls       cycls.get("total")
11  frame → host    cycls:data {op:"list"}                     over the port, not the window
12  host            appData(slug, op)  →  GET /apps/<slug>/data      with the VIEWER's JWT
13  server          _scope() picks the audience, app_shelf() builds the key
14  host → frame    cycls:data:result {result:[{key,value}…]}
```

### Client side, step by step

**Mounting (3–6).** `appScope(file.path)` returns `apps/<slug>` for `apps/<slug>/index.html` and
`null` for every other HTML file, and that single check decides whether a document gets a bridge at
all. `injectShim` splices the shim into `<head>`; the iframe is `srcDoc`, so there is no URL and no
origin. A shared or gallery view still mounts the shim — without it the first library that touches
`localStorage` white-screens the frame — but its bridge answers every request with a refusal.

**Handshake (7–9).** The shim posts `cycls:ready` on the window and keeps retrying, because nothing
guarantees the host's listener mounted first. The host cannot check `e.origin` (it is `"null"` for
an opaque origin), so identity is the window handle. It replies with `cycls:init` and **transfers a
MessagePort**; everything after that rides the port. A window reply would need `targetOrigin: "*"`,
and a sandboxed frame may navigate *itself* with `frame.contentWindow` following it — so the handle
check would still pass and the replacement document would receive workspace data. A port belongs to
the document that received it. A host that sends no port still works on the window alone.

**A call (10–14).** The shim keeps a `waiting` map keyed by a sequence number, posts, and resolves
on the matching `:result`. The host validates, calls the one function the canvas handed it, and
posts back. The frame never sees a token, a URL or a workspace path it did not already know.

### What changed: `cycls.get`/`set`

|  | before | now |
|---|---|---|
| first `get` | `cycls:read data/state.json` → `GET /files/…` → `JSON.parse` the whole file | `cycls:data {op:"list"}` → `GET /apps/<slug>/data` → rows |
| `set` | mutate memory, mark dirty, wait 250 ms | unchanged |
| the flush | **re-read** the file, merge the dirty keys onto it, `PUT` the whole object back | one `{op:"put", key, value}` per dirty key, in parallel |
| a delete | drop the key, rewrite the whole file | `{op:"delete", key}` |
| two writers | last full write wins unless the merge catches it | collide only on the same key |
| audiences | one, shared by everyone | three — see the slot section |

The merge existed only because the whole file was rewritten; per-key rows make it unnecessary, so it
is gone. What is *not* gone: there is still no compare-and-swap, so two writers on one key inside
the same 250 ms window still lose one.

`cycls.read`/`write`/`save` are untouched — those are files, and `canWrite` still allows `data/`
only.

### Why the frame is shaped like this

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
typed API — `read`, `write`, `save`, `get`/`set`, `me`, `users`, `connector`, `resize` — so an app
calls a function instead of hand-rolling the postMessage protocol.

**An app that throws says so.** The shim posts `cycls:loaderror` from `error` and
`unhandledrejection`, and the canvas shows it. A crashed app used to be a white rectangle.

**`cycls.save(name, content)`** is the only way out of the folder, and it opens a host dialog every
time. An app never holds standing permission to write elsewhere.

## Porting the phone client

`~/Desktop/code/mobile-app` stages the bundle to a `file://` URI in a WebView with
`originWhitelist: ["*"]`. It predates all of this, so today the same app reads rows on the web and
writes a file on a phone — and **nothing reads that file**. A phone user's `cycls.set` is invisible
to the web, to other members and to the agent. This is the item, not a nice-to-have.

In order of what breaks without it:

1. **Handle `cycls:data`.** The frame sends `{type, id, op, key, value, who, prefix}`; reply with
   `{type:"cycls:data:result", id, ok, result}` or `{ok:false, error}`. Map it to
   `GET|PUT|DELETE /apps/<slug>/data[/<key>][?who=&prefix=&limit=]` with the viewer's JWT. `ok:false`
   must carry the status text, because a 403 from the role gate is how an app tells which view to
   render.
2. **Ship the current shim.** `app-shim.ts` is one string; a stale copy still writes
   `data/state.json`, which nothing reads. Nothing else in the shim is web-specific.
3. **Transfer a MessagePort with `cycls:init`.** Optional — the shim falls back to the window — but
   without it a frame that navigates itself keeps receiving workspace data.
4. **Send `canWrite`** the same way, or `cycls.write` silently no-ops.
5. **Bundle size.** Android truncates `loadData` past roughly 2 MB; a 2.4 MB bundle rendered blank
   in production. Stage to a file URI, do not inline.

Until 1 and 2 land, pin the phone to file-backed apps or accept the divergence knowingly.

## Connectors from inside an app

`cycls.connector("salla").json(path, init)` → `cycls:fetch` → the host calls
`/connectors/{name}/fetch/{path}` with the signed-in user's JWT → `connectors.relay()` resolves that
user's grant, bounds the host to the connector's declared `api` base, and attaches the credential
server-side.

The page never holds a token, inherits a refreshed one for free, and keeps working after the chat
that built it has ended. Grant resolution is user → workspace, so two members opening the same shared
app each act with their own credential.

This path is live today — shim `cycls:fetch` → bridge → `fetchConnector` → `/connectors/{name}/fetch/{path}`
→ `oauth.relay()` — and **it has no tests**, at either end.

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

## Where app data lives — the `.apps` slot

`cycls.get`/`set` used to be one JSON file, `data/state.json`, rewritten whole on every flush: no
per-key granularity, and one torn write lost an app's entire state. App data is rows in the object
store now, in a third slot beside the two that were already there. Nothing in production depended on
the old file, so there is no migration path — the shelf simply starts empty.

| slot | holds | scoped |
|---|---|---|
| `.db` | chats | per user |
| `.database` | the agent's memory | per user |
| `.apps` | app data | **per app**, with a per-viewer shelf inside it |

```
{org}/ws/{ws}/.apps/<slug>/<key>            the workspace's copy — every member reads and writes
{org}/ws/{ws}/.apps/<slug>/u/<user>/<key>   this viewer's own — drafts, filters, submissions
```

A standup board keeps its entries in the first and each person's unsent draft in the second.
`state.app_shelf()` is the only thing that builds either, so both the tool and the route obey one
set of rules.

### Three verbs, and the route decides what each may do

```js
cycls.get(key) / set(key, v)                    the workspace's shelf — every member
cycls.update(key, fn)                           read-modify-write that cannot lose one
cycls.me.get(key) / set(key, v) / all(prefix)   this viewer's own
cycls.users.all(prefix) / get(u, k) / set(u, k, v)   everyone's — admins only
```

An app that must keep one member's data from another uses `cycls.me`, and it is not an `if` in the
bundle: the app is model-written HTML in a browser the viewer controls, so a client-side filter is
no boundary at all. **The frame names an audience, never a person.** `who=me` is resolved from the
session and `who=all` from `_admin()`, so there is no id in the call to get wrong and nothing to
forge. An app finds out which view to render by whether `cycls.users` resolves or rejects — the 403
is the answer.

`app.json` carries one flag, the only thing the route cannot infer:

```json
{ "write": "admin" }   // shared shelf becomes admin-write, member-read
```

Per-member privacy needs no flag (it is the verb) and admin-reads-all needs none (it is the role).
The default is that any member writes the shared shelf, matching the app's files, which every editor
can already write — a stricter default would have broken every app on the day it migrated.

### `set` overwrites, `update` does not

`set(key, v)` is last-write-wins, because "put this value here" is what it says. The lost update
happens when an app *meant* read-modify-write:

```js
const items = await cycls.get("items", []);   // Sara and Khalid both read [a, b]
items.push(x);
await cycls.set("items", items);              // one of them silently disappears
```

Per-key rows do not help — both touched the same key. `cycls.update` does:

```js
await cycls.update("items", (cur = []) => [...cur, x]);
```

It reads value **and version**, applies `fn`, and writes with `?version=`. The store passes that to
GCS as `ifGenerationMatch`, so a write whose row moved underneath comes back 412; the shim re-reads,
re-applies `fn` to what is actually there, and writes again — up to five times before giving up.
Nobody's write is lost, and the loser is the one that retries.

`get_gen()` and `put(gen=…)` are the DB surface. The file store's version is a hash of the bytes and
its compare-then-replace is not atomic — it is the dev and test store, where there is one writer.

### A list says when it did not fit

Nothing truncates an app's *files* — `cycls.read`/`write` are unchanged. The cap is on how many KV
rows one list returns, and it exists because `items()` is a LIST plus one GET per row.

The real protection is `FETCH_WIDTH`, a semaphore of 32 concurrent reads inside `items()`: a wide
prefix used to fan out one request per key all at once. With the fan-out bounded, the row cap is a
backstop at 10,000 rather than a policy — no realistic app is cut by it.

If one ever is, it is told. `cycls.get` loads the whole shared shelf into a map once and answers
from it, so a cut page makes "absent" meaningless: the key may be in the part that was dropped. The
reply carries `truncated`, and `cycls.get` **throws** rather than return a fallback for a key it
cannot vouch for. A key it did see still answers normally.

Truncation is judged on rows *fetched*, not rows returned — a shared list drops `u/` rows, and
counting survivors would call a cut page complete.

### Scope is in the path, permission is on the route

Keeping those apart is what lets an app flip from open to admin-write without moving a single row,
and it is why there is no `a/` prefix or per-key ACL. The path answers *who is this for*; the
request answers *who is asking*.

`u` is reserved directly under a slug. Without the marker every user id that will ever exist would
be a forbidden shared key, and nothing could check that locally — the write path has no list of
people. With it the check is one string compare, and `database scan apps/standup/` can leave other
members' rows out of what the agent sees.

### The slug is the only join, and the builder never learns it

`apps/<slug>/` is the folder and `.apps/<slug>/` is its shelf. Five apps are five folders and five
prefixes; no id, no registry, no manifest field that can drift.

`app-build` is `files → html` — handed source, returns a bundle, and knows nothing of the slug, the
workspace or the store. The scope is resolved at *runtime* by the host from the path the file was
served from, the same `appScope()` that decides whether a document gets a bridge at all. If the
frame could pass a slug, the invoices app could write the standup app's shelf. A bundle is therefore
portable: rename `apps/standup/` to `apps/daily/` and the same bytes address `.apps/daily/`.

### Deleting an app takes its data — at purge, not at delete

A delete is a move, and `data/state.json` used to ride inside the folder into `.trash/`, recoverable
for 30 days. Hard-deleting rows on delete would have thrown that away, so the rows follow the
folder's lifecycle one step behind:

| event | folder | rows |
|---|---|---|
| delete app | → `.trash/<id>/` | untouched |
| restore | ← back | untouched — the data reappears, **zero copies** |
| purge entry / empty trash | gone | `remove_prefix(.apps/<slug>/)` |
| `build_app` on a slug with no folder | fresh | stale rows purged first |
| rename app (`PATCH /files`) | moved | the shelf moves with it — O(N), admin-gated, rare |
| delete workspace | gone | swept by `wipe_workspace`'s existing prefix removal |

Why the viewer's shelf nests *under* the app rather than beside it: `.apps/<slug>/` is one prefix
delete that takes the shared rows, every member's private rows, and the rows of people who left
months ago. The alternative — `s/<slug>/` and `u/<user>/<slug>/` — needs the member list to find the
second half, and the member list is not the set of people holding rows. Data that outlives the list
that would have deleted it is the failure being avoided. Forgetting one person costs N deletes
instead of one, where N is the app count: single digits, and listable from `apps/` itself.

The reused-slug purge is what stops silent corruption: delete `standup`, build a new `standup` two
weeks later, and without it the new app opens onto the dead one's rows with a schema that does not
match.

`trash.sweep()` is sync and stdlib-only on purpose — the sandbox `rm` shim calls it, where `/app` is
masked — so a 30-day TTL expiry cannot await a `remove_prefix`. Rows can outlive their trash entry.
They are invisible, cost nothing, and can never be inherited, because the build-time purge catches
them.

**There is no migration from `data/state.json`.** Nothing in production used it, so the shelf starts
empty and the file is not read. An app that still wants a file uses `cycls.read`/`write`, which is
what injaz does with `data/<PROJECT>.json` — those are files and are unaffected.

## Known limitations

Current behaviour, not aspiration. Each is a real constraint someone will hit.

**Storage**
- No browser storage of any kind works in the frame — opaque origin means `localStorage`,
  `sessionStorage`, IndexedDB, Cache API and OPFS all fail by spec. **SQLite in the browser is
  therefore impossible**, in every persistence flavour.
- The bridge is **text-only in both directions**. `readFile` decodes as UTF-8, so binary cannot
  round-trip; an image or a database must be base64 at rest.
- A bridge *file* write is capped at 25 MB of UTF-8 and rewrites the whole file — there is no
  append, no delete and no directory listing. The cap used to be 1,000,000 `.length`, which is
  UTF-16 units, so it was ~1 MB of English and ~2 MB of Arabic under a name that said bytes.
- A **data row** is capped at 1 MB, and deliberately stays there: a list reads every row, so a value
  is a value and anything bigger belongs in a file.
- CAS exists (`put(gen=…)` → `ifGenerationMatch`) but is opt-in, and only app data uses it. Chats
  and the agent KV stay last-write-wins on purpose: both are `{slot}/{user}`, one person per shelf,
  so there is no second writer to lose to.
- A flush that fails rejects the pending `set`, so a tab closing on a dead connection can still lose
  its last 250 ms.

**App data**
- A list is capped at 10,000 rows. It says so (`truncated`) and `cycls.get` throws rather than lie,
  but there is still **no cursor** — the only way past the cap is a narrower `prefix`.
- `set` is last-write-wins by design; only `update` is safe against a concurrent writer. An app that
  does `get` → mutate → `set` is still losing writes, and nothing warns it.
- `update` retries five times and then throws. Under heavy contention on one key it gives up.
- `items()` is a LIST plus **one GET per row**, 32 at a time. A 1000-row list is 1001 reads however
  it is paced; a prefix is the only thing that makes it cheaper.
- `who=` costs a `resolve_role()` — one or two more object reads per request, uncached.
- A non-admin write to a shared shelf reads `app.json` to check `write: admin`. One small gcsfuse
  read per write, and writes are debounced, so it is not hot — but it is not free either.
- `cycls.users` has no "list the members" verb — it lists rows, so a member who has written nothing
  is invisible to an admin view.

**The frame**
- A shared or gallery view has no workspace. The app now gets the shim, so it renders, but every
  `cycls.read` and every `cycls.get` rejects — an app that needs its data shows nothing in a share.
- On mobile the app is staged to a `file://` URI in a WebView with `originWhitelist: ["*"]`, and
  Android truncates `loadData` past roughly 2 MB — a 2.4 MB bundle rendered blank in production.
- The mobile host has not been ported: it sends no MessagePort (so that frame still talks on the
  window) and knows nothing of `cycls:data`, so `cycls.set` there still writes `state.json` as a
  file. **Nothing reads it.** With no seed, a phone user's writes are invisible to the web and to
  the agent until the port lands — the strongest reason to do it. `~/Desktop/code/mobile-app`.

**The build**
- `_collect_source` skips binaries, so an app cannot ship an image file; icons must be data URIs.
- Vite tree-shakes an unused bad import, so a build can succeed with a dependency that was never
  resolvable. Only a *used* import fails the build.
- The service is a separate deployment in another repo. `--live` covers the contract; nothing
  covers it on every commit.

**Renaming**
- Only `PATCH /files` moves the shelf. `bash mv apps/a apps/b` does not go through the route, so the
  rows stay at `.apps/a/` and the renamed app opens empty. Nothing is lost — `database scan apps/a/`
  still finds them — but the agent has no rename *tool*, so bash is the only way it can rename, and
  it will hit this. An `mv` shim cannot fix it the way the `rm` shim does: shims are stdlib-only and
  sync, with no path to the store.

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
