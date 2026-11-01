"""A Word document's comments, kept by Cycls as well as in the file.

The file is what Word sees and stays the copy Word reads: a comment made in Cycls Docs is written into it when the
editor saves, and the agent's comments are written into it by the `docs` tool. The workspace's comment record
(design/comments.py, the store Cycls Sheets and Cycls Design use) mirrors it, so a Word document's comments are
Cycls comments too: who wrote each (their picture, the agent's badge), and others' new comments, replies and
resolves reaching an open editor at once (it polls the record), as in Cycls Sheets. The editor sends its own
changes to the record as they are made; the record is brought in line with the file when the file is read for the
editor (a new version) and after the agent comments.
"""
import json
from datetime import datetime, timezone

from ..design import comments
from ..logs import log

RESOURCE = "DOC_UNIVER_THREAD_COMMENT_PLUGIN"   # the engine's comment resource, as the reader gives it
SUBUNIT = "default_doc"


def _plain(body):
    """A comment's body (the engine's {dataStream, …}) → its words, a line per paragraph."""
    stream = body.get("dataStream", "") if isinstance(body, dict) else str(body or "")
    if stream.endswith("\r\n"):
        stream = stream[:-2]
    stream = stream.replace("\r", "\n")
    return "".join(c for c in stream if c == "\n" or c == "\t" or ord(c) >= 32).strip()


def _quote(ref):
    return " ".join("".join(c if ord(c) >= 32 else " " for c in str(ref or "")).split())[:comments.QUOTE_MAX]


def file_threads(document):
    """The comments a read of the file holds (the reader's comment resource), as comments.mirror_threads takes them:
    each with the paragraph its words are in and the words themselves."""
    if not isinstance(document, dict):
        return []
    res = next((r for r in document.get("resources") or [] if isinstance(r, dict) and r.get("name") == RESOURCE), None)
    if not res:
        return []
    try:
        threads = (json.loads(res.get("data") or "{}") or {}).get(SUBUNIT) or []
    except (TypeError, ValueError):
        return []
    paras = sorted((p.get("startIndex", 0), p.get("paragraphId")) for p in ((document.get("body") or {}).get("paragraphs") or [])
                   if isinstance(p, dict) and isinstance(p.get("startIndex"), int))
    out = []
    for t in threads:
        if not isinstance(t, dict) or t.get("id") is None:
            continue
        start = t.get("startOffset")
        para = next((pid for at, pid in paras if at >= start), None) if isinstance(start, int) else None
        out.append({
            "word": str(t["id"]), "author": t.get("authorName") or "", "at": t.get("dT"), "text": _plain(t.get("text")),
            "resolved": bool(t.get("resolved")), "para": para, "quote": _quote(t.get("ref")),
            "replies": [{"word": str(c["id"]), "author": c.get("authorName") or "", "at": c.get("dT"), "text": _plain(c.get("text"))}
                        for c in (t.get("children") or []) if isinstance(c, dict) and c.get("id") is not None],
        })
    return out


def written_at(path):
    """When the file was last written, as the record writes dates."""
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


async def mirror_file(ws, rel, document, written, agent=None, chat_id=None):
    """The record of `rel` brought in line with the comments of `document` (a read of the file written at
    `written`); `agent` the agent's author, for comments under its name. Never fails the caller."""
    if not comments.usable(ws):
        return
    try:
        await comments.mirror(ws, rel, file_threads(document), written, agent)
    except Exception as e:   # the file is what counts; the record catches up on the next read
        log("warn", chat_id=chat_id, message=f"docs comments not mirrored for {rel}: {type(e).__name__}: {e}"[:300])
