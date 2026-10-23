"""Design generation — a thin client to the shared cycls-design service. See docs/notes/design.md."""
from .client import (Rendered, Unavailable, add_fonts, apply, configured, evaluate, export, export_page, give_font,
                     inspect, outline, render, slides)

__all__ = ["Rendered", "Unavailable", "add_fonts", "apply", "configured", "evaluate", "export", "export_page",
           "give_font", "inspect", "outline", "render", "slides"]
