# The connector catalog — every connector this branch deploys, declared once.
#
#   from catalog import ALL, SERVERS, posthog_mcp
#   web = cycls.Web().connectors(*ALL)
#   llm = cycls.LLM().mcp(*SERVERS)
#
# Imported at module level by a deploy file, so the objects are built on your machine and pickled into
# the deployment. The container never imports this file, and nothing here needs to reach the image.
#
# DECLARATIONS ONLY — no lambdas, no defs, no module-level values a callable would close over.
# cloudpickle pickles a function defined in the file you deploy (`__main__`) by value, but one defined in
# an imported module by reference: the container would boot, try `import catalog`, and die. So a
# `.writes()` classifier or a custom-tool handler stays in the deploy file. Strings, lists and connector
# objects are safe — their classes live in the installed SDK.
#
# What belongs here is behaviour: endpoints, scopes, what a key looks like, which grant is shareable.
# NOT copy. Title, description, icon, story, prompts and links live in the CMS, bilingual, keyed by the
# name below — cms.cycls.ai/connectors, edited by whoever writes the copy, without a redeploy. A field
# declared here would still win over the CMS field by field, which is why none is: a title in this file
# is an English word the Arabic page cannot override.
import cycls

# ---- Google — parked, not offered ----
# Declared and working, but out of ALL/SERVERS below. All six Workspace MCP servers are in Google's
# Developer Preview, whose terms are explicit: "Features in Developer Preview may not be included in
# public applications prior to the General Availability announcement", and access may not be granted
# to end users outside your own domain or company. That is a harder gate than CASA — no fee or review
# lifts it. Worse, the servers list their tools anonymously, so a user would connect successfully and
# then have every call refused with "the caller does not have permission".
#
# Two ways back: Google announces GA, or these go over the GA REST APIs instead of the MCP servers,
# where `drive.file` needs no review. Either way the declarations below still stand.

google = cycls.OAuth2("google",
    authorize="https://accounts.google.com/o/oauth2/v2/auth",
    token="https://oauth2.googleapis.com/token",
    client_id=cycls.env("GOOGLE_CLIENT_ID"), secret=cycls.env("GOOGLE_CLIENT_SECRET"),
    scopes=["https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive.readonly",  # Drive MCP refuses a drive.file-only token
            "https://www.googleapis.com/auth/documents", "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/presentations"],
    extra={"access_type": "offline", "prompt": "consent"},
    scope="either")   # an admin can share one Drive with the team, or anyone links their own
# Drive, Docs, Sheets and Slides are one grant: they are all "the user's files", and their scopes read
# as one sentence on the consent screen. Gmail and Calendar are their own connectors below — asking for
# someone's mail because they wanted a spreadsheet is how a consent screen gets refused.
drive  = cycls.MCP("https://drivemcp.googleapis.com/mcp/v1").name("drive").connector(google)   # declared once: the directory lists its tools before any chat
gdocs  = cycls.MCP("https://docsmcp.googleapis.com/mcp/v1").name("docs").connector(google)
gsheet = cycls.MCP("https://sheetsmcp.googleapis.com/mcp/v1").name("sheets").connector(google)
gslide = cycls.MCP("https://slidesmcp.googleapis.com/mcp/v1").name("slides").connector(google)

# Gmail's scopes are "restricted" at Google: production use needs their CASA security assessment, which
# is the reason the RFC picked Microsoft 365 over Google for the productivity story. Declared so the
# directory can list it; it will not pass consent until that assessment is done.
gmail_c = cycls.OAuth2("gmail",
    authorize="https://accounts.google.com/o/oauth2/v2/auth", token="https://oauth2.googleapis.com/token",
    client_id=cycls.env("GOOGLE_CLIENT_ID"), secret=cycls.env("GOOGLE_CLIENT_SECRET"),
    scopes=["https://www.googleapis.com/auth/gmail.modify"],
    extra={"access_type": "offline", "prompt": "consent"}, scope="user")   # a mailbox is a person, never shared
gmail = cycls.MCP("https://gmailmcp.googleapis.com/mcp/v1").name("gmail").connector(gmail_c)

gcal_c = cycls.OAuth2("gcal",
    authorize="https://accounts.google.com/o/oauth2/v2/auth", token="https://oauth2.googleapis.com/token",
    client_id=cycls.env("GOOGLE_CLIENT_ID"), secret=cycls.env("GOOGLE_CLIENT_SECRET"),
    scopes=["https://www.googleapis.com/auth/calendar.events"],
    extra={"access_type": "offline", "prompt": "consent"}, scope="either")
gcal = cycls.MCP("https://calendarmcp.googleapis.com/mcp/v1").name("calendar").connector(gcal_c)

# ---- Servers that register themselves ----
# Salla, Notion and Apify publish their own authorization server and register clients on the fly:
# one line each, no app to pre-register, no secret to keep.

salla = cycls.OAuth2("salla", mcp="https://mcp.salla.dev/mcp", scopes=["offline_access"], scope="either",
                     api="https://api.salla.dev")
salla_mcp = cycls.MCP("https://mcp.salla.dev/mcp").name("salla").connector(salla)

notion = cycls.OAuth2("notion", mcp="https://mcp.notion.com/mcp", scopes=["default"], scope="either",
                      api="https://api.notion.com", api_headers={"Notion-Version": "2022-06-28"})   # Notion 400s without the version
notion_mcp = cycls.MCP("https://mcp.notion.com/mcp").name("notion").connector(notion)

apify = cycls.OAuth2("apify", mcp="https://mcp.apify.com", scopes=["full_api_access"], scope="either",
                     api="https://api.apify.com")
apify_mcp = cycls.MCP("https://mcp.apify.com").name("apify").connector(apify)

# Canva registers a client for any redirect, then refuses it at /authorize: their authorize step keeps a
# host allowlist — loopback and a few partner hosts pass, ours does not. Parked pending their MCP connector
# review, which the relay now gives a single host to allow. Same story for Foodics, Vercel, Square, Asana
# and Figma, which refuse at registration outright. Note scope="user": Canva does not permit org-level
# auth, so a workspace admin may not share one Canva account with the team. Its CMS copy is written and
# published, so uncommenting these two lines is the whole of shipping it.
# canva = cycls.OAuth2("canva", mcp="https://mcp.canva.com/mcp", scopes=["default"], scope="user")
# canva_mcp = cycls.MCP("https://mcp.canva.com/mcp").name("canva").connector(canva)

# ---- Apps registered by hand ----
# No registration endpoint, so each needs an OAuth app created in the provider's console with
# https://connect.cycls.ai/callback as its redirect URL, and its secret in deployment config.

github = cycls.OAuth2("github",
    authorize="https://github.com/login/oauth/authorize",
    token="https://github.com/login/oauth/access_token",
    client_id=cycls.env("GITHUB_CLIENT_ID"), secret=cycls.env("GITHUB_CLIENT_SECRET"),
    scopes=["repo", "read:org", "read:user", "user:email"], scope="either",
    api="https://api.github.com")
github_mcp = cycls.MCP("https://api.githubcopilot.com/mcp").name("github").connector(github)

hubspot = cycls.OAuth2("hubspot",
    authorize="https://mcp.hubspot.com/oauth/authorize/user", token="https://mcp.hubspot.com/oauth/v3/token",
    client_id=cycls.env("HUBSPOT_CLIENT_ID"), secret=cycls.env("HUBSPOT_CLIENT_SECRET"),
    scopes=["crm.objects.contacts.read", "crm.objects.companies.read", "crm.objects.deals.read", "oauth"],
    scope="either")   # a CRM is the team's, so an admin can connect it once for everyone
hubspot_mcp = cycls.MCP("https://mcp.hubspot.com/anthropic").name("hubspot").connector(hubspot)

# Slack publishes RFC 9728/8414 metadata but no registration_endpoint, so `mcp=` cannot discover it:
# it needs an app at api.slack.com with the relay redirect and `client_secret_post`. These are *user*
# scopes — /oauth/v2_user/authorize mints a token that is the person, so the grant is never shared.
# Turn token rotation on in the app: without it Slack returns no `expires_in` and no refresh token,
# and the grant is treated as hourly and cannot be renewed.
slack = cycls.OAuth2("slack",
    authorize="https://slack.com/oauth/v2_user/authorize", token="https://slack.com/api/oauth.v2.user.access",
    client_id=cycls.env("SLACK_CLIENT_ID"), secret=cycls.env("SLACK_CLIENT_SECRET"),
    scopes=["channels:read", "channels:history", "groups:read", "groups:history", "im:read", "im:history",
            "chat:write", "files:read", "users:read", "search:read.public"],
    scope="user", api="https://slack.com/api")
slack_mcp = cycls.MCP("https://mcp.slack.com/mcp").name("slack").connector(slack)

# ---- A pasted key, and a pasted address ----

posthog = cycls.Key("posthog", hint="phx_…", scope="either", api="https://us.posthog.com")

# Zid hands each merchant a private MCP link from the "AI Tools Connection" app and tells them to treat it
# like a password — so the link IS the credential: pasted like a key, used as the address, never sent anywhere.
# `host` is the guard; the subdomain is only visible once the app is installed, so it bounds the domain.
zid = cycls.Endpoint("zid", host="zid.sa", scope="either", hint="https://….zid.sa/…")
zid_mcp = cycls.MCP().name("zid").connector(zid)

# PostHog's catalog is hundreds of tools behind one `exec` tool that wants a schema hunt before each call.
# `features=` keeps the turn small and `.guidance()` hands the model the shapes, so a question costs one
# call. The third piece — `.writes()`, which says which of those calls change something so *Ask* stops
# only for those — is a lambda, so it is added in the deploy file: see the header.
posthog_mcp = (
    cycls.MCP("https://mcp.posthog.com/mcp?features=workspace,insights,dashboards,flags,error_tracking,sql")
    .name("posthog").connector(posthog)
    .guidance("""PostHog is one tool, `posthog_exec`, taking CLI-style commands. The shapes you need are here — go straight to `call`, do not run `info` or `schema` for these:
- Counts, breakdowns, anything tabular: `call execute-sql {"query": "<HogQL>"}` — `query` is a plain SQL string, not an object. The `events` table has `event`, `timestamp`, `distinct_id`, `properties`. Example: `SELECT event, count() AS total FROM events WHERE timestamp > now() - INTERVAL 24 HOUR GROUP BY event ORDER BY total DESC`.
- Never `SELECT properties` or `SELECT *`: `properties` is a large JSON blob per row and PostHog cuts long output at about 6 KB, marking it `...truncated`. Name the columns you need; a single property is `properties.$current_url`, `properties.$browser`, and so on. Keep result sets narrow and use LIMIT.
- Trends over time: `call query-trends {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": null, "math": "total"}], "dateRange": {"date_from": "-24h"}, "interval": "hour"}` — `event: null` means all events; `"trendsFilter": {"display": "BoldNumber"}` for a single total.
- Feature flags: `call feature-flag-get-all {}` to list; changing one is a write and will ask the user.
Use `info <tool>` only for a tool not covered above, at most once per chat, and answer with one query rather than several small ones. Results are already in the project's timezone.""")
)

# What a deploy file wires up. `.connectors(*ALL)` is the directory; `.mcp(*SERVERS)` is the tools.
# `posthog_mcp` is deliberately out of SERVERS — it needs its classifier attached first.
ALL = [posthog, salla, notion, apify, zid, github, hubspot, slack]
SERVERS = [salla_mcp, notion_mcp, apify_mcp, zid_mcp, github_mcp, hubspot_mcp, slack_mcp]
