"""State demo: KV + FS. Run with: uv run examples/app/state.py"""
import cycls

@cycls.app(state=True, copy=[".env"])
async def state_demo(context):
    msg = context.last_message.lower()

    # KV: counter
    if "count" in msg:
        count = (await context.kv.get("count") or 0) + 1
        await context.kv.set("count", count)
        yield f"Count: {count}"

    # KV: remember/recall
    elif msg.startswith("remember "):
        await context.kv.set("memory", msg[9:])
        yield f"Remembered: {msg[9:]}"
    elif "recall" in msg:
        yield f"Memory: {await context.kv.get('memory') or 'nothing'}"

    # FS: save/read/list
    elif msg.startswith("save ") and ":" in msg:
        name, content = msg[5:].split(":", 1)
        await context.fs.write(f"/{name.strip()}", content.strip())
        yield f"Saved {name.strip()}"
    elif msg.startswith("read "):
        yield await context.fs.read(f"/{msg[5:].strip()}")
    elif "files" in msg:
        yield "\n".join(await context.fs.list("/") or ["No files"])

    # Help
    else:
        yield "Commands: count, remember X, recall, save name: content, read name, files"

state_demo.local()
