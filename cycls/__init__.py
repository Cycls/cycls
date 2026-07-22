try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

_EXPORTS = {
    "._function": ("function", "Function", "Image", "Volume", "Cron"),
    "._function.remote": ("remote", "local_entrypoint", "RemoteError"),
    "._app": ("app", "App", "Clerk", "GCP", "JWT", "User",
              "Sandbox", "SandboxResult", "DB", "Workspace"),
    "._agent": ("LLM", "MCP", "agent", "Agent", "events", "to_ui"),
    "._agent.web": ("Web",),
    "._agent.logs": ("log",),
}

__all__ = [n for names in _EXPORTS.values() for n in names]

api_key = None
base_url = None


def __getattr__(name):
    for mod, names in _EXPORTS.items():
        if name in names:
            import importlib
            value = getattr(importlib.import_module(mod, __name__), name)
            globals()[name] = value
            return value
    raise AttributeError(f"module 'cycls' has no attribute {name!r}")


def __dir__():
    return sorted({*globals(), *__all__})
