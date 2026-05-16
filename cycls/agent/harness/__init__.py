"""The agent harness — the managed LLM loop and the parts a custom loop needs.

`LLM` configures and runs the default loop. To plug your own (`LLM().loop(fn)`),
compose these: `default_loop` (the built-in), `make_provider` (the wire),
`Session` (the message log + persistence), `build_tools`/`dispatch` (the tools),
`compact` (context budget), and the `events` module (dict event factories +
identity `to_ui` for back-compat).
"""
from .llm import LLM
from .main import _run as default_loop
from .providers import make_provider, AnthropicProvider, context_window
from .compact import compact
from . import events
from .events import to_ui
from ..state import Session
from ..tools import build_tools, dispatch
