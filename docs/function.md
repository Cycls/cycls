# Functions

`@cycls.function` turns a Python function into something that runs anywhere —
your Docker, the cloud, a teammate's laptop — without changing a line of it.
One decorator, three verbs:

```python
import cycls

@cycls.function(image=cycls.Image().pip("numpy"))
def simulate(n=1_000_000):
    import numpy as np
    pts = np.random.rand(int(n), 2)
    return float(4 * ((pts ** 2).sum(axis=1) <= 1).mean())
```

```python
simulate.run(1000)        # local Docker
simulate.remote(1000)     # cloud, current code
simulate.deploy()         # cloud, frozen — callable by name from anywhere
```

The mental model: **`run` is local, `remote` is cloud, `deploy` freezes.**
The CLI uses the same words (`cycls run`, `cycls run --remote`,
`cycls deploy`), so learning either teaches both.

## How it works

The function is serialized with cloudpickle — bytecode, closures, captured
variables and all — and executed inside a container built from your `Image`
declaration. Locally the container runs on your Docker; remotely it runs on
Cycls Cloud. Same image, same Python, same pickle: what you ran in dev is
byte-for-byte what runs in prod.

Two version rules keep the pickle safe, both enforced for you:

- The container's Python is pinned to your host's major.minor (bytecode
  doesn't cross Python versions). Passing a mismatched `python_version`
  raises at decoration time.
- The container's cloudpickle is pinned to your host's exact version.

## The Image

Build configuration is declared with the fluent `cycls.Image`:

```python
image = (cycls.Image()
    .pip("numpy", "pandas")          # PyPI packages
    .apt("gcc", "libc6-dev")         # system packages
    .run("playwright install chromium")   # arbitrary build commands
    .copy("routes.py")               # project files → /app (importable)
    .copy("data/", "data/"))         # directories too
```

Images are content-hashed: the hash covers packages, commands, and the
*contents* of copied files, so a change to any of them rebuilds and nothing
else does. First build of an image takes a minute or two; after that it's
cached everywhere the same config appears.

- `.rebuild()` forces a full rebuild (drops the cache).
- Anything installed via `pip`/`apt` is importable inside the function.
- Anything `copy`'d lands in `/app`, which is on `sys.path` — so
  `import routes` works remotely if you declared `copy("routes.py")`.
  Closures, lambdas, and functions defined in the same file travel in the
  pickle automatically; **imports of your own modules need `copy`**.

## Local: `run` and `shell`

```python
result = simulate.run(1000)      # build (or reuse) the image, execute, return
```

A function that takes a `port` parameter is a *server* — `run(port=8000)`
starts it in Docker with the port published. Anything that binds a port is
fair game:

```python
@cycls.function(image=cycls.Image().pip("fastapi", "uvicorn"))
def fast(port):
    from fastapi import FastAPI
    import uvicorn
    app = FastAPI()
    ...
    uvicorn.run(app, host="0.0.0.0", port=port)
```

To poke around inside the exact environment your function sees:

```bash
cycls shell file.py     # interactive bash in the built image
```

## The dev loop: `cycls run`

```bash
cycls run file.py                # rerun on save, local Docker
cycls run file.py --remote      # rerun on save, in the cloud
cycls run file.py --n 1000      # args bind to the function's signature
```

`cycls run` watches your file (and any `copy`'d files) and re-runs on every
save. Runs are sequential — a save during a run queues the next one instead
of killing it. Trailing `--name value` arguments bind to the function's
signature: annotated parameters convert through their annotation
(`n: int` → `int`), unannotated ones are literal-eval'd (`--data "[1,2]"`
becomes a list), and anything else stays a string.

For orchestration — several calls, mixed local/remote, `.map` — mark a
driver:

```python
@cycls.local_entrypoint
def main(n: int = 1_000_000):
    print(simulate.remote(n))
    print(simulate.map([10, 20]))
```

The entrypoint runs *locally* on every save; the verbs inside it decide
where work happens (so `--remote` doesn't apply and is rejected). CLI args
bind to the entrypoint's signature the same way. Keep driver calls inside
it — top-level `simulate.remote(...)` fires on **every import**, including
`cycls deploy` and `cycls shell`.

## Cloud, current code: `remote` and `map`

```python
simulate.remote(1000)            # this exact code, in the cloud, now
simulate.map([10**6] * 100)      # one call per item, autoscaled, ordered
```

`f.remote()` ships the live bytecode to an **executor** — a small service
provisioned once per image (named `exec-{hash}`, shared by every function
with the same image). The first call per image config provisions it
(~90s, one time); every call after is roughly network + compute. Edit the
function and call again: the new code runs. No redeploy, ever.

`f.map(items)` fans one call per item across autoscaled instances and
returns results in input order. It raises on the first failure — for
per-item fault tolerance, return errors as data:

```python
@cycls.function(image=cycls.Image().pip("httpx", "beautifulsoup4"))
def scrape(url):
    try:
        ...
    except Exception as e:
        return {"url": url, "error": str(e)}   # a bad item doesn't sink the batch
```

If the executor vanishes mid-fan, the whole fan retries after
reprovisioning — side effects should be idempotent.

**Live output:** anything the function `print`s streams back to your
terminal *while it runs*, not after. (Concurrent `.map` output interleaves.)

## Cloud, frozen: `deploy` and `cycls.remote`

```bash
cycls deploy file.py
# Deployed: https://simulate.cycls.ai
# Call it: cycls.remote("simulate")(...)
```

`deploy` reads the function's contract: a function that takes `port` deploys
as a **server** on its own URL; a bare function deploys as a **remote
endpoint** — frozen at deploy time, callable by name from any machine with
your API key:

```python
import cycls
pi = cycls.remote("simulate")(10_000_000)
results = cycls.remote("simulate").map([10**6] * 100)
```

The split matters: `f.remote()` runs *the code you're holding* (dev);
`cycls.remote("name")` calls *what was deployed* (product). You rarely want
last week's build while holding the source — and callers who don't have the
source get a stable, named API.

Redeploying the same name updates it in place. `cycls ls` lists deployments,
`cycls rm <name>` deletes one (workspace storage survives; redeploy picks it
back up).

## Security and versioning on the wire

Remote calls are pickle-RPC over HTTPS, protected twice:

- **Auth:** a token derived as `sha256(api_key : name)` — computed
  independently by deployer and caller, stored nowhere. Any machine with
  your `CYCLS_API_KEY` can call your deployments; nobody else can. Rotating
  the key strands existing services (their baked token is from the old key);
  `cycls rm` and redeploy them.
- **Version gate:** every request carries its Python/cloudpickle versions,
  and the server refuses pickles that couldn't cross (Python minor must
  match, cloudpickle major must match) with an explicit error instead of a
  cryptic unpickle crash. Redeploy from the calling environment to resolve.

URLs follow the convention `https://{name}.cycls.ai`.

## Patterns

**Warm state** — the process lives across calls on an instance, so cache
expensive setup in a mutable default and pay it once per instance:

```python
@cycls.function(image=cycls.Image().pip("fastembed"))
def embed(texts, _model={}):
    if "m" not in _model:
        from fastembed import TextEmbedding
        _model["m"] = TextEmbedding("BAAI/bge-small-en-v1.5")
    return [v.tolist() for v in _model["m"].embed(list(texts))]
```

First call loads the model; every call after is warm. That's a self-hosted
embedding API in ten lines (`examples/function/embed.py`).

**Any toolchain** — the image is the world; the closure carries the payload:

```python
@cycls.function(image=cycls.Image().apt("gcc", "libc6-dev"))
def triangle():
    import subprocess
    with open("t.c", "w") as f:
        f.write(C_CODE)                    # C source captured from the closure
    subprocess.run(["gcc", "t.c", "-o", "t"], check=True)
    return subprocess.run(["./t"], capture_output=True, text=True).stdout
```

**Agents calling heavy compute** — keep the agent image thin; deploy the
heavy function separately and call it by name from a tool handler:

```python
read = cycls.remote("scrape")
llm = cycls.LLM().on("read_pages", lambda inp: asyncio.to_thread(read.map, inp["urls"]))
```

More in `examples/function/`: `add.py`, `c.py`, `remote.py`, `scrape.py`,
`extract.py`, `embed.py`, `monte_carlo.py`, plus the server-shaped
`fast.py`, `jupyter.py`, `marimo.py`.

## Limits, honestly

- **First provision per image config is ~90s** (a real cloud build). After
  that, calls are fast; idle services scale to zero and cost nothing.
- **Cold starts**: the first call to an idle service takes a few seconds.
- **Executors linger** (`exec-*` in `cycls ls`). They're free while idle;
  `cycls rm` reaps them.
- **Payloads** should stay well under ~30MB per call.
- **Tracebacks from remote code lack source lines** — the container has your
  bytecode, not your files. The filename and line number are still correct.
- **Calls time out after an hour.** Long jobs should checkpoint or split.
- `cycls run`/`deploy`/`shell` all **import your file** — keep it
  side-effect-free (no top-level `.run()`/`.remote()` calls).

## Reference

| surface | meaning |
|---|---|
| `@cycls.function(name=, image=)` | declare a containerized function |
| `cycls.Image().pip/apt/run/copy/rebuild` | build config, content-hashed |
| `f.run(*args, **kwargs)` | execute in local Docker (`port=` serves) |
| `f.remote(*args, **kwargs)` | execute current code in the cloud |
| `f.map(items, workers=16)` | fan current code across instances, ordered |
| `f.deploy()` | freeze + publish (server or endpoint by signature) |
| `cycls.remote(name)` | callable for a deployed endpoint (`.map` too) |
| `@cycls.local_entrypoint` | the file's dev-loop driver |
| `cycls run file.py [--remote] [--args]` | rerun on save, local or cloud |
| `cycls deploy file.py` | deploy |
| `cycls shell file.py` | bash inside the image |
| `cycls ls` / `cycls rm <name>` | list / delete deployments |

The commands are covered in full in [cli.md](cli.md).
