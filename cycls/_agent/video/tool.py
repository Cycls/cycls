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
ACTIONS = ("guide", "write", "edit", "template", "look", "render", "restore", "voice", "music", "footage", "subtitles")

_PURPOSE = (
    "Video: make short videos that move — explainers, reels and stories, announcements, animated stats and "
    "charts, a deck or a design turned into a video, on-screen text and captions — with a voice-over in Arabic "
    "or English and music when the person wants sound. It also cuts the person's own clips (an interview, a "
    "phone video) and stock footage into a video, captioned from what is said. "
    "Stills, posters, slides and documents are Design, not Video. "
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
- render {name, quality?: "final" | "draft"}: the MP4, videos/<name>.mp4, opened for the user; when something is said in it, subtitle files beside it (videos/<name>.srt and .vtt). Refused while the checks report errors. It takes a minute or two; if the reply says it is still rendering, call render again to collect it — never start over.
- subtitles {name} then {name, to, lines}: the render's subtitles in another language. The first call lists the lines of videos/<name>.srt, numbered; translate them yourself and send them back in order with the language code (to: "ar", "en", …): they are written as videos/<name>.<to>.srt and .vtt with the original's timings.
- restore {name}: put back the version before the last save.
- voice {name, text, voice?: "default" | "saudi", language?: "ar" | "en"}: read the script aloud as videos/voice/<name>.m4a, with when each sentence and word is spoken; the reply gives the <audio> line to use. Call it before writing the scenes. The same name and text again is the same take; a changed text replaces it (the old take kept as a version). If the reply says it is still reading, call it again to collect it.
- music {query?}: the library's tracks for a mood or a few words ("calm piano", "upbeat"), each with the id to use as src="music:<id>".
- footage {path} or {stock: "a few words", pick?, orientation?}: make a clip ready for video — one of the person's, by its workspace path (MP4, MOV, WebM; up to 512 MB and 10 minutes), or a stock clip found for those words and saved in the workspace. The reply is what you cannot see or hear: the clip's length and shape, where its shots change, a sheet of its frames, what is said in it sentence by sentence with times, and the <video> line to use. Call it before writing a video that uses the clip; calling it again for the same clip is free. A long clip takes a minute or two: if the reply says it is still sending or reading, call footage again with the same path. With tidy: true the reply also gives the clip tidied — its long pauses cut, every word kept — as <video> pieces to put back to back: use it when the person asks to tighten, clean up or shorten a talking clip.

A reply shows lint errors with their fixes, or the browser check and ONE sheet of frames, each labelled with its time, the pieces of footage as you placed them, and the sound map when there is sound. Look at the sheet before you render.

THE PERSON'S EDITS
The person can open a video in the editor (Edit on the canvas) and change it by hand; their saves are kept as versions. When they select something there and ask you, their message carries a line such as [Selected in videos/launch.video.html at 4.2 s: title (h1) "Ready when you are"]: the video, where the playhead was, and each selected element by its id or name, its tag and its text. Change that element (find it by its id in the file) and keep what they did by hand. After they edit, read the file before you `edit` it: a save from the editor writes the file afresh, so text you remember may no longer match exactly."""


def _schema():
    return {"type": "object", "properties": {
        "action": {"type": "string", "enum": list(ACTIONS),
                   "description": "guide (first), write, edit, template, look, render, restore, voice, music, footage."},
        "name": {"type": "string",
                 "description": "The video's name: videos/<name>.video.html, rendered to videos/<name>.mp4. "
                                "Lowercase words and hyphens, e.g. launch-reel."},
        "html": {"type": "string", "description": "write: the whole composition, a full HTML document."},
        "path": {"type": "string",
                 "description": "write: a composition already in the workspace to adopt instead of passing html. "
                                "footage: the clip's workspace path, e.g. uploads/interview.mp4."},
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
        "text": {"type": "string", "description": "voice: the script to read aloud; figures, prices and dates are read out."},
        "voice": {"type": "string", "enum": ["default", "saudi"],
                  "description": "voice: default (any language) or saudi (Saudi dialect)."},
        "language": {"type": "string", "enum": ["ar", "en"],
                     "description": "voice: the script's language, when not plain from it. footage: the language spoken "
                                    "in the clip, when you know it."},
        "query": {"type": "string", "description": "music: a mood or a few words, e.g. calm piano."},
        "stock": {"type": "string", "description": "footage: a few words to find a stock clip, e.g. waves at sunset."},
        "pick": {"type": "integer", "description": "footage with stock: which result to fetch (0 is the first)."},
        "orientation": {"type": "string", "enum": ["landscape", "portrait", "square"],
                        "description": "footage with stock: the shape of clip to look for."},
        "tidy": {"type": "boolean", "description": "footage: also give the clip with its long pauses cut, as pieces."},
        "to": {"type": "string", "description": "subtitles: the language code of the translation, e.g. ar or en."},
        "lines": {"type": "array", "items": {"type": "string"},
                  "description": "subtitles: the translated lines, one per line listed, in order."},
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
    "video, export its slides as JPEG with Design first, then write a video that shows those files. Video can "
    "add a voice-over (Arabic or English) and music; add sound only when the person asks for it or agrees. "
    "A video file the person attaches (an interview, a product clip) is cut, captioned and titled with Video too: "
    "its `footage` action reads the clip first."
)
