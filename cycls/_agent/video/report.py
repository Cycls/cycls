"""What the model is told after a Video call: one text and at most one sheet of frames.

Bounded on purpose. On Kimi K3 a tool's images arrive unlabelled in a later message, so the times
are burned into the sheet; compaction counts base64 at four characters a token, so there is one
small sheet per reply; and the text stays well under the 20,000 characters past which a result is
filed away and only previewed.
"""
import base64

MAX_FINDINGS = 25
MAX_TEXT = 12_000


def _finding(f):
    where = []
    if f.get("line"):
        where.append(f"line {f['line']}")
    if f.get("time") is not None:
        where.append(f"at {f['time']} s")
    if f.get("selector"):
        where.append(f"on {f['selector']}")
    head = f"{f.get('code', 'issue')}" + (f" ({', '.join(where)})" if where else "")
    text = f"- {head}: {str(f.get('message') or '').strip()}"
    if f.get("fixHint"):
        text += f" Fix: {str(f['fixHint']).strip()}"
    return text[:900]


def findings_text(findings, *, title):
    errors = [f for f in findings if f.get("severity") == "error"]
    rest = [f for f in findings if f.get("severity") != "error"]
    shown = (errors + rest)[:MAX_FINDINGS]
    if not shown:
        return ""
    lines = [f"{title}: {len(errors)} error{'s' if len(errors) != 1 else ''}, "
             f"{len(rest)} warning{'s' if len(rest) != 1 else ''}."]
    lines += [_finding(f) for f in shown]
    if len(findings) > len(shown):
        lines.append(f"(and {len(findings) - len(shown)} more)")
    return "\n".join(lines)


def sheet_blocks(sheet_b64, times, rel):
    """The sheet as the model receives it: a line saying what it is, then the image."""
    if not sheet_b64:
        return []
    when = ", ".join(f"{t:g} s" for t in times or [])
    return [{"type": "text", "text": f"Frames of {rel}" + (f" at {when}" if when else "") +
             " — each cell is labelled with its number and time:"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": sheet_b64}}]


LOOK_AT_IT = ("Look at the sheet before you go on: every word on screen readable and inside the frame, nothing "
              "overlapping, numbers and counters showing their values (not stuck at 0), each scene's end state "
              "reached, Arabic joined and right to left, the frames consistent with each other. If anything is off, "
              "fix it with `edit`, or `look` at the moment more closely.")


def clip(text):
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "\n…"


def b64(data):
    return base64.b64encode(data).decode() if data else ""
