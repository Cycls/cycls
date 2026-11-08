"""A small edit, and the moments it shows.

After an `edit` the full check — the browser check and a sheet of nine frames — took about 16 s on
the GPU for a three-clip footage video; frames alone of one or three moments took 8 to 10 s (dev,
2026-11-08), and an edit's whole call in the app about 26 s. Most edits after the first draft are
small: a word, a colour, a size. An edit that changes only the words and the inline styles of
elements that were already there — the same elements in the same places, the same attributes, the
same script and <style> — is checked by lint and a frame of each scene it touched, up to three. The
browser check then runs beside the render (`run._render`), so nothing reaches the MP4 unchecked.
"""
import re
from html.parser import HTMLParser

MOST = 3                     # scenes one small edit may touch; more is a big edit
AT = 0.6                     # how far into its scene a frame is taken: in, and settled
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_REF = re.compile(r"^\s*([A-Za-z_][\w-]*)\s*(?:([+-])\s*(\d+(?:\.\d+)?))?\s*$")


class _Shape(HTMLParser):
    """The elements in order: tag and attributes but `style`, parent, inline style, own text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.parents, self.styles, self.texts, self.attrs = [], [], [], [], []
        self._open = []

    def handle_starttag(self, tag, attrs):
        i = len(self.tags)
        a = {k: v or "" for k, v in attrs}
        self.tags.append((tag, tuple(sorted((k, v) for k, v in a.items() if k != "style"))))
        self.parents.append(self._open[-1] if self._open else None)
        self.styles.append(a.get("style", ""))
        self.texts.append("")
        self.attrs.append(a)
        if tag not in _VOID:
            self._open.append(i)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self._open.pop()

    def handle_endtag(self, tag):
        for k in range(len(self._open) - 1, -1, -1):
            if self.tags[self._open[k]][0] == tag:
                del self._open[k:]
                return

    def handle_data(self, data):
        if self._open:
            self.texts[self._open[-1]] += data


def _shape(html):
    try:
        s = _Shape()
        s.feed(html)
        s.close()
        return s
    except Exception:  # noqa: BLE001 - what the parser cannot read is no small edit
        return None


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x >= 0 else None


def _window(s, i, root, depth=0):
    """[start, end) of the timed element `i` on the video's clock; a start may name another element
    ("s1", "s2 + 0.5": when that one ends). None when it cannot be told."""
    a = s.attrs[i]
    length = _num(a.get("data-duration"))
    start = _num(a.get("data-start"))
    if start is None and depth < 8:
        m = _REF.match(a.get("data-start", ""))
        ref = next((k for k, x in enumerate(s.attrs) if m and x.get("id") == m.group(1)), None)
        if ref is not None and s.parents[ref] == root:
            w = _window(s, ref, root, depth + 1)
            if w:
                off = float(m.group(3) or 0)
                start = w[1] + (off if m.group(2) != "-" else -off)
    if start is None or not length:
        return None
    return start, start + length


def moments(before, after):
    """The times to look at when `before` → `after` is a small edit (see above), else None."""
    a, b = _shape(before), _shape(after)
    if a is None or b is None or a.tags != b.tags or a.parents != b.parents:
        return None
    root = next((i for i, x in enumerate(a.attrs) if "data-composition-id" in x), None)
    if root is None:
        return None
    total = _num(a.attrs[root].get("data-duration"))
    scenes = []
    for i, (tag, _) in enumerate(a.tags):
        if a.styles[i] == b.styles[i] and a.texts[i] == b.texts[i]:
            continue
        if tag in ("script", "style") or i == root or tag in ("html", "head", "body", "title"):
            return None                     # rules and code reach anywhere: the full check
        top = i                             # the scene it is in: its ancestor at the root
        while top is not None and a.parents[top] != root:
            top = a.parents[top]
            if top is not None and "data-composition-id" in a.attrs[top]:
                return None                 # inside a composition of its own: its own clock
        if top is None:
            return None
        if top not in scenes:
            scenes.append(top)
    if not scenes or len(scenes) > MOST:
        return None
    times = []
    for top in scenes:
        w = _window(a, top, root)
        if not w:
            return None
        t = w[0] + (w[1] - w[0]) * AT
        if total:
            t = min(t, total - 0.05)
        times.append(round(max(0.0, t), 2))
    return sorted(set(times))
