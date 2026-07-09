# The CLI

One command, and its verbs mirror the object API — **`run` is local,
`--remote` is cloud, `deploy` freezes** — so learning either teaches both.

| command | meaning |
|---|---|
| `cycls init [name]` | scaffold a starter agent file |
| `cycls run file.py [--remote] [--args]` | the dev loop: rerun on save |
| `cycls deploy file.py` | freeze + publish |
| `cycls shell file.py` | bash inside the built image |
| `cycls ls` / `cycls rm <name>` | list / delete deployments |
| `cycls logs <name>` | fetch or tail a deployment's logs |
| `cycls cost <name>` | aggregate LLM spend |
| `cycls sql [QUERY]` | SQL over logs + billing |
| `cycls version` | print the installed version |

Auth for anything that hits the cloud: set `CYCLS_API_KEY`, or
`cycls.api_key = "..."` in Python. `CYCLS_BASE_URL` overrides the default
`https://api.cycls.ai`. Contributors inside this repo run the in-tree CLI
via `uv run cycls ...`; end users with cycls from PyPI call it directly.

`file` is `path.py`, or `path.py::name` to pick one of several decorated
instances. Every command imports the file — keep it side-effect-free
(no top-level `.run()`/`.remote()` calls).

## `cycls init [name]`

Scaffold a starter agent file at `{name}.py` (default: `my_agent.py`) — a
minimal `@cycls.agent` with Clerk auth, a system prompt, and an Anthropic
model. Edit it, then `run` or `deploy`.

```bash
cycls init notes
# → wrote notes.py
```

## `cycls run <file>`

The dev loop: watch the file (and any `copy`'d files), rerun on every save.
Where things run follows the one rule:

- **Functions** rerun locally in Docker — or, with `--remote`, on a warm
  per-image executor in the cloud (provisioned once, ~90s the first time,
  then ~1s per save, no Docker needed). Remote `print()`s stream back live.
- **Apps** serve locally in Docker — or, with `--remote`, on a live dev URL
  (`dev-{name}.cycls.ai`): each save hot-swaps the running app, no redeploy,
  with the server's request log streaming into your terminal.

```bash
cycls run examples/function/remote.py --remote --n 1000
# 3.2            ← edit anything, save, reprints in ~1s
cycls run examples/app/fast.py --remote
#   https://dev-fast.cycls.ai
#   │ 200 GET /
```

Trailing `--name value` args bind to the target's signature: annotated
params convert via their annotation, the rest literal-eval, else string.

For orchestration — several calls, `.map()`, mixed local/remote — mark a
driver with `@cycls.local_entrypoint`. Its code chooses the verbs, so
`--remote` doesn't apply there and is rejected. Keep driver calls inside
the entrypoint, not at module top level.

Saves during a run queue the next run rather than killing the current one —
a save can never interrupt a provision.

## `cycls deploy <file>`

Build and push to Cycls Cloud (managed runtime + per-tenant object-storage
workspace). The deployment name is the decorator's `name=` or the function
name; redeploying a name updates it in place.

```bash
cycls deploy notes.py
# → Building... Deploying... Deployed: https://notes.cycls.ai
```

`deploy` reads the function's contract: a function that takes `port` is a
server and serves it; a bare function deploys as a **remote-callable
endpoint** — frozen at deploy time, callable by name from any machine with
your `CYCLS_API_KEY`, no Docker:

```bash
cycls deploy examples/function/remote.py
# Deployed: https://simulate.cycls.ai
# Call it: cycls.remote("simulate")(...)
```

```python
import cycls
pi = cycls.remote("simulate")(10_000_000)
results = cycls.remote("simulate").map([10**6] * 100)
```

Auth is a token derived from your API key (nothing stored server-side), and
every call carries its Python/cloudpickle versions — the endpoint refuses
pickles that can't cross a version boundary with an explicit error. First
call after idle pays a cold start (a few seconds). See
[function.md](function.md) for the full remote-execution story.

## `cycls shell <file>`

Interactive bash inside the target's built image — the exact environment
`run` and `deploy` execute in. Builds (or reuses) the cached image, drops
you in `/app`, cleans up on exit.

```bash
cycls shell examples/function/c.py
# Entering cycls/triangle:730f149a (exit to leave)
root@a1b2c3:/app# gcc --version
```

Use it to verify what an `Image()` actually produced — check packages,
linked libraries, test commands before adding them to `.run(...)`.

## `cycls ls`

List your deployments.

```bash
cycls ls
# super-stage   https://super-stage.cycls.ai   [us-central1]   2026-05-15T18:14
# notes         https://notes.cycls.ai         [us-central1]   2026-05-10T09:00
```

Dev artifacts show up here too — `exec-*` (function executors) and `dev-*`
(app dev services). They scale to zero and cost nothing idle; `rm` reaps
them.

## `cycls rm <name> [-y]`

Delete a deployment. Asks for confirmation unless `-y`.

```bash
cycls rm notes -y
```

Doesn't delete the workspace storage — state survives, and redeploying the
same name picks it back up.

## `cycls logs <name>`

Fetch logs from a deployment. Returns the most recent batch and exits;
`-f` tails (polling every 2s); `-s 30m|24h|7d` narrows the window; `-q`
passes a structured filter through to the log backend.

```bash
cycls logs super-stage
# 2026-05-16 17:44:30  [INFO]  200 PUT /files/...
```

### `--query` is the QA mechanism

When an agent stream fails with an unhandled exception, the SSE encoder
emits one structured JSON line (captured by the log backend) and shows the
user a clean message with an `error_id` reference:

> Something went wrong. Reference: `abc12345`

When a user reports that reference, grep for it. Filter via
`jsonPayload.<field>`:

| field | values |
|---|---|
| `source` | `"agent"` — emitted by the agent runtime |
| `level` | `"error"` |
| `error_id` | short hex id, also shown to the user |
| `message` | `str(exception)`, untruncated |
| `stack` | full traceback |
| `user_id` / `chat_id` | tenant user and chat (null when anonymous) |

```bash
cycls logs super-stage --query 'jsonPayload.error_id="abc12345"'
cycls logs super-stage --query 'jsonPayload.level="error"'
cycls logs super-stage --query 'jsonPayload.user_id="user_2yY1..."'
cycls logs super-stage --query 'jsonPayload.chat_id="abc-123"'
```

`-f` works with `-q` — the filter is reapplied on every poll. Errors the
harness catches and shows as callouts (rate-limit retries, compaction
failures, tool timeouts) are *not* structured-logged — they're handled, not
QA signals.

### Cost logging

Each model turn also emits a structured `level=usage` line — queryable
per-user / per-chat / per-model / time range:

| field | values |
|---|---|
| `level` | `"usage"` |
| `model` | bare model id |
| `input` / `output` / `cached` / `cache_create` | token counts |
| `cost` | USD for the turn (6 dp) |
| `user_id` / `chat_id` / `at` | attribution |

Per-chat aggregates also persist in the chat index and surface via
`GET /chats`, so the sidebar can show spend without re-reading turns.

## `cycls cost <name>`

Aggregate spend across the `level=usage` stream — the friendly shortcut for
the common question.

```bash
cycls cost super-stage
# super-stage  $0.027126  (4 turns, 24h)
cycls cost super-stage --since 7d
cycls cost super-stage --month 2026-04
cycls cost super-stage --by user      # or: chat, model
```

- `-s, --since` — `30m`, `24h`, `7d` (default `24h`)
- `-m, --month [YYYY-MM]` — calendar month (no value = current); mutually
  exclusive with `--since`
- `-b, --by user|chat|model` — group rows

## `cycls sql [QUERY]`

SQL across all your deployment data — two tables, scoped automatically to
the deployments your API key owns. The escape hatch when `cost`'s canned
slicing isn't enough.

```bash
cycls sql 'SELECT ...'     # positional
cycls sql -f q.sql         # from file
cat q.sql | cycls sql      # stdin (auto-detected; `-` forces it)
```

Output: aligned table on a TTY, JSON when piped; `--format table|json|csv`
overrides, `--json` is a shortcut. Empty results print `(0 rows)` to stderr
and exit 0.

**`logs`** — every log entry, Log Analytics shape. Structured SDK emissions
land in `json_payload`:

| column | type | notes |
|---|---|---|
| `timestamp` / `severity` / `log_name` | | |
| `resource.labels` | JSON | `JSON_VALUE(resource.labels, '$.service_name')` = deployment |
| `json_payload` | JSON | by `level`: `error` (`error_id`, `message`, `stack`), `usage` (`model`, tokens, `cost`, `ms`), `tool_call` (`tool`, `ms`, `ok`, `output_bytes`) |
| `text_payload` | STRING | plain stdout/stderr |

**`billing`** — per-SKU per-day cost rows:

| column | type | notes |
|---|---|---|
| `usage_start_time` / `usage_end_time` | TIMESTAMP | |
| `service.description` / `sku.description` | STRING | compute service / SKU |
| `cost` / `currency` | FLOAT64 / STRING | usually USD |
| `resource.name` | STRING | deployment name directly |

```sql
-- LLM spend per user this month
SELECT JSON_VALUE(json_payload, '$.user_id')                    AS user_id,
       SUM(CAST(JSON_VALUE(json_payload, '$.cost') AS FLOAT64)) AS spend
FROM logs
WHERE JSON_VALUE(json_payload, '$.level') = 'usage'
  AND timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY user_id ORDER BY spend DESC

-- Infra cost per deployment, last 30 days
SELECT resource.name AS deploy, ROUND(SUM(cost), 4) AS usd
FROM billing
WHERE usage_start_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY deploy ORDER BY usd DESC

-- Tool-call p95 latency per tool, last 7 days
SELECT JSON_VALUE(json_payload, '$.tool') AS tool,
       APPROX_QUANTILES(CAST(JSON_VALUE(json_payload, '$.ms') AS INT64), 100)[OFFSET(95)] AS p95_ms,
       COUNT(*) AS calls
FROM logs
WHERE JSON_VALUE(json_payload, '$.level') = 'tool_call'
  AND timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY tool ORDER BY p95_ms DESC
```

Notes, honestly: the first `cycls sql` call after a deployment is created
can take 5–10s (lazy server-side setup); a per-query scanned-bytes cap is
enforced (add `LIMIT` or narrower predicates); SQL-engine errors surface
verbatim — they're actionable.

## `cycls version`

```bash
cycls version
# cycls 0.0.2.132
```
