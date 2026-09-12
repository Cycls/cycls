# Connectors

**Problem.** Extending an agent means four unrelated surfaces: `.tools([schema])` for
shapes, `.on(name, fn)` for handlers, `.skills(dir)` for instructions, `.mcp(server)` for
remote tools, and `.loop(fn)` when none of them reach far enough. Nothing bundles a related
set, so an integration can't be installed, versioned or removed as one thing. None of it
knows *whose* account a tool acts on — `dispatch` calls `handlers[name](inp)` with one
argument — so a tool that touches the end user's Gmail cannot be written at all. And
`cycls.MCP` rides the Anthropic connector, which `providers/openai.py` drops with a
warning: the provider our deployed agents actually run on.

## Naming

**Users see one word: Connectors** (Arabic: **التكاملات**; the action is **ربط** — *اربط
حسابك في سلة*). Avoid *أدوات الربط*, which is the grammar term for conjunctions, and
*موصلات*, which reads as electrical conductors.

**Developers see two kinds**, and users never learn the difference:

- an **MCP server** — someone else's service, reached over HTTP, contributing tools
- a **plugin** — Python in our container, contributing tools *plus* skills, prompt text,
  guards, UI events and workspace writes

"Apps" is already ours (the Apps tab), so it can't name this.

## Design decisions

**Shape**

1. **Most connectors are MCP, not plugins.** Google Workspace, Microsoft 365, Slack, Zoho,
   Odoo, PostHog, Canva, Figma, Notion, Linear, Stripe, GitHub and all four ad platforms
   ship official remote servers. **If an official server exists, use it.** Plugins are for
   what has none.

2. **"Has an MCP" is not the test — the test is *remote HTTP, the end user's own data,
   per-user auth*.** A vendor may ship more than one server and only one passes. Salla has
   `partners.mcp.salla.dev`, which builds apps and publishes to their App Store, and
   `mcp.salla.dev/mcp`, which serves a merchant's orders, products, customers and inventory
   over OAuth — the second is the connector, the first is a developer tool. Zid's server
   answers questions about their API docs, over stdio: a plugin despite having a server.

3. **A narrow server is not a dead end.** MCP is a transport, not a permission model. The
   official Google Ads server is read-only; the Ads API is not. When a vendor's server
   exposes less than their API, a plugin over the same REST API and the same credential
   gets the rest. Read via the connector, write via a plugin, one grant.

4. **A connector is an identity, not a source.** It is the credential and the consent the
   user grants once. Its tools may come from an MCP server, from plugin code, or from both
   at once — read Google Ads through the official server, write to it through plugin tools
   over the same grant, and the user sees one connector called Google Ads.

5. **Both MCP paths coexist; client-side is the default.** The existing `cycls.MCP` hands
   servers to the Anthropic connector, which runs the tool round-trip on their side — fewer
   hops, but Anthropic-only, with one deploy-time bearer for every user. Keeping it costs
   nothing; the harm today is that `.mcp()` silently does nothing on `providers/openai.py`.
   So `.mcp()` routes client-side once that exists, and `server_side=True` is the explicit
   opt-in for the latency win on `anthropic/*`.

6. **A plugin is a bundle of existing primitives, not an eighth primitive.** It composes
   tools, skills, prompt text and image deps, so `cycls.LLM().plugins(...)` keeps "seven
   primitives, three decorators" true. Distribution is pip — no manifest, no registry, the
   same move as "an example IS a public share" ([examples-gallery.md](examples-gallery.md)).
   Ship it **last**: connectors need only `auth=` on the existing `Tool` row, and until
   someone outside the team packages one, `Plugin` is ceremony over a module.

7. **The `Tool` row is the unit, and it exists.** `Tool(run, step, once, terminal, prompt)`
   shipped with `ask`/`suggest` ([tool-rows.md](tool-rows.md)). Connectors add `auth` and
   `writes`. One place owns a tool's contract and the loop reads facts, not prose.

8. **`ToolContext` is the keystone.** `dispatch` gains an optional second parameter,
   detected by signature so every existing `.on()` handler is untouched. Nothing per-user
   works until this lands; it is the first thing to build.

**Credentials**

9. **Auth is declared on the tool, never fetched inside it.** `auth=google("gmail.send")`
   is inspectable, so the exposure layer, the system prompt and the settings panel can
   enumerate what a tool needs without executing it. The token is injected into the context
   at call time and is never a tool argument, a tool result, or in the transcript.

10. **Not connected means retry, never a held connection.** The tool returns a reason plus a
   `{"type": "ui", "action": "connect"}` event, the turn ends, the user connects, the model
   calls again. This works with the `ask` channel exactly as it ships today; the
   defer/resume protocol in [ask-round-trip.md](ask-round-trip.md) would save one turn but
   is **not** a prerequisite.

11. **A credential belongs to an account, not a device.** Records live server-side in the
   volume, so connecting on web means connected on mobile, on the API, and in a scheduled
   run. Only the *flow* is per-client — OAuth finishes in a browser and its CSRF state is
   bound to the session that started it. The resulting grant is account-wide.

12. **Encrypted with no flag to forget.** Storing secrets in plaintext behind an opt-in
    encryption switch is a default that loses. Records are Fernet-encrypted with a key from
    deployment config, never a generated value — a key that changes on restart makes every
    stored grant undecryptable. Key ids are versioned so rotation re-auths rather than
    bricks.

13. **The connector declares its scope; resolution is user → workspace → deployment.**
    `scope="user"` for credentials that *are* a person (Gmail, Slack user token, LinkedIn):
    they follow the user into every workspace and can **never** be shared, because that is
    impersonation. They are the user's data in exactly the way chats are: stored under
    their own segment, resolved only for their own requests, and invisible to everyone
    else — a workspace admin can no more list a member's Gmail grant than read their chats. `scope="workspace"` for accounts a team shares (the Salla store, the
    PostHog project): a workspace admin connects it once and every member's agent uses it.
    `scope="either"` lets a workspace admin connect for the team or just for themselves, and
    a member only for themselves; the user's own grant wins at call time. The workspace, not the
    org, is the unit — an org can run several stores in several workspaces, files and the
    agent KV are already workspace-scoped, and the workspace ACL is the thing that actually
    governs who can use a shared credential. Most specific wins, the rule
    `skills.discover()` already applies when a user skill shadows a dev skill.

14. **Availability is three levels, each narrowing the one above.** The credential is a
    separate axis from any of them.

    | level | who | controls |
    |---|---|---|
    | org | org admin — `user.org_role` from the Clerk JWT | which connectors are **allowed** in the org at all |
    | workspace | owner/admin from the `.org` registry — the roles that gate delete-forever in the trash | which allowed connectors are **enabled** here, and the shared `scope="workspace"` credential |
    | user | anyone | their own `scope="user"` credential, and per-chat toggles |

    An org admin blocking LinkedIn removes it from every workspace's directory; a workspace
    admin disabling it removes it from that workspace. A solo account has no org layer. What
    a member sees on a card follows from the three:

    | state | the member sees |
    |---|---|
    | blocked by org, or disabled here | nothing |
    | enabled, `scope="user"` | Connect |
    | enabled, `scope="workspace"` + credential | connected · shared |
    | enabled, `scope="workspace"`, no credential | "Ask a workspace admin to connect this" |

15. **Some endpoints are per-user, not per-deployment.** Odoo is self-hosted so every
    customer is a different URL; some vendors' server URL *is itself* the credential. A
    connector record may therefore carry a user-supplied endpoint, encrypted like any other
    secret.

16. **Two kinds of credential, one record — and a generic escape hatch.** An API key the
    user pastes and an OAuth grant a flow obtains commit the same `{scope}/{id}` record.
    Beyond that, **a named key + a generic `http_request` tool + a `skills/<service>/SKILL.md`
    is a connector without writing one** — no code, no deploy, and no context cost for users
    who never touch that service. It is also the answer for social posting, where no major
    platform offers an API-key path and an aggregator's single key covers all of them.

17. **The generic key defaults to the agent never seeing it.** `http_request` runs in the
    server process and injects `Authorization` from the store, so the secret never enters
    the model, the transcript or the sandbox. A per-key opt-in exposes it as a bash env var
    for scripting — useful, the user's own credential, but a choice they make, because bash
    has network and the model can print the value.

**Safety**

18. **Gating is two-stage: an extensible pre-call hook, then monotonic guards.** A guard
    returns a denial reason or nothing and has *no allow result*, so listener order cannot
    turn a denial back into permission. This is the control for connectors, because the
    sandbox structurally is not: connector tools run in the server process outside bwrap,
    and the attack is not stealing the token — it is an injected prompt getting the model to
    *call* the tool. [sandbox-security.md](sandbox-security.md) needs a section saying so;
    its per-tenant-deploy escape hatch does not help when the injection and the mailbox
    belong to the same tenant.

19. **Confirmation is one preset, and `writes` is a declaration, not a classifier.** Three
    modes: *ask before acting*, *ask when risky* (default — outbound and irreversible only),
    *don't ask*. Asking a model to detect "potentially unsafe" is wrong in both directions;
    `writes=True` on the tool row is a fact the developer states, which is cheaper,
    predictable and auditable. The asking happens in chat through the **`ask` card** — one
    question component, not three.

20. **MCP servers are declared by the developer, never added by an end user.** A compromised
    server executes code and reads data with that user's access. Our list lives in the
    pickled function, which is already right — this decision exists so it stays that way.

**Context**

21. **A connector's tools do not enter the request until that user has it connected.**
    Schemas are the fixed cost — nine builtins already spend ~2,900 tokens on every request,
    ~320 each; forty Salla tools would be ~12,800. Exposure gated on connection state keeps
    the fixed cost proportional to what each user actually uses, which is why the number of
    supported connectors stops mattering.

22. **Connector tools are discovered, not injected.** The request carries one
    `find_tools(query)` tool plus a one-line index per *connector* — roughly 15 tokens each
    against ~320 for a schema, so twenty connectors cost 300 tokens instead of 6,400. The
    model calls `find_tools` and the matching schemas enter the request. Builtins are exempt:
    `bash`, `read`, `edit` and friends are used constantly and stay injected.

    **Discovery is sticky per chat.** Anthropic's cache breakpoint sits on the last tool, so
    appending schemas invalidates the cached prefix — paying that once per connector per
    chat is fine, once per turn is not. Once a connector's tools are in, they stay for the
    rest of the conversation. The index is built from the tool lists cached in decision 24,
    so discovery costs no network call of its own — and an `@` mention skips it entirely,
    injecting that connector's tools for the turn because the user already chose.

23. **A large tool result is a file to compute over, not text to read back.** Truncating a
    result loses data that has no other copy; spilling it to a file and telling the model to
    *read* it just delays the same explosion. We spill to the **workspace**, where bash
    already has `jq`, `rg` and python, so 4,812 orders become one `jq` and a five-row answer
    instead of a 2 MB read.

24. **Discovery is cached; connections are not pooled.** MCP is stateful — connect,
    `initialize`, `tools/list` — and `build_tools` runs before the first model call of every
    turn, so a naive client pays that handshake per server per turn. Pooling does not survive
    Cloud Run (the next turn may land on another instance, and connections are per-user), so
    instead the **tool list** is cached per server and scope with a TTL, and a connection is
    opened only when a tool is actually called. Turns that use no connector pay nothing.

25. **Spill lands in `.tmp/{chat_id}/`, and never sweeps on startup.** Per-workspace comes
    free from `workspace.root`; per-chat gives a lifecycle event — but a chat *delete* is
    now a tombstone that can be restored for 30 days ([trash.md](trash.md)), so the
    directory goes on **purge**, not delete, and a restored chat finds its spills where it
    left them. Day-to-day cleanup is the lazy sweep `trash.py` already uses: on any new
    spill, drop chat directories whose newest file is older than the TTL. No cron, no
    startup sweep — concurrent Cloud Run instances share the volume and would delete each
    other's live files.

    Two more consequences of the trash. `.tmp` is **exempt from the `rm` shim**: the shim
    routes workspace paths into the trash, and spilled output moved there would sit for 30
    days by design. And `.tmp` is *not* in the reserved list beside `.db`, `.database` and
    `.trash` — bash must read it and `read` must reach it.

## Connectors to build

Salla first; the rest is the shape of what follows. **Microsoft, not Google**: Microsoft 365
is the dominant productivity platform in Saudi organisations (~48% of enterprise globally vs
~27%, wider here) and has no CASA equivalent.

| | kind | setup gate |
|---|---|---|
| **Salla** | MCP | `mcp.salla.dev/mcp`, OAuth — **paid Salla plans only**. An App Store listing via the Partners platform is a separate distribution play, not a prerequisite |
| **Microsoft 365** | MCP | publisher verification. Mail, Calendar, Files, Excel, Teams in one consent |
| **PostHog, Canva, Slack, Notion, Linear, Figma** | MCP | none — hosted, OAuth, free |
| **Zoho / Odoo** | MCP | none, but per-user endpoints (15). Strong MENA SME presence |
| **Meta / TikTok / Google / Amazon Ads** | MCP + plugin | Meta is read+write, free in beta. Google's server reads only, so writes go through plugin tools on the Ads API (decision 4) — a developer token at **Basic** access already allows production writes, 15,000 ops/day; Standard lifts the cap |
| **Google Drive** | MCP | **the phase-1 proof**, `drivemcp.googleapis.com/mcp/v1`. Google's server requires `drive.file` **and** `drive.readonly` together — a `drive.file`-only token is refused on every tool, `create_file` included. `drive.readonly` is restricted: a test-mode client works for test users, publishing means CASA. **And the servers are in Developer Preview**: the client's project must be enrolled (`developers.google.com/workspace/preview`) and have `drivemcp.googleapis.com` enabled, or every tool answers *the caller does not have permission* with a perfectly valid token |
| **Gmail send** | MCP | *sensitive*: app review, weeks, no fee |
| **Gmail/Drive read, full Calendar** | MCP | **restricted**: CASA Tier 2, ~$540–1,000/yr, 4–12 weeks, **annual** |
| **Google Analytics** | plugin | no API-key path — OAuth or a service account; the Admin API and an edit scope are what writes need |
| **LinkedIn** | plugin, OAuth | no server; `w_member_social` + Marketing Developer Platform review |

## Setup

Four layers, each owned by a different person. Nothing below is a new primitive: connectors
ride on `cycls.LLM` and `cycls.Web`, where tools and auth already live. This is the surface
as shipped; the plugin half (`cycls.Key`, `auth=` and `writes=` on `.on()`) is phase 2.

**1. Declared in code** — by the developer, pickled with the agent:

```python
google = cycls.OAuth2("google", title="Google Drive",
    authorize="https://accounts.google.com/o/oauth2/v2/auth",
    token="https://oauth2.googleapis.com/token",
    client_id=cycls.env("GOOGLE_CLIENT_ID"), secret=cycls.env("GOOGLE_CLIENT_SECRET"),
    scopes=["https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive.readonly"],
    scope="user",                                   # or "workspace": one grant, every member
    extra={"access_type": "offline", "prompt": "consent"},
    description="Search, read and create files in your Drive", icon="https://…/drive_48dp.png",
    about="Connect Google Drive to search your documents, read file contents …",
    use_cases=[("Find and summarize", "Locate the right document and pull out what matters")],
    developer="Google", category="Productivity", website="https://drive.google.com",
    privacy="https://policies.google.com/privacy", terms="https://policies.google.com/terms",
    prompts=["ما آخر الملفات التي عدّلتها هذا الأسبوع؟", "Find the latest sales deck and summarize it"])

web = cycls.Web().auth(cycls.Clerk()).connectors(google)

llm = (cycls.LLM().model("anthropic/claude-sonnet-4-6")
    .mcp(cycls.MCP("https://drivemcp.googleapis.com/mcp/v1").name("drive").connector(google)))
```

A remote MCP server that follows the MCP authorization spec — Salla's, Notion's, Linear's — needs no
registered app at all: `cycls.OAuth2("salla", mcp="https://mcp.salla.dev/mcp", scopes=["offline_access"])`.
The connector reads the server's protected-resource and authorization-server metadata, registers a
public client once per org (dynamic client registration, PKCE, no secret, the client remembered in the
org's `.org` slot), passes the server URL as the resource, and refreshes at the endpoint the grant
remembers. The merchant signs in with their own account and approves; nobody at the vendor is involved.

A connector that takes a key instead of a login is `cycls.Key`, with the same directory fields and
the same scopes; the page shows a masked field and Save where OAuth shows Connect, and the key
lands in the same store. Its servers discover with the caller's key, so a person who hasn't
saved one sees no tools and the turn skips the server silently:

```python
posthog = cycls.Key("posthog", title="PostHog", hint="phx_…", scope="either", ...)
posthog_mcp = (cycls.MCP("https://mcp.posthog.com/mcp?features=insights,dashboards,flags,sql").name("posthog")
    .connector(posthog)
    .guidance("…the argument shapes and recipes the model should not have to discover…")
    .writes(lambda tool, args: args["command"].startswith("call flag-update")))
```

Two levers keep a one-tool server like PostHog's `exec` from burning a turn per schema: `.guidance()`
puts the shapes in the prompt whenever the server's tools are in the turn, so a question is one call;
`.writes()` classifies each call, so the tool defaults to *Ask* but only the calls that change
something stop for approval.

`cycls.env("NAME")` is a reference resolved at use — the value is never pickled. Everything
after `extra` is the directory's copy — the card's line and icon, the detail page's example
prompts and information table — declared once, in the deployment's languages. Declare the
server once too, `drive = cycls.MCP(url).name("drive").connector(google)` at module level, so the
directory lists its tools and prompt templates before any chat has run. Discovery
is anonymous, so the server's tools are known before anyone connects; each call fetches the
caller's bearer, refreshes a stale one, and with nothing stored returns the connect card and
tells the model to end its turn. A plugin tool reaches the same grant through
`ctx.secret("google")` on its `ToolContext`.

**2. Configured at deploy** — by the operator, in env: `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`, and `CYCLS_SECRET_KEY`, shipped the way provider keys already are.
Locally, `.providers.env` must be sourced — `load_dotenv()` reads only `.env`.

**3. Configured by an org admin** — the *Allowed in this organization* switch on a connector's
page (decision 14, org level): one row under the org's `.org` slot, `PATCH /connectors/{name}`.
A switched-off connector leaves members' directory, `authorize` refuses it, and its tools never
enter a turn. The workspace level — *enabled here* — is next. **A workspace admin** holds the
grant for any `scope="workspace"` connector (`authorize` and `disconnect` refuse a non-admin).

**4. Configured by the user** — in the directory: their own grant for a `scope="user"`
connector, from the card's detail page.

The developer writes none of the flow, the panel, or the not-connected handling.

## Runtime

The mechanics the decisions depend on, with what is built.

**The workspace is gcsfuse.** One large write is fine; many small files, or a stat per call,
is not — `TMPDIR` pointed at `.tmp/{chat}` turned every `pip` and `tar` temp file into a
network write and swelled the sweep, and was reverted. Spill and the credential store are
single writes; the sweep is throttled; a bash call touches nothing on the volume for scratch.
Anything future that walks or touches the volume per request goes on tmpfs or behind a
throttle.

**MCP tools dispatch through `handlers`** — built. `_TOOLS` is the static builtin registry;
discovered tools register on the `handlers` path `dispatch` already had, named
`{server}_{tool}`, with `tool_step` rendering `server · tool`.

**Discovery is cached; connections are not pooled** — built. The tool list is cached ten
minutes per url and token; a session is opened only when a tool is called.

**Discovered tools are derived, not stored** — phase 3, with `find_tools`. Until then a
connected server's tools are injected directly.

**`http_request` requires a connector, and the connector bounds the host** — phase 2. There
is no unbound form; that would be the SSRF `web_fetch` already guards against.

**Refresh is single-flight** — not yet. `bearer()` refreshes a stale grant and keeps a refresh
token the provider omits, but two concurrent turns can both refresh. Needed before a
provider that rotates refresh tokens on use.

**401 is `NotConnected`, not an error** — half. No grant → the connect card and a stop for
the model, built. A 401 answered mid-call is not yet caught; it surfaces as the tool's error.

**Calls are budgeted** — not yet. Needed with the guard layer.

## Storage and scoping

```
{org}/.db/{user}/                     chat log, shares            (existing)
{org}/ws/{ws}/.database/…             agent KV                    (existing, workspace-scoped)
{org}/.secrets/{user}/{name}          user grants — follow the user      (built)
{org}/.secrets/{user}/_pending/{n}    PKCE verifier + redirect, spent on callback
{workspace.root}/.connectors/{name}   workspace grants — admin-set        (built)
{workspace.root}/.tmp/{chat_id}/      spilled tool output                 (built)
```

Neither secret path needed a new mechanism — `workspace()` yields `{org}/{slot}/{user}` for
the first and `{workspace.root}` for the second. They are different slots on purpose: had
both used `.secrets`, the workspace path would be a prefix of every user's and one scan would
return them mixed. User grants sit at the org root so they are the same record from every
workspace, and under the user's own segment so no other user's request can reach them — the
`{user}` in the path is the isolation boundary, as it is for `.db/{user}/chat/`. A solo
account's root *is* its user id, so both resolve there too.

A record is `{access_token, refresh_token, expires_at}`, Fernet-encrypted under a key derived
from `CYCLS_SECRET_KEY`; one the current key cannot decrypt reads as absent, so rotation
means re-auth, never a crash. Resolution is user → workspace; env is not consulted for grants.

`.secrets` and `.connectors` get **both** guards `.db` has — the bwrap `--tmpfs` mask *and*
the `_resolve_path` rejection, in the tool and file-route path checks alike. `.tmp` gets
neither: bash must read it and `read` must reach it. It is hidden from listings, deleted for
real by the `rm` shim, refused by `canvas`, and removed on chat purge.

## The connect relay

Every agent is on its own subdomain and every provider requires an **exact** registered
redirect URI, so registering one per agent per provider does not scale — some providers cap
the list outright. One URI is registered instead, `https://connect.cycls.ai/callback`, and it
relays:

1. The user clicks Connect on `super.cycls.ai`. The agent mints a `state`: connector name,
   originating agent, user, org, nonce, short expiry — signed with a shared key.
2. The browser goes to the provider with `redirect_uri=https://connect.cycls.ai/callback`
   and that `state`.
3. The user approves. The provider redirects to the relay with `code` and `state`.
4. The relay verifies the signature, reads the originating agent out of the state, checks it
   against the registry of deployed agent origins, and **redirects the browser back** to
   `https://super.cycls.ai/connectors/callback?code=…&state=…`.
5. The agent exchanges the code — it holds the client secret and the PKCE verifier — and
   commits the record.

**The relay never sees a token.** It forwards an authorization code, which is useless without
the client secret and the verifier, both of which stay at the agent. That keeps the blast
radius of the one shared component near zero, and it means the relay stores nothing.

Three things it must get right, because a redirector that gets them wrong is an open redirect
with OAuth attached: the state is signed and short-lived, the target origin is checked against
a registry rather than a wildcard (customers may bring their own domains), and PKCE is used
wherever the provider supports it so an intercepted code cannot be exchanged.

It is a stateless service with one route and one secret — a `@cycls.function` would do.

## Context budget

Two costs, and they need different answers. **Schemas** are fixed — paid on every request
whether used or not. Nine builtins already spend ~2,900 tokens, ~320 each; twenty connectors
mapped naively would add tens of thousands. Decisions 21 and 22 handle it: a connector nobody
connected contributes nothing, and a connected one contributes ~15 tokens of index until the
model asks for it. **Results** are variable and unbounded — one order dump can exceed the
whole tool block — and that is what the rest of this section is about.

Three layers. We have the third; the gaps are the first generically and the second entirely.

| layer | when | LLM? | today |
|---|---|---|---|
| cap at ingest | as each result returns | no | builtins only (`bash` 30k, `web_fetch` 20k) |
| prune old results | mid-conversation | no | only inside `compact()` |
| summarize | near the window | yes | ✅ `compact()` |

**Cap → spill.** Above ~20–30 KB, write the full result to `.tmp/{chat_id}/<name>.json`
(extension inferred from content, so `jq` works) and replace the model-facing result with
size, record count, the **first two records**, and *"analyse it with bash — don't read the
whole file."* The preview is load-bearing: without a schema sample the model reads the file
just to learn its shape. Skip `read` itself, or it spills its own output and reads it again.
A spill failure must never turn a successful call into an error. This also replaces `bash`'s
middle-truncation, which currently loses the tail.

**Cleanup.** Chat delete removes `.tmp/{chat_id}/`; a throttled TTL sweep on write (marker
older than ~1h → drop chat dirs whose newest file is older than 24–48h) catches abandoned
chats; a total-size cap with LRU bounds a chat that pulls a hundred dumps. The TTL must
outlive a working session because the path lives in the durable transcript; a missing file
degrades to a re-fetch.

**Prune.** `microcompact` already blanks tool results model-free — it just fires too late.
Run it on results older than K turns against a token budget, before the window is near.

**Guards.** `canvas` refuses a `.tmp` path, and deliverables are written outside it: opening
a file the sweeper may delete tonight is a bug generator.

## UI

**Where — one directory modal.** Connectors live in a dedicated modal, not a settings tab:
a left rail with **Connectors** now and room for **Plugins** and **Skills** later, so every
kind of capability is browsed and managed in one place (the two later rails sit greyed with
*Soon*). It opens from *Manage connectors →* in the `+` menu and from a row in Settings. Two tabs:
**Discover** — everything the deployment declares that the org allows, minus what is already
connected — and **Yours** — what is connected, personal and shared. A search box and a
two-column grid of cards; a category filter when the catalog is big enough to need one.

The catalog is the developer's declaration (decision 20), so there is no *Add* for members;
whether an org admin may add a server by URL is a later question, not a phase-1 one.

**The card.** Icon, name, one line of description, and **+** — a green dot once connected.
Tapping opens the detail page. A verified mark for first-party servers comes with the relay.

**The detail page — one column, one button.** Logo, title, category, one line, and the primary
button on the right; that is the header. Then the long description. Then **Try asking** — one
gradient panel, two to four rows, each the connector's `@` pill followed by the prompt and an
arrow —

> **@Salla** أي منتج ربحيته أعلى هذا الربع؟ →
> **@Salla** كم طلب لم يُشحن بعد؟ اعرضهم مع عمر كل طلب →

Tapping one starts a new chat with the pill already set and the text filled, through the
same `@` mechanism as the composer (today: the text is filled and the composer focused). This
is how a user learns what a connector is *for*
without reading a tool list, and it is the starter-prompt pattern the empty-chat suggestions
and the examples gallery already use, scoped to one connector. Then **Use cases** — a title and
one line each — then **Tools**: every action the server lists, grouped read-only and write,
visible before connecting, with the Allow / Ask / Never controls once connected; then
**Prompts**, the server's own templates when it offers any; then an **Information** table:
Capabilities (*Read* / *Read, Write*, from the tools), Developer, Category, Website,
Privacy policy, Terms, Docs — the links as bare outbound arrows, no URL text. Last, a plain-language disclosure in the user's
language: what the agent may share with this connector, that connected tools carry risk, and
that it can be disconnected at any time.

The primary button is where scope lives, and it names the place. In a personal account or a
personal workspace there is only **Connect** — the grant follows the person everywhere. In a team
workspace an admin sees **Connect for General** (the workspace's own name) with **Connect just
for me** underneath; a member sees **Connect** and a line saying an admin can share one. The
server refuses a workspace grant anywhere that isn't a team workspace. The page then shows one
of these states:

| state | the page shows |
|---|---|
| not connected | the button above |
| connected, personal | green dot · *Connected just for you* · Disconnect |
| connected, workspace | green dot · *Connected for General* · Disconnect for admins, read-only for members |
| needs an admin | grey · *A workspace admin can connect one for everyone here* |
| revoked / refresh failed | amber · **Reconnect** |
| API key | a masked field and Save, in place of Connect |
| per-user endpoint | a URL field above the key |

The first four rows and the key field are built. *Reconnect* comes with refresh-failure
handling; the per-user endpoint field is not built.

Org admins get an **Allowed in this organization** switch on the page (decision 14 — built);
workspace admins get an **Enabled in this workspace** toggle under it (next). Blocked and disabled connectors are
hidden from members' Discover entirely — an admin sees them greyed with the toggle off.

**The connect flow.** Connect opens the provider in a **new tab** — the chat stays where it
is. On approval the provider returns to the agent's callback, which stores the grant, shows
*Connected* and closes itself; the original tab hears it through a window event, the same
pattern `followupschange` and `askchange` already use, and the card flips to green with a
toast. On mobile the system browser plays the new tab and the app refreshes on foreground.

**The composer — three layers of state.** The directory is *connected or not*
(durable). The **`+`** menu is *active in this chat* (per chat): the `AttachMenu` paperclip
becomes `+`, keeps Upload file and Browse files, then a divider, then one row per connected
connector — icon, name, a green dot — and *Manage connectors →*. The per-chat toggle on each
row lands with `find_tools` (phase 3), when a row that is off can actually keep the tools out
of the turn.
Unconnected connectors are not in the menu. And **`@`** is *invoked in this message*
(per message), below.

**`@` mentions — built.** The existing picker — `onMentionSearch` returning `{name, path}` — gains
connectors alongside files: every connector that is **active** (connected, enabled, and on
for this chat), with `kind: "connector"` and its icon, ranked above files when the query
matches a name. Picking a file works as today: the path is inserted as text and the model
reads it. Picking a connector is different, because a connector is a *scope*, not content:
the `@` token is removed from the text and a **small pill** — icon and name, with an × —
appears in the row above the textarea where attachments already sit. The message is sent
with a structured `connectors: ["salla"]` beside `attachments`, and the pills clear on send
like attachments do.

On the server a mentioned connector is **user-driven discovery**: one line — `[Using: Salla]` —
is appended to the user message so the intent is in the transcript and survives replay. Its
tools are injected for that turn without a `find_tools` round-trip (decision 22) once
`find_tools` exists; today every allowed connector's tools are already in the turn.
A connector typed as `@salla` by hand, without picking, is plain text: the model sees it,
calls the tool, and an unconnected one produces the connect card as usual.

**The pill is in the line** — built. Picking from the `@` menu inserts `@Google Drive ` at the caret and
the backdrop paints that token as a pill, the same trick file mentions use; there is no row of chips above
the composer. Deleting the text is how the mention is removed, and on send only the connectors whose token
is still in the line are attached. Nothing but colour may change in the backdrop: padding or weight would
slide the painted text off the real caret.

**In the transcript.** A connector call is a step row like any other tool's, with the connector's
logo standing where the dot goes and shimmering while the call runs — built. There is no check on a
row that has a face: the shimmer stopping is what says it finished, and the logo turning red with
*Failed* beside it is what says it didn't. The row opens on a chevron into **Request** (the arguments,
formatted) and **Response** (the result, cut to a few KB) — so the payload is one tap away instead of
dumped into the chat. The model still gets the whole result; when spilled, it reads it as a file in
`.tmp/`. The step line itself carries only the `context` sentence a server asks the model for, never
raw arguments.

**A custom tool can have the same row** — built. `.on(name, fn, label=…, icon="https://…", details=True)`:
`icon` is an image where a connector's logo goes, `details=True` opens the row into Request and Response
and sends the result there instead of into the chat, the model still receiving all of it. Without
`details` nothing changes — a custom tool's return value still streams to the body, which is what a
table or a card needs. The icon is a url the page loads, so it wants to be a small asset on a host you
control; it will not render in an offline share.

The same row serves the builtins, each with its own face: a globe for web search, which opens into the
pages it returned (favicon, title, domain) with the count on the row; the fetched page's own favicon
for a fetch; the file's tinted extension tile — the one the canvas and the file cards use — for a read
or a write; a terminal, a cylinder and the Cycls star for bash, the database and skills. Glyphs are
stroked at 1. A group of rows summarises as *Used {connector}* when every row is a connector's, and as
*N steps — searched the web · fetched pages* otherwise.

**Mid-chat, two cards.** Not connected: *"This needs Salla."* with
**Connect Salla** and *Not now*; Connect runs the flow above and the user re-sends. Confirm
(`writes=True` under the *ask when risky* preset): the action in words, not JSON — *"Refund
order #91823 — 340 SAR to ahmed@…?"* — with **Refund** and *Cancel*, the label coming from
the same `tool_step` text as the step line. One question component across web and mobile
([mention-picker-cache.md](mention-picker-cache.md) is what a second copy costs); defined as
a protocol — a question with options resolving to an answer — not a React component.

**Permissions — on the page, once connected.** *Tool permissions* lists the server's tools in
two groups, *read-only* and *write and delete* — the server's `readOnlyHint` when it gives one,
the tool's name otherwise — each row *Allow / Ask / Never*, each group a preset. Defaults: reads
run, writes ask. *Never* takes the tool out of the turn; *Ask* returns the confirm card instead
of running and the model ends its turn. Only choices that differ from the default are stored, so a
tool nobody has touched keeps following the switch below. Stored per user beside their grants.

**Approve is bound to the call, not the tool.** The card carries a key — the tool name plus a hash of
its arguments — and **Approve** sends *Approved: drive · create_file* as the next message with that key
in `approvals`. The same tool called with different arguments in the same turn asks again, which the
bare tool name did not do. Consent lives in the transcript and a replay cannot reuse it. The card also
carries **Always allow**, which sets that one tool to *Allow* through `PUT /connectors/{name}/tools/{tool}`
and then runs the call — one tap instead of a trip to the page.

**The composer switch — Auto or Manual, per person, per device.** A pill in the composer's action row,
shown only where the deployment has connectors. *Auto* (the default) lets a write run and pauses only
for the destructive: the server's `destructiveHint`, a name that reads delete / remove / trash / cancel /
refund, or a destructive command on a one-tool server. *Manual* asks before every write. It rides the
request as `auto: false` (absent means Auto), reaches the gate through `ToolContext.auto`, and sits under
the page's per-tool choices — a tool explicitly set to *Ask* asks in both modes, one set to *Allow* runs
in both. Every gated call writes an `approval` audit line saying which of *approved*, *auto* or *asked*
it took, with the user, the chat and the connector.

**Masking.** Keys and endpoints render masked with a reveal toggle. Presentation only —
decision 12 owns storage.

## Approvals

One schema for every tool the model can call, connector or builtin. Four layers resolve in order;
the first that answers, wins.

| # | layer | who sets it | says |
|---|---|---|---|
| 1 | **org policy** | org admin | a connector is switched off: its tools are not in the turn at all, for anyone in the org |
| 2 | **per-tool choice** | the person, on the connector's page | *Never* (out of the turn), *Allow* (runs), *Ask* (card, always) |
| 3 | **composer mode** | the person, per device | *Auto* (default): writes run, destructive still asks. *Manual*: every write asks |
| 4 | **the call's own risk** | the tool and the server | read → runs; write → follows layer 3; destructive → asks in both modes |

Only a choice that differs from the class default is stored at layer 2, so touching one tool never
silently pins the rest — an untouched tool keeps following the composer switch.

**What a tool's class is.** Read or write comes from the server's `readOnlyHint` when it gives one,
else the tool's name (`create|update|delete|send|post|upload|share|…`). Destructive comes from
`destructiveHint`, else a name that reads *delete, remove, trash, cancel, refund*. A one-tool server
that funnels everything through a single call (PostHog's `exec`) classifies per call with `.writes()`,
and its destructive test reads the command itself, so `call flag-update` runs under Auto and
`call flag-delete` stops.

**The builtins take the same schema** — built, through the same gate in `dispatch`. Their classes:

**A delete is not destructive when the trash catches it.** The sandbox shims `rm` and `rmdir` to move
workspace targets into the trash (30 days, restorable), and `edit`'s overwrite trashes the old content
first — so Auto lets those run and the card would have been asking about a move. What stays destructive
is what has no trash behind it: `database delete` (keys go, a trailing slash takes a namespace),
`git reset --hard`, `git clean -fdx`, `git push --force`, and `shred` / `dd` / `truncate` / `mkfs`.

| tool | class | Auto | Manual |
|---|---|---|---|
| `read`, `web_search`, `web_fetch`, `skill` | read | runs | runs |
| `edit`, `database` (write), `build_app` | write | runs | asks |
| `bash` | per call, like a one-tool server | runs; a command with no trash behind it asks | asks unless the command is a plain read (`ls`, `cat`, `grep`, `find`, …) |
| `canvas`, `ask`, `suggest` | how the agent talks to the person | never asks | never asks |

The builtins have no connector page, so layer 2 reaches them through the card: *Always allow* writes
`PUT /tools/{tool}` into the same per-user store under the reserved name `_builtin`, and the loop reads
those choices once a turn onto `ToolContext.modes`. A Settings list that shows and unsets them is the
remaining half.

**A card ends the turn.** The ack tells the model to stop, and a model that ignores it used to call the
same tool again and get a second card, and a third — a loop the person could not answer out of. The loop
now treats a `confirm` or `connect` card the way it treats `ask`: the turn ends there, and nothing else
runs until the person answers.

**The approval never appears as a message.** Approve sends *Approved: Bash · …* so the model learns the
person said yes, but the turn is stored `internal`: the chat renders no bubble for it, live or on reload,
and it never becomes the chat's title. What the person sees is the card going away and the work carrying on.

**The ack asks for the call back verbatim.** Binding the approval to the arguments has a cost: a model
that rewrites its own command between the ask and the approval gets a second card, correctly but
uselessly — Kimi K3 does exactly that. The ack now says the approval covers *this* call and that changed
arguments ask again. The complete fix is for Approve to resume the pending call server-side rather than
ask the model to reissue it; that wants the run to outlive the request (docs/notes/runs.md).

**The approval itself.** The card carries `tool` plus a hash of the arguments, narration fields
(`description`, `context`, `reason`) excluded — the model rewrites those on a retry, and an approval that
a reworded sentence invalidates is an approval that asks forever; **Approve** returns that
key in `approvals` on the next message. It authorises that call with those arguments, once, in that turn:
a second call with different arguments asks again, a replay of the transcript cannot reuse it, and no
key ever unlocks a whole tool. **Always allow** is the deliberate escape — it writes *Allow* at layer 2
and runs the call.

**Roles.**

| role | can |
|---|---|
| org admin | switch a connector off for the whole org (layer 1); everything a member can, for themselves |
| workspace admin | connect and disconnect a connector *for the team workspace*, so members act on the shared grant |
| member | connect for themselves, set their own per-tool choices and their own composer mode; never another person's |

Per-tool choices and the composer mode are **per person, never shared** — a team grant shares the
credential, not the consent. An admin cannot pre-approve a write on a member's behalf, and a member
cannot loosen what an org admin switched off.

**Every gated call writes an audit line** — `approval`, with the user, chat, tool, connector and which
of *approved*, *auto* or *asked* it took. A read that a classifier waved through is not logged twice;
its `tool_call` line already exists.

## Audit

Every tool call was already logged with its caller. Connectors add three things.

**`tool_call` carries `connector`, `credential_scope` and `tool_use_id`** — built. A call
through a connector names the grant it acted with and its scope, so a shared credential is
attributable; the `tool_use_id` joins the line to the `tool_use` block in the transcript,
which is where the arguments live. That is the right split: identity and timing in the log,
what was sent in the transcript, and user data copied nowhere new.

**A `connector` event on connect and disconnect** — built, from the callback and disconnect
routes: action, connector, scope, and who.

**An `approval` event on granted and declined** — waits for the guard layer; there is nothing
to approve yet. The client's `track("ask_answered", …)` is product analytics, not an audit
trail, and will not stand in for it.

**A credential is never a log field.** `log()` splats `**fields` straight to JSON.

## Phase 1 — a first connector, end to end

Proven with Google Drive: the server lists its tools anonymously, and it is a `scope="user"`
connector, so it exercises the isolation path Salla would not have. One finding from the live
run: Google's MCP needs `drive.readonly` alongside `drive.file` — so the no-review scope was
not enough after all, and CASA is a production question for Drive. A second: Google's MCP
servers are Developer Preview — a valid, correctly scoped token is refused until the client's
project is enrolled. Three gates Microsoft has none of. Salla is next, on the same machinery.

| # | item | state |
|---|---|---|
| 1 | `ToolContext` — the second handler argument | done |
| 2 | the credential store, both slots, both guards | done |
| 3 | `cycls.OAuth2`, `Web().connectors()`, the three routes | done |
| 4 | the MCP client, cached discovery, connect on call | done, live against DeepWiki |
| 5 | the directory | done — its own modal: Discover / Yours, search, cards, the detail page with example prompts and the information table; opens from `+` and from Settings |
| 6 | `NotConnected` → card + stop | done |
| 7 | spill to `.tmp/{chat_id}/`, shim exemption, purge | done |
| 8 | audit: `tool_call` fields and the `connector` event | done |
| 9 | the org admin's switch (decision 14, org level) | done — `allowed` / `blocked` audit rows |
| 10 | the page — tools, prompts, use cases, information — and `@` pills | done |
| 11 | `cycls.Key` — the key half, proven with PostHog | done |
| 12 | MCP authorization — discovery and dynamic client registration, proven with Salla | done |

The live run happened on the deployed agent: connect, grant, bearer, audit all worked; only
Google's preview gate remains (application submitted 2026-09-06). Phase 2 is the relay, the
plugin half (`cycls.Key`, `auth=` on `.on()`, `http_request`), single-flight refresh, and a
second connector. Phase 3 is `find_tools`. `Plugin` is phase 4, if anyone asks for it.

## Open questions

- **Does the platform register the provider apps, or does each deployment?** The relay works
  either way. A platform-owned app means one Google verification for everyone
  and instant setup for a developer; a deployment-owned one means the consent screen carries
  the customer's brand and the quota is theirs. Supporting both is easy; picking the default
  is the decision.
- **Does the customer need an activity view?** Cloud Logging is ours, not theirs. A merchant
  asking what the agent did with their store needs a view built from the workspace, not from
  logs. Real, and not this pass.
- **Does Google's own server still trigger CASA?** The consent still carries the scopes, so
  probably — but that is inference, and it is worth weeks and an annual fee.

## Later (not this pass)

- Lifecycle hooks beyond the guard (`on_turn_start` returning prompt/message injections).
- Re-homing the built-ins: with `on_turn_start`, the skills catalog and AGENT.md fence stop
  being welded into `_run`. That is the test of whether the hook set is the right size.
- The `ask` defer/resume channel — saves a turn on connect and confirm, once three callers
  justify the `normalize` carve-out.
- An org admin adding a server by URL — admin-only, never members — if a customer needs a
  connector the deployment did not declare.
- Plugins and Skills as further rails in the directory modal.
- A credential API for scheduled functions, if a Cron ever needs a workspace's grant.
- Per-user placeholders (`{{USER_ID}}`, `{{CHAT_ID}}`) in MCP headers.
- `cycls.Dict` / `cycls.Queue`.

## Tests

- **Context:** `ToolContext` reaches a two-arg handler; a one-arg handler is unchanged;
  `NotConnected` yields both the tool_result and the ui event.
- **Isolation:** a workspace admin's request cannot resolve, list, or use another member's
  user-scoped credential; two users in one workspace each see only their own Gmail.
- **Directory:** an example prompt opens a new chat with the pill set and the text filled;
  *Capabilities* reads *Write* iff some tool row has `writes=True`; an MCP server's
  `prompts/list` populates examples when the developer declares none.
- **Availability:** an org-level block hides a connector from every workspace's directory
  and from `build_tools`; a workspace disable hides it from that workspace only; a solo
  account has no org layer and both toggles collapse to the owner's.
- **Scoping:** user beats workspace beats deployment; a `scope="user"` connector refuses a
  workspace-level write; the same user credential resolves from two workspaces; two
  workspaces hold two different Salla grants; a disabled connector is absent from
  `build_tools` entirely.
- **Secrets:** a record round-trips encrypted; the sandbox cannot reach `.secrets` by path
  *or* by bash (both guards, mirroring `tests/app/sandbox_test.py`); env overrides a stored
  value; a rotated key id re-auths instead of throwing.
- **Guards:** a denial survives any listener order; a `writes=True` tool is denied in an
  unattended run; `canvas` refuses a `.tmp` path.
- **Spill:** over-threshold results land in `.tmp/{chat_id}/` with a preview and are absent
  from `_walk_catalog`; a spill failure leaves the original result and no error; `read` is
  never spilled; chat delete leaves the directory and purge removes it; a restored chat still
  finds its spills; the `rm` shim passes `.tmp` paths through to the real `rm`; the TTL
  sweep spares recent files.
- **Discovery:** connector schemas are absent from the first request and present after
  `find_tools` matches them; an `@` mention injects them without a `find_tools` call and
  appends `[Using: …]` to the stored user message; the picker lists only active connectors; they persist for the rest of the chat but not into a new one;
  builtins are never behind discovery; the index lists connected connectors only.
- **Audit:** a connector call logs `connector`, `credential_scope` and a `tool_use_id` that
  matches the transcript block; connect, disconnect and approval each emit their event; a
  declined confirmation is logged, not silently dropped; no log line ever contains a
  credential.
- **Runtime:** the discovered set rebuilds from the transcript alone; two concurrent
  refreshes produce one provider call and one record; a 401 surfaces as the connect card;
  `http_request` refuses a URL outside its connector's host and refuses to run without one;
  a per-turn budget stops the N+1th call with a clear result.
- **MCP:** client-side tools appear in `build_tools` on **both** providers; `.allow()`
  filters them; a per-user token resolves per request, not at deploy.
