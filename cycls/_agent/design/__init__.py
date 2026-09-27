"""Design generation for Cycls agents — a thin client to the shared cycls-design
service (OpenPencil headless). The SDK ships this client; the service is deployed
once. See docs/notes/design.md."""
from .client import Rendered, Unavailable, apply, configured, evaluate, export, inspect, render, slides

__all__ = ["Rendered", "Unavailable", "apply", "configured", "evaluate", "export", "inspect", "render", "slides"]
