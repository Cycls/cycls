"""The Video tool's executor. `_exec_video(inp, workspace, ctx)` reads a call and makes it:
guide, write, edit, look, render, restore. Registered in cycls/_agent/tools as the `video` tool.

The SDK owns the schema, the argument checks, every write to the workspace and the report; the
service owns the contract, the checks, the frames, the preview and the render.
"""
import asyncio
import difflib
import hashlib
import json
import re
from pathlib import Path

from .. import trash, versions
from ..design.deck import lock
from ..design.store import write_fig
from ..paths import _resolve_path
from . import contract as contract_mod
from . import files, media, report
from .tool import ACTIONS, VIDEO_LOADED

# How long a call waits for the service before it answers anyway. The harness has no per-tool
# limit, so the client keeps its own: a save with its frames, a look, a render.
BUDGET = {"check": 300, "look": 180, "render": 900}
MAX_HTML = 400_000

_LOADED_NOTE = ("\n\nVideo's full instructions were not loaded when you made this call; they are now in this tool's "
                "description. Read them before your next change.")


def _err(text):
    return f"Error: {text}"


def _read_changes(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        return None
    out = []
    for c in raw:
        if not isinstance(c, dict) or not isinstance(c.get("old"), str) or not isinstance(c.get("new"), str) or not c["old"]:
            return None
        out.append(c)
    return out


def apply_changes(html, changes):
    """Every change or none. → (new html, None) or (None, why)."""
    out = html
    for i, c in enumerate(changes, 1):
        n = out.count(c["old"])
        if n == 0:
            first = c["old"].strip().splitlines()[0] if c["old"].strip() else c["old"]
            lines = out.splitlines()
            near = difflib.get_close_matches(first.strip(), [ln.strip() for ln in lines], n=1, cutoff=0.5)
            hint = ""
            if near:
                at = next(k for k, ln in enumerate(lines, 1) if ln.strip() == near[0])
                hint = f" The closest line is {at}: {near[0][:200]!r}"
            return None, f"change {i}: the old text is not in the composition (nothing was changed).{hint}"
        if n > 1 and not c.get("all"):
            return None, (f"change {i}: the old text occurs {n} times (nothing was changed). Give more of the "
                          "surrounding text so it occurs once, or set all to replace every one.")
        out = out.replace(c["old"], c["new"]) if c.get("all") else out.replace(c["old"], c["new"], 1)
    return out, None


def _sha(html, images_files):
    h = hashlib.sha256(html.encode("utf-8"))
    for name in sorted(images_files):
        h.update(name.encode())
    return h.hexdigest()


async def _save(root, chat, name, html, reason):
    """Write the composition under this chat's name for it. → (name, rel, note)."""
    asked = name
    name = files.claim(root, chat, name)
    rel = files.composition(name)
    async with lock(root / rel):
        await write_fig(root, rel, html.encode("utf-8"), by="agent", reason=reason)
    files.remember(root, chat, name)
    note = (f" It is named '{name}' because a video called '{asked}' was already here and is not this chat's."
            if name != asked else "")
    return name, rel, note


def _root_text(root_info):
    if not root_info:
        return ""
    d, w, h = root_info.get("duration"), root_info.get("width"), root_info.get("height")
    return f"{d:g} s, {w}x{h}" if d and w and h else ""


async def _check(workspace, root, rel, html, *, kind="review", params=None, budget=None, again=True):
    """Lint at the door, then (when clean) the browser check and a sheet, or the frames asked for.
    → (text, sheet blocks, lint passed)."""
    from cycls._agent import video

    images, image_files, problems = media.collect(html, root)
    if problems:
        return "The images could not all be sent:\n" + "\n".join(f"- {p}" for p in problems), [], False
    # Keyed, so a retry after a dropped connection is the same job, not a second one.
    key = hashlib.sha256(f"{getattr(workspace, 'subject', '')}|{kind}|{_sha(html, image_files)}|"
                         f"{json.dumps(params or {}, sort_keys=True)}".encode()).hexdigest()
    try:
        job = await video.submit(workspace, kind, html, images, image_files, params=params, key=key)
    except video.Refused as e:
        text = report.findings_text(e.findings, title="Lint")
        return (text or str(e)) + "\nFix them with `edit`; the file is saved as it is.", [], False
    except video.OverAllowance as e:
        # Said only after lint passed: the file is good to preview; frames and the MP4 wait.
        return (f"Lint clean. {e} The file is saved and its preview works; the browser check, frames and "
                "the MP4 wait until then — tell the person so."), [], True
    shape = _root_text(job.get("root"))
    head = f"Lint clean ({shape})." if shape else "Lint clean."
    r = await video.wait(workspace, job["token"], budget or BUDGET["check"])
    state = r.get("state")
    if state == "gone" and again:   # the service restarted under the job: ask once more
        return await _check(workspace, root, rel, html, kind=kind, params=params, budget=budget, again=False)
    if state == "pending":
        what = "the frames" if kind == "look" else "the browser check and the frames"
        return (f"{head} The renderer is still starting or busy, so {what} are not ready yet (about "
                f"{r.get('eta_s', 60)} s more). Call `look` for them."), [], True
    if state != "done":
        return f"{head} The check could not run: {r.get('error') or state}.", [], True
    parts = [head]
    if kind == "review":
        if r.get("browser_skipped") or r.get("not_ready"):
            parts.append("The browser check did not run to the end (the page was not ready in time): treat it as "
                         "not checked, and look at the frames.")
        found = report.findings_text(r.get("findings") or [], title="Browser check")
        parts.append(found or "Browser check: no issues.")
    elif r.get("not_ready"):
        parts.append("The page was not ready in time for these frames: they may show it before it settled.")
    times = job.get("times") or []
    blocks = report.sheet_blocks(r.get("sheet"), times, rel)
    if blocks:
        parts.append(report.LOOK_AT_IT)
    return "\n".join(parts), blocks, True


def _shown(rel, name, clean):
    """What the canvas is told after a save: refresh the composition wherever it is open, and open
    it once it lints clean (with errors it would only show why it cannot play)."""
    ui = [{"type": "ui", "action": "refresh_canvas", "path": rel}]
    if clean:
        ui.insert(0, {"type": "ui", "action": "open_canvas", "path": rel, "name": f"{name}.video.html"})
    return ui


def _with_brand(root, template, given):
    """The workspace brand kit for the colours and fonts the model left out: the template's own
    defaults stay where the kit says nothing, or names a font the catalogue lacks."""
    from ..design.brand import _load_brand
    from .contract import cached
    from .fallback import FALLBACK

    brand = _load_brand(root) or {}
    if not brand:
        return given
    c = cached() or FALLBACK
    fonts = {f["family"] for f in c.get("fonts") or []}
    takes = next((t["vars"] for t in (cached() or {}).get("templates") or [] if t.get("id") == template), None)
    out = dict(given)
    for var, value in (("accent", brand.get("accent") or brand.get("primary")),
                       ("heading_font", brand.get("heading") if brand.get("heading") in fonts else None),
                       ("body_font", brand.get("body") if brand.get("body") in fonts else None)):
        if value and var not in out and (takes is None or var in takes):
            out[var] = value
    return out


def _result(text, blocks, note="", ui=None):
    text = report.clip(text + note)
    if not blocks and ui is None:
        return text
    out = {"_model": [*blocks, {"type": "text", "text": text}] if blocks else text}
    if ui is not None:
        out["_ui"] = ui
    return out


async def _guide(workspace, root, loaded):
    from cycls._agent import video

    asyncio.ensure_future(video.warm(workspace))
    c = await contract_mod.get(30)
    fonts = ", ".join(f["family"] + (" (Arabic)" if "arabic" in f.get("scripts", []) else "") for f in c["fonts"])
    formats = ", ".join(f"{k} {v[0]}x{v[1]}" for k, v in c["formats"].items())
    have = files.existing(root)
    lines = [f"Video's instructions are loaded (contract {c['version']}); the renderer is starting up.",
             f"Formats: {formats}.", f"Fonts: {fonts}."]
    if c.get("fallback"):
        lines.append(f"(The service's contract could not be used — {c['fallback']} — so the built-in copy is.)")
    lines.append("Videos here: " + (", ".join(f"{n}{' (rendered)' if mp4 else ''}" for n, mp4 in have) if have else "none yet."))
    if loaded is None:   # no harness swaps this tool's description: the instructions come in the reply
        lines.append("\n" + c["text"])
    else:
        lines.append("They are in this tool's description now: read them, then `write` the video.")
    return "\n".join(lines)


async def _render(workspace, root, chat, name, quality):
    from cycls._agent import video

    rel = files.composition(name)
    try:
        html = (root / rel).read_text(encoding="utf-8")
    except FileNotFoundError:
        return _err(f"there is no {rel} to render; `write` it first.")
    images, image_files, problems = media.collect(html, root)
    if problems:
        return _err("the images could not all be sent:\n" + "\n".join(f"- {p}" for p in problems))
    sha = _sha(html, image_files)
    pending = files.render_pending(root, chat, name)
    collected = bool(pending and pending.get("sha") == sha and pending.get("quality") == quality)
    if collected:
        token = pending["token"]
    else:
        key = hashlib.sha256(f"{getattr(workspace, 'subject', '')}|{name}|{sha}|{quality}".encode()).hexdigest()
        try:
            job = await video.submit(workspace, "render", html, images, image_files, params={"quality": quality}, key=key)
        except video.Refused as e:
            return report.findings_text(e.findings, title="Not rendered — lint") + "\nFix them with `edit`, then render."
        token = job["token"]
        files.render_started(root, chat, name, token, sha, quality)
    r = await video.wait(workspace, token, BUDGET["render"])
    if r.get("state") in ("gone", "expired") and collected:
        files.render_done(root, chat, name, None)   # that job is lost; start it again
        return await _render(workspace, root, chat, name, quality)
    if r.get("state") == "pending":
        return (f"Still rendering {rel} (about {r.get('eta_s', 60)} s more). Call `render` again with the same name "
                "to collect it — it keeps running; do not change the composition meanwhile.")
    if r.get("state") != "done":
        files.render_done(root, chat, name, None)
        return _err(f"the render failed: {r.get('error') or r.get('state')}. "
                    + (f"Details: {r['log'][-600:]}" if r.get("log") else ""))
    target = name
    if (root / files.mp4(target)).exists():
        if files.rendered_by_me(root, chat, target):
            await asyncio.to_thread(trash.trash_path, root, files.mp4(target), "agent", "re-render")
        else:
            n = 2
            while (root / files.mp4(f"{name}-{n}")).exists():
                n += 1
            target = f"{name}-{n}"
    dest = root / files.mp4(target)
    size = await video.fetch(workspace, token, dest, root / ".tmp" / (chat or "video"))
    files.render_done(root, chat, name, sha)
    if target != name:
        files.render_done(root, chat, target, sha)
    v = r.get("video") or {}
    stream = v.get("stream") or {}
    facts = [f"{v['duration']:.1f} s" if v.get("duration") else "",
             f"{stream.get('width')}x{stream.get('height')}" if stream.get("width") else "",
             f"{size / 1048576:.1f} MB", f"rendered in {v['render_s']:.0f} s" if v.get("render_s") else ""]
    rel_mp4 = files.mp4(target)
    text = (f"Rendered {rel_mp4} ({', '.join(f for f in facts if f)}); it is open on the canvas for the user. "
            f"Now make one `canvas` call with path {rel_mp4}, so the video stays in the chat as a file card "
            "(after a reload, and in a shared chat).")
    if target != name:
        text += f" It is named {target}.mp4 because {name}.mp4 was already here and is not this chat's render."
    if v.get("faults"):
        text += f" (The renderer noted: {', '.join(v['faults'])}.)"
    return {"_model": text, "_ui": {"type": "ui", "action": "open_canvas", "path": rel_mp4, "name": f"{target}.mp4"}}


async def _exec_video(inp, workspace, ctx=None):
    from cycls._agent import video

    inp = inp if isinstance(inp, dict) else {}
    root = Path(workspace.root)
    chat = getattr(ctx, "chat_id", None)
    action = str(inp.get("action") or "").lower().strip()
    loaded = VIDEO_LOADED.get()
    note = _LOADED_NOTE if loaded is False and action != "guide" else ""
    if action not in ACTIONS:
        return _err(f"action must be one of {', '.join(ACTIONS)}.")
    if not video.offered(workspace):
        return _err("Video is not switched on for this organisation.")
    try:
        if action == "guide":
            return await _guide(workspace, root, loaded)
        name = files.clean_name(inp.get("name"))
        if not name:
            return _err("name is required: the video's name, e.g. launch-reel.")
        rel = files.composition(name)

        if action == "write":
            html = inp.get("html")
            if not html and inp.get("path"):
                try:
                    src = _resolve_path(str(inp["path"]), root)
                except ValueError as e:
                    return _err(str(e))
                if not src.is_file() or src.suffix.lower() not in (".html", ".htm"):
                    return _err(f"{inp['path']} is not an HTML file in the workspace.")
                html = src.read_text(encoding="utf-8")
            if not isinstance(html, str) or not html.strip():
                return _err("write needs html (the whole composition) or path (a composition to adopt).")
            if len(html.encode("utf-8")) > MAX_HTML:
                return _err(f"the composition is over {MAX_HTML:,} bytes; keep it to the scenes and their animations.")
            name, rel, named = await _save(root, chat, name, html, "video-write")
            text, blocks, clean = await _check(workspace, root, rel, html)
            kb = len(html.encode("utf-8")) / 1024
            return _result(f"Saved {rel} ({kb:.1f} KB).{named}\n{text}", blocks, note, _shown(rel, name, clean))

        if action == "template":
            which = inp.get("template")
            given = inp.get("vars")
            if isinstance(given, str):
                try:
                    given = json.loads(given)
                except ValueError:
                    return _err("vars must be an object of the template's variables.")
            if not isinstance(which, str) or not which.strip():
                return _err("template needs template (its name) and vars.")
            try:
                html = await video.fill_template(workspace, which.strip(), _with_brand(root, which, given or {}))
            except video.Refused as e:
                return _err(f"the template was not filled: {e}. Nothing was saved.")
            name, rel, named = await _save(root, chat, name, html, "video-template")
            text, blocks, clean = await _check(workspace, root, rel, html)
            return _result(f"Made {rel} from the {which} template ({len(html) / 1024:.1f} KB).{named} It is an ordinary "
                           f"composition now: change it with `edit`.\n{text}", blocks, note, _shown(rel, name, clean))

        if action == "edit":
            changes = _read_changes(inp.get("changes"))
            if changes is None:
                return _err("edit needs changes: [{old, new, all?}], each old a non-empty exact text.")
            if not files.mine(root, chat, name) and not (root / rel).exists():
                return _err(f"there is no {rel}; `write` it first.")
            async with lock(root / rel):
                try:
                    html = (root / rel).read_text(encoding="utf-8")
                except FileNotFoundError:
                    return _err(f"there is no {rel}; `write` it first.")
                new, why = apply_changes(html, changes)
                if why:
                    return _err(why)
                await write_fig(root, rel, new.encode("utf-8"), by="agent", reason="video-edit")
            files.remember(root, chat, name)
            text, blocks, clean = await _check(workspace, root, rel, new)
            return _result(f"Edited {rel} ({len(changes)} change{'s' if len(changes) != 1 else ''}).\n{text}", blocks,
                           note, _shown(rel, name, clean))

        if action == "look":
            try:
                html = (root / rel).read_text(encoding="utf-8")
            except FileNotFoundError:
                return _err(f"there is no {rel}; `write` it first.")
            at = inp.get("at")
            if isinstance(at, (int, float)):
                at = [at]
            if at:
                if not isinstance(at, list) or not all(isinstance(t, (int, float)) for t in at):
                    return _err("at: a list of times in seconds.")
                params = {"at": [float(t) for t in at][:9], "zoom": str(inp.get("zoom") or "")[:200]}
                text, blocks, _ = await _check(workspace, root, rel, html, kind="look", params=params, budget=BUDGET["look"])
            else:
                text, blocks, _ = await _check(workspace, root, rel, html, budget=BUDGET["look"])
            return _result(text, blocks, note)

        if action == "render":
            quality = inp.get("quality") or "final"
            if quality not in ("final", "draft"):
                return _err("quality: final or draft.")
            out = await _render(workspace, root, chat, name, quality)
            if note and isinstance(out, str):
                out += note
            return out

        if action == "restore":
            history = versions.listing(root, rel)
            if not history:
                return _err(f"{rel} has no earlier version.")
            data = versions.read(root, rel, history[0]["id"])
            if data is None:
                return _err("that version could not be read.")
            async with lock(root / rel):
                await write_fig(root, rel, data, by="agent", reason="restore")
            return _result(f"Restored {rel} to the version from {history[0]['at'][:19]} UTC. Call `look` to see it.", [],
                           note, [{"type": "ui", "action": "refresh_canvas", "path": rel}])
    except video.Unavailable as e:
        return _err(f"Video is unavailable: {e}")
    except RuntimeError as e:
        return _err(f"the video service said: {e}")
    return _err("nothing was done.")


def _video_step(inp):
    inp = inp or {}
    return {"tool_name": "Video", "step": f"{inp.get('action', '')} {inp.get('name', '')}".strip()}
