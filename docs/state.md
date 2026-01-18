# State (KV + Filesystem)

> **Experimental** - This feature is local-only. Cloud persistence is not yet supported.

Enable persistent state per user with `state=True`. Provides key-value store and filesystem APIs built on [Turso's AgentFS](https://docs.turso.tech/agentfs).

## Enable State

```python
@cycls.app(state=True)
async def my_app(context):
    # context.kv - key-value store
    # context.fs - filesystem
    ...
```

## Key-Value Store (`context.kv`)

Simple key-value storage with JSON serialization.

```python
# Set a value
await context.kv.set("key", "value")
await context.kv.set("user", {"name": "Alice", "score": 100})

# Get a value (returns None if not found)
value = await context.kv.get("key")
user = await context.kv.get("user")

# Get with default
count = await context.kv.get("count") or 0

# Delete
await context.kv.delete("key")

# List keys by prefix
items = await context.kv.list("user:")  # Returns [{"key": "user:1", "value": ...}, ...]
```

## Filesystem (`context.fs`)

Virtual filesystem for storing files and documents.

```python
# Write a file
await context.fs.write("/notes.txt", "Hello world")
await context.fs.write("/data/config.json", '{"key": "value"}')

# Read a file
content = await context.fs.read("/notes.txt")

# List directory
files = await context.fs.list("/")  # Returns list of filenames

# Delete a file
await context.fs.delete("/notes.txt")
```

## User Scoping

State is automatically scoped per user when `auth=True`:

```python
@cycls.app(state=True, auth=True)
async def my_app(context):
    # Each authenticated user gets isolated state
    await context.kv.set("preference", "dark")  # Only this user sees this
```

Without auth, state uses "anonymous" scope (shared).

## Example

```python
import cycls

@cycls.app(state=True)
async def counter(context):
    count = (await context.kv.get("count") or 0) + 1
    await context.kv.set("count", count)
    yield f"Count: {count}"

counter.local()
```

## Storage

State is stored locally in SQLite via [Turso's AgentFS](https://docs.turso.tech/agentfs). Files are stored in `.agentfs/` directory, scoped by user ID. Cloud persistence (Turso Cloud) is planned but not yet supported.
