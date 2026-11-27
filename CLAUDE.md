# Cycls

Python SDK for building, deploying, and monetizing AI agents. Write a function, deploy it as an API, web interface, or both.

For a comprehensive walk through the primitives, decorators, CLI, and end-to-end patterns, see [docs/tutorial.md](docs/tutorial.md).

Published documentation lives at [docs.cycls.com](https://docs.cycls.com), source in [github.com/Cycls/docs](https://github.com/Cycls/docs). Keep it in step when the public surface changes.

## Tech Stack

- Python >= 3.9 (3.10+ for deployment)
- FastAPI + Hypercorn for web serving (hypercorn for h2 end-to-end on Cloud Run)
- Docker for containerization
- uv for package management
- Cloudpickle for function serialization
- JWT (Clerk) for authentication

## Commands

```bash
# Install dependencies
uv sync --group test

# Run all backend tests (mocked; live tier auto-skipped)
uv run pytest tests/

# Run live tests against real Anthropic (needs ANTHROPIC_API_KEY)
set -a && source .providers.env && set +a
uv run pytest tests/agent/scenarios/test_live.py --live

# Run FE tests (vitest)
cd client && npm test

# Run example app
uv run cycls run examples/apps/api.py

# Run example function
uv run cycls run examples/functions/hello.py

# Clean up Docker
docker system prune -af
```

## Project Structure

```
cycls/
├── cli.py                  # CLI: run, deploy, shell, ls, rm, logs, cost, sql, volume, init, version
├── _function/
│   ├── main.py             # Function class + @cycls.function decorator
│   ├── image.py            # cycls.Image fluent builder
│   ├── volume.py           # cycls.Volume — named persistent storage
│   ├── schedule.py         # cycls.Cron — fire a deployed function on a schedule
│   └── remote.py           # pickle-RPC shim + cycls.remote client (--remote deploys)
├── _app/
│   ├── main.py             # App class + @cycls.app + _make_decorator
│   ├── auth.py             # cycls.Clerk, cycls.JWT, GCP, User, AppleIAP, validator
│   └── web.py              # cycls.Web fluent builder
└── _agent/
    ├── main.py             # Agent class + @cycls.agent decorator
    ├── state.py            # all agent state — chat meta+log+Session, shares, agent KV tool
    ├── activity.py         # who made and changed each file (.files), people's faces, an org's audit log (docs/rfc-file-metadata.md)
    ├── catalog.py          # ready-made apps (Web.apps): bundles on a volume or beside the agent, each one's state in a workspace, install/update never over a changed app, the look (docs/notes/apps.md "Ready-made apps")
    ├── inbox.py            # a person's notifications across their workspaces (.inbox): `notify`, a team message's mentions and replies, the bell's read, each person's browsers (docs/rfc-notifications.md)
    ├── webpush.py          # Web Push from our own server: RFC 8291 encryption, a VAPID signature, sent straight to each browser's push service
    ├── routines.py         # routines: the record (each person's, per workspace), the clock (.clock, a key per routine by its next run), a run as its owner's chat message, `routine` and `tell` (docs/rfc-routines.md)
    ├── mcp.py              # cycls.MCP — remote MCP servers via the Anthropic connector
    ├── browser/            # cycls Browser tool — thin CDP client to a shared real-Chrome service (Steel); docs/notes/browser.md
    ├── video/              # cycls Video tool, over a thin client to the cycls-video service on Modal GPUs (HyperFrames compositions → MP4); docs/notes/video.md
    │   └── editor.py       # the video editor's sessions on the service (Edit on the canvas → client video-editor-view.tsx) and the render it asks for
    │   ├── client.py       # the door's API (contract, warm, compile, jobs, long-poll, the MP4 streamed to disk; a clip sent in pieces, ingest)
    │   ├── contract.py     # the signed contract, verified (fallback.py: the built-in copy); tool.py — short and whole forms
    │   └── run.py          # the executor (guide, write, edit, look, render, subtitles, dub, restore, voice, music, footage); files.py, media.py, report.py, stock.py (Pexels clips), subtitles.py (.srt/.vtt beside a render, and in each language translated by sentence), tidy.py (a talking clip's long pauses cut), sizes.py (one composition in several sizes: data-sizes, data-shape), dubbing.py (dub: the video said again in another language), brand.py + fonts.py (the brand kit and its font files in every video)
    ├── design/             # cycls Design tool, over a thin HTTP client to a shared design service (posts, carousels, decks, documents); docs/notes/design.md
    │   ├── tool.py         # the tool as the model is given it (and the short form a chat carries until it designs)
    │   ├── skill.py        # the tool's own skills (skills/*.md: design-direction, graphic-design, deck-design, document-design), loaded by `skill`
    │   ├── run.py          # the executor (_exec_design): render, script, edit, inspect, extract, import
    │   ├── actions.py      # slide, section and file actions; a document rendered
    │   ├── prepare.py      # what the model wrote, made ready: spec, pages, deck, document, slide, ops (brand.py, images.py)
    │   ├── extract.py      # a PDF taken apart to be made again; report.py — what the model is told; files.py — a design's files
    │   ├── powerpoint.py   # `import`: a PowerPoint deck the person brought, opened as a design to change (docs/notes/design.md "A PowerPoint deck brought in")
    │   ├── client.py       # the service client; deck.py slide ops, store.py versions + bases, refresh.py a design's preview made ready, live.py rooms, stock.py photos, assets.py the media library
    │   └── comments.py     # what people pin on a design — threads kept by the workspace (`.comments`), where a pin is now; docs/notes/design.md "Comments"
    ├── transcribe/         # cycls Transcribe tool + the mic, two engines: ElevenLabs Scribe (elevenlabs.py) and the cycls-transcribe service on Modal GPUs (client.py: Cohere Transcribe Arabic, Whisper); TRANSCRIBE_ENGINE picks the first; usage.py the daily allowance; docs/notes/transcribe.md
    ├── office/             # Cycls Sheets / Cycls Docs: thin client to the cycls-office service (its own repo; Univer engine), org gating (SHEETS_ORGS/DOCS_ORGS), the agent's `sheets` tool (sheets.py: read / edit / create, live replay via sheets_command) and `docs` tool (docs.py); guard.py keeps bash off their files; docs/notes/office.md
    ├── paths.py            # a path a tool was given, kept inside the workspace
    ├── tools/              # tool schemas + execution + `Tool` rows: run/step/once/terminal/prompt (docs/notes/tool-rows.md); Design and Video are imported from their packages; ondemand.py swaps a tool's whole form in on first use
    │   └── agent.py        # the `agent` tool: agents a run hands work to, in the background; their reports wake the parent; the developer's own (cycls.Subagent, LLM.subagents) (docs/rfc-subagents.md)
    ├── harness/            # the managed LLM loop and the kit a custom loop needs
    │   ├── llm.py          # cycls.LLM fluent builder (.loop(fn) swaps the loop; .price()/.context() set cost rates + window)
    │   ├── main.py         # the default loop (_run) + retry/recover + attachment ingest
    │   ├── providers/      # one streaming interface per vendor SDK
    │   │   ├── anthropic.py  # native Messages (cache breakpoints, thinking, MCP, server search)
    │   │   └── openai.py     # Chat Completions — also GLM (zai/*), Gemini-compat, Groq, vLLM via base_url
    │   ├── events.py       # typed loop events + to_ui (FE projection)
    │   ├── compact.py      # compaction — tool-result clearing, then a summary; append-only marker, file ledger (docs/notes/compaction.md)
    │   └── prompts.py      # system + compaction prompts + workspace instructions (AGENT.md)
    └── web/                # FastAPI chat server, state routers (routers.py; a design's routes in design_routes.py, a composition's ?as=player in video_routes.py, what they share in shared.py), OG images, themes
        └── voice.py        # the mic's speech-to-text, any OpenAI-shaped service, kept server-side (Web.voice) — behind the Transcribe engines when they are set; docs/notes/voice.md
```

## Core Architecture

```
Agent extends App (chat product + managed LLM loop)
  └── App extends Function (blocking ASGI service)
      └── Function (Docker containerization)
```

## Key Patterns

**Decorator pattern** - `@cycls.function()` and `@cycls.app()` transform functions

**Generator pattern** - All functions must be generators using `yield`:
```python
@cycls.app()
async def my_app(context):
    yield "Hello!"  # Streams to client
```

**Declarative infrastructure** - Build config via the `cycls.Image` primitive:
```python
@cycls.function(image=cycls.Image().pip("numpy").apt("curl").copy("data/"))
def my_func(x):
    ...
```

## Streaming Components

Yield these from app functions:
- `"text"` or `{"type": "text", "text": "..."}` - Plain text
- `{"type": "thinking", "thinking": "..."}` - Thinking bubble
- `{"type": "code", "code": "...", "language": "..."}` - Code block
- `{"type": "table", "headers": [...]}` / `{"row": [...]}` - Tables
- `{"type": "status", "status": "..."}` - Status indicator
- `{"type": "callout", "callout": "...", "style": "info|warning|error|success"}`
- `{"type": "image", "src": "...", "alt": "...", "caption": "..."}` - pictures side by side make a grid; a workspace picture opens in the canvas
- `{"type": "chart", "kind": "column|bar|stacked|line|area|pie|donut|treemap", "title": ..., "data": {"labels": [...], "series": [{"name": ..., "values": [...]}]}}` - drawn in SVG in the chat, no library (parts/data-chart.tsx), saved to files, as a PNG or a CSV; a reply draws the same from a ```chart block, and a time series (`series` of `[time, value]` rows, candles) is drawn with Lightweight Charts. A reply's ```flowchart block (`nodes`, `edges`, `direction`) is laid out and drawn the same way (parts/flow-chart.tsx)
- `{"type": "sources", "sources": [{"title": ..., "url": ..., "snippet": ...}]}` - citation chips; emitted by the `WebSearch` builtin, and by any tool as `_ui` with optional `label`, `quote`, `status`, `note`; they survive a reload
- `{"type": "usage", "used": 11, "limit": 14, "per": "month", "resets": "2026-11-01"}` - a limit, sent with a reply: a line over the composer in its last fifth; the reply that uses the last of it opens the plans as it ends (once a period on each device), and a reply refused for it is a thank-you note
- `{"type": "ui", "action": "open_plan_modal"}` — fire-and-forget UI trigger; not rendered, not persisted in session history (also `open_canvas`, `suggest`, `ask` — see docs/tutorial.md)

## Environment Variables

- `CYCLS_API_KEY` - API key for production deployment
- `CYCLS_BASE_URL` - Base URL for deployment service
- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` - For examples; `OPENAI_API_KEY` also turns on voice input unless `Web().voice()` names another model

## Code Style

- Use async for I/O operations, sync for CPU-bound work
- Functions are pickled - closures and lambdas work
- Yield frequently for responsive streaming UI
- Errors display as callouts in UI

## Testing

Three tiers, mirrored to source:

```
tests/
├── conftest.py                  # autouse store-pool reset; --live flag
├── function/                    # Function class + Image
├── app/                         # App, Sandbox argv, Workspace/DB, fence retry
├── agent/
│   ├── agent_test.py            # _run loop, retry, recovery, ingest, exec/_resolve_path
│   ├── chat_test.py             # to_ui_messages (FE projection) + _valid_prefix repair
│   ├── harness_test.py          # build_tools, web search/fetch, cost math, _resolve_path, LLM builder
│   ├── browser_test.py          # Browser tool: client config/providers, steel session parse, executor dispatch, gating
│   ├── design_test.py           # Design tool: client, spec/deck prep (images, brand theme), decks + carousels, slide actions, refresh, gating, its skills (every example goes through)
│   ├── design_comments_test.py  # comments on a design: the workspace's record, the routes, rename/trash, the agent's `comments`
│   ├── design_import_test.py    # a PowerPoint deck brought in: part by part, written once whole, the same file once, refusals, the attachment hint
│   ├── video_test.py            # Video tool: client, signed contract, short/whole forms + the ondemand seam, executor, ?as=player
│   ├── sheets_test.py           # Sheets tool: schema, gating, the service wire, edit/create, the stale-file retry
│   ├── transcribe_test.py       # Transcribe tool: client, executor (files beside the recording, kept, collected later), attachment hint, the mic + its fallback
│   ├── skills_test.py           # skill discovery, catalog text, the `skill` tool
│   ├── subagents_test.py        # agents in the background, reports waking the parent, four at once or the developer's number, their own agents with fixed instructions, file holds, cost
│   ├── app_catalog_test.py      # ready-made apps: install as build_app lands one, an update keeping data/name/icon, a changed or a person's own app never touched, the CMS's list, admins only, the look
│   ├── activity_test.py         # file records and their faces, the walk after a run, the audit log and its routes, a chat's files
│   ├── team_chats_test.py       # a team workspace's chats: who sees them, a message to the team alone, moving a chat there, reactions, edits, typing, unread, paging, writes at the same moment, a look that finds nothing new
│   ├── inbox_test.py            # the inbox: a mention, a reply and @all reach who they name, never the sender, whoever had the chat open, nor twice; push words and picks; a task ended while away; read, seen, a chat opened, the newest 30; Web Push (RFC 8291's example, a browser's push read back, one gone dropped, OneSignal to phones only)
│   ├── routines_test.py         # routines: local time across clock changes, set up only from the card, the clock starting each once, a run as its owner off the chat list, tell, three failures pausing it
│   ├── events_test.py           # to_ui wire shapes for the typed events
│   ├── pdf_test.py              # PDF page parsing
│   ├── web_test.py              # FastAPI routes, encoders, Messages, SEO/branding
│   ├── workspaces_test.py       # registry, ACL, team workspaces, admin lifecycle
│   ├── integration_test.py      # Agent on top of App
│   └── scenarios/
│       ├── test_load_repair.py  # store roundtrip + repair invariants
│       ├── test_build_contract.py # @pytest.mark.live, the real app-build service
│       ├── test_database.py     # the `database` tool over the agent KV
│       └── test_live.py         # @pytest.mark.live, real Anthropic
└── client/tests/                # vitest — useChat, auth headers, mentions, apps, the app bridge
```

**Mocked tier** (default): no API calls, no docker. Runs in ~2min.
```bash
uv run pytest tests/                       # all ~410 mocked tests
uv run pytest tests/agent/ -v              # just agent tests
uv run pytest tests/agent/scenarios/ -v    # just scenarios
```

**Live tier** (gated `--live`): hits real Anthropic, costs ~$0.30-0.50/run, takes ~40s.
Needs `ANTHROPIC_API_KEY` (in `.providers.env` for dev). Skips silently without it.
```bash
set -a && source .providers.env && set +a
uv run pytest tests/agent/scenarios/test_live.py --live -v
```

**FE tier** (vitest): 16 tests — `useChat` (URL plumbing, callback identity stability, attachment blob fetch, retry gating) + `useAuthHeaders` (workspace header). Run from `client/`:
```bash
cd client && npm test           # one-shot
cd client && npm run test:watch # interactive
```

Function tests need Docker running.

## Publishing

When asked to "publish":
1. **Build the web client first** — `cd client && npm run build`. It writes into
   `cycls/_agent/web/themes/default`, which the wheel ships as an artifact, so the package
   carries whatever was last built there. `uv build` does **not** rebuild it. Skip this and you
   publish a server speaking the current protocol with a browser bundle that does not —
   0.0.2.142 went out that way.
2. Bump the version in `pyproject.toml`
3. Commit and push the changes to git, rebuilt assets included (do not coauthor)
4. Run: `rm -rf dist && export $(cat .env | xargs) && uv build && uv publish`
5. Check the bundle inside the wheel, not the source tree — minification renames identifiers, so
   grep for a literal you changed rather than a function name:
   `python3 -c "import zipfile;z=zipfile.ZipFile('dist/cycls-<v>-py3-none-any.whl');print('<literal>' in z.read([n for n in z.namelist() if 'themes/default/assets/index-' in n and n.endswith('.js')][0]).decode())"`

PyPI's `latest` in the JSON API serves stale edge caches for a few minutes. `curl -o /dev/null -w
"%{http_code}" https://pypi.org/pypi/cycls/<version>/json` is the straight answer.

Yanking a bad release is **web UI only** — PyPI's upload endpoint returns 405 for `:action=yank`.
