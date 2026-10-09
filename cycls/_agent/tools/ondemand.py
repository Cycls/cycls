"""Tools whose long instructions join their description only once a chat uses them.

A registered tool is offered in a short form; from the chat's first call to it on (read back from
the transcript each turn, so nothing is stored) the harness swaps in its whole form. The whole
form may depend on something fetched — Video's contract comes from its service — so `start`
prepares it before the loop, bounded, and `advance` swaps it in when a call has been made.
`begun` is told when a call to a tool starts streaming, before its arguments are complete: Video
warms its GPU then, so the cold start overlaps the minutes the model spends writing.

Only Video registers. Design's on-demand form predates this and keeps its own lines in the loop.

    state = await ondemand.start(tools_list, messages)   # before the loop
    ondemand.advance(state, tools_list, messages)        # inside request(), before each call
    ondemand.begun(state, tool_name, context)            # as a tool call starts streaming
"""
import asyncio
from typing import Callable, NamedTuple


class OnDemand(NamedTuple):
    name: str                      # the tool's name as the model calls it
    label: str                     # its step label, which is what a starting call is known by
    called: Callable               # messages -> has this chat called it
    prepare: Callable              # async (wait) -> the whole form, given at most `wait` seconds
    ready: Callable                # () -> the whole form now, from whatever is cached
    mark: Callable                 # (loaded: bool) -> None: what the model is shown, for the executor
    on_begin: Callable = None      # (context) -> None, fire and forget


_REGISTRY = {}
START_WAIT = 4.0


def register(entry: OnDemand):
    _REGISTRY[entry.name] = entry


class State:
    def __init__(self):
        self.loaded = {}     # name -> bool
        self.begun = set()


async def start(tools_list, messages):
    """Before the loop: each registered tool in the list becomes its short or whole form."""
    state = State()
    for i, t in enumerate(tools_list):
        entry = _REGISTRY.get(t.get("name")) if isinstance(t, dict) else None
        if entry is None:
            continue
        loaded = entry.called(messages)
        if loaded:
            try:
                tools_list[i] = await entry.prepare(START_WAIT)
            except Exception:  # noqa: BLE001 - the short form stays; the executor still works
                loaded = False
        state.loaded[entry.name] = loaded
        entry.mark(loaded)
    return state


def advance(state, tools_list, messages):
    """Inside request(): a tool the chat has now called is whole from this call on."""
    if state is None:
        return
    for name, loaded in list(state.loaded.items()):
        entry = _REGISTRY[name]
        if loaded or not entry.called(messages):
            continue
        for i, t in enumerate(tools_list):
            if isinstance(t, dict) and t.get("name") == name:
                tools_list[i] = entry.ready()
        state.loaded[name] = True
        entry.mark(True)


def begun(state, label, context=None):
    """A tool call has started streaming. Once per run per tool; never awaited, never raises."""
    if state is None:
        return
    for name in state.loaded:
        entry = _REGISTRY[name]
        if entry.label == label and entry.on_begin and name not in state.begun:
            state.begun.add(name)
            try:
                entry.on_begin(context)
            except Exception:  # noqa: BLE001
                pass


def _video():
    from cycls._agent.video import contract, tool

    def ready():
        c = contract.cached()
        return tool.video_tool(True, c["text"] if c else None)

    async def prepare(wait):
        c = await contract.get(wait)
        return tool.video_tool(True, c["text"])

    def on_begin(context):
        from cycls._agent import video   # looked up when called, so a test can stand in for it

        asyncio.ensure_future(video.warm(getattr(context, "workspace", None)))

    return OnDemand(name="video", label="Video", called=tool.video_called, prepare=prepare, ready=ready,
                    mark=tool.VIDEO_LOADED.set, on_begin=on_begin)


register(_video())
