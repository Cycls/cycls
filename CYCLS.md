# cycls CLI

Single command: `cycls`. Subcommands: `init`, `run`, `deploy`, `ls`, `rm`, `logs`, `version`.

```bash
cycls <subcommand> [args]
```

Auth (for any command that hits the cloud): set `CYCLS_API_KEY` env var, or
`cycls.api_key = "..."` in Python. `CYCLS_BASE_URL` overrides the default
`https://api.cycls.ai`.

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

# Errors in the last hour
cycls logs super-stage --query 'jsonPayload.level="error" AND timestamp >= "1h ago"'
```

`-f` works with `-q` — the filter is reapplied on every poll.

Full query syntax: https://cloud.google.com/logging/docs/view/logging-query-language

### What's NOT logged

Errors the harness catches and yields as callouts (rate-limit retry
exhaustion, compaction failure, tool timeouts) are visible to the user
in the chat but NOT structured-logged — they're known/handled, not QA
signals. The encoder logs only what's truly unexpected.

## `cycls version`

Print the installed cycls version.

```bash
cycls version
# cycls 0.0.2.127
```i
