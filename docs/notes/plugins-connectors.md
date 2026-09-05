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
    `scope="either"` for metered keys, where the user's own wins. The workspace, not the
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
| **Google `drive.file`** | MCP | none — not a restricted scope, no CASA |
| **Gmail send** | MCP | *sensitive*: app review, weeks, no fee |
| **Gmail/Drive read, full Calendar** | MCP | **restricted**: CASA Tier 2, ~$540–1,000/yr, 4–12 weeks, **annual** |
| **Google Analytics** | plugin | no API-key path — OAuth or a service account; the Admin API and an edit scope are what writes need |
| **LinkedIn** | plugin, OAuth | no server; `w_member_social` + Marketing Developer Platform review |

## Setup

Four layers, each owned by a different person. Nothing below is a new primitive: connectors
ride on `cycls.LLM` where tools, skills and MCP already live.

**1. Declared in code** — by the developer, pickled with the agent. This is *what exists*:
which connectors, how each authenticates, which tools need which grant, and what is a write.

```python
# An OAuth connector. Endpoints and scopes are the provider's; the client id and
# secret are references, resolved from env at runtime — never pickled with the value.
salla = cycls.OAuth2("salla",
    authorize="https://accounts.salla.sa/oauth2/auth",
    token="https://accounts.salla.sa/oauth2/token",
    client_id=cycls.env("SALLA_CLIENT_ID"), secret=cycls.env("SALLA_CLIENT_SECRET"),
    scope="workspace",                          # one store per workspace (decision 13)
    # What the directory shows. An MCP server supplies name, description and version
    # from `initialize`, and its `prompts/list` seeds the examples; a plugin declares
    # them here. Either way the developer may override, and examples are theirs to write.
    description="طلبات متجرك ومنتجاته وعملاؤه",
    examples=["أي منتج ربحيته أعلى هذا الربع؟",
              "كم طلب لم يُشحن بعد؟ اعرضهم مع عمر كل طلب"],
    category="commerce")

# An API-key connector. No flow — a masked field in the directory, encrypted at rest.
posthog_key = cycls.Key("posthog", label="PostHog", scope="workspace")

llm = (cycls.LLM()
    .model("anthropic/claude-sonnet-4-6")
    .allowed_tools(["Bash", "Editor", "WebSearch", "Ask"])
    # MCP connectors. A server that speaks OAuth 2.1 describes its own auth — nothing
    # to declare. `.connector()` binds one to a grant declared above instead.
    .mcp(cycls.MCP("https://mcp.posthog.com/mcp"))
    .mcp(cycls.MCP("https://mcp.canva.com/mcp"))
    # Plugin tools. `auth=` names the grant and scope; `writes=True` is what the
    # permission preset and the guard key on.
    .tools(SALLA_TOOLS)
    .on("salla_orders", salla_orders, auth=salla("orders.read"))
    .on("salla_refund", salla_refund, auth=salla("orders.write"), writes=True)
    .key(posthog_key)
    .skills("skills/"))
```

```python
async def salla_orders(args, ctx):
    token = await ctx.token(salla)          # refreshed; raises NotConnected
    ...
```

That is the whole developer surface for phase 1 — `auth=` and `writes=` on `.on()`, `.key()`
on the builder, and `cycls.OAuth2` / `cycls.Key` to declare a grant. `Plugin` (decision 6)
bundles the same things later; it adds nothing a connector needs.

**2. Configured at deploy** — by the operator, in env. Client ids, client secrets, and the
encryption key (`CYCLS_SECRET_KEY`), shipped the way provider keys already are:
`Image().copy(".providers.env", ".env")`. The relay is the platform's; a developer never
touches it, and the redirect URI is implicit.

**3. Configured by a workspace admin** — in the directory. Which connectors are enabled in
this workspace (decision 14), and the credential for any `scope="workspace"` connector. An
admin connects the team's Salla store once; every member's agent uses it.

**4. Configured by the user** — in the directory. Their own credential for any `scope="user"`
or `scope="either"` connector: Connect for OAuth, paste for a key, a URL for a per-user
endpoint (decision 15).

The developer writes none of the connect flow, the panel, or the not-connected handling.
Declaring a connector is what makes it appear in the directory; the loop does the rest.

## Runtime

The mechanics the decisions above depend on but do not state.

**Discovered tools are derived, not stored.** "Sticky per chat" (22) needs the discovered set
back at the top of the next `_run`, and `tools_list` is a local. Rather than a new key, the
set is rebuilt from the transcript: every `find_tools` block in the log names its matches,
and the tool lists are cached (24), so the rebuild is deterministic and costs nothing. It is
the same rule the rest of the harness runs on — model-visible means logged.

**MCP tools dispatch through `handlers`.** `_TOOLS` is the static builtin registry; MCP tools
are dynamic and per-user, so they register on the `handlers` path `dispatch` already has,
named `{server}_{tool}`, with `tool_step` rendering `Server · tool` — the label the
server-side path already uses.

**`http_request` requires a connector, and the connector bounds the host.** The tool takes an
explicit `connector` argument; the URL must match that connector's declared base host, and
`_is_public_host` still applies. There is no unbound form — that would be a server-side fetch
to any URL the model chooses, which is the SSRF `web_fetch` already guards against.

**Refresh is single-flight.** Queued messages can run two turns close together; both see an
expired token and both refresh, and providers that rotate refresh tokens invalidate the old
one on use — the second refresh fails and clobbers the first. One refresh per (user,
connector) at a time, and the record write is compare-and-swap on `obtained_at`.

**401 is `NotConnected`, not an error.** A connector call answered 401 (or a 403 carrying
`invalid_grant`) refreshes once; if that fails the record is marked stale and the tool raises
`NotConnected`, so the user gets the connect card rather than the model reasoning around a
raw error.

**Calls are budgeted.** A per-connector cap per turn in the guard layer, and an org-wide cap
for `scope="workspace"` credentials — one user's runaway loop must not burn the company's quota.
A provider 429 becomes a tool_result with the retry-after, not an error the model retries in
a tight loop.

## Storage and scoping

```
{org}/.db/{user}/           chat log, shares            (existing)
{org}/ws/{ws}/.database/…   agent KV                    (existing, workspace-scoped)
{org}/.secrets/{user}/             user credentials — follow the user     (new)
{org}/.org/connectors/{name}       org policy: allowed or blocked           (new)
{workspace.root}/.connectors/      workspace credentials — admin-set        (new)
{workspace.root}/.tmp/{chat_id}/   spilled tool output                      (new)
```

Neither path needs a new mechanism — `workspace()` already yields `{org}/{slot}/{user}` for
the first and `{workspace.root}` is the second. They are different slots on purpose: had
both used `.secrets`, the workspace path would be a prefix of every user's and one scan
would return them mixed. User credentials sit at the org root so they are the same record
from every workspace, and under the user's own segment so nobody else's request can reach
them — the `{user}` in the path is the isolation boundary, as it is for `.db/{user}/chat/`.
No route resolves another user's segment; the panel lists only the requester's own.
Workspace credentials sit under the workspace, beside its files, its KV and its trash. A solo account's root *is* its user id, so both resolve there too. Records are
`{kind: "key"|"grant"|"endpoint", payload, scopes, obtained_at}`. Deployment env wins over
stored values, so a per-run override always applies.

`.secrets` and `.connectors` get **both** guards `.db` has — the bwrap `--tmpfs` mask *and* the
`_resolve_path` rejection — because [sandbox-security.md](sandbox-security.md) is explicit
that the tmpfs is defence in depth on top of the path check.

`.tmp` gets **neither**: bash must read it and `read` must reach it. It is a normal directory
that is merely hidden — `_walk_catalog` already skips dot-prefixed entries.

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
kind of capability is browsed and managed in one place. It opens from *Manage connectors →*
in the `+` menu, from a row in Settings, and from any connect card in chat. Two tabs:
**Discover** — everything the deployment declares that the org allows, minus what is already
connected — and **Yours** — what is connected, personal and shared. A search box, a category
filter, and a two-column grid of cards.

The catalog is the developer's declaration (decision 20), so there is no *Add* for members;
whether an org admin may add a server by URL is a later question, not a phase-1 one.

**The card.** Icon, name, a verified mark for first-party servers, one line of description,
and **+**. Tapping opens the detail page.

**The detail page — one column, one button.** Icon, name, one line, and the primary button
on the right; that is the whole header. Then a **hero of example prompts**: two to four, each
rendered as the connector's `@` pill followed by the prompt and an arrow —

> **@Salla** أي منتج ربحيته أعلى هذا الربع؟ →
> **@Salla** كم طلب لم يُشحن بعد؟ اعرضهم مع عمر كل طلب →

Tapping one starts a new chat with the pill already set and the text filled, through the
same `@` mechanism as the composer. This is how a user learns what a connector is *for*
without reading a tool list, and it is the starter-prompt pattern the empty-chat suggestions
and the examples gallery already use, scoped to one connector. Then a description paragraph,
then **Capabilities** — *Read* or *Read, Write*, derived from whether any tool row carries
`writes=True`, so the risk is visible before the tool names are — then the tool chips, then
an **Information** table: Developer, Category, Website, Version, Privacy policy, Terms. Last,
a plain-language disclosure in the user's language: what the agent may share with this
connector, that connected tools carry risk, and that it can be disconnected at any time.

The primary button is where scope lives: a single-scope connector shows **Connect** or
**Connect for this workspace**; a `scope="either"` one shows a split button — **Connect ▾**
with *for me* and *for this workspace* — and only admins see the second option. The page then
shows one of these states:

| state | the page shows |
|---|---|
| not connected | the button above |
| connected, personal | green dot · *Connected as ahmed@…* · Disconnect |
| connected, workspace | green dot · *Connected by Sara · shared with this workspace* · Disconnect for admins, read-only for members |
| needs an admin | grey · *Ask a workspace admin to connect this* |
| revoked / refresh failed | amber · **Reconnect** |
| API key | a masked field and Save, in place of Connect |
| per-user endpoint | a URL field above the key |

Workspace admins additionally get an **Enabled in this workspace** toggle; org admins get an
**Allowed in this org** toggle above it (decision 14). Blocked and disabled connectors are
hidden from members' Discover entirely — an admin sees them greyed with the toggle off.

**The connect flow.** Connect opens the provider in a **new tab** — the chat stays where it
is. On approval the provider returns to the agent's callback, which stores the grant, shows
*Connected* and closes itself; the original tab hears it through a window event, the same
pattern `followupschange` and `askchange` already use, and the card flips to green with a
toast. On mobile the system browser plays the new tab and the app refreshes on foreground.

**The composer — three layers of state.** The directory is *connected or not*
(durable). The **`+`** menu is *active in this chat* (per chat): the `AttachMenu` paperclip
becomes `+`, keeps Upload file and Browse files, then a divider, then one row per connected
connector — icon, name, a per-chat toggle on by default — and *Manage connectors →*.
Unconnected connectors are not in the menu. And **`@`** is *invoked in this message*
(per message), below.

**`@` mentions.** The existing picker — `onMentionSearch` returning `{name, path}` — gains
connectors alongside files: every connector that is **active** (connected, enabled, and on
for this chat), with `kind: "connector"` and its icon, ranked above files when the query
matches a name. Picking a file works as today: the path is inserted as text and the model
reads it. Picking a connector is different, because a connector is a *scope*, not content:
the `@` token is removed from the text and a **small pill** — icon and name, with an × —
appears in the row above the textarea where attachments already sit. The message is sent
with a structured `connectors: ["salla"]` beside `attachments`, and the pills clear on send
like attachments do.

On the server a mentioned connector is **user-driven discovery**: its tools are injected for
this turn without a `find_tools` round-trip (decision 22), and one line — `[Using: Salla]` —
is appended to the user message so the intent is in the transcript and survives replay.
A connector typed as `@salla` by hand, without picking, is plain text: the model sees it,
calls the tool, and an unconnected one produces the connect card as usual.

**In the transcript.** A connector call is a step line like any tool: `Salla · orders for
August`, rendered by `tool_step` through the existing `StepPart`, with the connector's icon
where builtins show a verb. The result, when spilled, reads as a file link into `.tmp/`.

**Mid-chat, two cards — both the `ask` card.** Not connected: *"This needs Salla."* with
**Connect Salla** and *Not now*; Connect runs the flow above and the user re-sends. Confirm
(`writes=True` under the *ask when risky* preset): the action in words, not JSON — *"Refund
order #91823 — 340 SAR to ahmed@…?"* — with **Refund** and *Cancel*, the label coming from
the same `tool_step` text as the step line. One question component across web and mobile
([mention-picker-cache.md](mention-picker-cache.md) is what a second copy costs); defined as
a protocol — a question with options resolving to an answer — not a React component.

**Permissions.** A row in General beside follow-ups and clarifying questions: *Confirm
actions — Always / When risky / Never*, the same segmented control the existing rows use.

**Masking.** Keys and endpoints render masked with a reveal toggle. Presentation only —
decision 12 owns storage.

## Audit

Every tool call is already logged with its caller — `log("tool_call", user=…, chat_id=…,
tool=…, ms=…, ok=…)` in `_run`, emitted as structured JSON carrying `user_id`, `org_id` and
`plan`. Connectors need three additions.

**`tool_call` gains `connector`, `credential_scope` and `tool_use_id`.** The tool name alone
doesn't say whether the call resolved to the user's own credential, the org's, or the
deployment's — and with `scope="workspace"` ten people share one account, so `user_id` says whose
agent called but not what it acted as.

**A `connector` event** on connect, disconnect and denied: which connector, which scope, by
whom. Granting a business account to an agent is the highest-value security event in the
system and nothing currently records it.

**An `approval` event** on granted and declined, carrying the tool, the `tool_use_id` and the
preset mode in force. The client already fires `track("ask_answered", …)`, but that is
product analytics — it can be blocked, dropped, or simply not sent. **Analytics is not an
audit trail**, and "a human authorised this refund" has to be durable and server-side.

**The transcript and the log are two halves.** Arguments — what was sent, and to whom — are
already persisted in the `tool_use` block; identity and timing live in the log. Carrying
`tool_use_id` in both is what lets them join, and it is the right split: copying arguments
into Cloud Logging would move user data somewhere new for no gain.

**A credential is never a log field.** `log()` splats `**fields` straight into JSON, so one
careless `args=inp` on a connector tool writes an Authorization header into Cloud Logging
permanently.

## Phase 1 — Salla

One connector, end to end, on its official server. That pulls two things forward that a
key-only warm-up would have deferred — OAuth and the MCP client — and leaves `find_tools`
for later: with one connector, Salla's tools are injected directly, gated on connection.

1. `ToolContext` — the second handler argument, detected by signature.
2. The credential store: `.secrets/{user}` and `.connectors/`, encrypted, both sandbox
   guards, env override.
3. `cycls.OAuth2` with `scope="workspace"`, and the callback route. **For one deployment the
   agent's own callback can be registered with Salla directly**; the relay is what the
   second deployment needs, not the first.
4. The client-side MCP client — Streamable HTTP, `tools/list` cached, connect on call —
   and `.mcp(...).connector(salla)` binding it to the grant.
5. The directory modal: Discover and Yours, the detail page, enable/disable for workspace
   admins, allow/block for org admins, and the shared credential.
6. `NotConnected` → tool_result + connect card, using `ask` as it is; 401 → refresh → card.
7. Spill to `.tmp/{chat_id}/` with the preview, the `rm`-shim exemption, purge cleanup.
8. The audit fields and the `connector` / `approval` events.

Phase 2 is the relay and a second connector. Phase 3 is `find_tools`. `Plugin` is phase 4,
if anyone asks for it.

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
