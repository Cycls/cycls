"""Agent class — App subclass that pre-packages Node.js + Codex."""

from .app import App


class Agent(App):
    """App with Node.js and Codex pre-installed in the container."""

    def __init__(self, func, name, *, node_version=None, codex_version=None, **kwargs):
        nv = node_version or "24.13.0"
        cv = codex_version or "0.98.0"
        agent_apt = ["curl", "proot", "xz-utils"]
        kwargs["apt"] = agent_apt + list(kwargs.get("apt") or [])
        kwargs["run_commands"] = [
            f"curl -fsSL https://nodejs.org/dist/v{nv}/node-v{nv}-linux-x64.tar.xz | tar -xJ -C /usr/local --strip-components=1",
            f"npm i -g @openai/codex@{cv}",
        ] + list(kwargs.get("run_commands") or [])
        kwargs.setdefault("memory", "512Mi")
        super().__init__(func=func, name=name, **kwargs)


def agent(name=None, **kwargs):
    """Decorator that transforms a function into a deployable Agent."""
    def decorator(func):
        return Agent(func=func, name=name or func.__name__, **kwargs)
    return decorator
