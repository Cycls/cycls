# Extensions — a package's tool and routes, on any agent

An extension is a Python package that brings a tool, and the HTTP routes its app calls, to
an agent that declares it once. The first one is Cycls Studio (a Blender-style 3D app, its own
repo, `cycls-studio`): it used to be a builtin, which tied every Studio fix to an SDK release
and put the Studio in every agent's wheel. Now the SDK knows nothing about it.

```python
import cycls, cycls_studio

@cycls.agent(image=cycls.Image().pip("https://github.com/Cycls/cycls-studio/archive/refs/heads/main.zip"),
             web=cycls.Web().auth(cycls.Clerk()).use(cycls_studio.Studio()),
             volumes={"/workspace": cycls.Volume("my-agent")})
async def my_agent(context):
    async for ev in llm.run(context=context):
        yield ev
```

## The contract

```python
class Extension:
    name = ""                        # the switch: Settings and `disabled_tools` name it
    def configured(self): ...        # False: tools left out, routes unmounted (an env var unset)
    def tools(self): ...             # {tool name: (schema, Tool)}
    def router(self, workspace, user): ...   # an APIRouter, or None
    def opens(self): ...             # the files its app opens: ("blend",)
    async def open(self, workspace, path): ...   # {"app", "command", "changed"?}
```

- **`tools()`** maps a tool name to the schema the model sees (Anthropic shape:
  `{"type": "custom", "name", "description", "input_schema"}`) and a `Tool` row — the
  builtins' row ([tool-rows.md](tool-rows.md)): `run(inp, workspace, **kw)`, `step(inp)`, and
  `prompt`, `interrupted`, `once`, `terminal`. So an extension's tool gets everything a builtin
  does: its guidance in the system prompt while it's on, its step line on a reloaded chat, its
  note when a call is cancelled. `run` returns a string, or `{_model, _ui}` where `_ui` is one
  UI event or a list (open the render *and* tell the open app).
- **`router(workspace, user)`** gets two FastAPI dependencies: the request's workspace (the
  `x-workspace` header resolved as every state route resolves it) and the signed-in user. Give
  routes a literal path (`/apps/studio/engine`, not `/apps/{slug}/engine`): a pattern would
  shadow another extension's routes.
- **`configured()`** is read when the server is built (routes) and on every run (tools).
- **`opens()`** and **`open()`** are the next section.

## A file its app opens

A file no canvas shows used to download when someone opened it in Files. An extension whose app
reads that kind of file claims it, and the file opens in the app (a `.blend`, in the Studio).

```python
def opens(self):
    return ("blend",)                       # extensions, lower case, no dot

async def open(self, workspace, path):      # path: the file, inside the workspace
    await install(workspace)                # the app may not be in this workspace yet
    return {"app": "apps/studio/index.html",
            "command": {"type": "open_file", "path": path},
            "changed": installed_or_upgraded}
```

- **What can be claimed.** Only a kind the canvas has no viewer for (`app_opens()` in
  `web/routers.py` drops the rest): an extension can't take `.pdf` or `.glb` away from their
  viewers. The first extension to claim a kind keeps it. An unconfigured one claims nothing.
- **How the browser knows.** `/config` carries `opens: {"blend": "Studio"}`. The Files panel
  opens such a file instead of downloading it, and so does every other way a file reaches the
  canvas (`openFileInCanvas` in `chat.tsx`).
- **The call.** `POST /apps/open {path}` resolves the path as the tools do, finds the extension
  and awaits `open(workspace, path)`. It answers `{app, name, command, changed}`; `app` must be
  an `apps/<slug>/index.html`. A `ValueError` from `open` is a 409 whose line the person is
  shown; anything the extension doesn't take is a 404, and the file gets a tab of its own, with
  the download card, as before.
- **What the host does.** It puts the app on the canvas and hands it `command` through
  `cycls.onCommand`, held until the app's channel is up ([apps.md](apps.md), *Pushed into*). With
  `changed`, a tab still showing the bundle that was replaced is closed first and opened anew:
  the document in it wouldn't know the command.
- **What opening means is the app's.** The SDK only delivers the path. The Studio holds one
  scene, so it asks before it replaces one someone made, and does the work through its own
  route.

## How it's wired

- `Web().use(*extensions)` keeps them (one per `name`; the first wins). It needs `auth(...)` —
  an extension works in the signed-in user's workspace — and `Agent` refuses it without.
- When the server is built, `install_routers` calls `extension.register(ext)` for each and
  mounts its router if it's configured. `register` puts the tool rows into `_TOOLS` (a name a
  builtin or another extension has is refused) and lists the extension in `names()`.
- `LLM.run()` adds every registered extension's `name` to the run's allowed tools unless the
  person switched it off in Settings (`disabled_tools`). `build_tools` turns a name it doesn't
  know as a builtin into `extension.schemas(name)` — the tools of a configured extension.
- Registration is per process and idempotent. Tests and custom loops can call
  `cycls._agent.extension.register` directly.

Pickling: the extension instance rides the agent into the container by reference to its class,
so the package must be installed in the image (`cycls.Image().pip(...)`). Cycls Studio
isn't on PyPI: an archive URL from GitHub installs it without git, which the image doesn't have.

## What a tool or a route may use

`cycls.extension` is the surface, so a package never imports SDK internals:

| | |
|---|---|
| `Extension`, `Tool` | the base class and the row |
| `resolve_path(path, root)` | a workspace path as the builtins read it; `ValueError` outside it or under `.db`/`.trash`/… |
| `await app_get(ws, slug, key, mine=False)` | an app's data — the workspace's (`cycls.get`), or the acting person's own (`cycls.me`) |
| `await app_reset(ws, slug)` | drop an app's data rows (a slug installed afresh) |
| `apps_changed(ws)` | the model's apps catalog is rebuilt next turn |
| `trash(root, rel, reason)` | move a workspace file to the trash before replacing it |
| `api_key()` | the key `cycls.remote` calls deployments with |

An app an extension installs names it in its manifest — `app.json` `"extension": "<name>"` —
and `build_app` refuses to build over it: the extension's own tool changes it.

An app talks back through the bridge verbs in [apps.md](apps.md): `cycls.engine` reaches the
extension's route, `cycls.onCommand` receives the tool's `app_command` events, `cycls.ask` hands
work back to the chat.

Tests: `tests/agent/extension_test.py`; the held command in `client/tests/app-bridge.test.ts`.
