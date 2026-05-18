# cycls CLI

Single command: `cycls`. Subcommands: `init`, `run`, `deploy`, `ls`, `rm`, `logs`, `cost`, `version`.

```bash
cycls <subcommand> [args]
```

Auth (for any command that hits the cloud): set `CYCLS_API_KEY` env var, or
`cycls.api_key = "..."` in Python. `CYCLS_BASE_URL` overrides the default
`https://api.cycls.ai`.

Contributors working inside this repo invoke the in-tree CLI via
`uv run cycls <subcommand>`. End users with `cycls` installed from PyPI
call it directly.

## `cycls init [name]`

Scaffold a starter agent file at `{name}.py` (default: `my_agent.py`).

```bash
cycls init notes
# → wrote notes.py
```

The starter is a minimal `@cycls.agent` with Clerk auth, a system prompt,
and an Anthropic Sonnet LLM. Edit it, then `run` or `deploy`.

## `cycls run <file>`

Run an agent locally in Docker. Builds the image the first time, mounts the
workspace, serves on `http://localhost:8080`.

```bash
cycls run notes.py
cycls run examples/agent/super.py::super     # explicit target
```

`file` is `path.py` or `path.py::name` if the file has multiple decorated
instances. Use `::name` to pick.

## `cycls deploy <file>`

Build and push to Cycls Cloud (Cloud Run + per-tenant GCS workspace).

```bash
cycls deploy notes.py
# → Building... Deploying... Deployed: https://notes.cycls.ai
```

The deployment name is the decorator's `name=` (e.g. `@cycls.agent(name="super-stage")`)
or the function name otherwise.

## `cycls ls`

List your deployed agents.

```bash
cycls ls
# super-stage   https://super-stage.cycls.ai   [us-central1]   2026-05-15T18:14
# notes         https://notes.cycls.ai         [us-central1]   2026-05-10T09:00
```

## `cycls rm <name> [-y]`

Delete a deployed agent. Asks for confirmation unless `-y` / `--yes`.

```bash
cycls rm notes
# Delete 'notes'? [y/N] y
cycls rm notes -y
```

Doesn't delete the bucket — workspace state survives. Re-deploy with the
same name to pick it back up.

## `cycls logs <name>`

Fetch logs from a deployed agent. By default returns the most recent batch
and exits.

```bash
cycls logs super-stage
# 2026-05-16 17:44:30  [INFO]  200 PUT /files/...
# 2026-05-16 17:47:25  [INFO]  200 GET /files/...
```

### Flags

- `-f, --follow` — tail logs, polling every 2 seconds.
- `-q, --query QUERY` — filter using **GCP Cloud Logging query syntax**.
  Passes through to the backend's `filter=` argument.

### `--query` is the QA mechanism

When the agent stream fails with an unhandled exception, the SSE encoder
emits one structured JSON line to stdout (captured by Cloud Logging) AND
shows the user a clean message with the `error_id` reference:

> Something went wrong. Reference: `abc12345`

When a user reports that reference, grep that id in the logs.

| Field | Values |
|---|---|
| `source` | `"agent"` — emitted by the agent runtime (vs platform components) |
| `level` | `"error"` |
| `error_id` | short hex id, also shown to the user in the callout |
| `message` | `str(exception)` (full, untruncated) |
| `stack` | `traceback.format_exc()` (full) |
| `user_id` | tenant user id (or null for anonymous) |
| `chat_id` | the chat where it happened |

Filter via `jsonPayload.<field>`.

### Query examples

```bash
# All agent errors
cycls logs super-stage --query 'jsonPayload.source="agent"'

# All structured errors (any source)
cycls logs super-stage --query 'jsonPayload.level="error"'

# Lookup a specific error the user pasted
cycls logs super-stage --query 'jsonPayload.error_id="abc12345"'

# All errors for one tenant
cycls logs super-stage --query 'jsonPayload.user_id="user_2yY1NGlkgUtCgYiPLSHQUriCWrr"'

# Everything that happened in one chat
cycls logs super-stage --query 'jsonPayload.chat_id="abc-123"'

# Errors in the last hour (Cloud Logging needs an absolute RFC-3339 timestamp;
# compute it client-side)
SINCE=$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ)
cycls logs super-stage --query "jsonPayload.level=\"error\" AND timestamp >= \"$SINCE\""
```

`-f` works with `-q` — the filter is reapplied on every poll.

Full query syntax: https://cloud.google.com/logging/docs/view/logging-query-language

### What's NOT logged

Errors the harness catches and yields as callouts (rate-limit retry
exhaustion, compaction failure, tool timeouts) are visible to the user
in the chat but NOT structured-logged — they're known/handled, not QA
signals. The encoder logs only what's truly unexpected.

### Cost logging

Each model turn also emits a structured `level=usage` line to Cloud Logging.
Same `--query` mechanism, queryable per-user / per-chat / per-model / time
range.

| Field | Values |
|---|---|
| `source` | `"agent"` |
| `level` | `"usage"` |
| `model` | bare model id (e.g. `claude-sonnet-4-20250514`) |
| `user_id` | tenant user id (or null for anonymous) |
| `chat_id` | the chat where the turn happened (or null) |
| `input` / `output` / `cached` / `cache_create` | token counts |
| `cost` | USD for this turn (float, 6 dp) |
| `at` | ISO timestamp |

```bash
# Every turn's cost
cycls logs super-stage --query 'jsonPayload.level="usage"'

# One user's spend in the last hour (compute the timestamp client-side)
SINCE=$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ)
cycls logs super-stage --query "jsonPayload.level=\"usage\" AND jsonPayload.user_id=\"user_xxx\" AND timestamp >= \"$SINCE\""

# Spend per model (then pipe to jq to sum)
cycls logs super-stage --query 'jsonPayload.level="usage" AND jsonPayload.model="claude-sonnet-4-20250514"'

# Most expensive chats
cycls logs super-stage --query 'jsonPayload.level="usage" AND jsonPayload.cost > 0.10'
```

Per-chat aggregate is also persisted in the chat index (`chat/{id}/index.cost`)
and surfaced via the `GET /chats` payload, so the sidebar can show
"this chat: $X.YZ" without re-reading turns.

## `cycls cost <name>`

Aggregate cost across the same `level=usage` log stream.

```bash
cycls cost super-stage
# super-stage  $0.027126  (4 turns, 24h)

cycls cost super-stage --since 7d
cycls cost super-stage --by user
# user_xxx  $0.022826  (3 turns)
# user_yyy  $0.004300  (1 turns)

cycls cost super-stage --by chat
cycls cost super-stage --by model
```

### Flags

- `-s, --since DURATION` — `30m`, `24h`, `7d` (default: `24h`). Translated
  to an absolute timestamp filter client-side.
- `-m, --month [YYYY-MM]` — calendar-month window. No value = current month.
  Mutually exclusive with `--since`.
- `-b, --by user|chat|model` — group rows by `user_id`, `chat_id`, or `model`.

```bash
cycls cost super-stage --month --by user      # this month, per user
cycls cost super-stage --month 2026-04        # April 2026 total
```

`--since` is also available on `cycls logs` for the same client-side
timestamp translation.

## `cycls sql [QUERY]`

Run SQL across all your deployment data — logs and infrastructure billing
— in one query. Two tables, both scoped automatically to the deployments
your API key owns.

```bash
cycls sql 'SELECT resource.name AS deploy, ROUND(SUM(cost), 4) AS usd
           FROM billing
           WHERE usage_start_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
           GROUP BY deploy ORDER BY usd DESC'
```

### Query sources

```bash
cycls sql 'SELECT ...'    # positional
cycls sql -f q.sql        # from file
cycls sql -                # from stdin
cat q.sql | cycls sql      # also stdin (auto-detected when piped)
```

### Output

Default: aligned table on a TTY, JSON when piped. Override with `--format
table|json|csv` or the `--json` shortcut. Empty results print `(0 rows)`
to stderr and exit 0.

### Tables

**`logs`** — all log entries for your deployments. Same shape as Cloud
Logging's Log Analytics view. Structured SDK emissions land in `json_payload`.

| Column | Type | Notes |
|---|---|---|
| `timestamp` | TIMESTAMP | |
| `severity` | STRING | |
| `log_name` | STRING | |
| `resource.labels` | JSON | use `JSON_VALUE(resource.labels, '$.service_name')` for the deployment |
| `json_payload` | JSON | structured fields by `level`: `error` (`error_id`, `message`, `stack`), `usage` (`model`, `input`, `output`, `cached`, `cache_create`, `cost`, `ms`), `tool_call` (`tool`, `ms`, `ok`, `output_bytes`). All share `user_id`, `chat_id`, `at`. |
| `text_payload` | STRING | plain stdout/stderr |

**`billing`** — per-SKU per-day cost rows for your deployments.

| Column | Type | Notes |
|---|---|---|
| `usage_start_time`, `usage_end_time` | TIMESTAMP | |
| `service.description` | STRING | always `"Cloud Run"` |
| `sku.description` | STRING | `"CPU Allocation Time"`, `"Memory Allocation"`, … |
| `cost` | FLOAT64 | in `currency` |
| `currency` | STRING | usually `"USD"` |
| `resource.name` | STRING | deployment name directly (e.g. `"super-stage"`) |

### Examples

```sql
-- Count error entries in the last 24h
SELECT COUNT(*) FROM logs
WHERE JSON_VALUE(json_payload, '$.level') = 'error'
  AND timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)

-- Top error kinds for one deployment
SELECT JSON_VALUE(json_payload, '$.kind') AS kind, COUNT(*) AS n
FROM logs
WHERE JSON_VALUE(resource.labels, '$.service_name') = 'super-stage'
  AND JSON_VALUE(json_payload, '$.level') = 'error'
GROUP BY kind ORDER BY n DESC LIMIT 10

-- LLM spend per user this month
SELECT JSON_VALUE(json_payload, '$.user_id')                 AS user_id,
       SUM(CAST(JSON_VALUE(json_payload, '$.cost') AS FLOAT64)) AS spend,
       COUNT(*)                                              AS turns
FROM logs
WHERE JSON_VALUE(json_payload, '$.level') = 'usage'
  AND timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY user_id ORDER BY spend DESC

-- All errors for one chat
SELECT timestamp, json_payload
FROM logs
WHERE JSON_VALUE(json_payload, '$.chat_id') = 'abc-123'
ORDER BY timestamp

-- Cost per deployment over the last 30 days
SELECT resource.name AS deploy, ROUND(SUM(cost), 4) AS usd
FROM billing
WHERE usage_start_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY deploy ORDER BY usd DESC

-- Tool-call latency percentiles per tool (last 7 days)
SELECT JSON_VALUE(json_payload, '$.tool') AS tool,
       APPROX_QUANTILES(CAST(JSON_VALUE(json_payload, '$.ms') AS INT64), 100)[OFFSET(50)] AS p50_ms,
       APPROX_QUANTILES(CAST(JSON_VALUE(json_payload, '$.ms') AS INT64), 100)[OFFSET(95)] AS p95_ms,
       COUNT(*) AS calls
FROM logs
WHERE JSON_VALUE(json_payload, '$.level') = 'tool_call'
  AND timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY tool ORDER BY p95_ms DESC

-- Tool reliability (success rate per tool)
SELECT JSON_VALUE(json_payload, '$.tool') AS tool,
       COUNTIF(JSON_VALUE(json_payload, '$.ok') = 'true') / COUNT(*) AS success_rate,
       COUNT(*) AS calls
FROM logs
WHERE JSON_VALUE(json_payload, '$.level') = 'tool_call'
GROUP BY tool

-- Per-turn duration (avg / median / p95)
SELECT ROUND(AVG(CAST(JSON_VALUE(json_payload, '$.ms') AS INT64)), 0) AS avg_ms,
       APPROX_QUANTILES(CAST(JSON_VALUE(json_payload, '$.ms') AS INT64), 100)[OFFSET(50)] AS median_ms,
       APPROX_QUANTILES(CAST(JSON_VALUE(json_payload, '$.ms') AS INT64), 100)[OFFSET(95)] AS p95_ms
FROM logs
WHERE JSON_VALUE(json_payload, '$.level') = 'usage'

-- Pipe to jq / scripts
cycls sql -f reports/cost.sql --json | jq '.[] | select(.usd > 1.0)'
```

### Caveats

- The first `cycls sql` call after a deployment is created can take 5–10s
  (lazy server-side setup). Subsequent calls are normal latency.
- A per-query cap on scanned bytes is enforced server-side; oversized
  queries fail with a clear error. Add `LIMIT` or narrower predicates.
- Errors from the underlying SQL engine are surfaced verbatim — they're
  actionable.

`cycls cost` is the friendly shortcut for the common cost question;
`cycls sql` is the escape hatch when the canned slicing isn't enough.

## `cycls version`

Print the installed cycls version.

```bash
cycls version
# cycls 0.0.2.129
```i
