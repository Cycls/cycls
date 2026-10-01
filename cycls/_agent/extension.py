"""Extensions — a package that brings a tool, and the routes its app calls, to any agent.

    import cycls, cycls_studio

    @cycls.agent(web=cycls.Web().auth(cycls.Clerk()).use(cycls_studio.Studio()),
                 image=cycls.Image().pip("https://github.com/Cycls/cycls-studio/archive/refs/heads/main.zip"), volumes={...})

Declared once, on the agent's Web: the server mounts the extension's routes and every
`LLM.run()` of the agent offers its tools — unless it isn't configured, or the person
switched it off in Settings (its `name` in `disabled_tools`). Its tools are rows like the
builtins' (`Tool`: step line, guidance, interrupted note, once/terminal), so the loop treats
them the same. The helpers below are what such a tool or route needs from a workspace,
so an extension never reaches into the SDK's internals. docs/notes/extensions.md
"""
from .tools import Tool

__all__ = ["Extension", "Tool", "resolve_path", "app_get", "app_reset", "apps_changed",
           "trash", "api_key"]


class Extension:
    """Subclass it, and pass an instance to `cycls.Web().use(...)`.

    `name` is the switch: what Settings shows and `disabled_tools` names (e.g. "Studio").
    `tools()` maps a tool name to `(schema, Tool)`: the schema is what the model sees
    (`{"type": "custom", "name", "description", "input_schema"}`); the row runs it —
    `run(inp, workspace, **kw)` returns an awaitable, `step(inp)` the `{tool_name, step}` line.
    `router(workspace, user)` returns an APIRouter (or None); `workspace` and `user` are
    FastAPI dependencies for the request's workspace (the x-workspace header honoured)
    and its signed-in user. `configured()` False leaves the tools out and the routes
    unmounted — an env var it needs is unset, say."""
    name = ""

    def configured(self):
        return True

    def tools(self):
        return {}

    def router(self, workspace, user):
        return None


_registered = {}    # name -> Extension
_owners = {}        # tool name -> extension name


def register(ext):
    """Make *ext* known to this process: its tool rows join the builtins' registry (dispatch,
    the step line on refetch, guidance), and `names()` lists it for `LLM.run()`. Idempotent —
    the server registers when it's built, tests and custom loops may call it directly."""
    from .tools import _TOOLS
    if not isinstance(ext, Extension) or not ext.name:
        raise TypeError("an extension is a cycls.Extension with a name")
    rows = ext.tools()
    for tool_name, (schema, row) in rows.items():
        if not isinstance(row, Tool) or schema.get("name") != tool_name:
            raise TypeError(f"{ext.name}: tools() maps a name to (schema named so, cycls.extension.Tool)")
        if tool_name in _TOOLS and _owners.get(tool_name) != ext.name:
            raise ValueError(f"{ext.name}: the tool name {tool_name!r} is taken")
    for tool_name, (_, row) in rows.items():
        _TOOLS[tool_name] = row
        _owners[tool_name] = ext.name
    _registered[ext.name] = ext


def names():
    return list(_registered)


def schemas(name):
    """The model-facing tools of a registered, configured extension — [] otherwise."""
    ext = _registered.get(name)
    if ext is None or not ext.configured():
        return []
    return [schema for schema, _ in ext.tools().values()]


# ---- What a tool or a route needs from the workspace ----

def resolve_path(path, root):
    """A workspace path as the builtins read it (`~/`, `/workspace/` and a leading `/` mean the
    workspace; nothing outside it, nothing cycls manages). Raises ValueError."""
    from .tools import _resolve_path
    return _resolve_path(path, root)


async def app_get(ws, slug, key, *, mine=False):
    """A value from an app's data: the workspace's (`cycls.get`), or with `mine` the acting
    person's own (`cycls.me.get`) — what an app keeps current about its viewer."""
    from .state import actor_of, app_shelf, apps_db
    user = actor_of(ws.subject) if mine else None
    return await apps_db(ws).get(app_shelf(slug, key, user=user))


async def app_reset(ws, slug):
    """Drop every row of an app's data — a slug installed afresh mustn't inherit an old app's."""
    from .state import app_shelf, apps_db
    await apps_db(ws).delete(app_shelf(slug))


def apps_changed(ws):
    """An app was installed, upgraded or removed: the model's apps catalog is rebuilt next turn."""
    from .tools import _apps_cache
    _apps_cache.pop(ws.root, None)


def trash(root, rel, reason="replace"):
    """Move a workspace file to the trash (recoverable) before replacing it."""
    from . import trash as _trash
    return _trash.trash_path(root, rel, by="agent", reason=reason)


def api_key():
    """The Cycls API key `cycls.remote` calls deployments with (cycls.api_key or CYCLS_API_KEY)."""
    from cycls._function.main import _get_api_key
    return _get_api_key()
