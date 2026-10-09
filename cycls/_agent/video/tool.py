"""The Video tool as the model is given it.

Every request carries the SHORT form (about 700 characters): what Video is for and that `guide`
comes first. The contract (how a composition is written, about 6,000 characters, fetched from the
service and verified, contract.py) joins the description from the first Video call of a chat on:
the harness swaps the tool through tools/ondemand.py, read back from the transcript each turn.

Unlike Design's on-demand form, a call made before the guide is never discarded: losing a
composition costs minutes of writing. It runs, and its reply says the instructions are now loaded.
"""
import contextvars

# What the model was shown when it made a call: True the whole tool, False the short form (the
# harness swaps it in after this call), None when no harness swaps it (a custom loop): then `guide`
# answers with the instructions themselves.
VIDEO_LOADED = contextvars.ContextVar("video_loaded", default=None)
ACTIONS = ("guide", "write", "edit", "template", "look", "render", "restore")

_PURPOSE = (
    "Video: make short videos that move — explainers, reels and stories, announcements, animated stats and "
    "charts, a deck or a design turned into a video, on-screen text and captions. They are silent and generated: "
    "no footage or sound yet. Stills, posters, slides and documents are Design, not Video. "
    "Each video is one file, videos/<name>.video.html; `render` makes videos/<name>.mp4 and opens it for the user."
)

_SHORT = _PURPOSE + (
    "\n\nThis is the SHORT form of the tool: how a video is written is not in it. Call {\"action\": \"guide\"} "
    "first — the full instructions load into this description and the renderer starts warming up — then write "
    "the video."
)

_ACTIONS_TEXT = """ACTIONS
- guide: load these instructions (done) and start the renderer; lists the formats, fonts and the videos already here.
- write {name, html}: save the whole composition as videos/<name>.video.html and check it. Or {name, path} to adopt a composition you wrote with the editor. Saved even when the checks find errors.
- edit {name, changes: [{old, new, all?}]}: exact find and replace in the saved composition; every change applies or none does. Same checks as write. Prefer it to rewriting the whole file.
- template {name, template, vars}: make the composition from one of the templates above with your words, numbers and images (the brand kit fills the colours and fonts you leave out), then the same checks as write.
- look {name, at?: [seconds], zoom?}: the frames at those times (up to 9), zoom a CSS selector or "x,y,w,h" to look closely. With no times, the file on disk is checked again.
- render {name, quality?: "final" | "draft"}: the MP4, videos/<name>.mp4, opened for the user. Refused while the checks report errors. It takes a minute or two; if the reply says it is still rendering, call render again to collect it — never start over.
- restore {name}: put back the version before the last save.

A reply shows lint errors with their fixes, or the browser check and ONE sheet of frames, each labelled with its time. Look at the sheet before you render."""


def _schema():
    return {"type": "object", "properties": {
        "action": {"type": "string", "enum": list(ACTIONS),
                   "description": "guide (first), write, edit, template, look, render, restore."},
        "name": {"type": "string",
                 "description": "The video's name: videos/<name>.video.html, rendered to videos/<name>.mp4. "
                                "Lowercase words and hyphens, e.g. launch-reel."},
        "html": {"type": "string", "description": "write: the whole composition, a full HTML document."},
        "path": {"type": "string",
                 "description": "write: a composition already in the workspace to adopt instead of passing html."},
        "changes": {"type": "array", "description": "edit: exact replacements, applied in order.",
                    "items": {"type": "object", "properties": {
                        "old": {"type": "string", "description": "Text that occurs exactly once (or set all)."},
                        "new": {"type": "string"},
                        "all": {"type": "boolean", "description": "Replace every occurrence."}},
                        "required": ["old", "new"]}},
        "template": {"type": "string", "description": "template: which template (they are listed in the instructions)."},
        "vars": {"type": "object", "description": "template: its variables, as the instructions list them."},
        "at": {"type": "array", "items": {"type": "number"},
               "description": "look: times in seconds, up to 9."},
        "zoom": {"type": "string", "description": "look: a CSS selector or x,y,w,h to look at closely."},
        "quality": {"type": "string", "enum": ["final", "draft"],
                    "description": "render: final (default) or draft (faster, larger file, softer)."},
    }, "required": ["action"]}


_SHORT_TOOL = {"type": "custom", "name": "video", "description": _SHORT, "input_schema": _schema()}
_full_cache = {}


def full_description(contract_text):
    return f"{_PURPOSE}\n\nHOW A VIDEO IS WRITTEN (contract)\n{contract_text.strip()}\n\n{_ACTIONS_TEXT}"


def video_tool(loaded=False, contract_text=None):
    """The tool as a chat carries it: short until the chat uses Video, then whole. The whole form
    is the same dict for the same contract, so the prompt cache holds across turns."""
    if not loaded:
        return _SHORT_TOOL
    if contract_text is None:
        from .fallback import FALLBACK
        contract_text = FALLBACK["text"]
    if contract_text not in _full_cache:
        _full_cache.clear()
        _full_cache[contract_text] = {"type": "custom", "name": "video",
                                      "description": full_description(contract_text), "input_schema": _schema()}
    return _full_cache[contract_text]


def is_video(tool):
    return isinstance(tool, dict) and tool.get("name") == "video"


def video_called(messages):
    """Has this chat called the Video tool — the guide included?"""
    for m in messages or []:
        if m.get("role") != "assistant" or not isinstance(m.get("content"), list):
            continue
        if any(isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "video" for b in m["content"]):
            return True
    return False


VIDEO_PROMPT = (
    "Video and Design: anything that moves — a reel, a story, an animated explainer, a deck or a design turned "
    "into a video — is Video; still images, posters, slides and documents are Design. To turn a deck into a "
    "video, export its slides as JPEG with Design first, then write a video that shows those files."
)
